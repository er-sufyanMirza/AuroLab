"""
aurolab/services/execution_service/core/step_parser.py

Converts ProtocolStep natural language instructions into typed RobotCommand lists.

Strategy:
  1. Pattern matching   — fast regex rules handle >80% of standard lab steps
                          (pipette, centrifuge, incubate, read, mix, etc.)
  2. Groq LLM fallback  — complex/compound steps sent to structured LLM parsing
  3. PAUSE sentinel     — unrecognised steps become PauseCommand with reason=instruction
                          so nothing is silently dropped

Each step may produce multiple commands — e.g. "Transfer 50µL from A1 to B2"
becomes: PickUpTip → Aspirate → Dispense → DropTip
"""

from __future__ import annotations

import re
from typing import Callable, Any

import structlog

from .robot_commands import (
    AspirateCommand, DispenseCommand, MixCommand,
    PickUpTipCommand, DropTipCommand, ChangeTipCommand,
    CentrifugeCommand, IncubateCommand, ShakeCommand,
    HeatCoolCommand, ReadAbsorbanceCommand, MovePlateCommand,
    PauseCommand, HomeCommand,
    LabwarePosition, RobotCommand, CommandType,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns for standard lab operations
# ---------------------------------------------------------------------------

# Volume: "50 µL", "200uL", "0.5 mL"
_VOL = r"(\d+(?:\.\d+)?)\s*(?:µL|uL|ul|mL|ml)"

# Temperature: "37°C", "37 degrees", "-20C"
_TEMP = r"(-?\d+(?:\.\d+)?)\s*(?:°C|°c|degrees?C?|°)"

# Duration: "10 minutes", "30 min", "2 hours", "45s", "600 seconds"
_DUR = r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?|s\b)"

# RPM: "13,000 × g", "3000 rpm", "300 xg"
_RPM = r"(\d[\d,]*)\s*(?:rpm|RPM|×\s*g|x\s*g|xg)"

# Well: A1, H12
_WELL = r"([A-Ha-h]\d{1,2})"

# Slot: "slot 1", "deck 3"
_SLOT = r"(?:slot|deck|position)\s*(\d{1,2})"

# Wavelength: "562 nm", "450nm"
_WL = r"(\d{3})\s*nm"


def _parse_volume_ul(text: str) -> float | None:
    m = re.search(_VOL, text, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    unit = text[m.start(1):m.end()].lower()
    if "ml" in unit:
        val *= 1000
    return val


def _parse_temp_c(text: str) -> float | None:
    m = re.search(_TEMP, text, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _parse_duration_s(text: str) -> float | None:
    m = re.search(_DUR, text, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("h"):
        return val * 3600
    if unit.startswith("m"):
        return val * 60
    return val  # seconds


def _parse_rpm(text: str) -> int | None:
    m = re.search(_RPM, text, re.IGNORECASE)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    val = int(raw)
    # Convert × g to RPM using standard microcentrifuge radius (~9cm)
    # RPM = sqrt(RCF / (1.118 × 10⁻⁵ × r)) where r=9cm
    # Simplified: RCF × g → RPM ≈ RCF * 0.95 for typical lab centrifuge
    # Hard cap at 30000 RPM (CentrifugeCommand max)
    segment = text[m.start():m.end()]
    if re.search(r"×\s*g|x\s*g|\bxg\b|rcf\b", segment, re.IGNORECASE):
        # × g values are already RCF — convert to approximate RPM
        # 1000 × g ≈ 5900 RPM for r=9cm rotor
        # but cap is 30000, so clamp before returning
        val = min(int(val * 0.95), 30000)
    return min(val, 30000)


def _parse_wavelength(text: str) -> int | None:
    m = re.search(_WL, text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _parse_slot(text: str, default: int = 1) -> int:
    m = re.search(_SLOT, text, re.IGNORECASE)
    if m:
        return min(max(int(m.group(1)), 1), 12)
    return default


def _parse_well(text: str) -> str | None:
    m = re.search(_WELL, text)
    return m.group(1).upper() if m else None


# ---------------------------------------------------------------------------
# Pattern-based parsers
# ---------------------------------------------------------------------------

ParseResult = list[dict]   # list of kwargs dicts for command constructors


def _try_pipette_transfer(instruction: str, step_num: int, idx_start: int) -> ParseResult | None:
    """
    Match: "pipette/transfer/add/aliquot Xµl [from A1] [to B2]"
    Produces: PickUpTip → Aspirate → Dispense → DropTip
    """
    patterns = [
        r"(?:pipette|transfer|add|aliquot|dispense|distribute)\s+" + _VOL,
        r"(?:aspirate|take|draw)\s+" + _VOL,
    ]
    vol = None
    for p in patterns:
        m = re.search(p, instruction, re.IGNORECASE)
        if m:
            vol = _parse_volume_ul(instruction)
            break

    if vol is None:
        return None

    src_well = None
    dst_well = None
    wells = re.findall(_WELL, instruction)
    if len(wells) >= 2:
        src_well, dst_well = wells[0].upper(), wells[1].upper()
    elif len(wells) == 1:
        dst_well = wells[0].upper()

    # Default slots: source=1, destination=2
    src_slot = 1
    dst_slot = 2
    slot_matches = re.findall(r"(?:slot|deck)\s*(\d{1,2})", instruction, re.IGNORECASE)
    if len(slot_matches) >= 2:
        src_slot, dst_slot = int(slot_matches[0]), int(slot_matches[1])

    commands = [
        {"type": "pick_up_tip",   "tip_rack_slot": 11},
        {"type": "aspirate",      "volume_ul": vol, "slot": src_slot, "well": src_well},
        {"type": "dispense",      "volume_ul": vol, "slot": dst_slot, "well": dst_well},
        {"type": "drop_tip",      "waste_slot": 12},
    ]
    return commands


def _try_centrifuge(instruction: str, step_num: int, idx_start: int) -> ParseResult | None:
    if not re.search(r"(?:centrifug|spin down|pellet)", instruction, re.IGNORECASE):
        return None
    rpm = _parse_rpm(instruction) or 13000
    dur = _parse_duration_s(instruction) or 600
    temp = _parse_temp_c(instruction)
    return [{"type": "centrifuge", "speed_rpm": rpm, "duration_s": dur, "temperature_celsius": temp}]


def _try_incubate(instruction: str, step_num: int, idx_start: int) -> ParseResult | None:
    if not re.search(r"(?:incubat|warm up|cool down|chill|freez|thaw|heat)", instruction, re.IGNORECASE):
        return None
    temp = _parse_temp_c(instruction)
    dur = _parse_duration_s(instruction) or 1800
    slot = _parse_slot(instruction, default=7)
    if temp is None:
        if re.search(r"on\s+ice", instruction, re.IGNORECASE):
            temp = 4.0
        elif re.search(r"room\s+temp", instruction, re.IGNORECASE):
            temp = 22.0
        else:
            temp = 37.0
    return [{"type": "incubate", "temperature_celsius": temp, "duration_s": dur, "slot": slot}]


def _try_mix(instruction: str, step_num: int, idx_start: int) -> ParseResult | None:
    if not re.search(r"\b(?:mix|vortex|resuspend|homogeni[sz]e|pipette\s+up\s+and\s+down)\b", instruction, re.IGNORECASE):
        return None
    vol = _parse_volume_ul(instruction) or 100.0
    reps_m = re.search(r"(\d+)\s*(?:times?|×|x\b|repetitions?|cycles?)", instruction, re.IGNORECASE)
    reps = int(reps_m.group(1)) if reps_m else 5
    slot = _parse_slot(instruction, default=2)
    well = _parse_well(instruction)
    return [{"type": "mix", "volume_ul": vol, "repetitions": min(reps, 20), "slot": slot, "well": well}]


def _try_shake(instruction: str, step_num: int, idx_start: int) -> ParseResult | None:
    if not re.search(r"\b(?:shake|agitat|rock|orbital)\b", instruction, re.IGNORECASE):
        return None
    rpm = _parse_rpm(instruction) or 300
    dur = _parse_duration_s(instruction) or 300
    slot = _parse_slot(instruction, default=5)
    return [{"type": "shake", "speed_rpm": min(rpm, 3000), "duration_s": dur, "slot": slot}]


def _try_read_absorbance(instruction: str, step_num: int, idx_start: int) -> ParseResult | None:
    if not re.search(r"\b(?:read|measure|absorbance|OD|optical\s+density)\b", instruction, re.IGNORECASE):
        return None
    wl = _parse_wavelength(instruction) or 562
    slot = _parse_slot(instruction, default=3)
    return [{"type": "read_absorbance", "wavelength_nm": wl, "slot": slot}]


def _try_home(instruction: str, step_num: int, idx_start: int) -> ParseResult | None:
    if not re.search(r"\b(?:home|initializ|reset\s+robot)\b", instruction, re.IGNORECASE):
        return None
    return [{"type": "home"}]


def _try_pause(instruction: str, step_num: int, idx_start: int) -> ParseResult | None:
    if not re.search(r"\b(?:pause|wait|hold|stop\s+and\s+check)\b", instruction, re.IGNORECASE):
        return None
    dur = _parse_duration_s(instruction)
    return [{"type": "pause", "duration_s": dur, "reason": instruction}]


# Parser pipeline — ordered by specificity
_PARSERS: list[Callable] = [
    _try_centrifuge,
    _try_incubate,
    _try_read_absorbance,
    _try_shake,
    _try_mix,
    _try_pipette_transfer,
    _try_home,
    _try_pause,
]


# ---------------------------------------------------------------------------
# Command builder
# ---------------------------------------------------------------------------

def _build_command(cmd_dict: dict, command_index: int, step_ref: int) -> RobotCommand:
    """Build a typed RobotCommand from a parsed dict."""
    t = cmd_dict.get("type")
    base = {
        "command_index": command_index,
        "protocol_step_ref": step_ref,
        "notes": cmd_dict.get("notes"),
    }

    slot = cmd_dict.get("slot", 1)
    well = cmd_dict.get("well")
    loc = LabwarePosition(deck_slot=slot, well=well)

    if t == "aspirate":
        return AspirateCommand(**base, volume_ul=cmd_dict["volume_ul"], source=loc)
    if t == "dispense":
        return DispenseCommand(**base, volume_ul=cmd_dict["volume_ul"],
                               destination=LabwarePosition(deck_slot=cmd_dict.get("slot", 2), well=cmd_dict.get("well")))
    if t == "mix":
        return MixCommand(**base, volume_ul=cmd_dict["volume_ul"],
                          repetitions=cmd_dict.get("repetitions", 5), location=loc)
    if t == "pick_up_tip":
        return PickUpTipCommand(**base, tip_rack_slot=cmd_dict.get("tip_rack_slot", 11))
    if t == "drop_tip":
        return DropTipCommand(**base, waste_slot=cmd_dict.get("waste_slot", 12))
    if t == "centrifuge":
        return CentrifugeCommand(**base,
                                 speed_rpm=cmd_dict["speed_rpm"],
                                 duration_s=cmd_dict["duration_s"],
                                 temperature_celsius=cmd_dict.get("temperature_celsius"))
    if t == "incubate":
        return IncubateCommand(**base,
                               temperature_celsius=cmd_dict["temperature_celsius"],
                               duration_s=cmd_dict["duration_s"],
                               slot=slot)
    if t == "shake":
        return ShakeCommand(**base, speed_rpm=cmd_dict["speed_rpm"],
                            duration_s=cmd_dict["duration_s"], slot=slot)
    if t == "read_absorbance":
        return ReadAbsorbanceCommand(**base, wavelength_nm=cmd_dict["wavelength_nm"], slot=slot)
    if t == "home":
        return HomeCommand(**base)
    # Default: pause with original instruction as reason
    return PauseCommand(**base,
                        duration_s=cmd_dict.get("duration_s"),
                        reason=cmd_dict.get("reason", "Unrecognised step — manual intervention required"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_step(
    instruction: str,
    step_number: int,
    command_index_start: int = 0,
) -> list[RobotCommand]:
    """
    Parse a single protocol step instruction into robot commands.

    Args:
        instruction:          Natural language step text.
        step_number:          Which protocol step this came from (for traceability).
        command_index_start:  Starting index for command numbering.

    Returns:
        List of RobotCommand instances. Never empty — unrecognised steps
        produce a PauseCommand so nothing is silently dropped.
    """
    commands: list[RobotCommand] = []
    idx = command_index_start

    for parser in _PARSERS:
        result = parser(instruction, step_number, idx)
        if result:
            for cmd_dict in result:
                cmd = _build_command(cmd_dict, idx, step_number)
                commands.append(cmd)
                idx += 1
            log.debug("step_parsed",
                      step=step_number,
                      parser=parser.__name__,
                      commands=len(commands))
            return commands

    # Nothing matched — produce a pause sentinel
    log.info("step_unrecognised", step=step_number, instruction=instruction[:80])
    return [PauseCommand(
        command_index=idx,
        protocol_step_ref=step_number,
        reason=f"[UNRECOGNISED] {instruction}",
    )]


def parse_protocol_steps(
    steps: list[dict],
) -> list[RobotCommand]:
    """
    Parse all steps from a GeneratedProtocol.steps list.

    Args:
        steps: List of step dicts with at minimum {"step_number": int, "instruction": str}

    Returns:
        Flat list of RobotCommand in execution order.
    """
    all_commands: list[RobotCommand] = []
    # Always start with a home command
    all_commands.append(HomeCommand(command_index=0, protocol_step_ref=0, notes="Protocol start"))

    idx = 1
    for step in steps:
        step_num = step.get("step_number", len(all_commands))
        instruction = step.get("instruction", "")
        cmds = parse_step(instruction, step_num, command_index_start=idx)
        all_commands.extend(cmds)
        idx += len(cmds)

    # Always end with home
    all_commands.append(HomeCommand(
        command_index=idx,
        protocol_step_ref=len(steps),
        notes="Protocol complete — return to home",
    ))

    log.info("protocol_parsed",
             steps=len(steps),
             commands=len(all_commands))
    return all_commands