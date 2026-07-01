"""Tests for get_analytics() against a seeded temp DB."""

import store


def _seed(tmp_path):
    store.DB_PATH = str(tmp_path / "test.db")
    store.init_db()

    submissions = [
        ("c1", "u1", "likely_ai",    "blog",       "text",              0),
        ("c2", "u2", "likely_human", "blog",       "text",              1),
        ("c3", "u3", "uncertain",    "news",       "text",              0),
        ("c4", "u4", "likely_human", "other",      "image_description", 0),
    ]
    for content_id, creator_id, attribution, genre, content_type, creator_verified in submissions:
        store.record_submission({
            "content_id": content_id,
            "creator_id": creator_id,
            "text": "x",
            "genre": genre,
            "attribution": attribution,
            "confidence": 0.75,
            "llm_score": 0.5,
            "stylo_score": 0.5,
            "label": "label",
            "status": "classified",
            "content_type": content_type,
            "creator_verified": creator_verified,
        })

    store.record_appeal("c1", "I wrote this myself.")


def test_total_submissions(tmp_path):
    _seed(tmp_path)
    data = store.get_analytics()
    assert data["total_submissions"] == 4


def test_attribution_counts(tmp_path):
    _seed(tmp_path)
    data = store.get_analytics()
    assert data["by_attribution"]["likely_ai"] == 1
    assert data["by_attribution"]["likely_human"] == 2
    assert data["by_attribution"]["uncertain"] == 1


def test_appeal_rate(tmp_path):
    _seed(tmp_path)
    data = store.get_analytics()
    assert data["appeal_rate"] == 0.25  # 1 appeal / 4 submissions


def test_content_type_breakdown(tmp_path):
    _seed(tmp_path)
    data = store.get_analytics()
    assert data["by_content_type"]["text"] == 3
    assert data["by_content_type"]["image_description"] == 1


def test_verified_creator_submissions(tmp_path):
    _seed(tmp_path)
    data = store.get_analytics()
    assert data["verified_creator_submissions"] == 1


def test_signal_agreement_rate(tmp_path):
    _seed(tmp_path)
    data = store.get_analytics()
    # 3 of 4 submissions are not uncertain
    assert data["signal_agreement_rate"] == 0.75


def test_avg_confidence(tmp_path):
    _seed(tmp_path)
    data = store.get_analytics()
    assert data["avg_confidence"] == 0.75
