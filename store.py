"""SQLite-backed storage for Provenance Guard.

Two tables:
  content   - canonical current state of each submission (used for lookup and
              status updates during the appeals workflow in M5).
  audit_log - append-only record of every event (submit, appeal), so we can
              show the full decision history via GET /log.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

# Overridable so tests can point at their own database (see tests/conftest.py).
DB_PATH = os.environ.get("PROVENANCE_DB", "provenance.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn):
    """Add columns introduced after the original schema, so an existing database
    is upgraded in place rather than dropped. Each entry is (table, column, decl).
    """
    additions = [
        ("content", "content_type", "TEXT DEFAULT 'text'"),
        ("audit_log", "content_type", "TEXT"),
        ("content", "creator_verified", "INTEGER DEFAULT 0"),
    ]
    for table, column, decl in additions:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    """Create tables if they do not exist, then migrate. Safe on every startup."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content (
                content_id       TEXT PRIMARY KEY,
                creator_id       TEXT NOT NULL,
                text             TEXT NOT NULL,
                genre            TEXT,
                attribution      TEXT,
                confidence       REAL,
                llm_score        REAL,
                stylo_score      REAL,
                label            TEXT,
                status           TEXT NOT NULL,
                content_type     TEXT DEFAULT 'text',
                creator_verified INTEGER DEFAULT 0,
                created_at       TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id       TEXT NOT NULL,
                creator_id       TEXT,
                timestamp        TEXT NOT NULL,
                event            TEXT NOT NULL,
                attribution      TEXT,
                confidence       REAL,
                llm_score        REAL,
                stylo_score      REAL,
                status           TEXT,
                content_type     TEXT,
                appeal_reasoning TEXT,
                details          TEXT
            )
            """
        )
        _migrate(conn)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def record_submission(entry):
    """Persist a new classification: write the content row and a 'submit' audit event.

    entry is a dict with keys: content_id, creator_id, text, genre, attribution,
    confidence, llm_score, stylo_score, label, status. Optional: content_type
    (defaults to 'text'), creator_verified (defaults to 0).
    """
    ts = now_iso()
    row = {"content_type": "text", "creator_verified": 0, **entry, "created_at": ts}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO content (content_id, creator_id, text, genre, attribution,
                                 confidence, llm_score, stylo_score, label, status,
                                 content_type, creator_verified, created_at)
            VALUES (:content_id, :creator_id, :text, :genre, :attribution,
                    :confidence, :llm_score, :stylo_score, :label, :status,
                    :content_type, :creator_verified, :created_at)
            """,
            row,
        )
        conn.execute(
            """
            INSERT INTO audit_log (content_id, creator_id, timestamp, event, attribution,
                                   confidence, llm_score, stylo_score, status,
                                   content_type, details)
            VALUES (:content_id, :creator_id, :timestamp, 'submit', :attribution,
                    :confidence, :llm_score, :stylo_score, :status,
                    :content_type, :details)
            """,
            {
                "content_id": row["content_id"],
                "creator_id": row["creator_id"],
                "timestamp": ts,
                "attribution": row["attribution"],
                "confidence": row["confidence"],
                "llm_score": row["llm_score"],
                "stylo_score": row["stylo_score"],
                "status": row["status"],
                "content_type": row["content_type"],
                "details": json.dumps({"genre": row["genre"], "label": row["label"]}),
            },
        )


def record_appeal(content_id, creator_reasoning):
    """Log an appeal and flip the content's status to under_review.

    Returns True if the content existed and was updated, False otherwise. The
    appeal audit entry preserves the original decision (attribution, confidence,
    both signal scores) so a reviewer sees it next to the creator's reasoning.
    """
    content = get_content(content_id)
    if content is None:
        return False

    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            "UPDATE content SET status = 'under_review' WHERE content_id = ?",
            (content_id,),
        )
        conn.execute(
            """
            INSERT INTO audit_log (content_id, creator_id, timestamp, event, attribution,
                                   confidence, llm_score, stylo_score, status,
                                   appeal_reasoning, details)
            VALUES (:content_id, :creator_id, :timestamp, 'appeal', :attribution,
                    :confidence, :llm_score, :stylo_score, 'under_review',
                    :appeal_reasoning, :details)
            """,
            {
                "content_id": content_id,
                "creator_id": content["creator_id"],
                "timestamp": ts,
                "attribution": content["attribution"],
                "confidence": content["confidence"],
                "llm_score": content["llm_score"],
                "stylo_score": content["stylo_score"],
                "appeal_reasoning": creator_reasoning,
                "details": json.dumps({"original_status": content["status"]}),
            },
        )
    return True


def get_appeal_queue():
    """Return all content currently awaiting human review (the reviewer's queue)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM content WHERE status = 'under_review' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_content(content_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM content WHERE content_id = ?", (content_id,)
        ).fetchone()
        return dict(row) if row else None


def get_log(limit=50):
    """Return the most recent audit-log entries as a list of dicts."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
