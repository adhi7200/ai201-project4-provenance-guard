"""SQLite-backed storage for Provenance Guard.

Two tables:
  content   - canonical current state of each submission (used for lookup and
              status updates during the appeals workflow in M5).
  audit_log - append-only record of every event (submit, appeal), so we can
              show the full decision history via GET /log.
"""

import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "provenance.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they do not exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content (
                content_id  TEXT PRIMARY KEY,
                creator_id  TEXT NOT NULL,
                text        TEXT NOT NULL,
                genre       TEXT,
                attribution TEXT,
                confidence  REAL,
                llm_score   REAL,
                stylo_score REAL,
                label       TEXT,
                status      TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id  TEXT NOT NULL,
                creator_id  TEXT,
                timestamp   TEXT NOT NULL,
                event       TEXT NOT NULL,
                attribution TEXT,
                confidence  REAL,
                llm_score   REAL,
                stylo_score REAL,
                status      TEXT,
                details     TEXT
            )
            """
        )


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def record_submission(entry):
    """Persist a new classification: write the content row and a 'submit' audit event.

    entry is a dict with keys: content_id, creator_id, text, genre, attribution,
    confidence, llm_score, stylo_score, label, status.
    """
    ts = now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO content (content_id, creator_id, text, genre, attribution,
                                 confidence, llm_score, stylo_score, label, status, created_at)
            VALUES (:content_id, :creator_id, :text, :genre, :attribution,
                    :confidence, :llm_score, :stylo_score, :label, :status, :created_at)
            """,
            {**entry, "created_at": ts},
        )
        conn.execute(
            """
            INSERT INTO audit_log (content_id, creator_id, timestamp, event, attribution,
                                   confidence, llm_score, stylo_score, status, details)
            VALUES (:content_id, :creator_id, :timestamp, 'submit', :attribution,
                    :confidence, :llm_score, :stylo_score, :status, :details)
            """,
            {
                "content_id": entry["content_id"],
                "creator_id": entry["creator_id"],
                "timestamp": ts,
                "attribution": entry["attribution"],
                "confidence": entry["confidence"],
                "llm_score": entry["llm_score"],
                "stylo_score": entry["stylo_score"],
                "status": entry["status"],
                "details": json.dumps({"genre": entry["genre"], "label": entry["label"]}),
            },
        )


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
