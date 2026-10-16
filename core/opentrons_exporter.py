"""
services/translation_service/core/opentrons_exporter.py

Converts an AuroLab GeneratedProtocol into a runnable Opentrons Python API v2 script.
The generated .py file can be loaded directly into the Opentrons App and run on a
physical OT-2 robot — no manual translation needed.

Supported commands:
  aspirate / dispense / mix → pipette operations
  pick_up_tip / drop_tip    → tip management
  centrifuge                → manual pause with instruction
  incubate                  → temperature module or manual pause
  read_absorbance           → pause with plate reader instruction
  shake                     → orbital shaker module or manual pause
  home                      → robot.home()
"""

from __future__ import annotations

import re
import textwrap
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Labware catalogue — maps AuroLab labware types to Opentrons API load names
# ---------------------------------------------------------------------------

LABWARE_MAP = {
    "96_well_plate":     "corning_96_wellplate_360ul_flat",
    "384_well_plate":    "corning_384_wellplate_112ul_flat",
    "tip_rack_300ul":    "opentrons_96_tiprack_300ul",
    "tip_rack_200ul":    "opentrons_96_tiprack_200ul",
    "tip_rack_10ul":     "opentrons_96_tiprack_10ul",
    "tip_rack_1000ul":   "opentrons_96_tiprack_1000ul",
    "tube_rack":         "opentrons_24_tuberack_generic_2ml_screwcap",
    "tube_rack_1.5ml":   "opentrons_24_tuberack_eppendorf_1.5ml_safelock_snapcap",
    "waste_container":   "agilent_1_reservoir_290ml",
    "reservoir_12_well": "usascientific_12_reservoir_22ml",
    "plate_reader_slot": "corning_96_wellplate_360ul_flat",
    "incubator_slot":    "corning_96_wellplate_360ul_flat",
    "generic":           "corning_96_wellplate_360ul_flat",
}

PIPETTE_MAP = {
    "p300": ("p300_single_gen2", "right"),
    "p20":  ("p20_single_gen2",  "left"),
    "p10":  ("p10_single",       "left"),
    "p1000":("p1000_single_gen2","right"),
    "p50":  ("p50_single",       "right"),
}

WELL_ROWS   = "ABCDEFGH"
WELL_COLS   = list(range(1, 13))


def _pick_pipette(max_volume: float) -> tuple[str, str]:
    """Choose the appropriate pipette based on max volume used."""
    if max_volume <= 20:
        return PIPETTE_MAP["p20"]
    if max_volume <= 300:
        return PIPETTE_MAP["p300"]
    return PIPETTE_MAP["p1000"]


def _slot_var(slot: int) -> str:
    return f"labware_{slot}"


def _duration_str(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    if m and s:
        return f"{m} min {s} sec"
    if m:
        return f"{m} min"
    return f"{s} sec"


# ---------------------------------------------------------------------------
# Command translators
# ---------------------------------------------------------------------------

def _translate_pipette(step: dict, plan_cmds: list[dict], pipette_var: str) -> list[str]:
    """Translate aspirate/dispense steps into Opentrons API calls."""
    lines = []
    inst = step.get("instruction", "").lower()
    vol  = step.get("volume_ul")

    # Extract volume from instruction if not in step metadata
    if vol is None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*[µu]l", inst)
        if m:
            vol = float(m.group(1))
        else:
            vol = 50.0  # default

    # Determine source and destination slots from instruction
    src_m  = re.search(r"(?:from|slot)\s*(\d+)", inst)
    dst_m  = re.search(r"(?:to|into|slot)\s*(\d+)", inst)
    src_slot = int(src_m.group(1)) if src_m else 1
    dst_slot = int(dst_m.group(1)) if dst_m else 2

    lines.append(f"    # Step {step['step_number']}: {step['instruction']}")
    lines.append(f"    {pipette_var}.pick_up_tip()")
    lines.append(f"    {pipette_var}.aspirate({vol:.1f}, {_slot_var(src_slot)}['A1'])")
    lines.append(f"    {pipette_var}.dispense({vol:.1f}, {_slot_var(dst_slot)}['A1'])")
    lines.append(f"    {pipette_var}.drop_tip()")
    return lines


def _translate_mix(step: dict, pipette_var: str) -> list[str]:
    inst = step.get("instruction","").lower()
    vol_m   = re.search(r"(\d+(?:\.\d+)?)\s*[µu]l", inst)
    rep_m   = re.search(r"(\d+)\s*(?:times|×|x)", inst)
    slot_m  = re.search(r"slot\s*(\d+)", inst)
    vol     = float(vol_m.group(1)) if vol_m else 50.0
    reps    = int(rep_m.group(1))   if rep_m else 3
    slot    = int(slot_m.group(1))  if slot_m else 2
    return [
        f"    # Step {step['step_number']}: {step['instruction']}",
        f"    {pipette_var}.pick_up_tip()",
        f"    {pipette_var}.mix({reps}, {vol:.1f}, {_slot_var(slot)}['A1'])",
        f"    {pipette_var}.drop_tip()",
    ]


def _translate_pause(step: dict, reason: str = "") -> list[str]:
    msg = reason or step.get("instruction", "Manual step required")
    safe = msg.replace("'", "\\'")
    return [
        f"    # Step {step['step_number']}: {step['instruction']}",
        f"    protocol.pause('{safe}')",
    ]


def _translate_incubate(step: dict) -> list[str]:
    inst     = step.get("instruction","")
    temp_m   = re.search(r"(\d+(?:\.\d+)?)\s*°?[Cc]", inst)
    dur_m    = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|minute)", inst)
    temp     = float(temp_m.group(1)) if temp_m else 37.0
    dur_s    = float(dur_m.group(1)) * 60 if dur_m else 1800.0
    dur_str  = _duration_str(dur_s)
    safe_inst = inst.replace("'","\\'")
    lines = [f"    # Step {step['step_number']}: {inst}"]
    if temp == 4.0 or "ice" in inst.lower():
        lines.append(f"    protocol.pause('Place plate on ice. Resume when ready. ({dur_str})')")
    elif temp == 37.0:
        lines += [
            "    # Temperature module: set 37°C",
            "    # If temperature_module is available:",
            "    # temperature_module.set_temperature(37)",
            f"    protocol.pause('Incubate at {temp:.0f}°C for {dur_str}. Resume when complete.')",
        ]
    else:
        lines.append(f"    protocol.pause('Incubate at {temp:.0f}°C for {dur_str} — {safe_inst}')")
    return lines


def _translate_centrifuge(step: dict) -> list[str]:
    inst    = step.get("instruction","")
    rpm_m   = re.search(r"(\d+)\s*(?:rpm|×\s*g|xg)", inst, re.I)
    dur_m   = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|minute)", inst)
    rpm     = rpm_m.group(1) if rpm_m else "3000"
    dur     = _duration_str(float(dur_m.group(1))*60) if dur_m else "5 min"
    safe    = inst.replace("'","\\'")
    return [
        f"    # Step {step['step_number']}: {inst}",
        f"    protocol.pause('Transfer plate to centrifuge. Spin at {rpm} rpm for {dur}. Return plate and resume.')",
    ]


def _translate_read_absorbance(step: dict) -> list[str]:
    inst   = step.get("instruction","")
    wl_m   = re.search(r"(\d{3})\s*nm", inst)
    wl     = wl_m.group(1) if wl_m else "562"
    safe   = inst.replace("'","\\'")
    return [
        f"    # Step {step['step_number']}: {inst}",
        f"    protocol.pause('Transfer plate to plate reader. Read absorbance at {wl} nm. Record results and return plate.')",
    ]


def _translate_shake(step: dict) -> list[str]:
    inst   = step.get("instruction","")
    rpm_m  = re.search(r"(\d+)\s*rpm", inst)
    dur_m  = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|minute)", inst)
    rpm    = rpm_m.group(1) if rpm_m else "300"
    dur    = _duration_str(float(dur_m.group(1))*60) if dur_m else "5 min"
    return [
        f"    # Step {step['step_number']}: {inst}",
        f"    protocol.pause('Place plate on orbital shaker at {rpm} rpm for {dur}. Resume when complete.')",
    ]


# ---------------------------------------------------------------------------
# Main exporter
# ---------------------------------------------------------------------------

def export_opentrons_script(protocol: dict, lab_state: dict | None = None) -> str:
    """
    Generate a runnable Opentrons Python API v2 script from an AuroLab protocol.

    Args:
        protocol:   GeneratedProtocol dict (from API or session state).
        lab_state:  Optional lab state dict with labware_map {slot: type}.

    Returns:
        Python source code string ready to save as .py and load in Opentrons App.
    """
    pid      = protocol.get("protocol_id", "unknown")[:8]
    title    = protocol.get("title", "AuroLab Protocol")
    desc     = protocol.get("description", "")
    steps    = protocol.get("steps", [])
    safety   = protocol.get("safety_level", "safe")
    notes    = protocol.get("safety_notes", [])
    reagents = protocol.get("reagents", [])
    equipment= protocol.get("equipment", [])
    conf     = protocol.get("confidence_score", 0.0)
    model    = protocol.get("model_used", "")
    now      = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Determine max volume to pick correct pipette
    volumes = []
    for step in steps:
        if step.get("volume_ul"):
            volumes.append(float(step["volume_ul"]))
        m = re.search(r"(\d+(?:\.\d+)?)\s*[µu]l", step.get("instruction","").lower())
        if m:
            volumes.append(float(m.group(1)))
    max_vol = max(volumes) if volumes else 300.0
    pip_name, pip_mount = _pick_pipette(max_vol)

    # Build labware map from lab state or defaults
    lw_map: dict[int, str] = {}
    if lab_state and lab_state.get("labware_map"):
        for slot, ltype in lab_state["labware_map"].items():
            lw_map[int(slot)] = ltype
    # Ensure tip rack and waste exist
    if not any(v.startswith("tip_rack") for v in lw_map.values()):
        lw_map[11] = "tip_rack_300ul"
    if 12 not in lw_map:
        lw_map[12] = "waste_container"

    # Generate labware load lines
    lw_lines = []
    lw_vars  = {}
    for slot in sorted(lw_map):
        ltype   = lw_map[slot]
        api_name = LABWARE_MAP.get(ltype, "corning_96_wellplate_360ul_flat")
        var_name = _slot_var(slot)
        lw_vars[slot] = var_name
        lw_lines.append(f"    {var_name} = protocol.load_labware('{api_name}', {slot})  # {ltype}")

    # Tip rack variable
    tip_vars = [v for s, v in lw_vars.items() if "tip_rack" in lw_map.get(s,"")]
    tip_rack_arg = f"tip_racks=[{', '.join(tip_vars)}]" if tip_vars else ""

    # Translate steps to Opentrons calls
    cmd_lines: list[str] = []
    pip_var = "pipette"
    for step in steps:
        inst_lower = step.get("instruction","").lower()
        if any(k in inst_lower for k in ["pipette","aspirate","transfer","add","aliquot","dispense"]):
            cmd_lines += _translate_pipette(step, [], pip_var)
        elif "mix" in inst_lower or "vortex" in inst_lower:
            cmd_lines += _translate_mix(step, pip_var)
        elif "centrifuge" in inst_lower or "spin" in inst_lower:
            cmd_lines += _translate_centrifuge(step)
        elif "incubate" in inst_lower or "warm" in inst_lower or "cool" in inst_lower:
            cmd_lines += _translate_incubate(step)
        elif "read" in inst_lower or "absorbance" in inst_lower or "fluorescence" in inst_lower:
            cmd_lines += _translate_read_absorbance(step)
        elif "shake" in inst_lower or "orbital" in inst_lower:
            cmd_lines += _translate_shake(step)
        elif "pause" in inst_lower or "wait" in inst_lower:
            cmd_lines += _translate_pause(step)
        elif "home" in inst_lower:
            cmd_lines.append(f"    # Step {step['step_number']}: {step['instruction']}")
            cmd_lines.append(f"    protocol.home()")
        else:
            # Unknown — emit as pause so it's not silently skipped
            cmd_lines += _translate_pause(step, f"Manual step: {step['instruction']}")
        cmd_lines.append("")

    safety_warning = ""
    if safety in ("warning", "hazardous") or notes:
        safety_lines = ["    # ⚠ SAFETY NOTES:"]
        for note in notes:
            safety_lines.append(f"    #   - {note}")
        safety_warning = "\n".join(safety_lines) + "\n\n"

    # Assemble the full script
    reagent_list = "\n".join(f"#   - {r}" for r in reagents) if reagents else "#   (none listed)"
    equip_list   = "\n".join(f"#   - {e}" for e in equipment) if equipment else "#   (none listed)"
    lw_block     = "\n".join(lw_lines)
    cmd_block    = "\n".join(cmd_lines)
    pip_rack_arg = f", {tip_rack_arg}" if tip_rack_arg else ""

    script = f'''"""
AuroLab — Generated Opentrons OT-2 Protocol
============================================
Title:       {title}
Protocol ID: {pid}
Generated:   {now}
Model:       {model}
Confidence:  {conf:.0%}
Safety:      {safety.upper()}

Description:
    {textwrap.fill(desc, width=70, subsequent_indent="    ")}

Reagents:
{reagent_list}

Equipment:
{equip_list}

Instructions:
    1. Load this file in the Opentrons App (File → Open Protocol)
    2. Verify labware positions match the deck map below
    3. Calibrate if prompted
    4. Click Run

Deck map:
{chr(10).join(f"    Slot {s}: {lw_map[s]}" for s in sorted(lw_map))}

⚠ IMPORTANT: Review all pause steps before running on a physical robot.
   Steps involving centrifugation, incubation, and plate reading require
   manual transfers — follow on-screen prompts during execution.

Generated by AuroLab autonomous lab automation system.
"""

from opentrons import protocol_api

metadata = {{
    "protocolName": "{title}",
    "author": "AuroLab v2.0",
    "description": "{desc[:120].replace(chr(34), chr(39))}",
    "apiLevel": "2.13",
}}


def run(protocol: protocol_api.ProtocolContext) -> None:
    # ── Labware ─────────────────────────────────────────────────────────────
{lw_block}

    # ── Instruments ──────────────────────────────────────────────────────────
    {pip_var} = protocol.load_instrument(
        "{pip_name}", "{pip_mount}"{pip_rack_arg}
    )

    # ── Protocol steps ───────────────────────────────────────────────────────
{safety_warning}{cmd_block}
    # ── Done ─────────────────────────────────────────────────────────────────
    protocol.comment("Protocol complete — AuroLab ID: {pid}")
'''
    return script


def export_opentrons_json(protocol: dict, lab_state: dict | None = None) -> dict:
    """
    Export as Opentrons Protocol Designer JSON format (v6).
    This can be imported directly into the Opentrons Protocol Designer web app.
    """
    steps = protocol.get("steps", [])
    commands = []
    for i, step in enumerate(steps):
        commands.append({
            "commandType": "comment",
            "params": {"message": f"Step {step['step_number']}: {step['instruction']}"},
            "key": f"step_{i}"
        })

    return {
        "schemaVersion": 6,
        "metadata": {
            "protocolName":  protocol.get("title", "AuroLab Protocol"),
            "author":        "AuroLab v2.0",
            "description":   protocol.get("description", ""),
            "created":       datetime.now().isoformat(),
            "lastModified":  datetime.now().isoformat(),
            "category":      None,
            "subcategory":   None,
            "tags":          ["aurolab", "generated", protocol.get("safety_level","safe")],
        },
        "robot": {"model": "OT-2 Standard", "deckId": "ot2_standard"},
        "commands": commands,
        "designerApplication": {
            "name":    "AuroLab",
            "version": "2.0.0",
        },
    }