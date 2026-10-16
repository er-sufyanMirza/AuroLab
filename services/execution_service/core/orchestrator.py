"""
aurolab/services/execution_service/core/orchestrator.py

Execution orchestrator — ties the full Phase 3 pipeline together.

Pipeline:
  GeneratedProtocol
    → parse_protocol_steps()     [step_parser]
    → validate_commands()        [validator]
    → IsaacSimBridge.validate()  [isaac_sim_bridge]
    → ExecutionPlan              [robot_commands]

The orchestrator also implements the auto-correction retry loop:
  If simulation fails with a collision, it attempts to re-plan the
  affected segment (up to MAX_REPLAN_ATTEMPTS) before returning FAILED.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional
import structlog

from .robot_commands import (
    ExecutionPlan, ExecutionStatus, SimulationResult,
    RobotCommand, ValidationError,
)
from .step_parser import parse_protocol_steps
from .validator import validate_commands
from .isaac_sim_bridge import IsaacSimBridge, SimMode

# Vision layer — optional import, graceful fallback if vision package not on path
try:
    from services.vision_service.core.lab_state import LabState
except ImportError:
    try:
        from vision_service.core.lab_state import LabState  # fallback for alternate layouts
    except ImportError:
        LabState = None  # type: ignore[assignment,misc]

log = structlog.get_logger(__name__)

MAX_REPLAN_ATTEMPTS = 2


def execute_protocol(
    protocol: dict,
    sim_mode: SimMode = SimMode.MOCK,
    auto_correct: bool = True,
    lab_state: Optional[Any] = None,
) -> ExecutionPlan:
    """
    Full Phase 3+4 pipeline: parse → validate → [vision] → simulate → plan.

    Args:
        protocol:     GeneratedProtocol as dict (from /api/v1/generate response).
        sim_mode:     SimMode.MOCK (default) or SimMode.LIVE (requires Isaac Sim).
        auto_correct: Whether to attempt auto-correction of validation errors.
        lab_state:    Optional LabState from vision layer. If provided, its labware
                      map overrides the static DEFAULT_LABWARE_MAP in the sim bridge.
                      If None, falls back to the static map (Phase 3 behaviour).

    Returns:
        ExecutionPlan with status, commands, validation errors, and sim result.
    """
    plan_id = str(uuid.uuid4())
    protocol_id = protocol.get("protocol_id", "unknown")
    protocol_title = protocol.get("title", "Untitled")
    steps = protocol.get("steps", [])

    log.info("execution_start",
             plan_id=plan_id, protocol_id=protocol_id,
             steps=len(steps), sim_mode=sim_mode.value)

    t0 = time.perf_counter()

    # ---- Step 1: Parse ----
    commands = parse_protocol_steps(steps)
    log.info("parse_complete", plan_id=plan_id, commands=len(commands))

    # ---- Step 2: Validate + auto-correct ----
    commands, errors = validate_commands(commands, auto_correct=auto_correct)

    critical = [e for e in errors if e.severity == "critical" and not e.auto_corrected]
    if critical:
        log.error("validation_critical_failure",
                  plan_id=plan_id,
                  errors=[e.error_code for e in critical])
        return ExecutionPlan(
            plan_id=plan_id,
            protocol_id=protocol_id,
            protocol_title=protocol_title,
            commands=commands,
            status=ExecutionStatus.SIM_FAILED,
            validation_errors=errors,
            estimated_total_duration_s=_estimate_duration(commands),
            created_at=time.time(),
        )

    # ---- Step 3: Simulation with retry loop ----
    # If a live LabState was provided from the vision layer, use its labware map.
    # Otherwise fall back to the static DEFAULT_LABWARE_MAP (Phase 3 behaviour).
    labware_map = lab_state.to_labware_map() if lab_state is not None else None
    bridge = IsaacSimBridge(mode=sim_mode, labware_map=labware_map)
    sim_result: SimulationResult | None = None

    for attempt in range(1, MAX_REPLAN_ATTEMPTS + 1):
        sim_result = bridge.validate_execution_plan(commands)

        if sim_result.passed:
            log.info("sim_passed", plan_id=plan_id, attempt=attempt)
            break

        if sim_result.collision_detected and attempt < MAX_REPLAN_ATTEMPTS:
            # Attempt to resolve by inserting a safety pause at collision point
            collision_idx = sim_result.collision_at_command
            log.warning("sim_collision_replan",
                        plan_id=plan_id,
                        attempt=attempt,
                        collision_idx=collision_idx)
            commands, correction = _insert_pause_at_collision(commands, collision_idx)
            if correction:
                errors.append(correction)
        else:
            break

    elapsed = time.perf_counter() - t0

    final_status = (
        ExecutionStatus.SIM_PASSED if (sim_result and sim_result.passed)
        else ExecutionStatus.SIM_FAILED
    )

    plan = ExecutionPlan(
        plan_id=plan_id,
        protocol_id=protocol_id,
        protocol_title=protocol_title,
        commands=commands,
        status=final_status,
        validation_errors=errors,
        simulation_result=sim_result,
        estimated_total_duration_s=_estimate_duration(commands),
        created_at=time.time(),
    )

    log.info("execution_complete",
             plan_id=plan_id,
             status=final_status.value,
             commands=len(commands),
             errors=len(errors),
             elapsed_ms=round(elapsed * 1000))

    return plan


def _estimate_duration(commands: list[RobotCommand]) -> float:
    """Sum estimated durations, adding 2s overhead per command for robot movement."""
    total = 0.0
    for cmd in commands:
        duration_s = getattr(cmd, "duration_s", None)
        estimated  = getattr(cmd, "estimated_duration_s", None)
        total += float(duration_s or estimated or 2.0)
    return total + len(commands) * 2.0


def _insert_pause_at_collision(
    commands: list[RobotCommand],
    collision_idx: int | None,
) -> tuple[list[RobotCommand], ValidationError | None]:
    """
    Insert a safety pause immediately before the colliding command.
    This gives the robot time to re-orient or allows operator intervention.
    """
    from .robot_commands import PauseCommand

    if collision_idx is None:
        return commands, None

    # Find the command at that index
    insert_at = next(
        (i for i, c in enumerate(commands) if c.command_index == collision_idx),
        None
    )
    if insert_at is None:
        return commands, None

    pause = PauseCommand(
        command_index=collision_idx,
        protocol_step_ref=commands[insert_at].protocol_step_ref,
        duration_s=3.0,
        reason=f"[AUTO] Safety pause before collision point (original cmd {collision_idx})",
        notes="Auto-inserted by collision re-planner",
    )

    new_commands = commands[:insert_at] + [pause] + commands[insert_at:]
    # Re-index
    for i, cmd in enumerate(new_commands):
        cmd.command_index = i

    correction = ValidationError(
        command_index=collision_idx,
        command_type="pause",
        error_code="AUTO_COLLISION_PAUSE",
        message=f"Inserted 3s safety pause at collision point (cmd {collision_idx})",
        severity="warning",
        auto_corrected=True,
        correction_applied="PauseCommand(duration_s=3.0) inserted",
    )

    return new_commands, correction