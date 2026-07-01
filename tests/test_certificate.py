"""Tests for the provenance certificate feature."""

import unittest.mock as mock

import store
from verification import get_challenge


def _fake_groq(p_ai):
    content = f'{{"p_ai": {p_ai}, "genre": "blog", "rationale": "ok"}}'
    m = mock.MagicMock()
    m.chat.completions.create.return_value.choices[0].message.content = content
    return m


def test_get_challenge_returns_prompt_and_id():
    c = get_challenge()
    assert "prompt" in c and "challenge_id" in c
    assert len(c["challenge_id"]) == 16


def test_set_and_get_creator(tmp_path):
    store.DB_PATH = str(tmp_path / "test.db")
    store.init_db()
    store.set_verified("u1", "cert-abc")
    rec = store.get_creator("u1")
    assert rec["verified"] == 1
    assert rec["certificate_id"] == "cert-abc"


def test_unknown_creator_returns_none(tmp_path):
    store.DB_PATH = str(tmp_path / "test.db")
    store.init_db()
    assert store.get_creator("nobody") is None


def test_verify_human_passage_earns_certificate(tmp_path):
    store.DB_PATH = str(tmp_path / "test.db")
    store.init_db()

    with mock.patch("signals._get_client", return_value=_fake_groq(0.15)):
        from signals import groq_signal, stylometric_signal, compression_signal
        from scoring import score

        human_text = (
            "ok so i finally tried that new ramen place downtown and honestly? "
            "underwhelming. the broth was fine but they put WAY too much sodium "
            "and i was thirsty for like three hours after. my friend got the spicy "
            "version and said it was better but i dunno, felt overpriced for what it was."
        )
        s1 = groq_signal(human_text)
        s2 = stylometric_signal(human_text, genre=s1["genre"])
        s3 = compression_signal(human_text)
        signals = {"llm": s1["llm_score"], "stylo": s2["stylo_score"]}
        if s3["informative"]:
            signals["compression"] = s3["compression_score"]
        result = score(signals)
        passed = result["attribution"] == "likely_human"
        if passed:
            store.set_verified("u1", "cert-001")

    assert store.get_creator("u1") is not None
    assert store.get_creator("u1")["verified"] == 1


def test_verify_ai_passage_does_not_certify(tmp_path):
    store.DB_PATH = str(tmp_path / "test.db")
    store.init_db()

    with mock.patch("signals._get_client", return_value=_fake_groq(0.92)):
        from signals import groq_signal, stylometric_signal, compression_signal
        from scoring import score

        ai_text = (
            "Artificial intelligence represents a transformative paradigm shift. "
            "It is important to note that the implications span numerous domains. "
            "Furthermore, stakeholders must collaborate to ensure responsible deployment. "
            "Moreover, ethical considerations remain paramount across all sectors."
        )
        s1 = groq_signal(ai_text)
        s2 = stylometric_signal(ai_text, genre=s1["genre"])
        s3 = compression_signal(ai_text)
        signals = {"llm": s1["llm_score"], "stylo": s2["stylo_score"]}
        if s3["informative"]:
            signals["compression"] = s3["compression_score"]
        result = score(signals)
        passed = result["attribution"] == "likely_human"
        if passed:
            store.set_verified("u2", "cert-002")

    assert store.get_creator("u2") is None


def test_verified_creator_submit_carries_badge(tmp_path):
    store.DB_PATH = str(tmp_path / "test.db")
    store.init_db()
    store.set_verified("u1", "cert-abc")

    entry = {
        "content_id": "c001",
        "creator_id": "u1",
        "text": "some text",
        "genre": "blog",
        "attribution": "likely_human",
        "confidence": 0.8,
        "llm_score": 0.2,
        "stylo_score": 0.25,
        "label": "human label",
        "status": "classified",
        "content_type": "text",
        "creator_verified": 1,
    }
    store.record_submission(entry)
    row = store.get_content("c001")
    assert row["creator_verified"] == 1
