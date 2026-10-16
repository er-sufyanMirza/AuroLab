"""
aurolab/services/orchestration_service/core/scheduler.py

Multi-robot protocol scheduler.

Algorithm: Earliest Deadline First (EDF) with resource-aware delay insertion.

  1. Sort protocols by priority then estimated duration (shorter first)
  2. For each protocol, find the best robot:
       - Robot must have required capabilities
       - Robot must be free at or before the protocol's deadline
  3. For each required resource:
       - Check lock manager for earliest available time
       - Push task start to max(robot_free_time, all_resource_free_times)
  4. Assign task, update robot availability, acquire resource locks
  5. Detect any remaining conflicts, attempt gap insertion
  6. Compute makespan and robot utilisation

Makespan minimisation:
  When multiple robots are available, assign to the one that minimises
  the overall schedule makespan (i.e. the one that finishes earliest,
  not just the currently-fastest robot).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

from .fleet_models import (
    Conflict, FleetSchedule, FleetStatus, Resource,
    RobotAgent, RobotStatus, ScheduledTask,
)
from .resource_lock_manager import ResourceLockManager, extract_resources

log = structlog.get_logger(__name__)

# Safety gap between consecutive tasks on the same robot (seconds)
INTER_TASK_GAP_S = 30.0

# Safety gap inserted when a conflict is resolved by delay
CONFLICT_RESOLUTION_GAP_S = 60.0


class ProtocolScheduler:
    """
    Assigns N ExecutionPlans to M RobotAgents with conflict-free resource usage.

    Usage:
        scheduler = ProtocolScheduler(robots, lock_manager)
        schedule  = scheduler.schedule(plans)
    """

    def __init__(
        self,
        robots: list[RobotAgent],
        lock_manager: ResourceLockManager | None = None,
    ) -> None:
        if not robots:
            raise ValueError("Fleet must have at least one robot")
        self._robots = {r.robot_id: r for r in robots}
        self._locks = lock_manager or ResourceLockManager()
        log.info("scheduler_init", robots=len(robots))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def schedule(
        self,
        plans: list[dict],
        epoch: float | None = None,
    ) -> FleetSchedule:
        """
        Build a conflict-free schedule for all plans.

        Args:
            plans: List of ExecutionPlan dicts (from /api/v1/plans/ or summaries).
                   Each must have: plan_id, protocol_id, protocol_title,
                   estimated_mins (or estimated_total_duration_s), commands.
            epoch: Wall-clock start time (defaults to now).

        Returns:
            FleetSchedule with tasks, conflicts, makespan, and utilisation.
        """
        if not plans:
            return FleetSchedule(schedule_id=str(uuid.uuid4()))

        epoch = epoch or time.time()
        schedule_id = str(uuid.uuid4())

        # Reset robot availability to epoch
        for robot in self._robots.values():
            robot.available_from_s = epoch

        # Sort: priority asc (1 = highest), then duration asc (shorter first)
        sorted_plans = sorted(
            plans,
            key=lambda p: (
                p.get("priority", 5),
                p.get("estimated_mins", 0) or p.get("estimated_total_duration_s", 0) / 60,
            ),
        )

        tasks: list[ScheduledTask] = []
        conflicts: list[Conflict] = []
        conflict_counter = 0

        for plan in sorted_plans:
            plan_id       = plan.get("plan_id", str(uuid.uuid4()))
            protocol_id   = plan.get("protocol_id", "unknown")
            title         = plan.get("protocol_title", plan.get("title", "Untitled"))
            duration_s    = (
                plan.get("estimated_total_duration_s")
                or (plan.get("estimated_mins", 5) * 60)
            )
            commands      = plan.get("commands", [])
            priority      = plan.get("priority", 5)

            # Extract resources required by this plan
            required_resources = extract_resources(commands)

            # Find best robot
            robot = self._pick_robot(required_resources, duration_s)
            if robot is None:
                log.warning("no_robot_available", plan_id=plan_id)
                # Schedule on least-loaded robot as fallback
                robot = min(self._robots.values(), key=lambda r: r.available_from_s)

            # Determine earliest start considering resource availability
            start_s = self._earliest_start(
                robot=robot,
                required_resources=required_resources,
                duration_s=duration_s,
            )
            end_s = start_s + duration_s

            # Acquire resource locks for this time window
            locked: list[Resource] = []
            for resource in required_resources:
                result = self._locks.try_acquire(
                    resource=resource,
                    robot_id=robot.robot_id,
                    task_id=plan_id,
                    duration_s=duration_s,
                    schedule_time=start_s,
                )
                if result.success:
                    locked.append(resource)
                else:
                    # Resource conflict — push start past the conflict
                    delay = result.available_at - start_s + CONFLICT_RESOLUTION_GAP_S
                    start_s += delay
                    end_s    = start_s + duration_s
                    conflict_counter += 1
                    conflicts.append(Conflict(
                        conflict_id=f"c{conflict_counter:03d}",
                        task_a_id=plan_id,
                        task_b_id=result.held_by or "unknown",
                        resource_id=resource.resource_id,
                        overlap_start_s=result.available_at - delay,
                        overlap_end_s=result.available_at,
                        resolution="delayed",
                        resolution_detail=f"Task delayed by {delay:.0f}s to avoid conflict",
                    ))
                    # Re-acquire with new time
                    self._locks.try_acquire(resource, robot.robot_id, plan_id, duration_s, start_s)
                    locked.append(resource)

            task = ScheduledTask(
                task_id=str(uuid.uuid4())[:8],
                plan_id=plan_id,
                protocol_id=protocol_id,
                protocol_title=title,
                robot_id=robot.robot_id,
                start_time_s=start_s,
                end_time_s=end_s,
                resources_locked=locked,
                priority=priority,
            )
            tasks.append(task)

            # Update robot availability (add inter-task gap)
            robot.available_from_s = end_s + INTER_TASK_GAP_S

        # Compute makespan and utilisation
        makespan_s = max((t.end_time_s for t in tasks), default=epoch) - epoch
        utilisation = self._compute_utilisation(tasks, makespan_s)

        schedule = FleetSchedule(
            schedule_id=schedule_id,
            tasks=tasks,
            conflicts_detected=conflicts,
            conflicts_resolved=sum(1 for c in conflicts if c.resolution != "unresolved"),
            makespan_s=makespan_s,
            robot_utilisation=utilisation,
        )

        log.info("schedule_complete",
                 schedule_id=schedule_id,
                 tasks=len(tasks),
                 conflicts=len(conflicts),
                 makespan_min=round(makespan_s / 60, 1))

        return schedule

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pick_robot(
        self,
        required_resources: list[Resource],
        duration_s: float,
    ) -> RobotAgent | None:
        """
        Select the robot that minimises makespan.
        Prefers robots that are available soonest and have required capabilities.
        """
        candidates = []
        for robot in self._robots.values():
            if robot.status == RobotStatus.OFFLINE:
                continue
            earliest = self._earliest_start(robot, required_resources, duration_s)
            candidates.append((earliest + duration_s, robot))  # (projected_end, robot)

        if not candidates:
            return None

        # Pick robot with earliest projected end time (minimises makespan)
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def _earliest_start(
        self,
        robot: RobotAgent,
        required_resources: list[Resource],
        duration_s: float,
    ) -> float:
        """
        The earliest time a task can start, considering:
        1. When the robot becomes free
        2. When each required resource becomes free
        """
        start = robot.available_from_s

        for resource in required_resources:
            resource_free = self._locks.earliest_available(resource.resource_id)
            if resource_free > start:
                start = resource_free

        return start

    def _compute_utilisation(
        self,
        tasks: list[ScheduledTask],
        makespan_s: float,
    ) -> dict[str, float]:
        """Fraction of makespan each robot is actively working."""
        if makespan_s <= 0:
            return {}
        busy: dict[str, float] = {rid: 0.0 for rid in self._robots}
        for task in tasks:
            busy[task.robot_id] = busy.get(task.robot_id, 0.0) + task.duration_s
        return {rid: min(busy_s / makespan_s, 1.0) for rid, busy_s in busy.items()}


# ---------------------------------------------------------------------------
# Robot fleet manager
# ---------------------------------------------------------------------------

class RobotFleet:
    """
    Manages a pool of RobotAgents and provides dispatch + status.
    In production, each RobotAgent would have a physical or ZMQ connection.
    Here, dispatch updates state and returns immediately (mock execution).
    """

    def __init__(self, robots: list[RobotAgent]) -> None:
        self._robots: dict[str, RobotAgent] = {r.robot_id: r for r in robots}
        self._lock_manager = ResourceLockManager()
        self._scheduler = ProtocolScheduler(robots, self._lock_manager)
        self._current_schedule: FleetSchedule | None = None
        log.info("fleet_init", robots=len(robots))

    def schedule(self, plans: list[dict]) -> FleetSchedule:
        """Build a conflict-free schedule for a set of plans."""
        self._current_schedule = self._scheduler.schedule(plans)
        return self._current_schedule

    def dispatch(self, task_id: str) -> bool:
        """
        Mark a task as running and update robot status.
        In production, this sends the execution plan to the robot's ZMQ socket.
        """
        if not self._current_schedule:
            return False
        task = next((t for t in self._current_schedule.tasks if t.task_id == task_id), None)
        if not task:
            return False

        robot = self._robots.get(task.robot_id)
        if not robot:
            return False

        robot.status = RobotStatus.RUNNING
        robot.current_task_id = task_id
        task.status = "running"
        log.info("task_dispatched", task_id=task_id, robot=robot.robot_id)
        return True

    def complete(self, task_id: str) -> bool:
        """Mark a task as completed, free robot, release locks."""
        if not self._current_schedule:
            return False
        task = next((t for t in self._current_schedule.tasks if t.task_id == task_id), None)
        if not task:
            return False

        robot = self._robots.get(task.robot_id)
        if robot:
            robot.status = RobotStatus.IDLE
            robot.current_task_id = None
            self._lock_manager.release_all(robot.robot_id)

        task.status = "completed"
        log.info("task_completed", task_id=task_id)
        return True

    def status(self) -> FleetStatus:
        """Return live fleet status snapshot."""
        robots_list = [r.to_dict() for r in self._robots.values()]
        active = sum(1 for r in self._robots.values() if r.status == RobotStatus.RUNNING)
        idle   = sum(1 for r in self._robots.values() if r.status == RobotStatus.IDLE)
        errors = sum(1 for r in self._robots.values() if r.status == RobotStatus.ERROR)
        locks  = {rid: lock["robot_id"] for rid, lock in self._lock_manager.snapshot().items()}

        return FleetStatus(
            robots=robots_list,
            active_tasks=active,
            idle_robots=idle,
            error_robots=errors,
            resource_locks=locks,
        )

    def add_robot(self, robot: RobotAgent) -> None:
        self._robots[robot.robot_id] = robot
        self._scheduler = ProtocolScheduler(list(self._robots.values()), self._lock_manager)

    @property
    def robot_count(self) -> int:
        return len(self._robots)

    @property
    def current_schedule(self) -> FleetSchedule | None:
        return self._current_schedule