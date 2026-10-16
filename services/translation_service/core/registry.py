"""
aurolab/services/translation_service/core/registry.py

Thread-safe document registry.
Tracks ingestion status per SHA-256 hash.
In production, swap the in-memory dict for Redis or a Postgres table.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class DocumentRegistry:
    """
    Tracks document ingestion lifecycle: queued → processing → ready | failed.
    Persists to a JSON file so state survives restarts.
    """

    def __init__(self, persist_path: str = "./data/registry.json") -> None:
        self._path = Path(persist_path)
        self._lock = threading.Lock()
        self._store: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._store = json.loads(self._path.read_text())
            except Exception:
                self._store = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._store, indent=2))

    def register(self, sha256: str, filename: str) -> None:
        with self._lock:
            self._store[sha256] = {"filename": filename, "status": "queued"}
            self._save()

    def update_status(self, sha256: str, status: str, **kwargs) -> None:
        with self._lock:
            if sha256 not in self._store:
                self._store[sha256] = {}
            self._store[sha256]["status"] = status
            self._store[sha256].update(kwargs)
            self._save()

    def get(self, sha256: str) -> dict | None:
        with self._lock:
            return self._store.get(sha256)

    def remove(self, sha256: str) -> None:
        with self._lock:
            self._store.pop(sha256, None)
            self._save()

    def list_all(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._store)