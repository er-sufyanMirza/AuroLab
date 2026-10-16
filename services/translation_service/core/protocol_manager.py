"""
services/translation_service/core/protocol_manager.py

Protocol Manager — CRUD, search, filtering, and export for generated protocols.

Stores protocols in-memory (dict backed by protocol_id).
In production, swap the dict for Redis or PostgreSQL without changing the API.

Responsibilities:
  - Store and retrieve GeneratedProtocol objects
  - Search and filter by title, date, safety level
  - Export to JSON or markdown
  - Track generation history for the dashboard
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Protocol manager
# ---------------------------------------------------------------------------

class ProtocolManager:
    """
    In-memory store for GeneratedProtocol objects.

    Thread-safe for single-process FastAPI (GIL protects dict operations).
    For multi-worker deployments, replace self._store with Redis.
    """

    def __init__(self, db_path: str = "./data/protocols.db") -> None:
        self._store: dict[str, dict] = {}   # protocol_id → protocol dict (in-memory cache)
        self._db_path = db_path
        self._init_db()
        self._load_from_db()

    def _init_db(self) -> None:
        """Initialise SQLite persistence for protocol history."""
        import sqlite3
        from pathlib import Path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS protocols (
                    protocol_id TEXT PRIMARY KEY,
                    title       TEXT,
                    safety_level TEXT,
                    confidence  REAL,
                    steps       INTEGER,
                    saved_at    REAL,
                    data        TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS protocol_versions (
                    version_id     TEXT PRIMARY KEY,
                    protocol_id    TEXT,
                    version_num    INTEGER,
                    parent_id      TEXT,
                    saved_at       REAL,
                    change_reason  TEXT,
                    data           TEXT
                )
            """)

    def _load_from_db(self) -> None:
        """Load all protocols from SQLite into in-memory store on startup."""
        import sqlite3, json
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute("SELECT data FROM protocols ORDER BY saved_at DESC").fetchall()
            for (data_json,) in rows:
                try:
                    d = json.loads(data_json)
                    self._store[d["protocol_id"]] = d
                except Exception:
                    pass
            log.info("protocols_loaded_from_db", count=len(self._store))
        except Exception as e:
            log.warning("db_load_failed", error=str(e))

    def _persist(self, data: dict) -> None:
        """Persist a protocol to SQLite."""
        import sqlite3, json
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO protocols
                    (protocol_id, title, safety_level, confidence, steps, saved_at, data)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    data.get("protocol_id",""),
                    data.get("title",""),
                    data.get("safety_level","safe"),
                    data.get("confidence_score",0),
                    len(data.get("steps",[])),
                    data.get("saved_at",0),
                    json.dumps(data),
                ))
        except Exception as e:
            log.warning("db_persist_failed", error=str(e))

    def _persist_delete(self, protocol_id: str) -> None:
        import sqlite3
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM protocols WHERE protocol_id=?", (protocol_id,))
        except Exception:
            pass

    def get_versions(self, protocol_id: str) -> list[dict]:
        """Get version history for a protocol."""
        import sqlite3, json
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute("""
                    SELECT version_id, version_num, parent_id, saved_at, change_reason, data
                    FROM protocol_versions WHERE protocol_id=? ORDER BY version_num DESC
                """, (protocol_id,)).fetchall()
            return [{"version_id":r[0],"version_num":r[1],"parent_id":r[2],
                     "saved_at":r[3],"change_reason":r[4]} for r in rows]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(self, protocol: Any) -> None:
        """
        Store a GeneratedProtocol (accepts Pydantic model or dict).
        """
        if hasattr(protocol, "model_dump"):
            data = protocol.model_dump(mode="json")
        elif isinstance(protocol, dict):
            data = protocol
        else:
            raise TypeError(f"Unsupported protocol type: {type(protocol)}")

        pid = data.get("protocol_id")
        if not pid:
            raise ValueError("Protocol must have a protocol_id")

        data.setdefault("saved_at", time.time())
        self._store[pid] = data
        self._persist(data)
        log.info("protocol_saved", protocol_id=pid, title=data.get("title", ""))

    def delete(self, protocol_id: str) -> bool:
        """Delete a protocol. Returns True if it existed."""
        if protocol_id in self._store:
            del self._store[protocol_id]
            self._persist_delete(protocol_id)
            log.info("protocol_deleted", protocol_id=protocol_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, protocol_id: str) -> dict | None:
        """Retrieve a protocol by ID. Returns None if not found."""
        return self._store.get(protocol_id)

    def get_all(self) -> list[dict]:
        """Return all protocols, most recent first."""
        return sorted(
            self._store.values(),
            key=lambda p: p.get("saved_at", 0),
            reverse=True,
        )

    def count(self) -> int:
        return len(self._store)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str = "",
        safety_level: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """
        Search protocols by title/description text and optional safety level.

        Args:
            query:        Case-insensitive text search across title + description.
            safety_level: Filter by "safe", "caution", or "hazardous".
            limit:        Max results.
            offset:       Pagination offset.
        """
        results = list(self._store.values())
        q = query.lower().strip()

        if q:
            results = [
                p for p in results
                if q in p.get("title", "").lower()
                or q in p.get("description", "").lower()
                or any(q in step.get("instruction", "").lower()
                       for step in p.get("steps", []))
            ]

        if safety_level:
            results = [
                p for p in results
                if p.get("safety_level", "").lower() == safety_level.lower()
            ]

        # Sort by saved_at descending
        results = sorted(results, key=lambda p: p.get("saved_at", 0), reverse=True)
        return results[offset: offset + limit]

    def total(self, query: str = "", safety_level: str | None = None) -> int:
        """Return total count matching the given filters."""
        return len(self.search(query=query, safety_level=safety_level, limit=10_000))

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_json(self, protocol_id: str) -> str | None:
        """Export a protocol as a JSON string. Returns None if not found."""
        p = self.get(protocol_id)
        if p is None:
            return None
        return json.dumps(p, indent=2, ensure_ascii=False)

    def export_markdown(self, protocol_id: str) -> str | None:
        """
        Export a protocol as a human-readable Markdown document.
        Returns None if not found.
        """
        p = self.get(protocol_id)
        if p is None:
            return None

        lines = [
            f"# {p.get('title', 'Untitled Protocol')}",
            "",
            f"**Protocol ID:** `{p.get('protocol_id', '')}`  ",
            f"**Safety level:** {p.get('safety_level', 'unknown').upper()}  ",
            f"**Confidence:** {p.get('confidence_score', 0):.0%}  ",
            f"**Model:** {p.get('model_used', '—')}",
            "",
            f"> {p.get('description', '')}",
            "",
        ]

        # Safety notes
        notes = p.get("safety_notes", [])
        if notes:
            lines += ["## ⚠ Safety Notes", ""]
            for note in notes:
                lines.append(f"- {note}")
            lines.append("")

        # Reagents
        reagents = p.get("reagents", [])
        if reagents:
            lines += ["## Reagents", ""]
            for r in reagents:
                lines.append(f"- {r}")
            lines.append("")

        # Equipment
        equipment = p.get("equipment", [])
        if equipment:
            lines += ["## Equipment", ""]
            for e in equipment:
                lines.append(f"- {e}")
            lines.append("")

        # Protocol steps
        steps = p.get("steps", [])
        if steps:
            lines += ["## Protocol Steps", ""]
            for step in steps:
                num  = step.get("step_number", "?")
                inst = step.get("instruction", "")
                dur  = step.get("duration_seconds")
                temp = step.get("temperature_celsius")
                vol  = step.get("volume_ul")
                note = step.get("safety_note")
                cites = step.get("citations", [])

                meta = []
                if dur:
                    meta.append(f"{dur}s")
                if temp is not None:
                    meta.append(f"{temp}°C")
                if vol is not None:
                    meta.append(f"{vol}µL")

                cite_str = "  " + " ".join(f"[{c}]" for c in cites) if cites else ""
                meta_str = f"  _{', '.join(meta)}_" if meta else ""

                lines.append(f"**{num}.** {inst}{meta_str}{cite_str}")
                if note:
                    lines.append(f"   > ⚠ {note}")
                lines.append("")

        # Sources
        sources = p.get("sources_used", [])
        if sources:
            lines += ["## Sources", ""]
            for i, src in enumerate(sources, 1):
                chunk_id = src.get("chunk_id", "")
                source   = src.get("source", "")
                section  = src.get("section_title", "")
                page     = src.get("page_start", "")
                lines.append(f"[SOURCE_{i}] {source} — {section} (p.{page})")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # History summary (for dashboard)
    # ------------------------------------------------------------------

    def history_summary(self, limit: int = 20) -> list[dict]:
        """Return lightweight summaries for the history page."""
        return [
            {
                "protocol_id":     p.get("protocol_id"),
                "title":           p.get("title", "Untitled"),
                "safety_level":    p.get("safety_level", "unknown"),
                "confidence_score":round(p.get("confidence_score", 0), 2),
                "step_count":      len(p.get("steps", [])),
                "saved_at":        p.get("saved_at", 0),
                "model_used":      p.get("model_used", ""),
            }
            for p in self.get_all()[:limit]
        ]