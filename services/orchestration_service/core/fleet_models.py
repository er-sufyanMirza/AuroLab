"""
aurolab/services/orchestration_service/core/fleet_models.py

Typed domain model for multi-robot fleet orchestration.

Key concepts:
  RobotAgent       — one physical or simulated robot with capabilities
  Resource         — anything two robots can't share simultaneously
                     (deck slot, centrifuge, plate reader, tip rack)
  ScheduledTask    — one ExecutionPlan assigned to one robot with a start time
  FleetSchedule    — the full conflict-free assignment of tasks to robots
  ConflictReport   — what conflicts were detected and how they were resolved
  FleetStatus      — live per-robot status snapshot
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Resource types
# ---------------------------------------------------------------------------

class ResourceType(str, Enum):
    DECK_SLOT        = "deck_slot"
    TIP_RACK         = "tip_rack"
    CENTRIFUGE       = "centrifuge"
    PLATE_READER     = "plate_reader"
    INCUBATOR        = "incubator"
    SHAKER           = "shaker"
    WASTE_CONTAINER  = "waste_container"
    REAGENT_RESERVOIR= "reagent_reservoir"


@dataclass
class Resource:
    """A shared lab resource that can only be used by one robot at a time."""
    resource_id: str
    resource_type: ResourceType
    capacity: int = 1          # how many robots can use simultaneously (usually 1)
    deck_slot: int | None = None  # for slot resources, which slot number

    def __hash__(self) -> int:
        return hash(self.resource_id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Resource) and self.resource_id == other.resource_id


# ---------------------------------------------------------------------------
# Robot agent
# ---------------------------------------------------------------------------

class RobotStatus(str, Enum):
    IDLE       = "idle"
    RUNNING    = "running"
    PAUSED     = "paused"
    ERROR      = "error"
    OFFLINE    = "offline"


@dataclass
class RobotAgent:
    """
    One physical or simulated robot in the fleet.
    Tracks capabilities, current status, and running task.
    """
    robot_id: str
    name: str
    status: RobotStatus = RobotStatus.IDLE
    capabilities: set[str] = field(default_factory=lambda: {
        "aspirate", "dispense", "mix", "centrifuge",
        "incubate", "read_absorbance", "shake",
    })
    current_task_id: str | None = None
    available_from_s: float = 0.0   # earliest time this robot is free (relative to schedule start)
    deck_slots: list[int] = field(default_factory=lambda: list(range(1, 13)))
    location: str = "lab_bench_1"

    @property
    def is_available(self) -> bool:
        return self.status in (RobotStatus.IDLE,) and self.current_task_id is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "robot_id":         self.robot_id,
            "name":             self.name,
            "status":           self.status.value,
            "current_task_id":  self.current_task_id,
            "available_from_s": round(self.available_from_s, 1),
            "is_available":     self.is_available,
            "location":         self.location,
        }


# ---------------------------------------------------------------------------
# Scheduled task
# ---------------------------------------------------------------------------

@dataclass
class ScheduledTask:
    """
    One ExecutionPlan assigned to one robot with a specific start time.
    Carries all resource locks held during execution.
    """
    task_id: str
    plan_id: str
    protocol_id: str
    protocol_title: str
    robot_id: str
    start_time_s: float         # seconds from schedule epoch
    end_time_s: float
    resources_locked: list[Resource] = field(default_factory=list)
    priority: int = 5           # 1 (highest) → 10 (lowest)
    status: str = "scheduled"   # "scheduled" | "running" | "completed" | "failed"

    @property
    def duration_s(self) -> float:
        return self.end_time_s - self.start_time_s

    @property
    def duration_min(self) -> float:
        return self.duration_s / 60

    def overlaps_with(self, other: "ScheduledTask") -> bool:
        """True if this task's time window overlaps with another's."""
        return self.start_time_s < other.end_time_s and self.end_time_s > other.start_time_s

    def shares_resource_with(self, other: "ScheduledTask") -> bool:
        """True if both tasks need the same resource."""
        self_ids  = {r.resource_id for r in self.resources_locked}
        other_ids = {r.resource_id for r in other.resources_locked}
        return bool(self_ids & other_ids)

    def conflicts_with(self, other: "ScheduledTask") -> bool:
        """True if this task temporally overlaps AND shares a resource."""
        return self.overlaps_with(other) and self.shares_resource_with(other)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id":          self.task_id,
            "plan_id":          self.plan_id,
            "protocol_id":      self.protocol_id,
            "protocol_title":   self.protocol_title,
            "robot_id":         self.robot_id,
            "start_time_s":     round(self.start_time_s, 1),
            "end_time_s":       round(self.end_time_s, 1),
            "duration_min":     round(self.duration_min, 1),
            "priority":         self.priority,
            "status":           self.status,
            "resources_locked": [r.resource_id for r in self.resources_locked],
        }


# ---------------------------------------------------------------------------
# Conflict
# ---------------------------------------------------------------------------

@dataclass
class Conflict:
    """A detected resource conflict between two scheduled tasks."""
    conflict_id: str
    task_a_id: str
    task_b_id: str
    resource_id: str
    overlap_start_s: float
    overlap_end_s: float
    resolution: str = "unresolved"   # "delayed" | "reassigned" | "unresolved"
    resolution_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id":      self.conflict_id,
            "task_a":           self.task_a_id,
            "task_b":           self.task_b_id,
            "resource":         self.resource_id,
            "overlap_s":        round(self.overlap_end_s - self.overlap_start_s, 1),
            "resolution":       self.resolution,
            "resolution_detail":self.resolution_detail,
        }


# ---------------------------------------------------------------------------
# Fleet schedule
# ---------------------------------------------------------------------------

@dataclass
class FleetSchedule:
    """
    Complete conflict-free assignment of tasks to robots.
    The primary output of ProtocolScheduler.
    """
    schedule_id: str
    created_at: float = field(default_factory=time.time)
    tasks: list[ScheduledTask] = field(default_factory=list)
    conflicts_detected: list[Conflict] = field(default_factory=list)
    conflicts_resolved: int = 0
    makespan_s: float = 0.0          # total wall-clock time from start to last task end
    robot_utilisation: dict[str, float] = field(default_factory=dict)

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    @property
    def conflict_count(self) -> int:
        return len(self.conflicts_detected)

    @property
    def is_conflict_free(self) -> bool:
        return all(c.resolution != "unresolved" for c in self.conflicts_detected)

    def tasks_for_robot(self, robot_id: str) -> list[ScheduledTask]:
        return sorted(
            [t for t in self.tasks if t.robot_id == robot_id],
            key=lambda t: t.start_time_s,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id":        self.schedule_id,
            "created_at":         self.created_at,
            "task_count":         self.task_count,
            "makespan_min":       round(self.makespan_s / 60, 1),
            "conflict_count":     self.conflict_count,
            "conflicts_resolved": self.conflicts_resolved,
            "is_conflict_free":   self.is_conflict_free,
            "robot_utilisation":  {k: round(v, 3) for k, v in self.robot_utilisation.items()},
            "tasks":              [t.to_dict() for t in self.tasks],
            "conflicts":          [c.to_dict() for c in self.conflicts_detected],
        }


# ---------------------------------------------------------------------------
# Fleet status (live snapshot)
# ---------------------------------------------------------------------------

@dataclass
class FleetStatus:
    """Live snapshot of all robots and their current tasks."""
    snapshot_time: float = field(default_factory=time.time)
    robots: list[dict] = field(default_factory=list)
    active_tasks: int = 0
    idle_robots: int = 0
    error_robots: int = 0
    resource_locks: dict[str, str] = field(default_factory=dict)  # resource_id → robot_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_time": self.snapshot_time,
            "robots":        self.robots,
            "active_tasks":  self.active_tasks,
            "idle_robots":   self.idle_robots,
            "error_robots":  self.error_robots,
            "resource_locks":self.resource_locks,
        }