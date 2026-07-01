"""Tests for multi-modal support (content_type=image_description)."""

import unittest.mock as mock

import pytest

import store
from signals import groq_signal, stylometric_signal


CAPTION = "A golden retriever leaping through autumn leaves in a sun-dappled park"


def test_groq_signal_accepts_image_description():
    fake = {"p_ai": 0.3, "genre": "image_description", "rationale": "Looks human."}
    with mock.patch("signals._get_client") as mc:
        mc.return_value.chat.completions.create.return_value.choices[0].message.content = (
            '{"p_ai": 0.3, "genre": "image_description", "rationale": "Looks human."}'
        )
        result = groq_signal(CAPTION, content_type="image_description")
    assert result["genre"] == "image_description"
    assert 0.0 <= result["llm_score"] <= 1.0


def test_stylometric_caption_min_word_threshold():
    # A short caption (above 8 words) should score rather than abstain.
    result = stylometric_signal(CAPTION, content_type="image_description")
    assert result["stylo_score"] != 0.5 or "note" not in result["features"]


def test_stylometric_very_short_caption_abstains():
    result = stylometric_signal("A dog.", content_type="image_description")
    assert result["stylo_score"] == 0.5


def test_submit_stores_content_type(tmp_path):
    store.DB_PATH = str(tmp_path / "test.db")
    store.init_db()

    fake_resp = '{"p_ai": 0.4, "genre": "image_description", "rationale": "ok"}'
    with mock.patch("signals._get_client") as mc:
        mc.return_value.chat.completions.create.return_value.choices[0].message.content = fake_resp
        from signals import groq_signal as gs, stylometric_signal as ss, compression_signal as cs
        from scoring import score as sc
        from labels import make_label

        signal1 = gs(CAPTION, content_type="image_description")
        signal2 = ss(CAPTION, content_type="image_description")
        signal3 = cs(CAPTION)
        signals = {"llm": signal1["llm_score"], "stylo": signal2["stylo_score"]}
        if signal3["informative"]:
            signals["compression"] = signal3["compression_score"]
        result = sc(signals)
        attribution = result["attribution"]
        confidence = result["display_confidence"]

        entry = {
            "content_id": "test-mm-001",
            "creator_id": "u1",
            "text": CAPTION,
            "genre": signal1["genre"],
            "attribution": attribution,
            "confidence": confidence,
            "llm_score": signal1["llm_score"],
            "stylo_score": signal2["stylo_score"],
            "label": make_label(attribution, confidence),
            "status": "classified",
            "content_type": "image_description",
        }
        store.record_submission(entry)

    row = store.get_content("test-mm-001")
    assert row["content_type"] == "image_description"

    log = store.get_log()
    assert any(e["content_type"] == "image_description" for e in log)
