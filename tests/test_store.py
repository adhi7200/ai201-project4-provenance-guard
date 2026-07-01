"""Tests for the SQLite audit log / content store (isolated temp DB)."""


def _sample_entry(content_id="c-1"):
    return {
        "content_id": content_id,
        "creator_id": "u1",
        "text": "some text",
        "genre": "blog",
        "attribution": "likely_ai",
        "confidence": 0.73,
        "llm_score": 0.8,
        "stylo_score": 0.65,
        "label": "placeholder",
        "status": "classified",
    }


def test_submission_is_retrievable(db):
    db.record_submission(_sample_entry())
    row = db.get_content("c-1")
    assert row["attribution"] == "likely_ai"
    assert row["llm_score"] == 0.8
    assert row["stylo_score"] == 0.65
    assert row["status"] == "classified"


def test_submission_writes_a_structured_audit_entry(db):
    db.record_submission(_sample_entry())
    log = db.get_log()
    assert len(log) == 1
    entry = log[0]
    assert entry["event"] == "submit"
    assert entry["content_id"] == "c-1"
    assert entry["llm_score"] == 0.8
    assert entry["stylo_score"] == 0.65
    assert entry["timestamp"].endswith("Z")


def test_log_is_most_recent_first(db):
    db.record_submission(_sample_entry("c-1"))
    db.record_submission(_sample_entry("c-2"))
    log = db.get_log()
    assert [e["content_id"] for e in log] == ["c-2", "c-1"]


def test_appeal_updates_status_and_logs(db):
    db.record_submission(_sample_entry("c-1"))
    ok = db.record_appeal("c-1", "I wrote this myself from personal experience.")
    assert ok is True

    # Content status flipped.
    assert db.get_content("c-1")["status"] == "under_review"

    # An appeal audit entry exists, preserving the original decision.
    appeal_entries = [e for e in db.get_log() if e["event"] == "appeal"]
    assert len(appeal_entries) == 1
    entry = appeal_entries[0]
    assert entry["status"] == "under_review"
    assert entry["appeal_reasoning"] == "I wrote this myself from personal experience."
    assert entry["attribution"] == "likely_ai"  # original decision preserved


def test_appeal_on_missing_content_returns_false(db):
    assert db.record_appeal("does-not-exist", "reason") is False


def test_appeal_queue_lists_under_review(db):
    db.record_submission(_sample_entry("c-1"))
    db.record_submission(_sample_entry("c-2"))
    db.record_appeal("c-2", "please review")
    queue = db.get_appeal_queue()
    assert [c["content_id"] for c in queue] == ["c-2"]
