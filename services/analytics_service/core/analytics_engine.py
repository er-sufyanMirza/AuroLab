"""
aurolab/services/analytics_service/core/analytics_engine.py

Four analytics engines that compute metrics from ExecutionPlan + telemetry.

All prices and factors are parameterised constants at the top of the file
so a lab manager can adjust them for their institution without touching logic.

Data sources used:
  - ExecutionPlan.commands       → tip changes, volumes, durations
  - SimulationResult.telemetry   → aspirated_ul, dispensed_ul, tip_changes
  - GeneratedProtocol            → reagent list, step count
  - LabState (optional)          → actual labware present
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from services.analytics_service.core.analytics_models import (
    AggregateAnalytics, CostLineItem, EfficiencyReport,
    ManualBaseline, ProtocolCost, SustainabilityScore,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pricing constants (USD) — adjust for your institution
# ---------------------------------------------------------------------------

# Reagents (per µL unless noted)
REAGENT_PRICES: dict[str, float] = {
    "bca":              0.0008,    # BCA working reagent per µL
    "bsa":              0.0012,    # BSA standard per µL
    "tris":             0.0001,    # generic buffer per µL
    "edta":             0.00015,
    "nacl":             0.00005,
    "pcr_master_mix":   0.0025,    # per µL
    "elisa_antibody":   0.015,     # per µL (expensive)
    "generic":          0.0003,    # fallback for unknown reagents
}

# Consumables
TIP_PRICES: dict[str, float] = {
    "tip_rack_10ul":   0.08,    # per tip
    "tip_rack_200ul":  0.05,
    "tip_rack_300ul":  0.06,
    "tip_rack_1000ul": 0.12,
    "default":         0.06,
}
PLATE_96_WELL_USD     = 1.20
TUBE_1_5ML_USD        = 0.08
TUBE_15ML_USD         = 0.18

# Labour
SCIENTIST_HOURLY_USD  = 75.0    # fully-loaded cost (salary + benefits)
ROBOT_HOURLY_USD      = 8.50    # amortised robot cost per hour

# Instrument energy (Watts)
ROBOT_WATTS           = 120.0
CENTRIFUGE_WATTS      = 800.0
INCUBATOR_WATTS       = 150.0
PLATE_READER_WATTS    = 85.0
FREEZER_WATTS         = 250.0   # -20°C storage during protocol

# Electricity cost
ELECTRICITY_USD_KWH   = 0.12

# Plastics mass (grams)
TIP_10UL_G            = 0.18
TIP_200UL_G           = 0.48
TIP_300UL_G           = 0.55
TIP_1000UL_G          = 1.20
TUBE_1_5ML_G          = 1.80
PLATE_96_G            = 18.0
PLATE_384_G           = 22.0

# Carbon intensity (gCO₂ per kWh) — US average 2024
GRID_CO2_G_PER_KWH    = 386.0

# Manual baseline assumptions
MANUAL_PIPETTING_MIN_PER_STEP = 1.5   # minutes per pipetting step for a human
MANUAL_ERROR_RATE_PCT         = 3.5   # human pipetting error rate
MANUAL_OVERHEAD_MULTIPLIER    = 1.25  # setup + cleanup overhead


# ---------------------------------------------------------------------------
# Helper: extract command lists by type
# ---------------------------------------------------------------------------

def _commands_of_type(commands: list[dict], cmd_type: str) -> list[dict]:
    return [c for c in commands if c.get("command_type") == cmd_type]


def _extract_reagent_keywords(text: str) -> list[str]:
    """Extract reagent keywords from instruction text for price lookup."""
    text_lower = text.lower()
    found = []
    for keyword in REAGENT_PRICES:
        if keyword in text_lower:
            found.append(keyword)
    return found or ["generic"]


# ---------------------------------------------------------------------------
# Engine 1: Cost
# ---------------------------------------------------------------------------

class CostEngine:
    """Compute itemised protocol cost from execution plan + protocol data."""

    def compute(
        self,
        plan: dict,
        protocol: dict,
        telemetry: dict | None = None,
    ) -> ProtocolCost:
        """
        Args:
            plan:      ExecutionPlan.summary() dict or full plan dict.
            protocol:  GeneratedProtocol dict.
            telemetry: SimulationResult.telemetry dict (optional).
        """
        protocol_id    = protocol.get("protocol_id", "unknown")
        protocol_title = protocol.get("title", "Untitled")
        tel            = telemetry or {}
        commands       = plan.get("commands", [])
        line_items: list[CostLineItem] = []

        # ---- Reagent costs ----
        aspirated_ul = tel.get("total_volume_aspirated_ul", 0.0)
        steps = protocol.get("steps", [])
        reagents = protocol.get("reagents", [])

        if aspirated_ul > 0 and steps:
            # Distribute volume across steps proportionally
            vol_per_step = aspirated_ul / max(len(steps), 1)
            for step in steps:
                instruction = step.get("instruction", "")
                keywords = _extract_reagent_keywords(instruction)
                for kw in keywords[:1]:   # one reagent per step to avoid double-counting
                    price_ul = REAGENT_PRICES.get(kw, REAGENT_PRICES["generic"])
                    total = vol_per_step * price_ul
                    line_items.append(CostLineItem(
                        category="reagent",
                        description=f"Reagent ({kw}) — step {step.get('step_number',0)}",
                        quantity=vol_per_step,
                        unit="µL",
                        unit_cost_usd=price_ul,
                        total_usd=total,
                    ))

        # ---- Tip costs ----
        tip_changes = tel.get("tip_changes", 0)
        if tip_changes == 0:
            # Estimate from commands
            tip_changes = len(_commands_of_type(commands, "pick_up_tip"))

        if tip_changes > 0:
            tip_price = TIP_PRICES["tip_rack_300ul"]  # default
            line_items.append(CostLineItem(
                category="tips",
                description=f"Disposable tips × {tip_changes}",
                quantity=tip_changes,
                unit="each",
                unit_cost_usd=tip_price,
                total_usd=tip_changes * tip_price,
            ))

        # ---- Consumable plates/tubes (from reagent list keywords) ----
        reagent_text = " ".join(reagents).lower()
        if "plate" in reagent_text or "well" in reagent_text:
            line_items.append(CostLineItem(
                category="consumables",
                description="96-well plate",
                quantity=1,
                unit="each",
                unit_cost_usd=PLATE_96_WELL_USD,
                total_usd=PLATE_96_WELL_USD,
            ))

        # ---- Robot time ----
        duration_min = plan.get("estimated_mins", 0)
        if duration_min == 0:
            duration_min = plan.get("estimated_total_duration_s", 0) / 60
        robot_cost = (duration_min / 60) * ROBOT_HOURLY_USD
        line_items.append(CostLineItem(
            category="instrument_time",
            description=f"Robot time ({duration_min:.1f} min)",
            quantity=duration_min,
            unit="minutes",
            unit_cost_usd=ROBOT_HOURLY_USD / 60,
            total_usd=robot_cost,
        ))

        # ---- Electricity ----
        duration_h = duration_min / 60
        energy_kwh = (ROBOT_WATTS / 1000) * duration_h
        elec_cost = energy_kwh * ELECTRICITY_USD_KWH
        line_items.append(CostLineItem(
            category="overhead",
            description=f"Electricity ({energy_kwh*1000:.1f} Wh)",
            quantity=energy_kwh,
            unit="kWh",
            unit_cost_usd=ELECTRICITY_USD_KWH,
            total_usd=elec_cost,
        ))

        return ProtocolCost(
            protocol_id=protocol_id,
            protocol_title=protocol_title,
            line_items=line_items,
        )


# ---------------------------------------------------------------------------
# Engine 2: Sustainability
# ---------------------------------------------------------------------------

class SustainabilityEngine:
    """Compute environmental impact metrics from execution plan."""

    def compute(
        self,
        plan: dict,
        protocol: dict,
        telemetry: dict | None = None,
    ) -> SustainabilityScore:
        tel      = telemetry or {}
        commands = plan.get("commands", [])
        pid      = protocol.get("protocol_id", "unknown")
        ptitle   = protocol.get("title", "Untitled")

        score = SustainabilityScore(protocol_id=pid, protocol_title=ptitle)

        # ---- Tips ----
        score.tip_count = tel.get("tip_changes", 0) or len(_commands_of_type(commands, "pick_up_tip"))
        score.tip_plastic_g = score.tip_count * TIP_300UL_G   # default 300µL

        # ---- Plates ----
        plate_count = sum(1 for r in protocol.get("reagents", [])
                          if "plate" in r.lower() or "well" in r.lower())
        score.plate_count   = plate_count
        score.plate_plastic_g = plate_count * PLATE_96_G

        # ---- Tubes ----
        tube_count = sum(1 for eq in protocol.get("equipment", [])
                         if "tube" in eq.lower() or "eppendorf" in eq.lower())
        score.tube_count    = tube_count
        score.tube_plastic_g = tube_count * TUBE_1_5ML_G

        score.total_plastic_g = score.tip_plastic_g + score.plate_plastic_g + score.tube_plastic_g

        # ---- Energy ----
        duration_h = plan.get("estimated_mins", 0) / 60 or \
                     plan.get("estimated_total_duration_s", 0) / 3600

        robot_kwh = (ROBOT_WATTS / 1000) * duration_h

        centrifuge_cmds = _commands_of_type(commands, "centrifuge")
        centrifuge_h = sum(c.get("duration_s", 0) for c in centrifuge_cmds) / 3600
        centrifuge_kwh = (CENTRIFUGE_WATTS / 1000) * centrifuge_h

        incubate_cmds = _commands_of_type(commands, "incubate")
        incubate_h = sum(c.get("duration_s", 0) for c in incubate_cmds) / 3600
        incubate_kwh = (INCUBATOR_WATTS / 1000) * incubate_h

        read_cmds = _commands_of_type(commands, "read_absorbance")
        read_kwh = (PLATE_READER_WATTS / 1000) * (len(read_cmds) * 0.01)  # ~36s per read

        score.instrument_energy_kwh = robot_kwh + centrifuge_kwh + incubate_kwh + read_kwh
        score.total_energy_kwh      = score.instrument_energy_kwh + score.cooling_energy_kwh

        # ---- Carbon ----
        score.co2_g = score.total_energy_kwh * GRID_CO2_G_PER_KWH

        # ---- Liquid waste ----
        score.liquid_waste_ml = tel.get("total_volume_dispensed_ul", 0) / 1000

        return score


# ---------------------------------------------------------------------------
# Engine 3: Manual baseline estimator
# ---------------------------------------------------------------------------

class ManualBaselineEngine:
    """Estimate what the same protocol would cost and take if done manually."""

    def compute(self, plan: dict, protocol: dict) -> ManualBaseline:
        steps = protocol.get("steps", [])
        pid   = protocol.get("protocol_id", "unknown")

        # Estimate manual time: each step + overhead
        pipette_steps = sum(
            1 for s in steps
            if re.search(r"\b(pipette|transfer|add|aspirate|dispense)\b",
                         s.get("instruction",""), re.IGNORECASE)
        )
        incubate_steps = sum(
            1 for s in steps
            if re.search(r"\b(incubate|centrifuge|wait|pause)\b",
                         s.get("instruction",""), re.IGNORECASE)
        )
        incubate_duration_min = plan.get("estimated_mins", 0) * 0.6   # 60% of robot time is wait time
        manual_active_min = pipette_steps * MANUAL_PIPETTING_MIN_PER_STEP
        manual_total_min = (manual_active_min + incubate_duration_min) * MANUAL_OVERHEAD_MULTIPLIER

        # Cost: scientist time + reagent waste from errors
        labour_cost = (manual_total_min / 60) * SCIENTIST_HOURLY_USD

        # Reagent waste from human error — roughly 15% more reagent used
        # (conservatively estimated from aspirated volume)
        commands = plan.get("commands", [])
        aspirate_cmds = _commands_of_type(commands, "aspirate")
        aspirated_ul = sum(c.get("volume_ul", 0) for c in aspirate_cmds)
        reagent_waste_usd = aspirated_ul * REAGENT_PRICES["generic"] * (MANUAL_OVERHEAD_MULTIPLIER - 1)

        manual_cost = labour_cost + reagent_waste_usd

        return ManualBaseline(
            protocol_id=pid,
            manual_duration_min=manual_total_min,
            manual_error_rate_pct=MANUAL_ERROR_RATE_PCT,
            manual_cost_usd=manual_cost,
        )


# ---------------------------------------------------------------------------
# Engine 4: Full efficiency report
# ---------------------------------------------------------------------------

class AnalyticsEngine:
    """
    Orchestrates all four engines into a single EfficiencyReport.
    This is the primary public API for Phase 5.
    """

    def __init__(self) -> None:
        self._cost       = CostEngine()
        self._sustain    = SustainabilityEngine()
        self._manual     = ManualBaselineEngine()

    def compute_report(
        self,
        plan: dict,
        protocol: dict,
        telemetry: dict | None = None,
    ) -> EfficiencyReport:
        """
        Compute full analytics for one protocol execution.

        Args:
            plan:      ExecutionPlan dict (from /api/v1/plans/{id} or summary).
            protocol:  GeneratedProtocol dict.
            telemetry: SimulationResult.telemetry (optional, enriches cost/sustain).

        Returns:
            EfficiencyReport with cost, sustainability, and vs-manual comparison.
        """
        cost     = self._cost.compute(plan, protocol, telemetry)
        sustain  = self._sustain.compute(plan, protocol, telemetry)
        baseline = self._manual.compute(plan, protocol)

        duration_min = (
            plan.get("estimated_mins")
            or plan.get("estimated_total_duration_s", 0) / 60
        )

        report = EfficiencyReport(
            protocol_id=protocol.get("protocol_id", "unknown"),
            protocol_title=protocol.get("title", "Untitled"),
            robot_duration_min=duration_min,
            manual_baseline=baseline,
            robot_cost=cost,
            robot_sustainability=sustain,
        )

        log.info("analytics_report_computed",
                 protocol_id=report.protocol_id,
                 cost_usd=round(cost.total_usd, 4),
                 time_saved_min=round(report.time_saved_min, 1),
                 plastic_g=round(sustain.total_plastic_g, 3))

        return report

    def compute_aggregate(self, reports: list[EfficiencyReport]) -> AggregateAnalytics:
        """Aggregate multiple EfficiencyReports into fleet-level analytics."""
        agg = AggregateAnalytics()
        for r in reports:
            agg.add_report(r)
        return agg