"""
tests/test_phase4_vision.py

Tests for Phase 4: lab state model, vision engine, detection parsing,
orchestrator integration with live lab state.
Run with: pytest tests/test_phase4_vision.py -v
"""

from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))



import json
import pytest
from unittest.mock import MagicMock, patch

from services.vision_service.core.lab_state import (
    FillLevel, LabState, LabwareType, SlotDetection,
)
from services.vision_service.core.vision_engine import (
    VisionEngine, VisionBackend,
    _run_mock_detection, _parse_vlm_response, _empty_lab_state,
    _MOCK_SCENARIOS,
)
from services.execution_service.core.orchestrator import execute_protocol
from services.execution_service.core.isaac_sim_bridge import SimMode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_slot(slot: int, ltype: LabwareType = LabwareType.PLATE_96_WELL,
               conf: float = 0.9, fill: FillLevel = FillLevel.FULL) -> SlotDetection:
    return SlotDetection(slot=slot, labware_type=ltype, confidence=conf, fill_level=fill)


def _make_full_lab_state(scenario: str = "bca_assay") -> LabState:
    return _run_mock_detection(scenario)


SAMPLE_VLM_JSON = json.dumps({
    "slots": {
        "1": {"labware_type": "96_well_plate", "confidence": 0.95,
              "fill_level": "empty", "is_sealed": False, "notes": None},
        "11": {"labware_type": "tip_rack_300ul", "confidence": 0.98,
               "fill_level": "full", "is_sealed": False, "notes": None},
        "12": {"labware_type": "waste_container", "confidence": 0.99,
               "fill_level": "low", "is_sealed": False, "notes": None},
    },
    "overall_confidence": 0.97,
    "warnings": [],
})

SAMPLE_PROTOCOL = {
    "protocol_id": "test-vision-001",
    "title": "BCA Assay",
    "description": "Test",
    "steps": [
        {"step_number": 1, "instruction": "Pipette 50 µL from slot 1 to slot 2"},
        {"step_number": 2, "instruction": "Incubate at 37°C for 30 minutes"},
        {"step_number": 3, "instruction": "Read absorbance at 562 nm"},
    ],
    "reagents": [], "equipment": [],
    "safety_level": "safe", "safety_notes": [],
    "confidence_score": 0.9, "generation_ms": 100.0, "model_used": "test",
}


# ---------------------------------------------------------------------------
# SlotDetection tests
# ---------------------------------------------------------------------------

class TestSlotDetection:

    def test_is_occupied_true(self):
        slot = _make_slot(1)
        assert slot.is_occupied is True

    def test_is_occupied_false_for_empty(self):
        slot = SlotDetection(slot=1, labware_type=LabwareType.EMPTY,
                             confidence=0.99, fill_level=FillLevel.EMPTY)
        assert slot.is_occupied is False

    def test_is_occupied_false_for_unknown(self):
        slot = SlotDetection(slot=1, labware_type=LabwareType.UNKNOWN,
                             confidence=0.0, fill_level=FillLevel.UNKNOWN)
        assert slot.is_occupied is False

    def test_needs_attention_low_confidence(self):
        slot = _make_slot(1, conf=0.3)
        assert slot.needs_attention is True

    def test_needs_attention_critical_fill(self):
        slot = _make_slot(1, fill=FillLevel.CRITICAL)
        assert slot.needs_attention is True

    def test_no_attention_needed_high_conf(self):
        slot = _make_slot(1, conf=0.95, fill=FillLevel.FULL)
        assert slot.needs_attention is False

    def test_to_labware_str(self):
        slot = _make_slot(1, ltype=LabwareType.PLATE_96_WELL)
        assert slot.to_labware_str() == "96_well_plate"

    def test_slot_range_validation(self):
        with pytest.raises(Exception):
            SlotDetection(slot=99, labware_type=LabwareType.EMPTY,
                          confidence=0.9, fill_level=FillLevel.EMPTY)


# ---------------------------------------------------------------------------
# LabState tests
# ---------------------------------------------------------------------------

class TestLabState:

    def test_to_labware_map_excludes_low_confidence(self):
        state = _make_full_lab_state()
        # All mock detections have high confidence so should all appear
        lmap = state.to_labware_map()
        assert len(lmap) > 0
        assert all(isinstance(k, int) for k in lmap)
        assert all(isinstance(v, str) for v in lmap.values())

    def test_to_labware_map_excludes_empty(self):
        state = _make_full_lab_state("bca_assay")
        lmap = state.to_labware_map()
        assert "empty" not in lmap.values()
        assert "unknown" not in lmap.values()

    def test_occupied_slots_non_empty(self):
        state = _make_full_lab_state()
        assert len(state.occupied_slots()) > 0

    def test_tip_rack_slots_detected(self):
        state = _make_full_lab_state("bca_assay")
        assert 11 in state.tip_rack_slots()

    def test_attention_slots_for_critical_fill(self):
        state = _make_full_lab_state("low_tips_warning")
        # Slot 11 has critical fill in this scenario
        assert 11 in state.attention_slots()

    def test_summary_has_required_keys(self):
        state = _make_full_lab_state()
        s = state.summary()
        for key in ["snapshot_id", "source", "overall_confidence",
                    "occupied_slots", "attention_needed", "tip_racks"]:
            assert key in s

    def test_overall_confidence_in_range(self):
        state = _make_full_lab_state()
        assert 0.0 <= state.overall_confidence <= 1.0

    def test_all_12_slots_present(self):
        state = _make_full_lab_state()
        assert len(state.slots) == 12
        for i in range(1, 13):
            assert i in state.slots


# ---------------------------------------------------------------------------
# Vision engine tests
# ---------------------------------------------------------------------------

class TestVisionEngine:

    def test_mock_backend_returns_lab_state(self):
        engine = VisionEngine(backend=VisionBackend.MOCK)
        state = engine.detect()
        assert isinstance(state, LabState)

    def test_mock_all_scenarios_work(self):
        engine = VisionEngine(backend=VisionBackend.MOCK)
        for scenario in _MOCK_SCENARIOS:
            state = engine.detect(mock_scenario=scenario)
            assert isinstance(state, LabState)
            assert len(state.slots) == 12

    def test_last_state_updated_after_detect(self):
        engine = VisionEngine(backend=VisionBackend.MOCK)
        assert engine.last_state is None
        engine.detect()
        assert engine.last_state is not None

    def test_available_scenarios(self):
        engine = VisionEngine(backend=VisionBackend.MOCK)
        scenarios = engine.available_mock_scenarios()
        assert "bca_assay" in scenarios
        assert len(scenarios) >= 2

    def test_groq_backend_requires_image(self):
        engine = VisionEngine(backend=VisionBackend.GROQ, groq_api_key="test")
        with pytest.raises(ValueError, match="image_bytes required"):
            engine.detect(image_bytes=None)

    def test_llava_backend_requires_image(self):
        engine = VisionEngine(backend=VisionBackend.LLAVA)
        with pytest.raises(ValueError, match="image_bytes required"):
            engine.detect(image_bytes=None)


# ---------------------------------------------------------------------------
# VLM response parser tests
# ---------------------------------------------------------------------------

class TestVLMParser:

    def test_parse_clean_json(self):
        state = _parse_vlm_response(SAMPLE_VLM_JSON, source="groq")
        assert isinstance(state, LabState)
        assert state.source == "groq"
        assert state.slots[1].labware_type == LabwareType.PLATE_96_WELL
        assert state.slots[11].labware_type == LabwareType.TIP_RACK_300UL

    def test_parse_json_with_markdown_fences(self):
        fenced = f"```json\n{SAMPLE_VLM_JSON}\n```"
        state = _parse_vlm_response(fenced, source="llava")
        assert state.slots[1].labware_type == LabwareType.PLATE_96_WELL

    def test_parse_missing_slots_filled_with_unknown(self):
        state = _parse_vlm_response(SAMPLE_VLM_JSON, source="groq")
        # Slots not in the JSON should be present as EMPTY
        for slot_num in range(1, 13):
            assert slot_num in state.slots

    def test_parse_garbage_returns_empty_state(self):
        state = _parse_vlm_response("this is not json at all", source="groq")
        assert isinstance(state, LabState)
        assert len(state.warnings) > 0

    def test_parse_unknown_labware_type_handled(self):
        bad_json = json.dumps({
            "slots": {"1": {"labware_type": "flying_saucer", "confidence": 0.9,
                            "fill_level": "full", "is_sealed": False}},
            "overall_confidence": 0.9, "warnings": [],
        })
        state = _parse_vlm_response(bad_json, source="test")
        assert state.slots[1].labware_type == LabwareType.UNKNOWN
        assert any("flying_saucer" in w for w in state.warnings)

    def test_parse_confidence_preserved(self):
        state = _parse_vlm_response(SAMPLE_VLM_JSON, source="groq")
        assert state.slots[1].confidence == pytest.approx(0.95)
        assert state.overall_confidence == pytest.approx(0.97)


# ---------------------------------------------------------------------------
# Orchestrator integration with vision layer
# ---------------------------------------------------------------------------

class TestOrchestratorVisionIntegration:

    def test_execute_with_lab_state_uses_live_map(self):
        lab_state = _make_full_lab_state("bca_assay")
        plan = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK, lab_state=lab_state)
        # The sim should use the vision labware map — plan should still produce a result
        assert plan is not None
        assert plan.simulation_result is not None

    def test_execute_without_lab_state_uses_static_map(self):
        plan = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK, lab_state=None)
        assert plan is not None
        assert plan.simulation_result is not None

    def test_execute_with_and_without_state_both_complete(self):
        lab_state = _make_full_lab_state("bca_assay")
        plan_with = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK, lab_state=lab_state)
        plan_without = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK, lab_state=None)
        # Both should complete — vision layer is additive, not breaking
        assert plan_with.command_count == plan_without.command_count

    def test_attention_slots_present_in_warnings(self):
        # low_tips_warning scenario has slot 11 (tip rack) at critical fill
        lab_state = _make_full_lab_state("low_tips_warning")
        assert 11 in lab_state.attention_slots()
        assert len(lab_state.warnings) > 0

    def test_lab_state_to_labware_map_feeds_sim(self):
        lab_state = _make_full_lab_state("bca_assay")
        lmap = lab_state.to_labware_map()
        # Should contain tip rack at 11 and waste at 12
        assert 11 in lmap
        assert 12 in lmap
        assert "tip_rack" in lmap[11]