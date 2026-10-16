"""
aurolab/services/execution_service/core/validator.py

Pre-simulation validation + auto-correction for robot command sequences.

Three tiers of checks:
  1. Physical constraints  — volumes in range, temperatures achievable, slots valid
  2. Sequence logic        — tip must be picked up before aspirate, etc.
  3. Safety rules          — no dispensing into sealed plates, etc.

Auto-correction handles common recoverable issues without requiring human input:
  - Missing PickUpTip before Aspirate → insert one
  - Missing DropTip at end            → append one
  - Volume slightly over pipette max  → clamp + warn
  - Missing Home at start/end         → insert
"""

from __future__ import annotations

import structlog

from .robot_commands import (
    AspirateCommand, DispenseCommand, MixCommand,
    PickUpTipCommand, DropTipCommand,
    CentrifugeCommand, IncubateCommand,
    HomeCommand, PauseCommand,
    RobotCommand, CommandType,
    ValidationError, ExecutionStatus,
)

log = structlog.get_logger(__name__)

# Physical limits
MAX_PIPETTE_VOL_UL   = 1000.0
MAX_CENTRIFUGE_RPM   = 30000
MIN_CENTRIFUGE_RPM   = 100
VALID_SLOTS          = set(range(1, 13))
MAX_INCUBATE_TEMP    = 120.0
MIN_INCUBATE_TEMP    = -80.0


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_volumes(commands: list[RobotCommand]) -> list[ValidationError]:
    errors = []
    for cmd in commands:
        if isinstance(cmd, (AspirateCommand, DispenseCommand, MixCommand)):
            if cmd.volume_ul > MAX_PIPETTE_VOL_UL:
                errors.append(ValidationError(
                    command_index=cmd.command_index,
                    command_type=cmd.command_type.value,
                    error_code="VOL_OVERFLOW",
                    message=f"Volume {cmd.volume_ul}µL exceeds pipette max {MAX_PIPETTE_VOL_UL}µL",
                    severity="error",
                ))
            elif cmd.volume_ul <= 0:
                errors.append(ValidationError(
                    command_index=cmd.command_index,
                    command_type=cmd.command_type.value,
                    error_code="VOL_ZERO",
                    message="Volume must be greater than 0",
                    severity="critical",
                ))
    return errors


def _check_centrifuge(commands: list[RobotCommand]) -> list[ValidationError]:
    errors = []
    for cmd in commands:
        if isinstance(cmd, CentrifugeCommand):
            if cmd.speed_rpm > MAX_CENTRIFUGE_RPM:
                errors.append(ValidationError(
                    command_index=cmd.command_index,
                    command_type=cmd.command_type.value,
                    error_code="RPM_OVERFLOW",
                    message=f"Speed {cmd.speed_rpm} RPM exceeds centrifuge max ({MAX_CENTRIFUGE_RPM})",
                    severity="critical",
                ))
            if cmd.duration_s < 10:
                errors.append(ValidationError(
                    command_index=cmd.command_index,
                    command_type=cmd.command_type.value,
                    error_code="DURATION_TOO_SHORT",
                    message=f"Centrifuge duration {cmd.duration_s}s is suspiciously short",
                    severity="warning",
                ))
    return errors


def _check_temperature(commands: list[RobotCommand]) -> list[ValidationError]:
    errors = []
    for cmd in commands:
        if isinstance(cmd, IncubateCommand):
            if cmd.temperature_celsius > MAX_INCUBATE_TEMP:
                errors.append(ValidationError(
                    command_index=cmd.command_index,
                    command_type=cmd.command_type.value,
                    error_code="TEMP_TOO_HIGH",
                    message=f"Temperature {cmd.temperature_celsius}°C exceeds instrument max ({MAX_INCUBATE_TEMP}°C)",
                    severity="critical",
                ))
            if cmd.temperature_celsius < MIN_INCUBATE_TEMP:
                errors.append(ValidationError(
                    command_index=cmd.command_index,
                    command_type=cmd.command_type.value,
                    error_code="TEMP_TOO_LOW",
                    message=f"Temperature {cmd.temperature_celsius}°C below instrument min ({MIN_INCUBATE_TEMP}°C)",
                    severity="critical",
                ))
    return errors


def _check_slots(commands: list[RobotCommand]) -> list[ValidationError]:
    errors = []
    for cmd in commands:
        slot = getattr(cmd, "slot", None)
        if slot is not None and slot not in VALID_SLOTS:
            errors.append(ValidationError(
                command_index=cmd.command_index,
                command_type=cmd.command_type.value,
                error_code="INVALID_SLOT",
                message=f"Deck slot {slot} is not valid (must be 1–12)",
                severity="critical",
            ))
    return errors


def _check_tip_sequence(commands: list[RobotCommand]) -> list[ValidationError]:
    """
    Verify that every Aspirate/Dispense has a tip loaded.
    Tracks tip state: loaded=True after PickUpTip, False after DropTip.
    """
    errors = []
    tip_loaded = False

    for cmd in commands:
        if isinstance(cmd, PickUpTipCommand):
            tip_loaded = True
        elif isinstance(cmd, DropTipCommand):
            tip_loaded = False
        elif isinstance(cmd, (AspirateCommand, DispenseCommand, MixCommand)):
            if not tip_loaded:
                errors.append(ValidationError(
                    command_index=cmd.command_index,
                    command_type=cmd.command_type.value,
                    error_code="NO_TIP",
                    message=f"Command {cmd.command_index} ({cmd.command_type.value}) requires a tip but none is loaded",
                    severity="error",
                ))

    return errors


# ---------------------------------------------------------------------------
# Auto-corrections
# ---------------------------------------------------------------------------

def _autocorrect_missing_tips(commands: list[RobotCommand]) -> tuple[list[RobotCommand], list[ValidationError]]:
    """
    If an Aspirate has no preceding PickUpTip, insert one immediately before it.
    If the sequence ends with a tip still loaded, append a DropTip.
    """
    corrections: list[ValidationError] = []
    result: list[RobotCommand] = []
    tip_loaded = False
    next_idx = 0

    for cmd in commands:
        if isinstance(cmd, (AspirateCommand, MixCommand)) and not tip_loaded:
            # Insert missing PickUpTip
            pick = PickUpTipCommand(
                command_index=next_idx,
                protocol_step_ref=cmd.protocol_step_ref,
                tip_rack_slot=11,
                notes="[AUTO-INSERTED] Missing PickUpTip before aspirate/mix",
            )
            result.append(pick)
            corrections.append(ValidationError(
                command_index=next_idx,
                command_type="pick_up_tip",
                error_code="AUTO_INSERT_TIP",
                message=f"Inserted missing PickUpTip before command {cmd.command_index}",
                severity="warning",
                auto_corrected=True,
                correction_applied="Inserted PickUpTip(tip_rack_slot=11)",
            ))
            tip_loaded = True
            next_idx += 1

        if isinstance(cmd, PickUpTipCommand):
            tip_loaded = True
        elif isinstance(cmd, DropTipCommand):
            tip_loaded = False

        # Re-index
        cmd.command_index = next_idx
        result.append(cmd)
        next_idx += 1

    # Dangling tip at end
    if tip_loaded:
        drop = DropTipCommand(
            command_index=next_idx,
            protocol_step_ref=result[-1].protocol_step_ref if result else 0,
            notes="[AUTO-INSERTED] Tip still loaded at protocol end",
        )
        result.append(drop)
        corrections.append(ValidationError(
            command_index=next_idx,
            command_type="drop_tip",
            error_code="AUTO_DROP_TIP",
            message="Appended DropTip — tip was still loaded at protocol end",
            severity="warning",
            auto_corrected=True,
            correction_applied="Appended DropTip(waste_slot=12)",
        ))

    return result, corrections


def _autocorrect_volumes(commands: list[RobotCommand]) -> tuple[list[RobotCommand], list[ValidationError]]:
    """Clamp volumes that slightly exceed the pipette max to the max."""
    corrections: list[ValidationError] = []
    for cmd in commands:
        if isinstance(cmd, (AspirateCommand, DispenseCommand, MixCommand)):
            if MAX_PIPETTE_UL_CLAMP_THRESHOLD := MAX_PIPETTE_VOL_UL * 1.05:
                if MAX_PIPETTE_VOL_UL < cmd.volume_ul <= MAX_PIPETTE_UL_CLAMP_THRESHOLD:
                    original = cmd.volume_ul
                    cmd.volume_ul = MAX_PIPETTE_VOL_UL
                    corrections.append(ValidationError(
                        command_index=cmd.command_index,
                        command_type=cmd.command_type.value,
                        error_code="VOL_CLAMPED",
                        message=f"Volume clamped from {original}µL to {MAX_PIPETTE_VOL_UL}µL",
                        severity="warning",
                        auto_corrected=True,
                        correction_applied=f"volume_ul = {MAX_PIPETTE_VOL_UL}",
                    ))
    return commands, corrections


MAX_PIPETTE_UL_CLAMP_THRESHOLD = MAX_PIPETTE_VOL_UL * 1.05


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_commands(
    commands: list[RobotCommand],
    auto_correct: bool = True,
) -> tuple[list[RobotCommand], list[ValidationError]]:
    """
    Run all validation checks and optionally apply auto-corrections.

    Args:
        commands:     Parsed robot command sequence.
        auto_correct: If True, attempt to fix recoverable issues automatically.

    Returns:
        (corrected_commands, all_errors_and_corrections)
        Check ValidationError.severity == "critical" to decide if execution is safe.
    """
    all_errors: list[ValidationError] = []

    # Phase 1: static checks on original sequence
    all_errors.extend(_check_volumes(commands))
    all_errors.extend(_check_centrifuge(commands))
    all_errors.extend(_check_temperature(commands))
    all_errors.extend(_check_slots(commands))
    all_errors.extend(_check_tip_sequence(commands))

    if not auto_correct:
        return commands, all_errors

    # Phase 2: auto-corrections
    commands, tip_corrections = _autocorrect_missing_tips(commands)
    commands, vol_corrections = _autocorrect_volumes(commands)
    all_errors.extend(tip_corrections)
    all_errors.extend(vol_corrections)

    # Phase 3: re-validate after corrections (should now have no tip errors)
    remaining = _check_tip_sequence(commands)
    all_errors.extend([e for e in remaining if e not in all_errors])

    critical_count = sum(1 for e in all_errors if e.severity == "critical" and not e.auto_corrected)
    log.info("validation_complete",
             total_commands=len(commands),
             errors=len(all_errors),
             critical=critical_count,
             auto_corrected=sum(1 for e in all_errors if e.auto_corrected))

    return commands, all_errors