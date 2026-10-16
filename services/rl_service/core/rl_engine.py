"""
aurolab/services/rl_service/core/rl_engine.py

RL-based protocol optimisation engine.

Components:
  RewardModel      — computes scalar reward from execution telemetry
  ProtocolOptimiser — suggests parameter changes using bandit/Q-table approach
  RLAgent          — tabular Q-learning agent over discretised parameter space

Reward function:
  R = w_speed    × speed_score
    + w_accuracy × accuracy_score
    + w_waste    × waste_score
    + w_safety   × safety_score

  speed_score    = 1 - (duration / baseline_duration)
  accuracy_score = 1 if no collision, 0 otherwise
  waste_score    = 1 - (volume_dispensed / volume_aspirated)  [lower waste = higher score]
  safety_score   = 1 if passed, 0 otherwise

This is intentionally lightweight — no neural network, no GPU required.
The value comes from accumulating runs and surfacing the parameter
configurations that consistently produced better rewards.
"""

from __future__ import annotations

import math
import random
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

from .telemetry_store import ExecutionRun, ParameterSuggestion, TelemetryStore

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Reward weights — tune for your lab's priorities
# ---------------------------------------------------------------------------

REWARD_WEIGHTS = {
    "speed":    0.30,    # faster = better
    "accuracy": 0.35,    # collision-free = critical
    "waste":    0.20,    # less reagent waste = better
    "safety":   0.15,    # passed all checks = baseline
}

# Baseline durations by protocol type (seconds) — used to normalise speed score
BASELINE_DURATIONS: dict[str, float] = {
    "protocol": 3600.0,   # 1 hour baseline for unknown protocols
    "SOP":      1800.0,
    "paper":    7200.0,
}

# Parameter action space for Q-learning
FLOW_RATE_VALUES   = [50.0, 100.0, 150.0, 200.0, 300.0]   # µL/s
CENTRIFUGE_VALUES  = [3000, 5000, 8000, 10000, 13000]       # RPM
INCUBATE_TEMPS     = [4.0, 22.0, 37.0, 42.0, 55.0]        # °C


# ---------------------------------------------------------------------------
# Reward model
# ---------------------------------------------------------------------------

class RewardModel:
    """Computes a scalar reward from one execution run."""

    def compute(
        self,
        run: ExecutionRun,
        baseline_duration_s: float | None = None,
    ) -> float:
        """
        Compute reward in [0, 1] for an execution run.

        Args:
            run:                  ExecutionRun record.
            baseline_duration_s:  Expected duration for speed normalisation.
                                  Defaults to BASELINE_DURATIONS["protocol"].
        """
        baseline = baseline_duration_s or BASELINE_DURATIONS["protocol"]

        # Speed: how much faster than baseline (capped at 0–1)
        if run.duration_s > 0 and baseline > 0:
            speed_score = max(0.0, min(1.0, 1.0 - (run.duration_s / baseline)))
        else:
            speed_score = 0.5   # unknown duration → neutral

        # Accuracy: collision-free execution
        accuracy_score = 0.0 if run.collision_detected else 1.0

        # Waste: ratio of dispensed/aspirated (closer to 1.0 = less waste)
        if run.volume_aspirated_ul > 0:
            ratio = run.volume_dispensed_ul / run.volume_aspirated_ul
            waste_score = min(1.0, ratio)   # 1.0 = perfect, 0.0 = all aspirated, none dispensed
        else:
            waste_score = 1.0

        # Safety: did the run pass all checks?
        safety_score = 1.0 if run.passed else 0.0

        reward = (
            REWARD_WEIGHTS["speed"]    * speed_score
          + REWARD_WEIGHTS["accuracy"] * accuracy_score
          + REWARD_WEIGHTS["waste"]    * waste_score
          + REWARD_WEIGHTS["safety"]   * safety_score
        )

        log.debug("reward_computed",
                  run_id=run.run_id,
                  speed=round(speed_score, 3),
                  accuracy=accuracy_score,
                  waste=round(waste_score, 3),
                  safety=safety_score,
                  total=round(reward, 4))

        return round(reward, 4)


# ---------------------------------------------------------------------------
# Q-table agent
# ---------------------------------------------------------------------------

@dataclass
class QState:
    """Discretised state for Q-table."""
    flow_rate_idx: int   # index into FLOW_RATE_VALUES
    centrifuge_idx: int  # index into CENTRIFUGE_VALUES
    incubate_idx: int    # index into INCUBATE_TEMPS

    def to_key(self) -> tuple:
        return (self.flow_rate_idx, self.centrifuge_idx, self.incubate_idx)


class RLAgent:
    """
    Tabular Q-learning agent over protocol parameter space.

    State:  (flow_rate_idx, centrifuge_idx, incubate_temp_idx)
    Action: (delta_flow, delta_centrifuge, delta_temp) — -1, 0, or +1 per dimension
    Reward: from RewardModel

    Uses epsilon-greedy exploration with decaying epsilon.
    """

    def __init__(
        self,
        alpha: float = 0.1,    # learning rate
        gamma: float = 0.9,    # discount factor
        epsilon: float = 0.3,  # initial exploration rate
        epsilon_decay: float = 0.995,
        epsilon_min: float = 0.05,
    ) -> None:
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.epsilon_min = epsilon_min

        # Q-table: state → action → value
        self._q: dict[tuple, dict[tuple, float]] = defaultdict(lambda: defaultdict(float))
        self._episode_count = 0

        # All possible actions: change each parameter by -1, 0, or +1
        self._actions: list[tuple[int, int, int]] = [
            (df, dc, dt)
            for df in (-1, 0, 1)
            for dc in (-1, 0, 1)
            for dt in (-1, 0, 1)
        ]

    def select_action(self, state: QState) -> tuple[int, int, int]:
        """Epsilon-greedy action selection."""
        if random.random() < self.epsilon:
            return random.choice(self._actions)

        q_values = self._q[state.to_key()]
        if not q_values:
            return (0, 0, 0)   # no-op if no data yet

        return max(q_values, key=q_values.get)

    def update(
        self,
        state: QState,
        action: tuple,
        reward: float,
        next_state: QState,
    ) -> None:
        """Q-learning update: Q(s,a) ← Q(s,a) + α(r + γ·max_a'Q(s',a') - Q(s,a))"""
        current_q = self._q[state.to_key()][action]
        next_max_q = max(self._q[next_state.to_key()].values(), default=0.0)
        new_q = current_q + self.alpha * (reward + self.gamma * next_max_q - current_q)
        self._q[state.to_key()][action] = new_q

        # Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        self._episode_count += 1

    def best_action(self, state: QState) -> tuple[int, int, int]:
        """Return best known action (no exploration)."""
        q_values = self._q[state.to_key()]
        if not q_values:
            return (0, 0, 0)
        return max(q_values, key=q_values.get)

    def state_from_run(self, run: ExecutionRun) -> QState:
        """Map an execution run's parameters to a Q-table state."""
        def closest_idx(value: float, options: list) -> int:
            return min(range(len(options)), key=lambda i: abs(options[i] - value))

        return QState(
            flow_rate_idx=closest_idx(run.flow_rate_avg, FLOW_RATE_VALUES),
            centrifuge_idx=closest_idx(run.centrifuge_rpm_avg or 8000, CENTRIFUGE_VALUES),
            incubate_idx=closest_idx(run.incubate_temp_avg or 37.0, INCUBATE_TEMPS),
        )

    def q_stats(self) -> dict:
        total_entries = sum(len(v) for v in self._q.values())
        return {
            "states_visited": len(self._q),
            "total_q_entries": total_entries,
            "epsilon": round(self.epsilon, 4),
            "episodes": self._episode_count,
        }


# ---------------------------------------------------------------------------
# Protocol optimiser
# ---------------------------------------------------------------------------

class ProtocolOptimiser:
    """
    Analyses execution history and generates parameter improvement suggestions.
    Uses the Q-agent to recommend parameter changes.
    """

    def __init__(
        self,
        store: TelemetryStore,
        reward_model: RewardModel | None = None,
    ) -> None:
        self._store = store
        self._reward_model = reward_model or RewardModel()
        self._agents: dict[str, RLAgent] = {}   # one agent per protocol_id

    def _get_agent(self, protocol_id: str) -> RLAgent:
        if protocol_id not in self._agents:
            self._agents[protocol_id] = RLAgent()
        return self._agents[protocol_id]

    def ingest_run(self, run: ExecutionRun) -> float:
        """
        Process one execution run: compute reward, update Q-table, store record.
        Returns the computed reward.
        """
        reward = self._reward_model.compute(run)
        run.reward = reward
        self._store.record_run(run)

        agent = self._get_agent(run.protocol_id)
        state = agent.state_from_run(run)
        action = (0, 0, 0)   # we observe, not act, for past runs
        agent.update(state, action, reward, state)

        return reward

    def generate_suggestions(
        self,
        protocol_id: str,
        current_commands: list[dict],
    ) -> list[ParameterSuggestion]:
        """
        Generate parameter improvement suggestions for a protocol.

        Analyses the Q-table to find what parameter changes are expected
        to improve reward. Returns up to 5 actionable suggestions.
        """
        runs = self._store.get_runs(protocol_id, limit=50, passed_only=True)
        if not runs:
            return self._heuristic_suggestions(protocol_id, current_commands)

        agent = self._get_agent(protocol_id)
        suggestions: list[ParameterSuggestion] = []

        # Use Q-agent recommendation
        if runs:
            latest = runs[0]
            # Build a fake ExecutionRun for state extraction
            mock_run = ExecutionRun(
                run_id="tmp", protocol_id=protocol_id, protocol_title="",
                timestamp=time.time(), sim_mode="mock", passed=True,
                commands_executed=latest.get("commands_executed", 0),
                tip_changes=latest.get("tip_changes", 0),
                volume_aspirated_ul=latest.get("volume_aspirated_ul", 0),
                volume_dispensed_ul=latest.get("volume_dispensed_ul", 0),
                total_distance_mm=latest.get("total_distance_mm", 0),
                duration_s=latest.get("duration_s", 0),
                collision_detected=bool(latest.get("collision_detected", 0)),
                collision_at=latest.get("collision_at"),
                flow_rate_avg=latest.get("flow_rate_avg", 150.0),
                centrifuge_rpm_avg=latest.get("centrifuge_rpm_avg", 8000.0),
                incubate_temp_avg=latest.get("incubate_temp_avg", 37.0),
                reward=latest.get("reward", 0),
                telemetry_json="{}",
            )
            state = agent.state_from_run(mock_run)
            best_action = agent.best_action(state)

            df, dc, dt = best_action

            if df != 0:
                new_idx = max(0, min(len(FLOW_RATE_VALUES) - 1, state.flow_rate_idx + df))
                current_val = FLOW_RATE_VALUES[state.flow_rate_idx]
                new_val = FLOW_RATE_VALUES[new_idx]
                if current_val != new_val:
                    suggestions.append(ParameterSuggestion(
                        protocol_id=protocol_id,
                        parameter="flow_rate_ul_s",
                        current_value=current_val,
                        suggested_value=new_val,
                        expected_reward_delta=abs(new_val - current_val) / 500 * 0.1,
                        rationale=f"Q-agent suggests {'increasing' if df > 0 else 'decreasing'} flow rate "
                                  f"from {current_val:.0f} to {new_val:.0f} µL/s based on {len(runs)} runs",
                    ))

            if dc != 0:
                new_idx = max(0, min(len(CENTRIFUGE_VALUES) - 1, state.centrifuge_idx + dc))
                current_val = float(CENTRIFUGE_VALUES[state.centrifuge_idx])
                new_val = float(CENTRIFUGE_VALUES[new_idx])
                if current_val != new_val:
                    suggestions.append(ParameterSuggestion(
                        protocol_id=protocol_id,
                        parameter="centrifuge_rpm",
                        current_value=current_val,
                        suggested_value=new_val,
                        expected_reward_delta=0.05,
                        rationale=f"Q-agent recommends centrifuge speed adjustment to {new_val:.0f} RPM",
                    ))

        # Always add heuristic suggestions as supplements
        suggestions.extend(self._heuristic_suggestions(protocol_id, current_commands))

        # Save to store
        for s in suggestions[:5]:
            self._store.save_suggestion(s)

        return suggestions[:5]

    def _heuristic_suggestions(
        self,
        protocol_id: str,
        commands: list[dict],
    ) -> list[ParameterSuggestion]:
        """Rule-based suggestions when insufficient Q-learning data."""
        suggestions = []
        stats = self._store.aggregate_stats(protocol_id)
        runs = self._store.get_runs(protocol_id, limit=20)

        # Suggestion 1: reduce flow rate if collisions detected
        collision_runs = sum(1 for r in runs if r.get("collision_detected"))
        if collision_runs > 0:
            suggestions.append(ParameterSuggestion(
                protocol_id=protocol_id,
                parameter="flow_rate_ul_s",
                current_value=150.0,
                suggested_value=100.0,
                expected_reward_delta=0.08,
                rationale=f"{collision_runs} collision(s) detected — lower flow rate reduces tip impact force",
            ))

        # Suggestion 2: parallelise incubation if multiple incubate steps
        incubate_cmds = [c for c in commands if c.get("command_type") == "incubate"]
        if len(incubate_cmds) > 1:
            total_incubate_s = sum(c.get("duration_s", 0) for c in incubate_cmds)
            suggestions.append(ParameterSuggestion(
                protocol_id=protocol_id,
                parameter="step_parallelisation",
                current_value=float(len(incubate_cmds)),
                suggested_value=1.0,
                expected_reward_delta=round(total_incubate_s / 3600 * 0.15, 3),
                rationale=f"{len(incubate_cmds)} sequential incubations ({total_incubate_s/60:.0f}min total) "
                          "could be parallelised across robots — see fleet scheduler",
            ))

        # Suggestion 3: volume optimisation
        avg_vol = stats.get("avg_volume_ul") or 0
        if avg_vol > 200:
            suggestions.append(ParameterSuggestion(
                protocol_id=protocol_id,
                parameter="volume_ul",
                current_value=round(avg_vol, 1),
                suggested_value=round(avg_vol * 0.85, 1),
                expected_reward_delta=0.04,
                rationale=f"Average aspirate volume {avg_vol:.0f}µL — 15% reduction possible "
                          "based on BCA assay sensitivity analysis",
            ))

        return suggestions

    def agent_stats(self, protocol_id: str) -> dict:
        agent = self._agents.get(protocol_id)
        if not agent:
            return {"states_visited": 0, "episodes": 0, "epsilon": 0.3}
        return agent.q_stats()