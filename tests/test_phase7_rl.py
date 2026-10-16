"""
tests/test_phase7_rl.py

Tests for Phase 7: telemetry store, reward model, Q-agent, optimiser.
Run with: pytest tests/test_phase7_rl.py -v
"""

from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))



import os
import time
import pytest

from services.rl_service.core.telemetry_store import ExecutionRun, ParameterSuggestion, TelemetryStore
from services.rl_service.core.rl_engine import (
    ProtocolOptimiser, QState, RLAgent, RewardModel,
    FLOW_RATE_VALUES, CENTRIFUGE_VALUES, INCUBATE_TEMPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_store(tmp_path):
    db = str(tmp_path / "test_telemetry.db")
    return TelemetryStore(db_path=db)


def _make_run(
    protocol_id: str = "proto_001",
    passed: bool = True,
    duration_s: float = 1800.0,
    volume_aspirated: float = 50.0,
    volume_dispensed: float = 48.0,
    collision: bool = False,
    flow_rate: float = 150.0,
    centrifuge_rpm: float = 8000.0,
    incubate_temp: float = 37.0,
    reward: float = 0.75,
) -> ExecutionRun:
    return ExecutionRun(
        run_id=f"run_{time.time_ns()}",
        protocol_id=protocol_id,
        protocol_title="BCA Assay",
        timestamp=time.time(),
        sim_mode="mock",
        passed=passed,
        commands_executed=8,
        tip_changes=1,
        volume_aspirated_ul=volume_aspirated,
        volume_dispensed_ul=volume_dispensed,
        total_distance_mm=1200.0,
        duration_s=duration_s,
        collision_detected=collision,
        collision_at=None,
        flow_rate_avg=flow_rate,
        centrifuge_rpm_avg=centrifuge_rpm,
        incubate_temp_avg=incubate_temp,
        reward=reward,
        telemetry_json="{}",
    )


SAMPLE_COMMANDS = [
    {"command_type": "home",            "command_index": 0},
    {"command_type": "pick_up_tip",     "command_index": 1, "tip_rack_slot": 11},
    {"command_type": "aspirate",        "command_index": 2, "volume_ul": 50, "flow_rate_ul_s": 150},
    {"command_type": "dispense",        "command_index": 3, "volume_ul": 50, "flow_rate_ul_s": 150},
    {"command_type": "drop_tip",        "command_index": 4},
    {"command_type": "incubate",        "command_index": 5, "duration_s": 1800, "temperature_celsius": 37},
    {"command_type": "centrifuge",      "command_index": 6, "speed_rpm": 8000, "duration_s": 600},
    {"command_type": "read_absorbance", "command_index": 7, "wavelength_nm": 562},
]


# ---------------------------------------------------------------------------
# TelemetryStore tests
# ---------------------------------------------------------------------------

class TestTelemetryStore:

    def test_record_and_retrieve(self, tmp_store):
        run = _make_run()
        tmp_store.record_run(run)
        runs = tmp_store.get_runs(run.protocol_id)
        assert len(runs) == 1
        assert runs[0]["run_id"] == run.run_id

    def test_multiple_runs_returned_in_order(self, tmp_store):
        for i in range(5):
            tmp_store.record_run(_make_run(protocol_id="proto_001", reward=float(i) * 0.1))
        runs = tmp_store.get_runs("proto_001")
        assert len(runs) == 5
        # Most recent first
        assert runs[0]["timestamp"] >= runs[-1]["timestamp"]

    def test_filter_by_protocol_id(self, tmp_store):
        tmp_store.record_run(_make_run(protocol_id="proto_A"))
        tmp_store.record_run(_make_run(protocol_id="proto_B"))
        runs_a = tmp_store.get_runs("proto_A")
        assert all(r["protocol_id"] == "proto_A" for r in runs_a)

    def test_passed_only_filter(self, tmp_store):
        tmp_store.record_run(_make_run(passed=True))
        tmp_store.record_run(_make_run(passed=False))
        passed = tmp_store.get_runs(passed_only=True)
        assert all(r["passed"] for r in passed)

    def test_aggregate_stats(self, tmp_store):
        for i in range(3):
            tmp_store.record_run(_make_run(passed=True, reward=0.5 + i * 0.1))
        stats = tmp_store.aggregate_stats()
        assert stats["total_runs"] == 3
        assert stats["success_rate"] == pytest.approx(1.0)
        assert stats["avg_reward"] == pytest.approx(0.6, abs=0.05)

    def test_save_and_get_suggestion(self, tmp_store):
        s = ParameterSuggestion(
            protocol_id="proto_001",
            parameter="flow_rate_ul_s",
            current_value=150.0,
            suggested_value=100.0,
            expected_reward_delta=0.08,
            rationale="Test suggestion",
        )
        tmp_store.save_suggestion(s)
        suggestions = tmp_store.get_suggestions("proto_001")
        assert len(suggestions) == 1
        assert suggestions[0]["parameter"] == "flow_rate_ul_s"

    def test_update_suggestion_status(self, tmp_store):
        s = ParameterSuggestion(protocol_id="proto_001", parameter="flow_rate_ul_s",
                                 current_value=150, suggested_value=100)
        tmp_store.save_suggestion(s)
        tmp_store.update_suggestion_status(s.suggestion_id, "accepted")
        accepted = tmp_store.get_suggestions("proto_001", status="accepted")
        assert len(accepted) == 1

    def test_reward_trend(self, tmp_store):
        for i in range(5):
            tmp_store.record_run(_make_run(protocol_id="proto_001", reward=float(i) * 0.2))
        trend = tmp_store.get_reward_trend("proto_001", last_n=5)
        assert len(trend) == 5

    def test_from_sim_result_factory(self):
        sim_result = {
            "passed": True,
            "collision_detected": False,
            "collision_at_command": None,
            "sim_duration_s": 1800.0,
            "telemetry": {
                "commands_executed": 8,
                "tip_changes": 1,
                "total_volume_aspirated_ul": 50.0,
                "total_volume_dispensed_ul": 48.0,
                "total_distance_mm": 1200.0,
            },
        }
        run = ExecutionRun.from_sim_result("proto", "Test", sim_result, SAMPLE_COMMANDS)
        assert run.passed is True
        assert run.commands_executed == 8
        assert run.flow_rate_avg == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# RewardModel tests
# ---------------------------------------------------------------------------

class TestRewardModel:

    def test_perfect_run_high_reward(self):
        model = RewardModel()
        run = _make_run(passed=True, collision=False, duration_s=500,
                        volume_aspirated=50, volume_dispensed=50)
        reward = model.compute(run, baseline_duration_s=3600)
        assert reward > 0.7

    def test_failed_run_low_reward(self):
        model = RewardModel()
        run = _make_run(passed=False, collision=True, duration_s=3600)
        reward = model.compute(run)
        assert reward < 0.4

    def test_collision_penalises_accuracy(self):
        model = RewardModel()
        r_clean    = model.compute(_make_run(collision=False, passed=True))
        r_collision= model.compute(_make_run(collision=True,  passed=True))
        assert r_clean > r_collision

    def test_faster_run_better_reward(self):
        model = RewardModel()
        r_fast = model.compute(_make_run(duration_s=500),  baseline_duration_s=3600)
        r_slow = model.compute(_make_run(duration_s=3000), baseline_duration_s=3600)
        assert r_fast > r_slow

    def test_reward_in_0_1(self):
        model = RewardModel()
        for _ in range(10):
            run = _make_run(
                passed=bool(round(0.5)),
                collision=False,
                duration_s=1800,
            )
            r = model.compute(run)
            assert 0.0 <= r <= 1.0

    def test_waste_penalised(self):
        model = RewardModel()
        r_no_waste   = model.compute(_make_run(volume_aspirated=50, volume_dispensed=50))
        r_with_waste = model.compute(_make_run(volume_aspirated=50, volume_dispensed=10))
        assert r_no_waste > r_with_waste


# ---------------------------------------------------------------------------
# RLAgent tests
# ---------------------------------------------------------------------------

class TestRLAgent:

    def test_select_action_returns_tuple(self):
        agent = RLAgent()
        state = QState(0, 0, 0)
        action = agent.select_action(state)
        assert isinstance(action, tuple)
        assert len(action) == 3
        assert all(a in (-1, 0, 1) for a in action)

    def test_update_changes_q_value(self):
        agent = RLAgent(epsilon=0.0)
        state = QState(2, 2, 2)
        action = (0, 0, 0)
        agent.update(state, action, reward=0.8, next_state=state)
        assert agent._q[state.to_key()][action] > 0

    def test_best_action_no_op_when_no_data(self):
        agent = RLAgent()
        state = QState(1, 1, 1)
        assert agent.best_action(state) == (0, 0, 0)

    def test_epsilon_decays(self):
        agent = RLAgent(epsilon=0.3, epsilon_decay=0.99)
        initial_eps = agent.epsilon
        for _ in range(10):
            agent.update(QState(0,0,0), (0,0,0), 0.5, QState(0,0,0))
        assert agent.epsilon < initial_eps

    def test_epsilon_floor(self):
        agent = RLAgent(epsilon=0.3, epsilon_decay=0.5, epsilon_min=0.05)
        for _ in range(100):
            agent.update(QState(0,0,0), (0,0,0), 0.5, QState(0,0,0))
        assert agent.epsilon >= agent.epsilon_min

    def test_state_from_run_valid_indices(self):
        agent = RLAgent()
        run = _make_run(flow_rate=150.0, centrifuge_rpm=8000, incubate_temp=37.0)
        state = agent.state_from_run(run)
        assert 0 <= state.flow_rate_idx < len(FLOW_RATE_VALUES)
        assert 0 <= state.centrifuge_idx < len(CENTRIFUGE_VALUES)
        assert 0 <= state.incubate_idx < len(INCUBATE_TEMPS)

    def test_q_stats(self):
        agent = RLAgent()
        agent.update(QState(0,0,0), (0,0,0), 0.5, QState(0,0,0))
        stats = agent.q_stats()
        assert "states_visited" in stats
        assert "episodes" in stats
        assert stats["episodes"] == 1


# ---------------------------------------------------------------------------
# ProtocolOptimiser tests
# ---------------------------------------------------------------------------

class TestProtocolOptimiser:

    def test_ingest_run_stores_with_reward(self, tmp_store):
        optimiser = ProtocolOptimiser(tmp_store)
        run = _make_run()
        reward = optimiser.ingest_run(run)
        assert 0.0 <= reward <= 1.0
        stored = tmp_store.get_runs(run.protocol_id)
        assert len(stored) == 1
        assert stored[0]["reward"] == pytest.approx(reward, abs=0.001)

    def test_generate_suggestions_returns_list(self, tmp_store):
        optimiser = ProtocolOptimiser(tmp_store)
        # Ingest some runs first
        for _ in range(5):
            optimiser.ingest_run(_make_run())
        suggestions = optimiser.generate_suggestions("proto_001", SAMPLE_COMMANDS)
        assert isinstance(suggestions, list)

    def test_heuristic_suggestion_on_collision(self, tmp_store):
        optimiser = ProtocolOptimiser(tmp_store)
        optimiser.ingest_run(_make_run(collision=True, passed=False))
        suggestions = optimiser.generate_suggestions("proto_001", SAMPLE_COMMANDS)
        params = [s.parameter for s in suggestions]
        assert "flow_rate_ul_s" in params

    def test_parallelisation_suggestion_for_multiple_incubations(self, tmp_store):
        optimiser = ProtocolOptimiser(tmp_store)
        multi_incubate = SAMPLE_COMMANDS + [
            {"command_type": "incubate", "command_index": 9, "duration_s": 3600, "slot": 7},
        ]
        suggestions = optimiser.generate_suggestions("proto_001", multi_incubate)
        params = [s.parameter for s in suggestions]
        assert "step_parallelisation" in params

    def test_agent_stats_empty_without_runs(self, tmp_store):
        optimiser = ProtocolOptimiser(tmp_store)
        stats = optimiser.agent_stats("nonexistent_proto")
        assert stats["states_visited"] == 0

    def test_multiple_protocols_independent_agents(self, tmp_store):
        optimiser = ProtocolOptimiser(tmp_store)
        optimiser.ingest_run(_make_run(protocol_id="proto_A", reward=0.9))
        optimiser.ingest_run(_make_run(protocol_id="proto_B", reward=0.3))
        assert "proto_A" in optimiser._agents
        assert "proto_B" in optimiser._agents
        # Agents are independent
        assert optimiser._agents["proto_A"] is not optimiser._agents["proto_B"]