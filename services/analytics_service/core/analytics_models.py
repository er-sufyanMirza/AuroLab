"""
aurolab/services/analytics_service/core/analytics_models.py

Typed output models for all Phase 5 analytics engines.

Every metric has a value, unit, and basis so downstream consumers
(dashboard, export, API) always know what they're displaying.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Cost models
# ---------------------------------------------------------------------------

@dataclass
class CostLineItem:
    """One line in a protocol cost breakdown."""
    category: str          # "reagent" | "tips" | "labour" | "instrument_time" | "overhead"
    description: str
    quantity: float
    unit: str              # "µL", "each", "minutes", "runs"
    unit_cost_usd: float
    total_usd: float

    @property
    def formatted(self) -> str:
        return f"${self.total_usd:.4f}"


@dataclass
class ProtocolCost:
    """Full cost breakdown for one protocol execution."""
    protocol_id: str
    protocol_title: str
    line_items: list[CostLineItem] = field(default_factory=list)
    currency: str = "USD"

    @property
    def total_usd(self) -> float:
        return sum(i.total_usd for i in self.line_items)

    @property
    def reagent_cost_usd(self) -> float:
        return sum(i.total_usd for i in self.line_items if i.category == "reagent")

    @property
    def consumable_cost_usd(self) -> float:
        return sum(i.total_usd for i in self.line_items if i.category == "tips")

    @property
    def labour_cost_usd(self) -> float:
        return sum(i.total_usd for i in self.line_items if i.category == "labour")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_id":          self.protocol_id,
            "protocol_title":       self.protocol_title,
            "total_usd":            round(self.total_usd, 4),
            "reagent_cost_usd":     round(self.reagent_cost_usd, 4),
            "consumable_cost_usd":  round(self.consumable_cost_usd, 4),
            "labour_cost_usd":      round(self.labour_cost_usd, 4),
            "line_items": [
                {
                    "category":      i.category,
                    "description":   i.description,
                    "quantity":      round(i.quantity, 4),
                    "unit":          i.unit,
                    "unit_cost_usd": round(i.unit_cost_usd, 6),
                    "total_usd":     round(i.total_usd, 4),
                }
                for i in self.line_items
            ],
        }


# ---------------------------------------------------------------------------
# Sustainability models
# ---------------------------------------------------------------------------

@dataclass
class SustainabilityScore:
    """Environmental impact metrics for one protocol execution."""
    protocol_id: str
    protocol_title: str

    # Plastic waste
    tip_count: int = 0
    tip_plastic_g: float = 0.0           # grams of plastic from tips
    tube_count: int = 0
    tube_plastic_g: float = 0.0
    plate_count: int = 0
    plate_plastic_g: float = 0.0
    total_plastic_g: float = 0.0

    # Energy
    instrument_energy_kwh: float = 0.0   # centrifuge + incubator + reader + robot
    cooling_energy_kwh: float = 0.0      # -20°C / -80°C steps
    total_energy_kwh: float = 0.0

    # Carbon
    co2_g: float = 0.0                   # gCO₂eq (energy × regional grid factor)
    grid_factor_g_per_kwh: float = 386.0 # US average 2024

    # Water
    water_ml: float = 0.0

    # Waste liquid
    liquid_waste_ml: float = 0.0

    @property
    def plastic_rating(self) -> str:
        if self.total_plastic_g < 2:    return "A"
        if self.total_plastic_g < 5:    return "B"
        if self.total_plastic_g < 15:   return "C"
        if self.total_plastic_g < 30:   return "D"
        return "F"

    @property
    def energy_rating(self) -> str:
        if self.total_energy_kwh < 0.05:  return "A"
        if self.total_energy_kwh < 0.2:   return "B"
        if self.total_energy_kwh < 0.5:   return "C"
        if self.total_energy_kwh < 1.0:   return "D"
        return "F"

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_id":           self.protocol_id,
            "protocol_title":        self.protocol_title,
            "tip_count":             self.tip_count,
            "tip_plastic_g":         round(self.tip_plastic_g, 3),
            "total_plastic_g":       round(self.total_plastic_g, 3),
            "plastic_rating":        self.plastic_rating,
            "instrument_energy_kwh": round(self.instrument_energy_kwh, 5),
            "total_energy_kwh":      round(self.total_energy_kwh, 5),
            "energy_rating":         self.energy_rating,
            "co2_g":                 round(self.co2_g, 3),
            "water_ml":              round(self.water_ml, 1),
            "liquid_waste_ml":       round(self.liquid_waste_ml, 1),
        }


# ---------------------------------------------------------------------------
# Efficiency models
# ---------------------------------------------------------------------------

@dataclass
class ManualBaseline:
    """
    Estimated manual execution metrics for the same protocol.
    Used as the comparison baseline for ROI calculations.
    """
    protocol_id: str
    manual_duration_min: float         # estimated human time
    manual_error_rate_pct: float       # typical human pipetting error rate
    manual_cost_usd: float             # labour + reagent waste from errors
    scientist_hourly_rate_usd: float = 75.0
    error_waste_multiplier: float = 1.15  # 15% extra reagent due to errors


@dataclass
class EfficiencyReport:
    """Comparison of robot vs manual execution."""
    protocol_id: str
    protocol_title: str
    robot_duration_min: float
    manual_baseline: ManualBaseline
    robot_cost: ProtocolCost
    robot_sustainability: SustainabilityScore

    @property
    def time_saved_min(self) -> float:
        return max(0, self.manual_baseline.manual_duration_min - self.robot_duration_min)

    @property
    def time_saved_pct(self) -> float:
        if self.manual_baseline.manual_duration_min == 0:
            return 0.0
        return (self.time_saved_min / self.manual_baseline.manual_duration_min) * 100

    @property
    def cost_saved_usd(self) -> float:
        return max(0, self.manual_baseline.manual_cost_usd - self.robot_cost.total_usd)

    @property
    def cost_saved_pct(self) -> float:
        if self.manual_baseline.manual_cost_usd == 0:
            return 0.0
        return (self.cost_saved_usd / self.manual_baseline.manual_cost_usd) * 100

    @property
    def annual_savings_usd(self, runs_per_year: int = 250) -> float:
        return self.cost_saved_usd * runs_per_year

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_id":             self.protocol_id,
            "protocol_title":          self.protocol_title,
            "robot_duration_min":      round(self.robot_duration_min, 1),
            "manual_duration_min":     round(self.manual_baseline.manual_duration_min, 1),
            "time_saved_min":          round(self.time_saved_min, 1),
            "time_saved_pct":          round(self.time_saved_pct, 1),
            "robot_cost_usd":          round(self.robot_cost.total_usd, 4),
            "manual_cost_usd":         round(self.manual_baseline.manual_cost_usd, 4),
            "cost_saved_usd":          round(self.cost_saved_usd, 4),
            "cost_saved_pct":          round(self.cost_saved_pct, 1),
            "annual_savings_usd_250runs": round(self.cost_saved_usd * 250, 2),
            "plastic_g":               round(self.robot_sustainability.total_plastic_g, 3),
            "co2_g":                   round(self.robot_sustainability.co2_g, 3),
            "energy_kwh":              round(self.robot_sustainability.total_energy_kwh, 5),
            "plastic_rating":          self.robot_sustainability.plastic_rating,
            "energy_rating":           self.robot_sustainability.energy_rating,
        }


# ---------------------------------------------------------------------------
# Aggregate analytics (across multiple protocols)
# ---------------------------------------------------------------------------

@dataclass
class AggregateAnalytics:
    """Fleet-level analytics across all protocols run in a session."""
    total_protocols: int = 0
    total_cost_usd: float = 0.0
    total_time_saved_min: float = 0.0
    total_cost_saved_usd: float = 0.0
    total_plastic_g: float = 0.0
    total_co2_g: float = 0.0
    total_energy_kwh: float = 0.0
    total_tip_count: int = 0
    total_volume_aspirated_ul: float = 0.0
    protocol_reports: list[dict] = field(default_factory=list)

    def add_report(self, report: EfficiencyReport) -> None:
        self.total_protocols += 1
        self.total_cost_usd          += report.robot_cost.total_usd
        self.total_time_saved_min    += report.time_saved_min
        self.total_cost_saved_usd    += report.cost_saved_usd
        self.total_plastic_g         += report.robot_sustainability.total_plastic_g
        self.total_co2_g             += report.robot_sustainability.co2_g
        self.total_energy_kwh        += report.robot_sustainability.total_energy_kwh
        self.total_tip_count         += report.robot_sustainability.tip_count
        self.protocol_reports.append(report.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_protocols":        self.total_protocols,
            "total_cost_usd":         round(self.total_cost_usd, 2),
            "total_time_saved_min":   round(self.total_time_saved_min, 1),
            "total_cost_saved_usd":   round(self.total_cost_saved_usd, 2),
            "annual_savings_usd":     round(self.total_cost_saved_usd * 250, 2),
            "total_plastic_g":        round(self.total_plastic_g, 2),
            "total_co2_g":            round(self.total_co2_g, 2),
            "total_energy_kwh":       round(self.total_energy_kwh, 4),
            "total_tip_count":        self.total_tip_count,
            "protocol_reports":       self.protocol_reports,
        }