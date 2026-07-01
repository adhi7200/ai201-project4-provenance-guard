"""Provenance Guard - Flask API (Milestone 3).

Endpoints so far:
  POST /submit  - accept text + creator_id, run signal 1, return a classification
  GET  /log     - return the most recent audit-log entries

Confidence scoring (agreement gate) and the second signal arrive in M4; the
transparency label, appeals, and rate limiting arrive in M5. For now the
confidence and label fields carry placeholders derived from signal 1 only.
"""

import uuid

from flask import Flask, jsonify, render_template_string, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import store
from injection_filter import check_injection
from labels import make_label
from scoring import score
from signals import compression_signal, groq_signal, stylometric_signal
from verification import get_challenge

app = Flask(__name__)
store.init_db()

# Rate limiting. Limits are per client IP. See README for the reasoning behind
# these specific numbers (realistic single-writer usage vs. scripted flooding).
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    creator_id = (body.get("creator_id") or "").strip()
    content_type = body.get("content_type", "text")
    if content_type not in ("text", "image_description"):
        content_type = "text"

    if not text or not creator_id:
        return jsonify({"error": "both 'text' and 'creator_id' are required"}), 400

    # Prompt-injection filter: reject text that reads as an instruction to the
    # classifier before spending a GROQ call on it.
    injection = check_injection(text)
    if not injection["clean"]:
        return jsonify({
            "error": "submission rejected: text contains prompt-injection patterns",
            "matches": injection["matches"],
        }), 400

    content_id = str(uuid.uuid4())

    # Signal 1: GROQ semantic classification (also detects genre).
    signal1 = groq_signal(text, content_type=content_type)
    llm_score = signal1["llm_score"]
    genre = signal1["genre"]

    # Signal 2: stylometric heuristics, calibrated by the detected genre.
    signal2 = stylometric_signal(text, genre=genre, content_type=content_type)
    stylo_score = signal2["stylo_score"]

    # Signal 3: compression / predictability. It abstains on ordinary prose and
    # only joins the ensemble when it detects real redundancy.
    signal3 = compression_signal(text)
    compression_score = signal3["compression_score"]

    signals = {"llm": llm_score, "stylo": stylo_score}
    if signal3["informative"]:
        signals["compression"] = compression_score

    # Weighted ensemble with the generalized agreement gate.
    result = score(signals)
    attribution = result["attribution"]
    confidence = result["display_confidence"]
    label = make_label(attribution, confidence)

    creator_rec = store.get_creator(creator_id)
    creator_verified = bool(creator_rec and creator_rec.get("verified"))

    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "text": text,
        "genre": genre,
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": llm_score,
        "stylo_score": stylo_score,
        "label": label,
        "status": "classified",
        "content_type": content_type,
        "creator_verified": int(creator_verified),
    }
    store.record_submission(entry)

    resp = {
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "genre": genre,
        "content_type": content_type,
        "llm_score": llm_score,
        "stylo_score": stylo_score,
        "compression_score": compression_score,
        "combined": result["combined"],
        "signals_agree": result["agree"],
        "rationale": signal1["rationale"],
        "label": label,
        "creator_verified": creator_verified,
    }
    if creator_verified:
        resp["badge"] = "Verified Human creator"
    return jsonify(resp)


@app.route("/appeal", methods=["POST"])
@limiter.limit("5 per minute;50 per day")
def appeal():
    body = request.get_json(silent=True) or {}
    content_id = (body.get("content_id") or "").strip()
    creator_reasoning = (body.get("creator_reasoning") or "").strip()

    if not content_id or not creator_reasoning:
        return jsonify({"error": "both 'content_id' and 'creator_reasoning' are required"}), 400

    updated = store.record_appeal(content_id, creator_reasoning)
    if not updated:
        return jsonify({"error": f"no content found with id '{content_id}'"}), 404

    return jsonify(
        {
            "content_id": content_id,
            "status": "under_review",
            "message": "Request under review. Please check back later.",
        }
    )


@app.route("/verify/challenge", methods=["GET"])
def verify_challenge():
    return jsonify(get_challenge())


@app.route("/verify", methods=["POST"])
def verify():
    body = request.get_json(silent=True) or {}
    creator_id = (body.get("creator_id") or "").strip()
    text = (body.get("text") or "").strip()

    if not creator_id or not text:
        return jsonify({"error": "both 'creator_id' and 'text' are required"}), 400

    # A verification passage that tries to steer the classifier is an attempt to
    # fraudulently earn a certificate, so reject it outright.
    injection = check_injection(text)
    if not injection["clean"]:
        return jsonify({
            "error": "verification rejected: text contains prompt-injection patterns",
            "matches": injection["matches"],
        }), 400

    signal1 = groq_signal(text)
    signal2 = stylometric_signal(text, genre=signal1["genre"])
    signal3 = compression_signal(text)
    signals = {"llm": signal1["llm_score"], "stylo": signal2["stylo_score"]}
    if signal3["informative"]:
        signals["compression"] = signal3["compression_score"]
    result = score(signals)

    passed = result["attribution"] == "likely_human"
    store.log_verify(creator_id, result["attribution"], result["display_confidence"], passed)

    if passed:
        certificate_id = str(uuid.uuid4())
        store.set_verified(creator_id, certificate_id)
        return jsonify({
            "verified": True,
            "certificate_id": certificate_id,
            "message": "Verification passed. Your Verified Human badge is now active.",
        })
    return jsonify({
        "verified": False,
        "message": "Verification not passed. The passage did not score as likely human. Try a different sample.",
    })


@app.route("/creator/<creator_id>", methods=["GET"])
def creator_status(creator_id):
    rec = store.get_creator(creator_id)
    if rec is None:
        return jsonify({"creator_id": creator_id, "verified": False, "certificate_id": None})
    return jsonify({
        "creator_id": creator_id,
        "verified": bool(rec["verified"]),
        "certificate_id": rec.get("certificate_id"),
        "verified_at": rec.get("verified_at"),
    })


@app.route("/analytics", methods=["GET"])
def analytics():
    return jsonify(store.get_analytics())


_DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Provenance Guard Dashboard</title>
<style>
  body { font-family: sans-serif; max-width: 700px; margin: 2rem auto; color: #222; }
  h1 { font-size: 1.4rem; }
  h2 { font-size: 1rem; margin-top: 1.5rem; border-bottom: 1px solid #ddd; padding-bottom: .25rem; }
  table { border-collapse: collapse; width: 100%; margin-top: .5rem; }
  td, th { padding: .35rem .6rem; border: 1px solid #ddd; text-align: left; }
  th { background: #f5f5f5; }
  .stat { font-size: 1.6rem; font-weight: bold; }
  .label { color: #555; font-size: .85rem; }
</style>
</head>
<body>
<h1>Provenance Guard -- Analytics Dashboard</h1>

<h2>Submissions</h2>
<p><span class="stat">{{ d.total_submissions }}</span><br>
<span class="label">total submissions</span></p>

<h2>Attribution breakdown</h2>
<table>
<tr><th>Attribution</th><th>Count</th></tr>
{% for k, v in d.by_attribution.items() %}
<tr><td>{{ k }}</td><td>{{ v }}</td></tr>
{% endfor %}
</table>

<h2>By genre</h2>
<table>
<tr><th>Genre</th><th>Count</th></tr>
{% for k, v in d.by_genre.items() %}
<tr><td>{{ k }}</td><td>{{ v }}</td></tr>
{% endfor %}
</table>

<h2>By content type</h2>
<table>
<tr><th>Content type</th><th>Count</th></tr>
{% for k, v in d.by_content_type.items() %}
<tr><td>{{ k }}</td><td>{{ v }}</td></tr>
{% endfor %}
</table>

<h2>Signal quality</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Average confidence</td><td>{{ d.avg_confidence }}</td></tr>
<tr><td>Signal agreement rate</td><td>{{ d.signal_agreement_rate }}</td></tr>
<tr><td>Appeal rate</td><td>{{ d.appeal_rate }}</td></tr>
<tr><td>Verified-creator submissions</td><td>{{ d.verified_creator_submissions }}</td></tr>
</table>
</body>
</html>"""


@app.route("/dashboard", methods=["GET"])
def dashboard():
    data = store.get_analytics()
    return render_template_string(_DASHBOARD_TEMPLATE, d=data)


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": store.get_log()})


@app.route("/appeals", methods=["GET"])
def appeals_queue():
    # Reviewer view: everything currently awaiting human review.
    return jsonify({"queue": store.get_appeal_queue()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
