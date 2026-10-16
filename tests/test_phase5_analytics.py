"""
tests/test_phase5_analytics.py

Tests for Phase 5: analytics models, cost engine, sustainability engine,
manual baseline, efficiency report, and aggregate analytics.
Run with: pytest tests/test_phase5_analytics.py -v
"""

from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))



import pytest

from services.analytics_service.core.analytics_models import (
    AggregateAnalytics, CostLineItem, EfficiencyReport,
    ManualBaseline, ProtocolCost, SustainabilityScore,
)
from services.analytics_service.core.analytics_engine import (
    AnalyticsEngine, CostEngine, SustainabilityEngine, ManualBaselineEngine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PROTOCOL = {
    "protocol_id":    "test-analytics-001",
    "title":          "BCA Protein Assay",
    "description":    "Standard BCA assay",
    "steps": [
        {"step_number": 1, "instruction": "Pipette 50 µL BCA reagent from slot 1 to slot 2"},
        {"step_number": 2, "instruction": "Incubate at 37°C for 30 minutes"},
        {"step_number": 3, "instruction": "Read absorbance at 562 nm"},
    ],
    "reagents":  ["BCA reagent", "BSA standard", "96-well plate"],
    "equipment": ["plate reader", "incubator", "1.5 mL tubes"],
    "safety_level": "safe", "safety_notes": [],
    "confidence_score": 0.9, "generation_ms": 100.0, "model_used": "test",
}

SAMPLE_PLAN = {
    "protocol_id":     "test-analytics-001",
    "estimated_mins":  45.0,
    "commands": [
        {"command_type": "home",           "command_index": 0, "protocol_step_ref": 0},
        {"command_type": "pick_up_tip",    "command_index": 1, "protocol_step_ref": 1},
        {"command_type": "aspirate",       "command_index": 2, "protocol_step_ref": 1, "volume_ul": 50.0},
        {"command_type": "dispense",       "command_index": 3, "protocol_step_ref": 1, "volume_ul": 50.0},
        {"command_type": "drop_tip",       "command_index": 4, "protocol_step_ref": 1},
        {"command_type": "incubate",       "command_index": 5, "protocol_step_ref": 2, "duration_s": 1800},
        {"command_type": "read_absorbance","command_index": 6, "protocol_step_ref": 3, "wavelength_nm": 562},
        {"command_type": "home",           "command_index": 7, "protocol_step_ref": 3},
    ],
}

SAMPLE_TELEMETRY = {
    "commands_executed":        8,
    "tip_changes":              1,
    "total_volume_aspirated_ul": 50.0,
    "total_volume_dispensed_ul": 50.0,
    "warnings":                 [],
}


# ---------------------------------------------------------------------------
# CostLineItem and ProtocolCost model tests
# ---------------------------------------------------------------------------

class TestCostModels:

    def test_line_item_formatted(self):
        item = CostLineItem("reagent", "BCA", 50.0, "µL", 0.0008, 0.04)
        assert item.formatted == "$0.0400"

    def test_protocol_cost_total(self):
        items = [
            CostLineItem("reagent", "A", 1, "µL", 0.001, 0.001),
            CostLineItem("tips",    "B", 1, "each", 0.06, 0.06),
        ]
        pc = ProtocolCost("id", "title", items)
        assert pc.total_usd == pytest.approx(0.061)

    def test_protocol_cost_category_breakdown(self):
        items = [
            CostLineItem("reagent", "A", 1, "µL", 0.001, 0.50),
            CostLineItem("tips",    "B", 1, "each", 0.06, 0.06),
            CostLineItem("labour",  "C", 1, "min", 1.25, 1.25),
        ]
        pc = ProtocolCost("id", "title", items)
        assert pc.reagent_cost_usd == pytest.approx(0.50)
        assert pc.consumable_cost_usd == pytest.approx(0.06)
        assert pc.labour_cost_usd == pytest.approx(1.25)

    def test_protocol_cost_to_dict_keys(self):
        pc = ProtocolCost("id", "title", [])
        d = pc.to_dict()
        for k in ["protocol_id", "total_usd", "line_items"]:
            assert k in d


# ---------------------------------------------------------------------------
# SustainabilityScore model tests
# ---------------------------------------------------------------------------

class TestSustainabilityModel:

    def test_plastic_rating_A(self):
        s = SustainabilityScore("id", "t", total_plastic_g=1.0)
        assert s.plastic_rating == "A"

    def test_plastic_rating_F(self):
        s = SustainabilityScore("id", "t", total_plastic_g=50.0)
        assert s.plastic_rating == "F"

    def test_energy_rating_A(self):
        s = SustainabilityScore("id", "t", total_energy_kwh=0.01)
        assert s.energy_rating == "A"

    def test_to_dict_has_ratings(self):
        s = SustainabilityScore("id", "t", total_plastic_g=3.0, total_energy_kwh=0.1)
        d = s.to_dict()
        assert "plastic_rating" in d
        assert "energy_rating" in d


# ---------------------------------------------------------------------------
# EfficiencyReport tests
# ---------------------------------------------------------------------------

class TestEfficiencyReport:

    def _make_report(self, robot_dur=30.0, manual_dur=60.0,
                     robot_cost_usd=0.50, manual_cost_usd=2.00) -> EfficiencyReport:
        pc = ProtocolCost("id", "t", [CostLineItem("reagent","r",1,"µL",robot_cost_usd,robot_cost_usd)])
        ss = SustainabilityScore("id", "t", total_plastic_g=2.0, total_energy_kwh=0.05, co2_g=19.3)
        mb = ManualBaseline("id", manual_dur, 3.5, manual_cost_usd)
        return EfficiencyReport("id", "title", robot_dur, mb, pc, ss)

    def test_time_saved(self):
        r = self._make_report(robot_dur=30, manual_dur=60)
        assert r.time_saved_min == pytest.approx(30.0)

    def test_time_saved_pct(self):
        r = self._make_report(robot_dur=30, manual_dur=60)
        assert r.time_saved_pct == pytest.approx(50.0)

    def test_cost_saved(self):
        r = self._make_report(robot_cost_usd=0.5, manual_cost_usd=2.0)
        assert r.cost_saved_usd == pytest.approx(1.5)

    def test_cost_saved_pct(self):
        r = self._make_report(robot_cost_usd=0.5, manual_cost_usd=2.0)
        assert r.cost_saved_pct == pytest.approx(75.0)

    def test_time_saved_never_negative(self):
        r = self._make_report(robot_dur=90, manual_dur=30)
        assert r.time_saved_min == 0.0

    def test_cost_saved_never_negative(self):
        r = self._make_report(robot_cost_usd=5.0, manual_cost_usd=1.0)
        assert r.cost_saved_usd == 0.0

    def test_to_dict_keys(self):
        r = self._make_report()
        d = r.to_dict()
        for k in ["robot_duration_min", "manual_duration_min", "time_saved_min",
                  "cost_saved_usd", "annual_savings_usd_250runs",
                  "plastic_rating", "energy_rating"]:
            assert k in d


# ---------------------------------------------------------------------------
# CostEngine tests
# ---------------------------------------------------------------------------

class TestCostEngine:

    def test_returns_protocol_cost(self):
        engine = CostEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        assert isinstance(result, ProtocolCost)

    def test_total_cost_positive(self):
        engine = CostEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        assert result.total_usd > 0

    def test_tip_cost_present(self):
        engine = CostEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        categories = [i.category for i in result.line_items]
        assert "tips" in categories

    def test_instrument_time_cost_present(self):
        engine = CostEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        categories = [i.category for i in result.line_items]
        assert "instrument_time" in categories

    def test_to_dict_serialisable(self):
        engine = CostEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        d = result.to_dict()
        assert isinstance(d["total_usd"], float)
        assert isinstance(d["line_items"], list)

    def test_zero_duration_still_returns_result(self):
        plan = dict(SAMPLE_PLAN, estimated_mins=0)
        engine = CostEngine()
        result = engine.compute(plan, SAMPLE_PROTOCOL)
        assert result.total_usd >= 0


# ---------------------------------------------------------------------------
# SustainabilityEngine tests
# ---------------------------------------------------------------------------

class TestSustainabilityEngine:

    def test_returns_score(self):
        engine = SustainabilityEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        assert isinstance(result, SustainabilityScore)

    def test_tip_count_from_telemetry(self):
        engine = SustainabilityEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        assert result.tip_count == 1   # from telemetry tip_changes=1

    def test_tip_plastic_positive(self):
        engine = SustainabilityEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        assert result.tip_plastic_g > 0

    def test_energy_positive(self):
        engine = SustainabilityEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        assert result.total_energy_kwh > 0

    def test_co2_positive(self):
        engine = SustainabilityEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        assert result.co2_g > 0

    def test_plate_detected_from_reagents(self):
        engine = SustainabilityEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        # "96-well plate" is in SAMPLE_PROTOCOL reagents
        assert result.plate_count >= 1


# ---------------------------------------------------------------------------
# ManualBaselineEngine tests
# ---------------------------------------------------------------------------

class TestManualBaselineEngine:

    def test_returns_baseline(self):
        engine = ManualBaselineEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL)
        assert isinstance(result, ManualBaseline)

    def test_manual_duration_positive(self):
        engine = ManualBaselineEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL)
        assert result.manual_duration_min > 0

    def test_manual_cost_positive(self):
        engine = ManualBaselineEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL)
        assert result.manual_cost_usd > 0

    def test_error_rate_reasonable(self):
        engine = ManualBaselineEngine()
        result = engine.compute(SAMPLE_PLAN, SAMPLE_PROTOCOL)
        assert 0 < result.manual_error_rate_pct < 20


# ---------------------------------------------------------------------------
# Full AnalyticsEngine tests
# ---------------------------------------------------------------------------

class TestAnalyticsEngine:

    def test_compute_report_returns_efficiency_report(self):
        engine = AnalyticsEngine()
        report = engine.compute_report(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        assert isinstance(report, EfficiencyReport)

    def test_report_to_dict_complete(self):
        engine = AnalyticsEngine()
        report = engine.compute_report(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        d = report.to_dict()
        for key in ["robot_duration_min", "manual_duration_min", "time_saved_min",
                    "robot_cost_usd", "manual_cost_usd", "cost_saved_pct",
                    "annual_savings_usd_250runs", "plastic_g", "co2_g",
                    "plastic_rating", "energy_rating"]:
            assert key in d, f"Missing key: {key}"

    def test_time_saved_non_negative(self):
        engine = AnalyticsEngine()
        report = engine.compute_report(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        assert report.time_saved_min >= 0

    def test_cost_saved_non_negative(self):
        engine = AnalyticsEngine()
        report = engine.compute_report(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        assert report.cost_saved_usd >= 0

    def test_aggregate_single_report(self):
        engine = AnalyticsEngine()
        report = engine.compute_report(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        agg = engine.compute_aggregate([report])
        assert agg.total_protocols == 1
        assert agg.total_cost_usd > 0

    def test_aggregate_multiple_reports(self):
        engine = AnalyticsEngine()
        r1 = engine.compute_report(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        r2 = engine.compute_report(SAMPLE_PLAN, dict(SAMPLE_PROTOCOL, protocol_id="other"), SAMPLE_TELEMETRY)
        agg = engine.compute_aggregate([r1, r2])
        assert agg.total_protocols == 2
        assert agg.total_plastic_g == pytest.approx(r1.robot_sustainability.total_plastic_g * 2)

    def test_aggregate_to_dict_keys(self):
        engine = AnalyticsEngine()
        r = engine.compute_report(SAMPLE_PLAN, SAMPLE_PROTOCOL, SAMPLE_TELEMETRY)
        agg = engine.compute_aggregate([r])
        d = agg.to_dict()
        for k in ["total_protocols", "total_cost_usd", "total_cost_saved_usd",
                  "annual_savings_usd", "total_plastic_g", "total_co2_g"]:
            assert k in d, f"Missing key: {k}"

    def test_empty_aggregate(self):
        engine = AnalyticsEngine()
        agg = engine.compute_aggregate([])
        assert agg.total_protocols == 0
        assert agg.total_cost_usd == 0.0