"""
core/scheduler_jobs.py — Experiment scheduling for AuroLab.
Uses Python's built-in threading + SQLite only. No APScheduler needed.
Schedules recurring protocol runs: once, hourly, daily, weekly.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import structlog
log = structlog.get_logger(__name__)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    job_id       TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    protocol_id  TEXT NOT NULL,
    schedule     TEXT NOT NULL,
    cron_expr    TEXT DEFAULT '',
    sim_mode     TEXT DEFAULT 'mock',
    enabled      INTEGER DEFAULT 1,
    interval_s   REAL DEFAULT 86400,
    last_run     REAL DEFAULT 0,
    next_run     REAL DEFAULT 0,
    run_count    INTEGER DEFAULT 0,
    created_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS job_runs (
    run_id    TEXT PRIMARY KEY,
    job_id    TEXT NOT NULL,
    started   REAL NOT NULL,
    finished  REAL,
    status    TEXT DEFAULT 'pending',
    result    TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_job ON job_runs(job_id);
"""

SCHEDULE_INTERVALS = {
    "once":    0,
    "hourly":  3600,
    "daily":   86400,
    "weekly":  604800,
    "monthly": 2592000,
}


@dataclass
class ScheduledJob:
    job_id:      str
    name:        str
    protocol_id: str
    schedule:    str
    cron_expr:   str   = ""
    sim_mode:    str   = "mock"
    enabled:     bool  = True
    interval_s:  float = 86400.0
    last_run:    float = 0.0
    next_run:    float = 0.0
    run_count:   int   = 0
    created_at:  float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "job_id":      self.job_id,
            "name":        self.name,
            "protocol_id": self.protocol_id,
            "schedule":    self.schedule,
            "cron_expr":   self.cron_expr,
            "sim_mode":    self.sim_mode,
            "enabled":     self.enabled,
            "interval_s":  self.interval_s,
            "last_run":    self.last_run,
            "next_run":    self.next_run,
            "run_count":   self.run_count,
            "created_at":  self.created_at,
        }


class JobScheduler:
    """
    Lightweight experiment scheduler backed by SQLite.
    Uses a background daemon thread to poll for due jobs every 60 seconds.
    No APScheduler dependency — works with Python stdlib only.
    """

    def __init__(
        self,
        db_path:         str      = "./data/scheduler.db",
        execute_fn:      Callable | None = None,
        poll_interval_s: int      = 60,
    ) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db             = db_path
        self._execute_fn     = execute_fn   # optional: services.execution_service execute_protocol
        self._poll_interval  = poll_interval_s
        self._stop_event     = threading.Event()

        with sqlite3.connect(self._db) as c:
            c.executescript(DB_SCHEMA)

        # Start background polling thread
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="scheduler")
        self._thread.start()
        log.info("scheduler_ready", db=db_path, poll_s=poll_interval_s)

    # ── Public API ────────────────────────────────────────────────────────────

    def add_job(
        self,
        name:        str,
        protocol_id: str,
        schedule:    str = "daily",
        cron_expr:   str = "",
        sim_mode:    str = "mock",
    ) -> ScheduledJob:
        jid        = str(uuid.uuid4())
        now        = time.time()
        interval_s = SCHEDULE_INTERVALS.get(schedule, 86400)
        next_run   = now + interval_s if interval_s > 0 else 0.0

        with sqlite3.connect(self._db) as c:
            c.execute("""
                INSERT INTO scheduled_jobs
                (job_id,name,protocol_id,schedule,cron_expr,sim_mode,
                 interval_s,next_run,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (jid, name, protocol_id, schedule, cron_expr,
                  sim_mode, interval_s, next_run, now))

        log.info("job_added", job_id=jid, name=name, schedule=schedule)
        return ScheduledJob(
            job_id=jid, name=name, protocol_id=protocol_id,
            schedule=schedule, cron_expr=cron_expr, sim_mode=sim_mode,
            interval_s=interval_s, next_run=next_run, created_at=now,
        )

    def list_jobs(self) -> list[dict]:
        with sqlite3.connect(self._db) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT * FROM scheduled_jobs ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_job(self, job_id: str) -> dict | None:
        with sqlite3.connect(self._db) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM scheduled_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_job(self, job_id: str) -> bool:
        with sqlite3.connect(self._db) as c:
            cur = c.execute("DELETE FROM scheduled_jobs WHERE job_id=?", (job_id,))
        deleted = cur.rowcount > 0
        if deleted:
            log.info("job_deleted", job_id=job_id)
        return deleted

    def enable_job(self, job_id: str, enabled: bool = True) -> None:
        with sqlite3.connect(self._db) as c:
            c.execute("UPDATE scheduled_jobs SET enabled=? WHERE job_id=?",
                      (int(enabled), job_id))

    def get_job_runs(self, job_id: str, limit: int = 20) -> list[dict]:
        with sqlite3.connect(self._db) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("""
                SELECT * FROM job_runs WHERE job_id=?
                ORDER BY started DESC LIMIT ?
            """, (job_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def trigger_now(self, job_id: str) -> str:
        """Immediately execute a job. Returns run_id."""
        return self._execute_job(job_id)

    def stop(self) -> None:
        self._stop_event.set()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Background thread: check for due jobs every poll_interval_s seconds."""
        while not self._stop_event.is_set():
            try:
                self._check_due_jobs()
            except Exception as e:
                log.error("scheduler_poll_error", error=str(e))
            self._stop_event.wait(timeout=self._poll_interval)

    def _check_due_jobs(self) -> None:
        now = time.time()
        with sqlite3.connect(self._db) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("""
                SELECT job_id FROM scheduled_jobs
                WHERE enabled=1 AND next_run > 0 AND next_run <= ?
            """, (now,)).fetchall()
        for row in rows:
            self._execute_job(row["job_id"])

    def _execute_job(self, job_id: str) -> str:
        run_id = str(uuid.uuid4())
        now    = time.time()

        with sqlite3.connect(self._db) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM scheduled_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        if not row:
            log.warning("job_not_found", job_id=job_id)
            return run_id

        job = dict(row)
        log.info("job_executing", job_id=job_id, name=job.get("name"))

        # Record start
        with sqlite3.connect(self._db) as c:
            c.execute(
                "INSERT INTO job_runs (run_id,job_id,started,status) VALUES (?,?,?,'running')",
                (run_id, job_id, now))
            c.execute("""
                UPDATE scheduled_jobs
                SET last_run=?, run_count=run_count+1,
                    next_run=CASE WHEN interval_s>0 THEN ?+interval_s ELSE 0 END
                WHERE job_id=?
            """, (now, now, job_id))

        # Execute — call execute_fn if provided, else log only
        status = "completed"
        result = ""
        try:
            if self._execute_fn:
                proto_id = job.get("protocol_id", "")
                result   = f"executed protocol {proto_id[:8]}"
                self._execute_fn(proto_id, job.get("sim_mode", "mock"))
            else:
                result = "mock run — no execute_fn attached"
            log.info("job_completed", job_id=job_id, run_id=run_id)
        except Exception as e:
            status = "failed"
            result = str(e)
            log.error("job_failed", job_id=job_id, error=str(e))

        # Record finish
        with sqlite3.connect(self._db) as c:
            c.execute("""
                UPDATE job_runs SET finished=?,status=?,result=?
                WHERE run_id=?
            """, (time.time(), status, result, run_id))

        return run_id