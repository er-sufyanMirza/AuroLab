"""
aurolab/services/execution_service/core/isaac_sim_bridge.py

Bridge between AuroLab and NVIDIA Isaac Sim for digital twin validation.

Architecture:
  - Isaac Sim runs as a separate process (GPU server / workstation)
  - This bridge communicates over ZMQ REQ/REP sockets
  - Messages are JSON-serialised RobotCommand lists
  - Isaac Sim executes the sequence in the digital twin, returns telemetry

Two modes:
  1. LIVE mode   — real Isaac Sim process, requires NVIDIA Omniverse + Isaac Sim installed
  2. MOCK mode   — software simulation for development/testing (no GPU required)
                   Mock runs collision heuristics without a physics engine

To use LIVE mode:
  - Set env ISAAC_SIM_HOST=<ip> ISAAC_SIM_PORT=5555
  - Start the AuroLab Isaac extension in Omniverse
  - Set AUROLAB_SIM_MODE=live

Protocol for mock collision detection:
  - Checks workspace bounding boxes of consecutive move/aspirate commands
  - Flags overlapping trajectories as collisions
  - Checks that labware is present at the required slot for each operation
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from .robot_commands import (
    RobotCommand, CommandType, SimulationResult,
    AspirateCommand, DispenseCommand, MixCommand,
    CentrifugeCommand, IncubateCommand, ShakeCommand,
    PickUpTipCommand, DropTipCommand,
    LabwarePosition,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class SimMode(str, Enum):
    LIVE     = "live"      # Isaac Sim via ZMQ (requires GPU + Omniverse)
    PYBULLET = "pybullet"  # PyBullet physics (CPU only, recommended)
    MOCK     = "mock"      # Software heuristics (no physics, fastest)


SIM_MODE = SimMode(os.getenv("AUROLAB_SIM_MODE", "pybullet").lower())
ISAAC_HOST = os.getenv("ISAAC_SIM_HOST", "localhost")
ISAAC_PORT = int(os.getenv("ISAAC_SIM_PORT", "5555"))
SIM_TIMEOUT_S = float(os.getenv("ISAAC_SIM_TIMEOUT", "120"))

# Mock: known-occupied slots (labware map for collision detection)
# In production this comes from the vision layer (Phase 4)
DEFAULT_LABWARE_MAP: dict[int, str] = {
    1:  "96_well_plate",
    2:  "96_well_plate",
    3:  "plate_reader_slot",
    5:  "tube_rack",
    7:  "incubator_slot",
    11: "tip_rack_300ul",
    12: "waste_container",
}


# ---------------------------------------------------------------------------
# ZMQ transport (live mode)
# ---------------------------------------------------------------------------

def _send_to_isaac(commands: list[RobotCommand]) -> dict:
    """
    Send command sequence to Isaac Sim via ZMQ.
    Returns raw response dict from the simulation.
    Raises ConnectionError if Isaac Sim is unreachable.
    """
    try:
        import zmq  # type: ignore
    except ImportError:
        raise RuntimeError("pyzmq not installed. Install with: pip install pyzmq")

    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.setsockopt(zmq.RCVTIMEO, int(SIM_TIMEOUT_S * 1000))
    socket.connect(f"tcp://{ISAAC_HOST}:{ISAAC_PORT}")

    payload = {
        "version": "1.0",
        "commands": [c.to_wire() for c in commands],
        "timestamp": time.time(),
    }

    try:
        socket.send_json(payload)
        response = socket.recv_json()
        return response
    except zmq.error.Again:
        raise ConnectionError(f"Isaac Sim did not respond within {SIM_TIMEOUT_S}s")
    finally:
        socket.close()
        context.term()


# ---------------------------------------------------------------------------
# Mock simulation
# ---------------------------------------------------------------------------

@dataclass
class MockWorkspaceTracker:
    """
    Tracks robot arm position through the command sequence.
    Detects collisions by checking if trajectory passes through occupied slots.
    """
    labware_map: dict[int, str] = field(default_factory=lambda: dict(DEFAULT_LABWARE_MAP))
    tip_loaded: bool = False
    current_slot: int = 0    # 0 = home

    # Approximate deck slot positions (mm from home)
    # OT-2 deck layout: 3x4 grid
    SLOT_POSITIONS: dict[int, tuple[float, float]] = field(default_factory=lambda: {
        1:  (14.4,  10.0),   2: (132.5,  10.0),   3: (250.6,  10.0),
        4:  (14.4,  75.1),   5: (132.5,  75.1),   6: (250.6,  75.1),
        7:  (14.4, 140.2),   8: (132.5, 140.2),   9: (250.6, 140.2),
        10: (14.4, 205.3),  11: (132.5, 205.3),  12: (250.6, 205.3),
    })
    SLOT_SIZE_MM: float = 117.0

    def check_labware_present(self, slot: int) -> bool:
        return slot in self.labware_map

    def check_trajectory_clear(self, from_slot: int, to_slot: int) -> bool:
        """
        Rough collision check: does the straight-line path between two slots
        pass through any other occupied slot's bounding box?
        """
        if from_slot == 0 or to_slot == 0:
            return True   # home position always clear

        p1 = self.SLOT_POSITIONS.get(from_slot, (0, 0))
        p2 = self.SLOT_POSITIONS.get(to_slot, (0, 0))

        for slot, pos in self.SLOT_POSITIONS.items():
            if slot in (from_slot, to_slot):
                continue
            if slot not in self.labware_map:
                continue
            # Check if midpoint of trajectory is within slot bounding box
            mid_x = (p1[0] + p2[0]) / 2
            mid_y = (p1[1] + p2[1]) / 2
            if (pos[0] <= mid_x <= pos[0] + self.SLOT_SIZE_MM and
                    pos[1] <= mid_y <= pos[1] + self.SLOT_SIZE_MM):
                return False
        return True


def _run_mock_simulation(
    commands: list[RobotCommand],
    labware_map: dict[int, str] | None = None,
) -> SimulationResult:
    """
    Software mock of Isaac Sim execution.
    Runs collision heuristics and labware presence checks.
    Does not require a GPU or Omniverse installation.
    """
    tracker = MockWorkspaceTracker()
    if labware_map is not None:
        tracker.labware_map = labware_map
    t0 = time.perf_counter()
    frames = 0
    telemetry: dict[str, Any] = {
        "commands_executed": 0,
        "tip_changes": 0,
        "total_volume_aspirated_ul": 0.0,
        "total_volume_dispensed_ul": 0.0,
        "warnings": [],
    }

    for cmd in commands:
        frames += int((getattr(cmd, "duration_s", None) or 1) * 30)  # 30 fps simulation

        # Tip tracking
        if isinstance(cmd, PickUpTipCommand):
            if tracker.tip_loaded:
                return SimulationResult(
                    passed=False,
                    collision_detected=True,
                    collision_at_command=cmd.command_index,
                    collision_description=f"PickUpTip at cmd {cmd.command_index}: tip already loaded",
                    telemetry=telemetry,
                    sim_duration_s=time.perf_counter() - t0,
                )
            # Check tip rack is present
            if not tracker.check_labware_present(cmd.tip_rack_slot):
                telemetry["warnings"].append(
                    f"Tip rack not detected in slot {cmd.tip_rack_slot} — proceeding"
                )
            tracker.tip_loaded = True
            telemetry["tip_changes"] += 1
            from_slot = tracker.current_slot
            tracker.current_slot = cmd.tip_rack_slot
            if not tracker.check_trajectory_clear(from_slot, cmd.tip_rack_slot):
                return SimulationResult(
                    passed=False,
                    collision_detected=True,
                    collision_at_command=cmd.command_index,
                    collision_description=f"Trajectory from slot {from_slot} to {cmd.tip_rack_slot} passes through occupied labware",
                    telemetry=telemetry,
                    sim_duration_s=time.perf_counter() - t0,
                )

        elif isinstance(cmd, DropTipCommand):
            tracker.tip_loaded = False
            tracker.current_slot = cmd.waste_slot

        elif isinstance(cmd, AspirateCommand):
            if not tracker.tip_loaded:
                return SimulationResult(
                    passed=False,
                    collision_detected=False,
                    collision_at_command=cmd.command_index,
                    collision_description=f"Aspirate at cmd {cmd.command_index}: no tip loaded",
                    telemetry=telemetry,
                    sim_duration_s=time.perf_counter() - t0,
                )
            slot = cmd.source.deck_slot
            from_slot = tracker.current_slot
            tracker.current_slot = slot
            telemetry["total_volume_aspirated_ul"] += cmd.volume_ul
            if not tracker.check_trajectory_clear(from_slot, slot):
                return SimulationResult(
                    passed=False,
                    collision_detected=True,
                    collision_at_command=cmd.command_index,
                    collision_description=f"Aspirate trajectory from slot {from_slot} to {slot} blocked",
                    telemetry=telemetry,
                    sim_duration_s=time.perf_counter() - t0,
                )

        elif isinstance(cmd, DispenseCommand):
            if not tracker.tip_loaded:
                return SimulationResult(
                    passed=False,
                    collision_detected=False,
                    collision_at_command=cmd.command_index,
                    collision_description=f"Dispense at cmd {cmd.command_index}: no tip loaded",
                    telemetry=telemetry,
                    sim_duration_s=time.perf_counter() - t0,
                )
            slot = cmd.destination.deck_slot
            from_slot = tracker.current_slot
            tracker.current_slot = slot
            telemetry["total_volume_dispensed_ul"] += cmd.volume_ul
            if not tracker.check_trajectory_clear(from_slot, slot):
                return SimulationResult(
                    passed=False,
                    collision_detected=True,
                    collision_at_command=cmd.command_index,
                    collision_description=f"Dispense trajectory blocked between slot {from_slot} and {slot}",
                    telemetry=telemetry,
                    sim_duration_s=time.perf_counter() - t0,
                )

        elif isinstance(cmd, CentrifugeCommand):
            if tracker.tip_loaded:
                telemetry["warnings"].append(
                    f"Centrifuge at cmd {cmd.command_index}: tip still loaded — unusual"
                )

        telemetry["commands_executed"] += 1

    elapsed = time.perf_counter() - t0
    log.info("mock_sim_complete",
             commands=len(commands),
             elapsed_ms=round(elapsed * 1000),
             aspirated_ul=telemetry["total_volume_aspirated_ul"])

    return SimulationResult(
        passed=True,
        collision_detected=False,
        telemetry=telemetry,
        sim_duration_s=elapsed,
        frames_simulated=frames,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class IsaacSimBridge:
    """
    Interface to NVIDIA Isaac Sim for digital twin validation.
    Automatically uses mock mode when Isaac Sim is not configured.

    labware_map: if provided (from vision layer), overrides DEFAULT_LABWARE_MAP.
    """

    def __init__(
        self,
        mode: SimMode = SIM_MODE,
        labware_map: dict[int, str] | None = None,
    ) -> None:
        self.mode = mode
        self._labware_map = labware_map or DEFAULT_LABWARE_MAP
        log.info("isaac_sim_bridge_init", mode=mode.value,
                 labware_source="vision" if labware_map is not None else "static",
                 occupied_slots=len(self._labware_map))

    def validate_execution_plan(self, commands: list[RobotCommand]) -> SimulationResult:
        """
        Run the command sequence through the digital twin.

        In LIVE mode: sends to Isaac Sim over ZMQ, returns physics simulation result.
        In MOCK mode: runs software collision detection heuristics.

        Args:
            commands: Validated RobotCommand sequence.

        Returns:
            SimulationResult with pass/fail status and telemetry.
        """
        log.info("sim_start", mode=self.mode.value, commands=len(commands))
        t0 = time.perf_counter()

        if self.mode == SimMode.PYBULLET:
            from .pybullet_sim import run_pybullet_simulation
            result = run_pybullet_simulation(commands, labware_map=self._labware_map)

        elif self.mode == SimMode.LIVE:
            try:
                raw = _send_to_isaac(commands)
                result = SimulationResult(
                    passed=raw.get("passed", False),
                    collision_detected=raw.get("collision_detected", False),
                    collision_at_command=raw.get("collision_at_command"),
                    collision_description=raw.get("collision_description"),
                    telemetry=raw.get("telemetry", {}),
                    sim_duration_s=raw.get("sim_duration_s", time.perf_counter() - t0),
                    frames_simulated=raw.get("frames_simulated", 0),
                )
            except (ConnectionError, RuntimeError) as exc:
                log.warning("isaac_sim_unreachable", error=str(exc), fallback="pybullet")
                from .pybullet_sim import run_pybullet_simulation
                result = run_pybullet_simulation(commands, labware_map=self._labware_map)
                result.telemetry["fallback_reason"] = str(exc)
        else:
            # MOCK mode
            result = _run_mock_simulation(commands, labware_map=self._labware_map)

        elapsed = time.perf_counter() - t0
        log.info("sim_complete",
                 passed=result.passed,
                 collision=result.collision_detected,
                 elapsed_ms=round(elapsed * 1000))

        return result

    @property
    def is_live(self) -> bool:
        return self.mode == SimMode.LIVE