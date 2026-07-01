"""Provenance Guard - Flask API (Milestone 3).

Endpoints so far:
  POST /submit  - accept text + creator_id, run signal 1, return a classification
  GET  /log     - return the most recent audit-log entries

Confidence scoring (agreement gate) and the second signal arrive in M4; the
transparency label, appeals, and rate limiting arrive in M5. For now the
confidence and label fields carry placeholders derived from signal 1 only.
"""

import uuid

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import store
from labels import make_label
from scoring import score
from signals import groq_signal, stylometric_signal

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

    if not text or not creator_id:
        return jsonify({"error": "both 'text' and 'creator_id' are required"}), 400

    content_id = str(uuid.uuid4())

    # Signal 1: GROQ semantic classification (also detects genre).
    signal1 = groq_signal(text)
    llm_score = signal1["llm_score"]
    genre = signal1["genre"]

    # Signal 2: stylometric heuristics, calibrated by the detected genre.
    signal2 = stylometric_signal(text, genre=genre)
    stylo_score = signal2["stylo_score"]

    # Agreement-gated combination of both signals.
    result = score(llm_score, stylo_score)
    attribution = result["attribution"]
    confidence = result["display_confidence"]
    label = make_label(attribution, confidence)

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
    }
    store.record_submission(entry)

    return jsonify(
        {
            "content_id": content_id,
            "attribution": attribution,
            "confidence": confidence,
            "genre": genre,
            "llm_score": llm_score,
            "stylo_score": stylo_score,
            "combined": result["combined"],
            "signals_agree": result["agree"],
            "rationale": signal1["rationale"],
            "label": label,
        }
    )


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


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": store.get_log()})


@app.route("/appeals", methods=["GET"])
def appeals_queue():
    # Reviewer view: everything currently awaiting human review.
    return jsonify({"queue": store.get_appeal_queue()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
