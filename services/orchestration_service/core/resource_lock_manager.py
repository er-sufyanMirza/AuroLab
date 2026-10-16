"""
aurolab/services/orchestration_service/core/resource_lock_manager.py

Thread-safe resource lock manager for shared lab instruments and deck slots.

A Resource is locked when a robot is using it. Attempting to acquire a
lock held by another robot returns the earliest time it will be free,
allowing the scheduler to insert a delay rather than failing.

Resources extracted from ExecutionPlan commands:
  - centrifuge     → ResourceType.CENTRIFUGE
  - incubate       → ResourceType.INCUBATOR
  - read_absorbance → ResourceType.PLATE_READER
  - pick_up_tip    → ResourceType.TIP_RACK (slot-specific)
  - aspirate/dispense → ResourceType.DECK_SLOT (source/dest slot)
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from .fleet_models import Resource, ResourceType

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lock record
# ---------------------------------------------------------------------------

@dataclass
class LockRecord:
    lock_id: str
    resource_id: str
    robot_id: str
    acquired_at: float
    held_until: float           # estimated release time (epoch seconds)
    task_id: str

    @property
    def is_expired(self) -> bool:
        return time.time() > self.held_until


# ---------------------------------------------------------------------------
# Resource extractor
# ---------------------------------------------------------------------------

# Commands that imply a shared instrument resource
_INSTRUMENT_MAP: dict[str, ResourceType] = {
    "centrifuge":      ResourceType.CENTRIFUGE,
    "incubate":        ResourceType.INCUBATOR,
    "read_absorbance": ResourceType.PLATE_READER,
    "read_fluorescence": ResourceType.PLATE_READER,
    "shake":           ResourceType.SHAKER,
}

_SLOT_COMMANDS = {"aspirate", "dispense", "mix", "move_to", "move_plate",
                  "incubate", "shake", "read_absorbance"}


def extract_resources(commands: list[dict]) -> list[Resource]:
    """
    Extract the set of shared resources needed by a command sequence.
    Returns deduplicated Resource list.
    """
    resources: dict[str, Resource] = {}

    for cmd in commands:
        cmd_type = cmd.get("command_type", "")

        # Instrument resources
        if cmd_type in _INSTRUMENT_MAP:
            rtype = _INSTRUMENT_MAP[cmd_type]
            rid = rtype.value
            if rid not in resources:
                resources[rid] = Resource(
                    resource_id=rid,
                    resource_type=rtype,
                )

        # Deck slot resources
        for slot_field in ("slot", "tip_rack_slot", "source_slot", "destination_slot"):
            slot = cmd.get(slot_field) or cmd.get("source", {}).get("deck_slot") \
                   or cmd.get("destination", {}).get("deck_slot")
            if slot and isinstance(slot, int) and cmd_type in _SLOT_COMMANDS:
                rid = f"deck_slot_{slot}"
                if rid not in resources:
                    resources[rid] = Resource(
                        resource_id=rid,
                        resource_type=ResourceType.DECK_SLOT,
                        deck_slot=slot,
                    )

        # Tip rack
        if cmd_type == "pick_up_tip":
            slot = cmd.get("tip_rack_slot", 11)
            rid = f"tip_rack_{slot}"
            if rid not in resources:
                resources[rid] = Resource(
                    resource_id=rid,
                    resource_type=ResourceType.TIP_RACK,
                    deck_slot=slot,
                )

    return list(resources.values())


# ---------------------------------------------------------------------------
# Resource lock manager
# ---------------------------------------------------------------------------

class ResourceLockManager:
    """
    Thread-safe manager for exclusive resource locks.

    Usage:
        manager = ResourceLockManager()
        result = manager.try_acquire(resource, robot_id, task_id, duration_s)
        if result.success:
            # proceed
        else:
            # result.available_at tells when the resource is free
    """

    def __init__(self) -> None:
        self._locks: dict[str, LockRecord] = {}   # resource_id → LockRecord
        self._mutex = threading.Lock()

    @dataclass
    class AcquireResult:
        success: bool
        lock_id: str | None = None
        available_at: float = 0.0   # only set on failure
        held_by: str | None = None  # robot_id currently holding it

    def try_acquire(
        self,
        resource: Resource,
        robot_id: str,
        task_id: str,
        duration_s: float,
        schedule_time: float | None = None,
    ) -> "ResourceLockManager.AcquireResult":
        """
        Attempt to acquire exclusive lock on a resource.

        Args:
            resource:      Resource to lock.
            robot_id:      Which robot is requesting.
            task_id:       Which task requires this resource.
            duration_s:    How long the lock needs to be held.
            schedule_time: If scheduling ahead of time, the wall-clock epoch
                           when the lock should start. Defaults to now.

        Returns:
            AcquireResult with success=True and lock_id on success,
            or success=False with available_at on failure.
        """
        start = schedule_time or time.time()
        end   = start + duration_s

        with self._mutex:
            existing = self._locks.get(resource.resource_id)

            if existing and not existing.is_expired and existing.robot_id != robot_id:
                # Resource is held by another robot
                log.debug("resource_lock_conflict",
                          resource=resource.resource_id,
                          held_by=existing.robot_id,
                          requested_by=robot_id)
                return self.AcquireResult(
                    success=False,
                    available_at=existing.held_until,
                    held_by=existing.robot_id,
                )

            # Grant the lock
            lock_id = str(uuid.uuid4())[:8]
            self._locks[resource.resource_id] = LockRecord(
                lock_id=lock_id,
                resource_id=resource.resource_id,
                robot_id=robot_id,
                acquired_at=start,
                held_until=end,
                task_id=task_id,
            )
            log.debug("resource_lock_acquired",
                      resource=resource.resource_id,
                      robot=robot_id,
                      duration_s=duration_s)
            return self.AcquireResult(success=True, lock_id=lock_id)

    def release(self, resource_id: str, robot_id: str) -> bool:
        """Release a lock held by robot_id. Returns True if released."""
        with self._mutex:
            lock = self._locks.get(resource_id)
            if lock and lock.robot_id == robot_id:
                del self._locks[resource_id]
                log.debug("resource_lock_released", resource=resource_id, robot=robot_id)
                return True
            return False

    def release_all(self, robot_id: str) -> int:
        """Release all locks held by a robot. Returns count released."""
        with self._mutex:
            to_release = [rid for rid, lock in self._locks.items()
                          if lock.robot_id == robot_id]
            for rid in to_release:
                del self._locks[rid]
            if to_release:
                log.info("robot_locks_released", robot=robot_id, count=len(to_release))
            return len(to_release)

    def earliest_available(self, resource_id: str) -> float:
        """Return the earliest time this resource will be free (epoch seconds)."""
        with self._mutex:
            lock = self._locks.get(resource_id)
            if not lock or lock.is_expired:
                return time.time()
            return lock.held_until

    def snapshot(self) -> dict[str, dict]:
        """Return current lock state for status display."""
        with self._mutex:
            return {
                rid: {
                    "robot_id":    lock.robot_id,
                    "task_id":     lock.task_id,
                    "held_until":  lock.held_until,
                    "is_expired":  lock.is_expired,
                }
                for rid, lock in self._locks.items()
            }

    def clear_expired(self) -> int:
        """Garbage-collect expired locks. Returns count removed."""
        with self._mutex:
            expired = [rid for rid, lock in self._locks.items() if lock.is_expired]
            for rid in expired:
                del self._locks[rid]
            return len(expired)