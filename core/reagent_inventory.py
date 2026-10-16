"""
services/translation_service/core/reagent_inventory.py

Reagent inventory management for AuroLab.
Tracks what's in the lab — quantities, expiry dates, locations.
Before protocol generation, checks if required reagents are available.
Warns when reagents are low or expired.

Storage: SQLite (same pattern as telemetry_store.py)
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
CREATE TABLE IF NOT EXISTS reagents (
    reagent_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    cas_number      TEXT,
    quantity_ml     REAL NOT NULL DEFAULT 0,
    quantity_g      REAL,
    unit            TEXT NOT NULL DEFAULT 'ml',
    location        TEXT,
    lot_number      TEXT,
    expiry_date     TEXT,
    supplier        TEXT,
    hazard_class    TEXT DEFAULT 'none',
    minimum_stock   REAL DEFAULT 10.0,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_log (
    log_id          TEXT PRIMARY KEY,
    reagent_id      TEXT NOT NULL,
    protocol_id     TEXT,
    quantity_used   REAL NOT NULL,
    unit            TEXT NOT NULL DEFAULT 'ml',
    used_at         REAL NOT NULL,
    notes           TEXT,
    FOREIGN KEY (reagent_id) REFERENCES reagents(reagent_id)
);
"""


@dataclass
class Reagent:
    reagent_id:   str
    name:         str
    quantity_ml:  float
    unit:         str       = "ml"
    quantity_g:   Optional[float] = None
    location:     str       = ""
    lot_number:   str       = ""
    expiry_date:  str       = ""
    supplier:     str       = ""
    hazard_class: str       = "none"
    minimum_stock:float     = 10.0
    cas_number:   str       = ""
    created_at:   float     = field(default_factory=time.time)
    updated_at:   float     = field(default_factory=time.time)

    @property
    def is_low(self) -> bool:
        return self.quantity_ml < self.minimum_stock

    @property
    def is_expired(self) -> bool:
        if not self.expiry_date:
            return False
        try:
            from datetime import datetime
            exp = datetime.strptime(self.expiry_date, "%Y-%m-%d")
            return exp < datetime.now()
        except ValueError:
            return False

    @property
    def status(self) -> str:
        if self.is_expired:  return "expired"
        if self.is_low:      return "low"
        return "ok"

    def to_dict(self) -> dict:
        return {
            "reagent_id":   self.reagent_id,
            "name":         self.name,
            "quantity_ml":  self.quantity_ml,
            "unit":         self.unit,
            "location":     self.location,
            "lot_number":   self.lot_number,
            "expiry_date":  self.expiry_date,
            "supplier":     self.supplier,
            "hazard_class": self.hazard_class,
            "minimum_stock":self.minimum_stock,
            "status":       self.status,
            "is_low":       self.is_low,
            "is_expired":   self.is_expired,
        }


@dataclass
class InventoryCheck:
    """Result of checking inventory against a protocol's reagent requirements."""
    protocol_id:    str
    all_available:  bool
    missing:        list[str]   = field(default_factory=list)
    low_stock:      list[str]   = field(default_factory=list)
    expired:        list[str]   = field(default_factory=list)
    warnings:       list[str]   = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "protocol_id":   self.protocol_id,
            "all_available": self.all_available,
            "missing":       self.missing,
            "low_stock":     self.low_stock,
            "expired":       self.expired,
            "warnings":      self.warnings,
        }


class ReagentInventory:
    """
    SQLite-backed reagent inventory store.
    One instance per AuroLab deployment, shared across all sessions.
    """

    def __init__(self, db_path: str = "./data/inventory.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(path)
        self._init_db()
        log.info("inventory_ready", path=self._db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(DB_SCHEMA)

    # ── Write ──────────────────────────────────────────────────────────────

    def add_reagent(
        self,
        name:          str,
        quantity_ml:   float,
        unit:          str   = "ml",
        expiry_date:   str   = "",
        location:      str   = "",
        supplier:      str   = "",
        lot_number:    str   = "",
        hazard_class:  str   = "none",
        minimum_stock: float = 10.0,
        cas_number:    str   = "",
    ) -> Reagent:
        now = time.time()
        rid = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO reagents
                (reagent_id,name,quantity_ml,unit,expiry_date,location,supplier,
                 lot_number,hazard_class,minimum_stock,cas_number,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (rid, name, quantity_ml, unit, expiry_date, location, supplier,
                  lot_number, hazard_class, minimum_stock, cas_number, now, now))
        log.info("reagent_added", name=name, quantity=quantity_ml, unit=unit)
        return self.get(rid)

    def update_quantity(
        self, reagent_id: str, new_quantity: float
    ) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE reagents SET quantity_ml=?, updated_at=? WHERE reagent_id=?",
                (new_quantity, time.time(), reagent_id)
            )
        return cur.rowcount > 0

    def consume(
        self, reagent_id: str, amount: float,
        protocol_id: str = "", notes: str = ""
    ) -> bool:
        """Deduct amount from inventory and log the usage."""
        r = self.get(reagent_id)
        if r is None:
            return False
        new_qty = max(0.0, r.quantity_ml - amount)
        with self._conn() as conn:
            conn.execute(
                "UPDATE reagents SET quantity_ml=?, updated_at=? WHERE reagent_id=?",
                (new_qty, time.time(), reagent_id)
            )
            conn.execute("""
                INSERT INTO usage_log
                (log_id,reagent_id,protocol_id,quantity_used,unit,used_at,notes)
                VALUES (?,?,?,?,?,?,?)
            """, (str(uuid.uuid4()), reagent_id, protocol_id,
                  amount, r.unit, time.time(), notes))
        log.info("reagent_consumed", reagent_id=reagent_id, amount=amount, remaining=new_qty)
        return True

    def delete(self, reagent_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM reagents WHERE reagent_id=?", (reagent_id,))
        return cur.rowcount > 0

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, reagent_id: str) -> Reagent | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM reagents WHERE reagent_id=?", (reagent_id,)
            ).fetchone()
        return self._row_to_reagent(row) if row else None

    def search(self, query: str = "") -> list[Reagent]:
        with self._conn() as conn:
            if query:
                rows = conn.execute(
                    "SELECT * FROM reagents WHERE name LIKE ? OR location LIKE ? ORDER BY name",
                    (f"%{query}%", f"%{query}%")
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reagents ORDER BY name"
                ).fetchall()
        return [self._row_to_reagent(r) for r in rows]

    def get_low_stock(self) -> list[Reagent]:
        return [r for r in self.search() if r.is_low and not r.is_expired]

    def get_expired(self) -> list[Reagent]:
        return [r for r in self.search() if r.is_expired]

    def usage_history(self, reagent_id: str, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT l.*, r.name as reagent_name
                FROM usage_log l JOIN reagents r ON l.reagent_id=r.reagent_id
                WHERE l.reagent_id=?
                ORDER BY l.used_at DESC LIMIT ?
            """, (reagent_id, limit)).fetchall()
        return [dict(r) for r in rows]

    # ── Inventory check against protocol ─────────────────────────────────

    def check_protocol(
        self, protocol_id: str, protocol_reagents: list[str]
    ) -> InventoryCheck:
        """
        Check if all reagents required by a protocol are available.
        Scored fuzzy matching — picks best match, not first partial match.
        Score = token overlap ratio. Threshold 0.4 avoids false positives.
        """
        all_reagents = self.search()

        missing   = []
        low_stock = []
        expired   = []
        warnings  = []

        for req in protocol_reagents:
            req_lower = req.lower()
            req_words = set(w for w in req_lower.split() if len(w) > 3)

            best_match = None
            best_score = 0.0

            for reagent in all_reagents:
                name_lower = reagent.name.lower()
                name_words = set(w for w in name_lower.split() if len(w) > 3)

                if req_lower == name_lower:
                    best_match = reagent
                    best_score = 1.0
                    break

                if req_words and name_words:
                    overlap = len(req_words & name_words)
                    score   = overlap / max(len(req_words), len(name_words))
                    if score > best_score:
                        best_score = score
                        best_match = reagent

            if best_score < 0.4:
                best_match = None

            if best_match is None:
                missing.append(req)
                warnings.append(f"'{req}' not found in inventory")
            elif best_match.is_expired:
                expired.append(best_match.name)
                warnings.append(f"'{best_match.name}' is EXPIRED (lot {best_match.lot_number})")
            elif best_match.is_low:
                low_stock.append(best_match.name)
                warnings.append(
                    f"'{best_match.name}' is LOW — "
                    f"{best_match.quantity_ml:.1f} {best_match.unit} remaining "
                    f"(min {best_match.minimum_stock})")

        return InventoryCheck(
            protocol_id=protocol_id,
            all_available=not missing and not expired,
            missing=missing,
            low_stock=low_stock,
            expired=expired,
            warnings=warnings,
        )

    @staticmethod
    def _row_to_reagent(row: sqlite3.Row) -> Reagent:
        return Reagent(
            reagent_id=row["reagent_id"],
            name=row["name"],
            quantity_ml=row["quantity_ml"],
            unit=row["unit"],
            quantity_g=row["quantity_g"],
            location=row["location"] or "",
            lot_number=row["lot_number"] or "",
            expiry_date=row["expiry_date"] or "",
            supplier=row["supplier"] or "",
            hazard_class=row["hazard_class"] or "none",
            minimum_stock=row["minimum_stock"],
            cas_number=row["cas_number"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )