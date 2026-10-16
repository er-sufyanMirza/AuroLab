"""
services/translation_service/core/workflow_engine.py

Multi-protocol workflow chains for AuroLab.
Connects protocols sequentially — output of one feeds into the next.

Example workflow:
  1. BCA Assay → measure protein concentration
  2. Western Blot Prep → use measured concentration to set loading volume
  3. Western Blot Run → execute with computed parameters

Workflows are stored in SQLite and can be reused.
Each step can have:
  - A fixed protocol
  - A condition (only run if previous step passed)
  - Parameter injection (take value from previous step output)
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

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id   TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    steps         TEXT NOT NULL,   -- JSON array of WorkflowStep dicts
    status        TEXT DEFAULT 'draft',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id        TEXT PRIMARY KEY,
    workflow_id   TEXT NOT NULL,
    status        TEXT DEFAULT 'pending',
    current_step  INTEGER DEFAULT 0,
    results       TEXT DEFAULT '[]',   -- JSON array of step results
    started_at    REAL,
    completed_at  REAL,
    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);
"""


@dataclass
class WorkflowStep:
    step_index:   int
    name:         str
    protocol_id:  str
    description:  str   = ""
    condition:    str   = "always"   # "always" | "on_pass" | "on_fail"
    inject_from:  int   = -1         # index of previous step to pull value from
    inject_field: str   = ""         # field name to inject
    inject_target:str   = ""         # where to inject in instruction template
    timeout_s:    float = 3600.0

    def to_dict(self) -> dict:
        return {
            "step_index":    self.step_index,
            "name":          self.name,
            "protocol_id":   self.protocol_id,
            "description":   self.description,
            "condition":     self.condition,
            "inject_from":   self.inject_from,
            "inject_field":  self.inject_field,
            "inject_target": self.inject_target,
            "timeout_s":     self.timeout_s,
        }

    @staticmethod
    def from_dict(d: dict) -> "WorkflowStep":
        return WorkflowStep(
            step_index=   d.get("step_index", 0),
            name=         d.get("name", ""),
            protocol_id=  d.get("protocol_id", ""),
            description=  d.get("description", ""),
            condition=    d.get("condition", "always"),
            inject_from=  d.get("inject_from", -1),
            inject_field= d.get("inject_field", ""),
            inject_target=d.get("inject_target", ""),
            timeout_s=    d.get("timeout_s", 3600.0),
        )


@dataclass
class WorkflowStepResult:
    step_index:  int
    name:        str
    protocol_id: str
    status:      str      = "pending"  # pending | running | passed | failed | skipped
    started_at:  float    = 0.0
    completed_at:float    = 0.0
    plan_id:     str      = ""
    sim_passed:  bool     = False
    reward:      float    = 0.0
    output_data: dict     = field(default_factory=dict)
    error:       str      = ""

    @property
    def duration_s(self) -> float:
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return 0.0

    def to_dict(self) -> dict:
        return {
            "step_index":   self.step_index,
            "name":         self.name,
            "protocol_id":  self.protocol_id,
            "status":       self.status,
            "started_at":   self.started_at,
            "completed_at": self.completed_at,
            "duration_s":   round(self.duration_s, 2),
            "plan_id":      self.plan_id,
            "sim_passed":   self.sim_passed,
            "reward":       round(self.reward, 4),
            "output_data":  self.output_data,
            "error":        self.error,
        }


@dataclass
class WorkflowRun:
    run_id:      str
    workflow_id: str
    status:      str                      = "pending"
    current_step:int                      = 0
    results:     list[WorkflowStepResult] = field(default_factory=list)
    started_at:  float                    = 0.0
    completed_at:float                    = 0.0

    @property
    def is_complete(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")

    @property
    def steps_passed(self) -> int:
        return sum(1 for r in self.results if r.status == "passed")

    @property
    def steps_failed(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    def to_dict(self) -> dict:
        return {
            "run_id":       self.run_id,
            "workflow_id":  self.workflow_id,
            "status":       self.status,
            "current_step": self.current_step,
            "steps_passed": self.steps_passed,
            "steps_failed": self.steps_failed,
            "total_steps":  len(self.results),
            "results":      [r.to_dict() for r in self.results],
            "started_at":   self.started_at,
            "completed_at": self.completed_at,
        }


class WorkflowEngine:
    """
    Manages workflow definitions and executes multi-protocol chains.
    """

    def __init__(self, db_path: str = "./data/workflows.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(path)
        self._init_db()
        log.info("workflow_engine_ready", path=self._db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(DB_SCHEMA)

    # ── Workflow CRUD ─────────────────────────────────────────────────────────

    def create_workflow(
        self,
        name:        str,
        steps:       list[WorkflowStep],
        description: str = "",
    ) -> str:
        wid = str(uuid.uuid4())
        now = time.time()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO workflows (workflow_id, name, description, steps, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (wid, name, description,
                  json.dumps([s.to_dict() for s in steps]), now, now))
        log.info("workflow_created", workflow_id=wid, name=name, steps=len(steps))
        return wid

    def get_workflow(self, workflow_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["steps"] = [WorkflowStep.from_dict(s).to_dict()
                      for s in json.loads(d["steps"])]
        return d

    def list_workflows(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT workflow_id, name, description, status, created_at FROM workflows ORDER BY created_at DESC"
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            result.append(d)
        return result

    def delete_workflow(self, workflow_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM workflows WHERE workflow_id=?", (workflow_id,))
        return cur.rowcount > 0

    # ── Execution ──────────────────────────────────────────────────────────────

    def start_run(self, workflow_id: str) -> WorkflowRun:
        """Create a new run for a workflow."""
        rid = str(uuid.uuid4())
        wf  = self.get_workflow(workflow_id)
        if not wf:
            raise ValueError(f"Workflow {workflow_id} not found")

        steps   = [WorkflowStep.from_dict(s) for s in wf["steps"]]
        results = [WorkflowStepResult(
            step_index=s.step_index, name=s.name, protocol_id=s.protocol_id
        ) for s in steps]

        now = time.time()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO workflow_runs (run_id, workflow_id, status, results, started_at)
                VALUES (?, ?, 'running', ?, ?)
            """, (rid, workflow_id, json.dumps([r.to_dict() for r in results]), now))

        log.info("workflow_run_started", run_id=rid, workflow_id=workflow_id)
        return WorkflowRun(run_id=rid, workflow_id=workflow_id,
                           status="running", results=results, started_at=now)

    def execute_step(
        self,
        run:        WorkflowRun,
        step_index: int,
        protocol_registry: dict,
        sim_mode:   str = "mock",
    ) -> WorkflowStepResult:
        """Execute a single step of a workflow run."""
        wf     = self.get_workflow(run.workflow_id)
        steps  = [WorkflowStep.from_dict(s) for s in wf["steps"]]
        step   = steps[step_index]
        result = run.results[step_index]

        result.started_at = time.time()
        result.status     = "running"

        # Check condition
        if step.condition == "on_pass" and step_index > 0:
            prev = run.results[step_index - 1]
            if not prev.sim_passed:
                result.status = "skipped"
                result.error  = f"Skipped — previous step '{prev.name}' did not pass"
                result.completed_at = time.time()
                return result

        if step.condition == "on_fail" and step_index > 0:
            prev = run.results[step_index - 1]
            if prev.sim_passed:
                result.status = "skipped"
                result.error  = f"Skipped — previous step '{prev.name}' passed (condition: on_fail)"
                result.completed_at = time.time()
                return result

        # Get protocol
        protocol = protocol_registry.get(step.protocol_id)
        if not protocol:
            result.status = "failed"
            result.error  = f"Protocol {step.protocol_id} not found in registry"
            result.completed_at = time.time()
            return result

        if hasattr(protocol, "model_dump"):
            protocol = protocol.model_dump(mode="json")

        # Parameter injection
        if step.inject_from >= 0 and step.inject_field and step.inject_target:
            prev_result = run.results[step.inject_from]
            inject_value = prev_result.output_data.get(step.inject_field)
            if inject_value is not None:
                # Inject into protocol description or first step instruction
                protocol = dict(protocol)
                protocol["description"] = protocol.get("description","") + \
                    f" [Injected from step {step.inject_from}: {step.inject_field}={inject_value}]"

        # Simulate
        try:
            from services.execution_service.core.orchestrator import execute_protocol
            from services.execution_service.core.isaac_sim_bridge import SimMode
            mode_map = {"mock": SimMode.MOCK, "pybullet": SimMode.PYBULLET}
            mode = mode_map.get(sim_mode, SimMode.MOCK)
            plan = execute_protocol(protocol, sim_mode=mode)

            result.plan_id    = plan.plan_id
            result.sim_passed = (plan.simulation_result is not None
                                 and plan.simulation_result.passed)
            result.status     = "passed" if result.sim_passed else "failed"
            if plan.simulation_result:
                result.output_data = plan.simulation_result.telemetry or {}

        except Exception as exc:
            result.status = "failed"
            result.error  = str(exc)
            log.error("workflow_step_failed", step=step.name, error=str(exc))

        result.completed_at = time.time()
        log.info("workflow_step_complete",
                 step=step.name, status=result.status,
                 duration_s=round(result.duration_s, 2))
        return result

    def get_run(self, run_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["results"] = json.loads(d["results"])
        return d

    def list_runs(self, workflow_id: str | None = None) -> list[dict]:
        with self._conn() as conn:
            if workflow_id:
                rows = conn.execute(
                    "SELECT * FROM workflow_runs WHERE workflow_id=? ORDER BY started_at DESC",
                    (workflow_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM workflow_runs ORDER BY started_at DESC LIMIT 50"
                ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["results"] = json.loads(d["results"])
            result.append(d)
        return result