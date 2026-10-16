"""
tests/test_phase3_execution.py

Tests for Phase 3: robot commands, step parser, validator, sim bridge, orchestrator.
Run with: pytest tests/test_phase3_execution.py -v
"""

from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))



import pytest
from unittest.mock import MagicMock, patch

from services.execution_service.core.robot_commands import (
    AspirateCommand, DispenseCommand, MixCommand,
    PickUpTipCommand, DropTipCommand,
    CentrifugeCommand, IncubateCommand,
    PauseCommand, HomeCommand,
    LabwarePosition, Vec3,
    ExecutionPlan, ExecutionStatus, SimulationResult, ValidationError,
    CommandType,
)
from services.execution_service.core.step_parser import parse_step, parse_protocol_steps
from services.execution_service.core.validator import validate_commands
from services.execution_service.core.isaac_sim_bridge import IsaacSimBridge, SimMode, _run_mock_simulation
from services.execution_service.core.orchestrator import execute_protocol


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _aspirate(idx=0, vol=50.0, slot=1):
    return AspirateCommand(
        command_index=idx,
        protocol_step_ref=1,
        volume_ul=vol,
        source=LabwarePosition(deck_slot=slot),
    )

def _dispense(idx=1, vol=50.0, slot=2):
    return DispenseCommand(
        command_index=idx,
        protocol_step_ref=1,
        volume_ul=vol,
        destination=LabwarePosition(deck_slot=slot),
    )

def _pick_tip(idx=0):
    return PickUpTipCommand(command_index=idx, protocol_step_ref=1, tip_rack_slot=11)

def _drop_tip(idx=3):
    return DropTipCommand(command_index=idx, protocol_step_ref=1)

SAMPLE_PROTOCOL = {
    "protocol_id":      "test-proto-001",
    "title":            "BCA Protein Assay",
    "description":      "Standard BCA assay",
    "steps": [
        {"step_number": 1, "instruction": "Pipette 50 µL from slot 1 well A1 to slot 2 well B1"},
        {"step_number": 2, "instruction": "Centrifuge at 3000 rpm for 5 minutes"},
        {"step_number": 3, "instruction": "Incubate at 37°C for 30 minutes"},
        {"step_number": 4, "instruction": "Read absorbance at 562 nm"},
    ],
    "reagents": ["BCA reagent"], "equipment": ["plate reader"],
    "safety_level": "safe", "safety_notes": [],
    "confidence_score": 0.9, "generation_ms": 100.0, "model_used": "test",
}


# ---------------------------------------------------------------------------
# RobotCommand model tests
# ---------------------------------------------------------------------------

class TestRobotCommands:

    def test_aspirate_valid(self):
        cmd = _aspirate()
        assert cmd.volume_ul == 50.0
        assert cmd.command_type == CommandType.ASPIRATE

    def test_aspirate_rejects_zero_volume(self):
        with pytest.raises(Exception):
            AspirateCommand(command_index=0, protocol_step_ref=1, volume_ul=0,
                            source=LabwarePosition(deck_slot=1))

    def test_aspirate_rejects_over_max(self):
        with pytest.raises(Exception):
            AspirateCommand(command_index=0, protocol_step_ref=1, volume_ul=1500,
                            source=LabwarePosition(deck_slot=1))

    def test_centrifuge_valid(self):
        cmd = CentrifugeCommand(command_index=0, protocol_step_ref=1,
                                speed_rpm=13000, duration_s=600)
        assert cmd.speed_rpm == 13000

    def test_centrifuge_rejects_over_max_rpm(self):
        with pytest.raises(Exception):
            CentrifugeCommand(command_index=0, protocol_step_ref=1,
                              speed_rpm=99999, duration_s=600)

    def test_labware_position_well_normalised(self):
        pos = LabwarePosition(deck_slot=1, well="a1")
        assert pos.well == "A1"

    def test_labware_position_invalid_slot(self):
        with pytest.raises(Exception):
            LabwarePosition(deck_slot=99, well="A1")

    def test_to_wire_serialisable(self):
        cmd = _aspirate()
        wire = cmd.to_wire()
        assert isinstance(wire, dict)
        assert "command_type" in wire
        assert "volume_ul" in wire

    def test_execution_plan_is_executable_no_critical(self):
        plan = ExecutionPlan(
            plan_id="p1", protocol_id="x", protocol_title="t",
            commands=[_pick_tip(), _aspirate(1), _dispense(2), _drop_tip(3)],
            status=ExecutionStatus.SIM_PASSED,
            validation_errors=[],
        )
        assert plan.is_executable is True

    def test_execution_plan_not_executable_with_critical(self):
        plan = ExecutionPlan(
            plan_id="p1", protocol_id="x", protocol_title="t",
            commands=[_aspirate()],
            status=ExecutionStatus.VALIDATED,
            validation_errors=[ValidationError(
                command_index=0, command_type="aspirate",
                error_code="CRITICAL_ERR", message="critical",
                severity="critical", auto_corrected=False,
            )],
        )
        assert plan.is_executable is False

    def test_execution_plan_summary_keys(self):
        plan = ExecutionPlan(
            plan_id="p1", protocol_id="x", protocol_title="t",
            commands=[_pick_tip(), _aspirate(1), _drop_tip(2)],
            status=ExecutionStatus.SIM_PASSED,
        )
        s = plan.summary()
        for key in ["plan_id", "status", "command_count", "estimated_mins", "is_executable"]:
            assert key in s


# ---------------------------------------------------------------------------
# Step parser tests
# ---------------------------------------------------------------------------

class TestStepParser:

    def test_pipette_produces_commands(self):
        cmds = parse_step("Pipette 50 µL from slot 1 to slot 2", 1)
        assert len(cmds) > 0

    def test_pipette_includes_tip_management(self):
        cmds = parse_step("Transfer 200 uL from A1 to B2", 1)
        types = {c.command_type for c in cmds}
        assert CommandType.PICK_UP_TIP in types
        assert CommandType.ASPIRATE in types
        assert CommandType.DISPENSE in types
        assert CommandType.DROP_TIP in types

    def test_aspirate_volume_parsed(self):
        cmds = parse_step("Pipette 75 µL from slot 1 to slot 2", 1)
        aspirates = [c for c in cmds if c.command_type == CommandType.ASPIRATE]
        assert len(aspirates) == 1
        assert aspirates[0].volume_ul == 75.0

    def test_centrifuge_parsed(self):
        cmds = parse_step("Centrifuge at 13000 × g for 10 minutes at 4°C", 1)
        assert len(cmds) == 1
        assert cmds[0].command_type == CommandType.CENTRIFUGE
        assert cmds[0].duration_s == 600.0
        assert cmds[0].temperature_celsius == 4.0

    def test_incubate_parsed(self):
        cmds = parse_step("Incubate at 37°C for 30 minutes", 1)
        assert cmds[0].command_type == CommandType.INCUBATE
        assert cmds[0].temperature_celsius == 37.0
        assert cmds[0].duration_s == 1800.0

    def test_on_ice_maps_to_4c(self):
        cmds = parse_step("Incubate on ice for 5 minutes", 1)
        incubates = [c for c in cmds if c.command_type == CommandType.INCUBATE]
        assert incubates[0].temperature_celsius == 4.0

    def test_read_absorbance_parsed(self):
        cmds = parse_step("Read absorbance at 562 nm", 1)
        assert cmds[0].command_type == CommandType.READ_ABSORBANCE
        assert cmds[0].wavelength_nm == 562

    def test_mix_parsed(self):
        cmds = parse_step("Mix 100 µL 5 times", 1)
        assert cmds[0].command_type == CommandType.MIX
        assert cmds[0].repetitions == 5

    def test_unknown_step_produces_pause(self):
        cmds = parse_step("Do something completely novel and unspecified", 1)
        assert len(cmds) == 1
        assert cmds[0].command_type == CommandType.PAUSE

    def test_parse_protocol_steps_adds_home_bookends(self):
        steps = [{"step_number": 1, "instruction": "Centrifuge at 3000 rpm for 5 min"}]
        cmds = parse_protocol_steps(steps)
        assert cmds[0].command_type == CommandType.HOME
        assert cmds[-1].command_type == CommandType.HOME

    def test_parse_protocol_steps_monotonic_index(self):
        steps = [
            {"step_number": 1, "instruction": "Pipette 50 µL from slot 1 to slot 2"},
            {"step_number": 2, "instruction": "Centrifuge at 3000 rpm for 5 min"},
        ]
        cmds = parse_protocol_steps(steps)
        indices = [c.command_index for c in cmds]
        assert indices == sorted(indices)


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestValidator:

    def test_clean_sequence_no_errors(self):
        cmds = [_pick_tip(0), _aspirate(1), _dispense(2), _drop_tip(3)]
        _, errors = validate_commands(cmds, auto_correct=False)
        critical = [e for e in errors if e.severity == "critical"]
        assert len(critical) == 0

    def test_missing_tip_flagged(self):
        cmds = [_aspirate(0), _dispense(1)]
        _, errors = validate_commands(cmds, auto_correct=False)
        codes = [e.error_code for e in errors]
        assert "NO_TIP" in codes

    def test_autocorrect_inserts_tip(self):
        cmds = [_aspirate(0), _dispense(1)]
        corrected, errors = validate_commands(cmds, auto_correct=True)
        types = [c.command_type for c in corrected]
        assert CommandType.PICK_UP_TIP in types
        auto_codes = [e.error_code for e in errors if e.auto_corrected]
        assert "AUTO_INSERT_TIP" in auto_codes

    def test_autocorrect_drops_dangling_tip(self):
        cmds = [_pick_tip(0), _aspirate(1), _dispense(2)]
        corrected, errors = validate_commands(cmds, auto_correct=True)
        types = [c.command_type for c in corrected]
        assert CommandType.DROP_TIP in types
        auto_codes = [e.error_code for e in errors if e.auto_corrected]
        assert "AUTO_DROP_TIP" in auto_codes

    def test_critical_volume_overflow(self):
        cmd = DispenseCommand(command_index=0, protocol_step_ref=1,
                              volume_ul=50.0,
                              destination=LabwarePosition(deck_slot=2))
        cmd.volume_ul = 2000.0  # bypass validator via direct set
        _, errors = validate_commands([cmd], auto_correct=False)
        codes = [e.error_code for e in errors]
        assert "VOL_OVERFLOW" in codes

    def test_centrifuge_critical_over_max(self):
        cmd = CentrifugeCommand(command_index=0, protocol_step_ref=1,
                                speed_rpm=13000, duration_s=600)
        cmd.speed_rpm = 50000  # force over max
        _, errors = validate_commands([cmd], auto_correct=False)
        codes = [e.error_code for e in errors]
        assert "RPM_OVERFLOW" in codes

    def test_invalid_slot_flagged(self):
        cmd = IncubateCommand(command_index=0, protocol_step_ref=1,
                              temperature_celsius=37.0, duration_s=1800, slot=7)
        cmd.slot = 99  # force invalid
        _, errors = validate_commands([cmd], auto_correct=False)
        codes = [e.error_code for e in errors]
        assert "INVALID_SLOT" in codes


# ---------------------------------------------------------------------------
# Simulation bridge tests
# ---------------------------------------------------------------------------

class TestSimBridge:

    def test_mock_clean_sequence_passes(self):
        cmds = [_pick_tip(0), _aspirate(1, slot=1), _dispense(2, slot=2), _drop_tip(3)]
        result = _run_mock_simulation(cmds)
        assert result.passed is True
        assert result.collision_detected is False

    def test_mock_double_pickup_fails(self):
        cmds = [_pick_tip(0), _pick_tip(1)]
        result = _run_mock_simulation(cmds)
        assert result.passed is False
        assert result.collision_detected is True

    def test_mock_aspirate_no_tip_fails(self):
        cmds = [_aspirate(0)]
        result = _run_mock_simulation(cmds)
        assert result.passed is False
        assert result.collision_at_command == 0

    def test_mock_telemetry_volume_tracking(self):
        cmds = [_pick_tip(0), _aspirate(1, vol=75.0), _dispense(2, vol=75.0), _drop_tip(3)]
        result = _run_mock_simulation(cmds)
        assert result.telemetry["total_volume_aspirated_ul"] == 75.0
        assert result.telemetry["total_volume_dispensed_ul"] == 75.0

    def test_bridge_mock_mode(self):
        bridge = IsaacSimBridge(mode=SimMode.MOCK)
        cmds = [_pick_tip(0), _aspirate(1), _dispense(2), _drop_tip(3)]
        result = bridge.validate_execution_plan(cmds)
        assert isinstance(result, SimulationResult)

    def test_bridge_is_live_false_for_mock(self):
        bridge = IsaacSimBridge(mode=SimMode.MOCK)
        assert bridge.is_live is False


# ---------------------------------------------------------------------------
# Orchestrator end-to-end tests
# ---------------------------------------------------------------------------

class TestOrchestrator:

    def test_full_pipeline_produces_plan(self):
        plan = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK)
        assert isinstance(plan, ExecutionPlan)
        assert plan.plan_id != ""
        assert plan.protocol_id == "test-proto-001"

    def test_full_pipeline_has_commands(self):
        plan = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK)
        assert plan.command_count > 0

    def test_full_pipeline_sim_result_present(self):
        plan = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK)
        assert plan.simulation_result is not None

    def test_full_pipeline_status_is_sim_result(self):
        plan = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK)
        assert plan.status in (ExecutionStatus.SIM_PASSED, ExecutionStatus.SIM_FAILED)

    def test_home_bookends_present(self):
        plan = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK)
        assert plan.commands[0].command_type == CommandType.HOME
        assert plan.commands[-1].command_type == CommandType.HOME

    def test_auto_correct_applied(self):
        plan = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK, auto_correct=True)
        # All corrected errors should be flagged
        auto_corrected = [e for e in plan.validation_errors if e.auto_corrected]
        # At minimum, the pipeline should not have uncorrected critical errors
        critical_uncorrected = [e for e in plan.validation_errors
                                 if e.severity == "critical" and not e.auto_corrected]
        assert len(critical_uncorrected) == 0

    def test_empty_steps_produces_bookend_plan(self):
        proto = dict(SAMPLE_PROTOCOL, steps=[])
        plan = execute_protocol(proto, sim_mode=SimMode.MOCK)
        assert plan.command_count >= 2  # at least 2 Home commands

    def test_estimated_duration_positive(self):
        plan = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK)
        assert plan.estimated_total_duration_s > 0

    def test_plan_summary_is_executable_after_sim_pass(self):
        plan = execute_protocol(SAMPLE_PROTOCOL, sim_mode=SimMode.MOCK)
        if plan.status == ExecutionStatus.SIM_PASSED:
            assert plan.is_executable is True