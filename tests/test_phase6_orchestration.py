"""
tests/test_phase6_orchestration.py

Tests for Phase 6: fleet models, resource lock manager, scheduler, and fleet.
Run with: pytest tests/test_phase6_orchestration.py -v
"""

from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))



import time
import pytest

from services.orchestration_service.core.fleet_models import (
    Conflict, FleetSchedule, FleetStatus,
    Resource, ResourceType, RobotAgent, RobotStatus, ScheduledTask,
)
from services.orchestration_service.core.resource_lock_manager import (
    ResourceLockManager, extract_resources,
)
from services.orchestration_service.core.scheduler import ProtocolScheduler, RobotFleet


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _robot(robot_id: str = "r1", name: str = "Robot 1") -> RobotAgent:
    return RobotAgent(robot_id=robot_id, name=name)

def _resource(rid: str = "centrifuge", rtype: ResourceType = ResourceType.CENTRIFUGE) -> Resource:
    return Resource(resource_id=rid, resource_type=rtype)

def _task(task_id: str = "t1", robot_id: str = "r1",
          start: float = 0, end: float = 600,
          resources: list | None = None) -> ScheduledTask:
    return ScheduledTask(
        task_id=task_id, plan_id="p1", protocol_id="proto1",
        protocol_title="Test", robot_id=robot_id,
        start_time_s=start, end_time_s=end,
        resources_locked=resources or [],
    )

SAMPLE_PLAN = {
    "plan_id":        "plan_001",
    "protocol_id":    "proto_001",
    "protocol_title": "BCA Assay",
    "estimated_mins": 30.0,
    "priority":       5,
    "commands": [
        {"command_type": "home",            "command_index": 0},
        {"command_type": "pick_up_tip",     "command_index": 1, "tip_rack_slot": 11},
        {"command_type": "aspirate",        "command_index": 2, "source": {"deck_slot": 1}, "volume_ul": 50},
        {"command_type": "dispense",        "command_index": 3, "destination": {"deck_slot": 2}, "volume_ul": 50},
        {"command_type": "drop_tip",        "command_index": 4},
        {"command_type": "incubate",        "command_index": 5, "slot": 7, "duration_s": 1800},
        {"command_type": "read_absorbance", "command_index": 6, "slot": 3, "wavelength_nm": 562},
        {"command_type": "home",            "command_index": 7},
    ],
}

SAMPLE_PLAN_2 = dict(SAMPLE_PLAN, plan_id="plan_002", protocol_id="proto_002",
                      protocol_title="PCR Protocol", estimated_mins=45.0)


# ---------------------------------------------------------------------------
# Fleet model tests
# ---------------------------------------------------------------------------

class TestFleetModels:

    def test_robot_is_available_when_idle(self):
        robot = _robot()
        assert robot.is_available is True

    def test_robot_not_available_when_running(self):
        robot = _robot()
        robot.status = RobotStatus.RUNNING
        robot.current_task_id = "t1"
        assert robot.is_available is False

    def test_robot_to_dict_keys(self):
        robot = _robot()
        d = robot.to_dict()
        for k in ["robot_id", "name", "status", "is_available", "location"]:
            assert k in d

    def test_scheduled_task_duration(self):
        task = _task(start=0, end=1800)
        assert task.duration_s == 1800
        assert task.duration_min == 30

    def test_tasks_overlap_true(self):
        t1 = _task("t1", start=0,    end=1800)
        t2 = _task("t2", start=900,  end=2700)
        assert t1.overlaps_with(t2) is True

    def test_tasks_overlap_false(self):
        t1 = _task("t1", start=0,    end=900)
        t2 = _task("t2", start=1000, end=2000)
        assert t1.overlaps_with(t2) is False

    def test_tasks_share_resource_true(self):
        r = _resource("centrifuge")
        t1 = _task("t1", resources=[r])
        t2 = _task("t2", resources=[r])
        assert t1.shares_resource_with(t2) is True

    def test_tasks_share_resource_false(self):
        r1 = _resource("centrifuge")
        r2 = _resource("plate_reader", ResourceType.PLATE_READER)
        t1 = _task("t1", resources=[r1])
        t2 = _task("t2", resources=[r2])
        assert t1.shares_resource_with(t2) is False

    def test_task_conflicts_when_overlap_and_shared_resource(self):
        r = _resource("centrifuge")
        t1 = _task("t1", start=0, end=1800, resources=[r])
        t2 = _task("t2", start=900, end=2700, resources=[r])
        assert t1.conflicts_with(t2) is True

    def test_task_no_conflict_when_no_overlap(self):
        r = _resource("centrifuge")
        t1 = _task("t1", start=0, end=900, resources=[r])
        t2 = _task("t2", start=1000, end=2000, resources=[r])
        assert t1.conflicts_with(t2) is False

    def test_fleet_schedule_to_dict(self):
        schedule = FleetSchedule(schedule_id="s1", tasks=[_task()], makespan_s=1800)
        d = schedule.to_dict()
        for k in ["schedule_id", "task_count", "makespan_min", "is_conflict_free"]:
            assert k in d

    def test_fleet_schedule_tasks_for_robot(self):
        t1 = _task("t1", robot_id="r1", start=0, end=600)
        t2 = _task("t2", robot_id="r2", start=0, end=600)
        t3 = _task("t3", robot_id="r1", start=700, end=1200)
        schedule = FleetSchedule(schedule_id="s1", tasks=[t1, t2, t3])
        r1_tasks = schedule.tasks_for_robot("r1")
        assert len(r1_tasks) == 2
        assert all(t.robot_id == "r1" for t in r1_tasks)

    def test_fleet_schedule_is_conflict_free_true(self):
        schedule = FleetSchedule(schedule_id="s1")
        assert schedule.is_conflict_free is True

    def test_fleet_schedule_is_conflict_free_false(self):
        c = Conflict("c1", "t1", "t2", "centrifuge", 0, 100, resolution="unresolved")
        schedule = FleetSchedule(schedule_id="s1", conflicts_detected=[c])
        assert schedule.is_conflict_free is False


# ---------------------------------------------------------------------------
# Resource lock manager tests
# ---------------------------------------------------------------------------

class TestResourceLockManager:

    def test_acquire_free_resource_succeeds(self):
        mgr = ResourceLockManager()
        resource = _resource()
        result = mgr.try_acquire(resource, "r1", "t1", 600)
        assert result.success is True
        assert result.lock_id is not None

    def test_acquire_held_resource_fails(self):
        mgr = ResourceLockManager()
        resource = _resource()
        mgr.try_acquire(resource, "r1", "t1", 600, schedule_time=time.time() + 100)
        result = mgr.try_acquire(resource, "r2", "t2", 600, schedule_time=time.time() + 100)
        assert result.success is False
        assert result.held_by == "r1"

    def test_same_robot_can_reacquire(self):
        mgr = ResourceLockManager()
        resource = _resource()
        mgr.try_acquire(resource, "r1", "t1", 600, schedule_time=time.time() + 100)
        result = mgr.try_acquire(resource, "r1", "t2", 600, schedule_time=time.time() + 100)
        assert result.success is True

    def test_release_frees_resource(self):
        mgr = ResourceLockManager()
        resource = _resource()
        mgr.try_acquire(resource, "r1", "t1", 600, schedule_time=time.time() + 100)
        mgr.release(resource.resource_id, "r1")
        result = mgr.try_acquire(resource, "r2", "t2", 600, schedule_time=time.time() + 200)
        assert result.success is True

    def test_release_all_frees_all_robot_locks(self):
        mgr = ResourceLockManager()
        r1 = _resource("centrifuge")
        r2 = _resource("plate_reader", ResourceType.PLATE_READER)
        t = time.time() + 100
        mgr.try_acquire(r1, "robot_a", "t1", 600, t)
        mgr.try_acquire(r2, "robot_a", "t1", 600, t)
        released = mgr.release_all("robot_a")
        assert released == 2

    def test_earliest_available_no_lock(self):
        mgr = ResourceLockManager()
        t = mgr.earliest_available("nonexistent")
        assert t <= time.time() + 1

    def test_snapshot_returns_dict(self):
        mgr = ResourceLockManager()
        mgr.try_acquire(_resource(), "r1", "t1", 600, time.time() + 100)
        snap = mgr.snapshot()
        assert "centrifuge" in snap


# ---------------------------------------------------------------------------
# Resource extraction tests
# ---------------------------------------------------------------------------

class TestExtractResources:

    def test_extracts_incubator(self):
        cmds = [{"command_type": "incubate", "slot": 7, "duration_s": 1800}]
        resources = extract_resources(cmds)
        types = {r.resource_type for r in resources}
        assert ResourceType.INCUBATOR in types

    def test_extracts_plate_reader(self):
        cmds = [{"command_type": "read_absorbance", "slot": 3, "wavelength_nm": 562}]
        resources = extract_resources(cmds)
        types = {r.resource_type for r in resources}
        assert ResourceType.PLATE_READER in types

    def test_extracts_tip_rack(self):
        cmds = [{"command_type": "pick_up_tip", "tip_rack_slot": 11}]
        resources = extract_resources(cmds)
        types = {r.resource_type for r in resources}
        assert ResourceType.TIP_RACK in types

    def test_deduplicates_resources(self):
        cmds = [
            {"command_type": "incubate", "slot": 7, "duration_s": 900},
            {"command_type": "incubate", "slot": 7, "duration_s": 1800},
        ]
        resources = extract_resources(cmds)
        incubators = [r for r in resources if r.resource_type == ResourceType.INCUBATOR]
        assert len(incubators) == 1

    def test_empty_commands_returns_empty(self):
        assert extract_resources([]) == []


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------

class TestProtocolScheduler:

    def _make_scheduler(self, n_robots: int = 2) -> ProtocolScheduler:
        robots = [_robot(f"r{i}", f"Robot {i}") for i in range(1, n_robots + 1)]
        return ProtocolScheduler(robots)

    def test_single_plan_scheduled(self):
        scheduler = self._make_scheduler(1)
        schedule = scheduler.schedule([SAMPLE_PLAN], epoch=0)
        assert schedule.task_count == 1

    def test_task_assigned_to_robot(self):
        scheduler = self._make_scheduler(1)
        schedule = scheduler.schedule([SAMPLE_PLAN], epoch=0)
        assert schedule.tasks[0].robot_id == "r1"

    def test_two_plans_two_robots_parallel(self):
        scheduler = self._make_scheduler(2)
        schedule = scheduler.schedule([SAMPLE_PLAN, SAMPLE_PLAN_2], epoch=0)
        robot_ids = {t.robot_id for t in schedule.tasks}
        # With 2 robots and 2 plans, both robots should be used
        assert len(robot_ids) == 2

    def test_two_plans_one_robot_sequential(self):
        scheduler = self._make_scheduler(1)
        schedule = scheduler.schedule([SAMPLE_PLAN, SAMPLE_PLAN_2], epoch=0)
        tasks = sorted(schedule.tasks, key=lambda t: t.start_time_s)
        # Second task must start after first ends (with gap)
        assert tasks[1].start_time_s >= tasks[0].end_time_s

    def test_makespan_positive(self):
        scheduler = self._make_scheduler(2)
        schedule = scheduler.schedule([SAMPLE_PLAN], epoch=0)
        assert schedule.makespan_s > 0

    def test_utilisation_between_0_and_1(self):
        scheduler = self._make_scheduler(2)
        schedule = scheduler.schedule([SAMPLE_PLAN, SAMPLE_PLAN_2], epoch=0)
        for util in schedule.robot_utilisation.values():
            assert 0.0 <= util <= 1.0

    def test_empty_plans_returns_empty_schedule(self):
        scheduler = self._make_scheduler(2)
        schedule = scheduler.schedule([])
        assert schedule.task_count == 0

    def test_conflict_resolution_delays_task(self):
        # Both plans need the incubator — should be delayed, not rejected
        scheduler = self._make_scheduler(1)
        schedule = scheduler.schedule([SAMPLE_PLAN, SAMPLE_PLAN_2], epoch=0)
        tasks = sorted(schedule.tasks, key=lambda t: t.start_time_s)
        assert len(tasks) == 2
        # All conflicts should be resolved
        assert schedule.is_conflict_free

    def test_schedule_to_dict_complete(self):
        scheduler = self._make_scheduler(2)
        schedule = scheduler.schedule([SAMPLE_PLAN], epoch=0)
        d = schedule.to_dict()
        for k in ["schedule_id", "task_count", "makespan_min",
                  "is_conflict_free", "tasks", "robot_utilisation"]:
            assert k in d


# ---------------------------------------------------------------------------
# RobotFleet tests
# ---------------------------------------------------------------------------

class TestRobotFleet:

    def _make_fleet(self) -> RobotFleet:
        return RobotFleet(robots=[_robot("r1", "R1"), _robot("r2", "R2")])

    def test_fleet_robot_count(self):
        fleet = self._make_fleet()
        assert fleet.robot_count == 2

    def test_fleet_schedule_returns_schedule(self):
        fleet = self._make_fleet()
        schedule = fleet.schedule([SAMPLE_PLAN])
        assert schedule.task_count == 1

    def test_dispatch_marks_running(self):
        fleet = self._make_fleet()
        schedule = fleet.schedule([SAMPLE_PLAN])
        task_id = schedule.tasks[0].task_id
        assert fleet.dispatch(task_id) is True

    def test_complete_marks_idle(self):
        fleet = self._make_fleet()
        schedule = fleet.schedule([SAMPLE_PLAN])
        task_id = schedule.tasks[0].task_id
        fleet.dispatch(task_id)
        assert fleet.complete(task_id) is True

    def test_fleet_status_has_robots(self):
        fleet = self._make_fleet()
        status = fleet.status()
        assert len(status.robots) == 2

    def test_add_robot_increases_count(self):
        fleet = self._make_fleet()
        fleet.add_robot(_robot("r3", "R3"))
        assert fleet.robot_count == 3

    def test_dispatch_nonexistent_task_fails(self):
        fleet = self._make_fleet()
        assert fleet.dispatch("nonexistent_task") is False

    def test_complete_nonexistent_task_fails(self):
        fleet = self._make_fleet()
        assert fleet.complete("nonexistent_task") is False