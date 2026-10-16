"""
aurolab/services/rl_service/core/telemetry_store.py

Persistent execution telemetry store for RL training.

Every time a protocol is simulated (mock or live), the telemetry is
appended here. The RL agent reads this store to learn which parameter
configurations produced better outcomes.

Schema:
  execution_runs:
    run_id         TEXT PRIMARY KEY
    protocol_id    TEXT
    protocol_title TEXT
    timestamp      REAL
    sim_mode       TEXT        -- "mock" | "live"
    passed         INTEGER     -- 1 = success, 0 = failure
    commands_executed INTEGER
    tip_changes    INTEGER
    volume_aspirated_ul  REAL
    volume_dispensed_ul  REAL
    total_distance_mm    REAL
    duration_s           REAL
    collision_detected   INTEGER
    collision_at         INTEGER
    flow_rate_avg        REAL    -- avg flow rate across aspirate/dispense commands
    centrifuge_rpm_avg   REAL
    incubate_temp_avg    REAL
    reward               REAL    -- computed by RewardModel
    telemetry_json       TEXT    -- full raw telemetry blob

  parameter_suggestions:
    suggestion_id  TEXT PRIMARY KEY
    protocol_id    TEXT
    created_at     REAL
    parameter      TEXT
    current_value  REAL
    suggested_value REAL
    expected_reward_delta REAL
    status         TEXT        -- "pending" | "accepted" | "rejected"
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

DEFAULT_DB_PATH = "./data/telemetry.db"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ExecutionRun:
    """One execution record stored in the telemetry DB."""
    run_id: str
    protocol_id: str
    protocol_title: str
    timestamp: float
    sim_mode: str
    passed: bool
    commands_executed: int
    tip_changes: int
    volume_aspirated_ul: float
    volume_dispensed_ul: float
    total_distance_mm: float
    duration_s: float
    collision_detected: bool
    collision_at: int | None
    flow_rate_avg: float
    centrifuge_rpm_avg: float
    incubate_temp_avg: float
    reward: float
    telemetry_json: str

    @classmethod
    def from_sim_result(
        cls,
        protocol_id: str,
        protocol_title: str,
        sim_result: dict,
        commands: list[dict],
        sim_mode: str = "mock",
        reward: float = 0.0,
    ) -> "ExecutionRun":
        tel = sim_result.get("telemetry", {})

        # Extract parameter averages from commands
        flow_rates = [c.get("flow_rate_ul_s", 150.0) for c in commands
                      if c.get("command_type") in ("aspirate", "dispense")]
        centrifuge_rpms = [c.get("speed_rpm", 0) for c in commands
                           if c.get("command_type") == "centrifuge"]
        incubate_temps = [c.get("temperature_celsius", 0) for c in commands
                          if c.get("command_type") == "incubate"]

        return cls(
            run_id=str(uuid.uuid4()),
            protocol_id=protocol_id,
            protocol_title=protocol_title,
            timestamp=time.time(),
            sim_mode=sim_mode,
            passed=sim_result.get("passed", False),
            commands_executed=tel.get("commands_executed", 0),
            tip_changes=tel.get("tip_changes", 0),
            volume_aspirated_ul=tel.get("total_volume_aspirated_ul", 0.0),
            volume_dispensed_ul=tel.get("total_volume_dispensed_ul", 0.0),
            total_distance_mm=tel.get("total_distance_mm", 0.0),
            duration_s=sim_result.get("sim_duration_s", 0.0),
            collision_detected=sim_result.get("collision_detected", False),
            collision_at=sim_result.get("collision_at_command"),
            flow_rate_avg=sum(flow_rates) / len(flow_rates) if flow_rates else 150.0,
            centrifuge_rpm_avg=sum(centrifuge_rpms) / len(centrifuge_rpms) if centrifuge_rpms else 0.0,
            incubate_temp_avg=sum(incubate_temps) / len(incubate_temps) if incubate_temps else 0.0,
            reward=reward,
            telemetry_json=json.dumps(tel),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id":               self.run_id,
            "protocol_id":          self.protocol_id,
            "protocol_title":       self.protocol_title,
            "timestamp":            self.timestamp,
            "sim_mode":             self.sim_mode,
            "passed":               self.passed,
            "commands_executed":    self.commands_executed,
            "tip_changes":          self.tip_changes,
            "volume_aspirated_ul":  round(self.volume_aspirated_ul, 2),
            "volume_dispensed_ul":  round(self.volume_dispensed_ul, 2),
            "total_distance_mm":    round(self.total_distance_mm, 2),
            "duration_s":           round(self.duration_s, 3),
            "collision_detected":   self.collision_detected,
            "flow_rate_avg":        round(self.flow_rate_avg, 2),
            "centrifuge_rpm_avg":   round(self.centrifuge_rpm_avg, 1),
            "incubate_temp_avg":    round(self.incubate_temp_avg, 1),
            "reward":               round(self.reward, 4),
        }


@dataclass
class ParameterSuggestion:
    suggestion_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    protocol_id: str = ""
    created_at: float = field(default_factory=time.time)
    parameter: str = ""          # e.g. "flow_rate_ul_s", "centrifuge_rpm"
    current_value: float = 0.0
    suggested_value: float = 0.0
    expected_reward_delta: float = 0.0
    rationale: str = ""
    status: str = "pending"      # "pending" | "accepted" | "rejected"

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestion_id":         self.suggestion_id,
            "protocol_id":           self.protocol_id,
            "parameter":             self.parameter,
            "current_value":         round(self.current_value, 4),
            "suggested_value":       round(self.suggested_value, 4),
            "expected_reward_delta": round(self.expected_reward_delta, 4),
            "rationale":             self.rationale,
            "status":                self.status,
        }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class TelemetryStore:
    """
    SQLite-backed store for execution runs and parameter suggestions.
    Thread-safe via connection-per-call pattern.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        log.info("telemetry_store_ready", path=str(self._db_path))

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_runs (
                    run_id TEXT PRIMARY KEY,
                    protocol_id TEXT NOT NULL,
                    protocol_title TEXT,
                    timestamp REAL,
                    sim_mode TEXT,
                    passed INTEGER,
                    commands_executed INTEGER,
                    tip_changes INTEGER,
                    volume_aspirated_ul REAL,
                    volume_dispensed_ul REAL,
                    total_distance_mm REAL,
                    duration_s REAL,
                    collision_detected INTEGER,
                    collision_at INTEGER,
                    flow_rate_avg REAL,
                    centrifuge_rpm_avg REAL,
                    incubate_temp_avg REAL,
                    reward REAL,
                    telemetry_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS parameter_suggestions (
                    suggestion_id TEXT PRIMARY KEY,
                    protocol_id TEXT,
                    created_at REAL,
                    parameter TEXT,
                    current_value REAL,
                    suggested_value REAL,
                    expected_reward_delta REAL,
                    rationale TEXT,
                    status TEXT DEFAULT 'pending'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_protocol ON execution_runs(protocol_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_time ON execution_runs(timestamp)")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_run(self, run: ExecutionRun) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO execution_runs VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                run.run_id, run.protocol_id, run.protocol_title,
                run.timestamp, run.sim_mode,
                int(run.passed), run.commands_executed, run.tip_changes,
                run.volume_aspirated_ul, run.volume_dispensed_ul,
                run.total_distance_mm, run.duration_s,
                int(run.collision_detected), run.collision_at,
                run.flow_rate_avg, run.centrifuge_rpm_avg, run.incubate_temp_avg,
                run.reward, run.telemetry_json,
            ))
        log.info("run_recorded", run_id=run.run_id, reward=round(run.reward, 4))

    def save_suggestion(self, suggestion: ParameterSuggestion) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO parameter_suggestions VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                suggestion.suggestion_id, suggestion.protocol_id,
                suggestion.created_at, suggestion.parameter,
                suggestion.current_value, suggestion.suggested_value,
                suggestion.expected_reward_delta, suggestion.rationale,
                suggestion.status,
            ))

    def update_suggestion_status(self, suggestion_id: str, status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE parameter_suggestions SET status=? WHERE suggestion_id=?",
                (status, suggestion_id),
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_runs(
        self,
        protocol_id: str | None = None,
        limit: int = 100,
        passed_only: bool = False,
    ) -> list[dict]:
        where = []
        params: list = []
        if protocol_id:
            where.append("protocol_id = ?")
            params.append(protocol_id)
        if passed_only:
            where.append("passed = 1")
        where_clause = "WHERE " + " AND ".join(where) if where else ""
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM execution_runs {where_clause} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_suggestions(self, protocol_id: str | None = None, status: str = "pending") -> list[dict]:
        where = ["status = ?"]
        params: list = [status]
        if protocol_id:
            where.append("protocol_id = ?")
            params.append(protocol_id)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM parameter_suggestions WHERE {' AND '.join(where)} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def aggregate_stats(self, protocol_id: str | None = None) -> dict[str, Any]:
        where = "WHERE protocol_id = ?" if protocol_id else ""
        params = [protocol_id] if protocol_id else []
        with self._conn() as conn:
            row = conn.execute(f"""
                SELECT
                    COUNT(*) as total_runs,
                    SUM(passed) as successful_runs,
                    AVG(reward) as avg_reward,
                    MAX(reward) as best_reward,
                    AVG(duration_s) as avg_duration_s,
                    AVG(volume_aspirated_ul) as avg_volume_ul,
                    SUM(tip_changes) as total_tip_changes,
                    AVG(total_distance_mm) as avg_distance_mm
                FROM execution_runs {where}
            """, params).fetchone()
        d = dict(row) if row else {}
        d["success_rate"] = round(
            (d.get("successful_runs") or 0) / max(d.get("total_runs") or 1, 1), 4
        )
        return d

    def get_reward_trend(self, protocol_id: str, last_n: int = 50) -> list[dict]:
        """Return reward values over time for a protocol (for trend chart)."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT run_id, timestamp, reward, passed, sim_mode
                FROM execution_runs
                WHERE protocol_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (protocol_id, last_n)).fetchall()
        return [dict(r) for r in rows]