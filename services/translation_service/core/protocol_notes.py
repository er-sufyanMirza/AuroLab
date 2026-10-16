"""
core/protocol_notes.py

Protocol annotations and lab notebook system for AuroLab.

Each protocol can have:
  - Free-text notes (multi-paragraph, markdown supported)
  - Tags (e.g. "validated", "BCA", "cell-line-HEK293")
  - Star/pin status (for quick access)
  - Execution results log (actual outcomes vs simulated)
  - Linked protocols (e.g. "follow-up: western blot")

Storage: SQLite alongside the protocol database.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS protocol_notes (
    note_id     TEXT PRIMARY KEY,
    protocol_id TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS protocol_tags (
    tag_id      TEXT PRIMARY KEY,
    protocol_id TEXT NOT NULL,
    tag         TEXT NOT NULL,
    created_at  REAL NOT NULL,
    UNIQUE(protocol_id, tag)
);

CREATE TABLE IF NOT EXISTS protocol_stars (
    protocol_id TEXT PRIMARY KEY,
    starred     INTEGER NOT NULL DEFAULT 1,
    starred_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS protocol_links (
    link_id      TEXT PRIMARY KEY,
    protocol_id  TEXT NOT NULL,
    linked_id    TEXT NOT NULL,
    relationship TEXT NOT NULL DEFAULT 'related',
    note         TEXT,
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_logs (
    log_id        TEXT PRIMARY KEY,
    protocol_id   TEXT NOT NULL,
    executed_at   REAL NOT NULL,
    operator      TEXT,
    outcome       TEXT NOT NULL,
    observations  TEXT,
    deviations    TEXT,
    actual_time_min REAL,
    success       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_notes_protocol    ON protocol_notes(protocol_id);
CREATE INDEX IF NOT EXISTS idx_tags_protocol     ON protocol_tags(protocol_id);
CREATE INDEX IF NOT EXISTS idx_tags_tag          ON protocol_tags(tag);
CREATE INDEX IF NOT EXISTS idx_links_protocol    ON protocol_links(protocol_id);
CREATE INDEX IF NOT EXISTS idx_execlog_protocol  ON execution_logs(protocol_id);
"""


@dataclass
class ProtocolNote:
    note_id:     str
    protocol_id: str
    content:     str
    created_at:  float
    updated_at:  float

    def to_dict(self) -> dict:
        return {"note_id": self.note_id, "protocol_id": self.protocol_id,
                "content": self.content, "created_at": self.created_at,
                "updated_at": self.updated_at}


@dataclass
class ExecutionLog:
    log_id:          str
    protocol_id:     str
    executed_at:     float
    outcome:         str        # "success" | "partial" | "failed" | "aborted"
    operator:        str        = ""
    observations:    str        = ""    # what was actually observed
    deviations:      str        = ""    # deviations from protocol
    actual_time_min: float      = 0.0
    success:         bool       = False

    def to_dict(self) -> dict:
        return {
            "log_id": self.log_id, "protocol_id": self.protocol_id,
            "executed_at": self.executed_at, "operator": self.operator,
            "outcome": self.outcome, "observations": self.observations,
            "deviations": self.deviations, "actual_time_min": self.actual_time_min,
            "success": self.success,
        }


class ProtocolNotesStore:
    """
    SQLite-backed lab notebook — notes, tags, stars, links, execution logs.
    One instance per deployment, shared across sessions.
    """

    def __init__(self, db_path: str = "./data/notes.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = str(path)
        self._init()
        log.info("notes_store_ready", path=self._db)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(DB_SCHEMA)

    # ── Notes ─────────────────────────────────────────────────────────────

    def get_note(self, protocol_id: str) -> ProtocolNote | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM protocol_notes WHERE protocol_id=? ORDER BY updated_at DESC LIMIT 1",
                (protocol_id,)).fetchone()
        if not row:
            return None
        return ProtocolNote(note_id=row["note_id"], protocol_id=row["protocol_id"],
                            content=row["content"], created_at=row["created_at"],
                            updated_at=row["updated_at"])

    def upsert_note(self, protocol_id: str, content: str) -> ProtocolNote:
        """Create or update the note for a protocol."""
        now      = time.time()
        existing = self.get_note(protocol_id)
        if existing:
            with self._conn() as c:
                c.execute("UPDATE protocol_notes SET content=?, updated_at=? WHERE note_id=?",
                          (content, now, existing.note_id))
            existing.content    = content
            existing.updated_at = now
            return existing
        note_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute("INSERT INTO protocol_notes (note_id,protocol_id,content,created_at,updated_at) VALUES (?,?,?,?,?)",
                      (note_id, protocol_id, content, now, now))
        log.info("note_created", protocol_id=protocol_id)
        return ProtocolNote(note_id=note_id, protocol_id=protocol_id,
                            content=content, created_at=now, updated_at=now)

    def delete_note(self, protocol_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM protocol_notes WHERE protocol_id=?", (protocol_id,))
        return cur.rowcount > 0

    # ── Tags ──────────────────────────────────────────────────────────────

    def add_tag(self, protocol_id: str, tag: str) -> bool:
        tag = tag.lower().strip().replace(" ", "-")
        try:
            with self._conn() as c:
                c.execute("INSERT OR IGNORE INTO protocol_tags (tag_id,protocol_id,tag,created_at) VALUES (?,?,?,?)",
                          (str(uuid.uuid4()), protocol_id, tag, time.time()))
            return True
        except Exception:
            return False

    def remove_tag(self, protocol_id: str, tag: str) -> bool:
        tag = tag.lower().strip().replace(" ", "-")
        with self._conn() as c:
            cur = c.execute("DELETE FROM protocol_tags WHERE protocol_id=? AND tag=?",
                            (protocol_id, tag))
        return cur.rowcount > 0

    def get_tags(self, protocol_id: str) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT tag FROM protocol_tags WHERE protocol_id=? ORDER BY tag",
                             (protocol_id,)).fetchall()
        return [r["tag"] for r in rows]

    def get_all_tags(self) -> list[dict]:
        """Return all unique tags with usage count."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT tag, COUNT(*) as count
                FROM protocol_tags GROUP BY tag ORDER BY count DESC
            """).fetchall()
        return [{"tag": r["tag"], "count": r["count"]} for r in rows]

    def search_by_tag(self, tag: str) -> list[str]:
        """Return protocol IDs that have this tag."""
        with self._conn() as c:
            rows = c.execute("SELECT protocol_id FROM protocol_tags WHERE tag=?",
                             (tag.lower(),)).fetchall()
        return [r["protocol_id"] for r in rows]

    # ── Stars ─────────────────────────────────────────────────────────────

    def star(self, protocol_id: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO protocol_stars (protocol_id,starred,starred_at) VALUES (?,1,?)",
                      (protocol_id, time.time()))

    def unstar(self, protocol_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM protocol_stars WHERE protocol_id=?", (protocol_id,))

    def is_starred(self, protocol_id: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT 1 FROM protocol_stars WHERE protocol_id=?",
                            (protocol_id,)).fetchone()
        return row is not None

    def get_starred(self) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT protocol_id FROM protocol_stars ORDER BY starred_at DESC").fetchall()
        return [r["protocol_id"] for r in rows]

    # ── Links ─────────────────────────────────────────────────────────────

    def link_protocols(
        self, protocol_id: str, linked_id: str,
        relationship: str = "related", note: str = ""
    ) -> str:
        link_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute("""
                INSERT INTO protocol_links
                (link_id,protocol_id,linked_id,relationship,note,created_at)
                VALUES (?,?,?,?,?,?)
            """, (link_id, protocol_id, linked_id, relationship, note, time.time()))
        return link_id

    def get_links(self, protocol_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT * FROM protocol_links
                WHERE protocol_id=? OR linked_id=?
                ORDER BY created_at DESC
            """, (protocol_id, protocol_id)).fetchall()
        return [dict(r) for r in rows]

    # ── Execution Logs ────────────────────────────────────────────────────

    def log_execution(
        self,
        protocol_id:    str,
        outcome:        str,
        operator:       str   = "",
        observations:   str   = "",
        deviations:     str   = "",
        actual_time_min:float = 0.0,
        success:        bool  = False,
    ) -> ExecutionLog:
        log_id = str(uuid.uuid4())
        now    = time.time()
        with self._conn() as c:
            c.execute("""
                INSERT INTO execution_logs
                (log_id,protocol_id,executed_at,operator,outcome,
                 observations,deviations,actual_time_min,success)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (log_id, protocol_id, now, operator, outcome,
                  observations, deviations, actual_time_min, int(success)))
        log.info("execution_logged", protocol_id=protocol_id, outcome=outcome)
        return ExecutionLog(
            log_id=log_id, protocol_id=protocol_id, executed_at=now,
            operator=operator, outcome=outcome, observations=observations,
            deviations=deviations, actual_time_min=actual_time_min, success=success)

    def get_execution_logs(
        self, protocol_id: str, limit: int = 20
    ) -> list[ExecutionLog]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT * FROM execution_logs WHERE protocol_id=?
                ORDER BY executed_at DESC LIMIT ?
            """, (protocol_id, limit)).fetchall()
        return [ExecutionLog(
            log_id=r["log_id"], protocol_id=r["protocol_id"],
            executed_at=r["executed_at"], operator=r["operator"] or "",
            outcome=r["outcome"], observations=r["observations"] or "",
            deviations=r["deviations"] or "",
            actual_time_min=r["actual_time_min"] or 0.0,
            success=bool(r["success"])) for r in rows]

    # ── Summary ───────────────────────────────────────────────────────────

    def get_annotations(self, protocol_id: str) -> dict:
        """Get all annotations for a protocol in one call."""
        note     = self.get_note(protocol_id)
        tags     = self.get_tags(protocol_id)
        starred  = self.is_starred(protocol_id)
        links    = self.get_links(protocol_id)
        exe_logs = self.get_execution_logs(protocol_id, limit=5)
        return {
            "protocol_id": protocol_id,
            "note":        note.to_dict() if note else None,
            "tags":        tags,
            "starred":     starred,
            "links":       links,
            "execution_logs": [l.to_dict() for l in exe_logs],
            "execution_count": len(exe_logs),
            "success_rate": (
                sum(1 for l in exe_logs if l.success) / len(exe_logs)
                if exe_logs else None
            ),
        }