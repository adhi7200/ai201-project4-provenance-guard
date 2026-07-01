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

import store
from signals import groq_signal

app = Flask(__name__)
store.init_db()


@app.route("/submit", methods=["POST"])
def submit():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    creator_id = (body.get("creator_id") or "").strip()

    if not text or not creator_id:
        return jsonify({"error": "both 'text' and 'creator_id' are required"}), 400

    content_id = str(uuid.uuid4())

    # Signal 1: GROQ semantic classification.
    signal1 = groq_signal(text)
    llm_score = signal1["llm_score"]

    # Placeholder attribution/confidence/label from signal 1 alone.
    # M4 replaces this with the agreement-gated combination of both signals.
    attribution = "likely_ai" if llm_score >= 0.70 else "likely_human" if llm_score <= 0.40 else "uncertain"
    confidence = llm_score
    label = "(placeholder - full label generated in M5)"

    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "text": text,
        "genre": signal1["genre"],
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": llm_score,
        "stylo_score": None,  # signal 2 arrives in M4
        "label": label,
        "status": "classified",
    }
    store.record_submission(entry)

    return jsonify(
        {
            "content_id": content_id,
            "attribution": attribution,
            "confidence": confidence,
            "genre": signal1["genre"],
            "llm_score": llm_score,
            "rationale": signal1["rationale"],
            "label": label,
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": store.get_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
