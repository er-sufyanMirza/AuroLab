"""
services/translation_service/core/llm_reflection.py

LLM Reflection Engine for AuroLab.
When a protocol fails simulation, automatically:
  1. Analyses the failure reason
  2. Asks the LLM to generate a corrected version
  3. Re-simulates the correction
  4. Returns both the diagnosis and the fix

This closes the intelligence loop:
  Generate → Simulate → FAIL → Reflect → Fix → Re-simulate → PASS

Also handles low-reward protocols (reward < threshold) with
parameter optimisation suggestions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass
class ReflectionResult:
    original_protocol_id: str
    success: bool
    failure_reason: str         = ""
    diagnosis: str              = ""
    corrections: list[str]      = field(default_factory=list)
    revised_protocol: dict|None = None
    revised_sim_passed: bool    = False
    reflection_ms: float        = 0.0
    attempt_count: int          = 1

    def to_dict(self) -> dict:
        return {
            "original_protocol_id": self.original_protocol_id,
            "success":              self.success,
            "failure_reason":       self.failure_reason,
            "diagnosis":            self.diagnosis,
            "corrections":          self.corrections,
            "revised_protocol_id":  self.revised_protocol.get("protocol_id","") if self.revised_protocol else "",
            "revised_sim_passed":   self.revised_sim_passed,
            "reflection_ms":        round(self.reflection_ms, 1),
            "attempt_count":        self.attempt_count,
        }


REFLECTION_SYSTEM = """You are an expert lab automation engineer reviewing a failed robotic protocol.
Your task is to diagnose the failure and produce a corrected protocol.

Rules:
1. Identify the specific failure cause from the error description
2. Generate a corrected protocol that addresses the root cause
3. Keep all successful steps unchanged — only modify what's needed
4. Output valid JSON matching the exact same schema as the original protocol
5. Add a "reflection_note" field to the corrected protocol explaining what you changed and why

Common failure causes and fixes:
- Tip collision: reduce flow rate, add tip change steps, increase Z-clearance in instructions
- Missing tip: add explicit pick_up_tip step before first aspirate
- Volume overflow: reduce aspirate volume or use appropriate labware
- Slot conflict: re-assign labware to different slots
- Invalid command sequence: reorder steps (home → pick_up_tip → aspirate → dispense → drop_tip)
"""


class LLMReflectionEngine:
    """
    Wraps the LLM engine to perform failure analysis and protocol correction.
    Requires an AurolabLLMEngine instance for actual LLM calls.
    """

    def __init__(self, llm_engine: Any, max_attempts: int = 2) -> None:
        self._llm = llm_engine
        self._max_attempts = max_attempts

    def reflect_on_failure(
        self,
        protocol: dict,
        sim_result: dict,
        sim_mode: str = "mock",
    ) -> ReflectionResult:
        """
        Diagnose a simulation failure and generate a corrected protocol.

        Args:
            protocol:   The original GeneratedProtocol dict.
            sim_result: The SimulationResult dict (contains passed, errors, telemetry).
            sim_mode:   Simulation mode to use for re-simulation.

        Returns:
            ReflectionResult with diagnosis, corrections, and revised protocol.
        """
        t0 = time.perf_counter()
        pid = protocol.get("protocol_id", "unknown")

        passed = sim_result.get("passed", sim_result.get("simulation_passed", False))
        if passed:
            return ReflectionResult(
                original_protocol_id=pid,
                success=True,
                diagnosis="Protocol simulation passed — no reflection needed.",
                reflection_ms=0.0,
            )

        # Extract failure information
        errors      = sim_result.get("errors", [])
        collision   = sim_result.get("collision_detected", False)
        collision_at= sim_result.get("collision_at")
        telemetry   = sim_result.get("telemetry", {})

        failure_parts = []
        if collision:
            cmd_idx = collision_at or "unknown"
            failure_parts.append(f"Collision detected at command index {cmd_idx}")
        if errors:
            for e in errors[:3]:
                failure_parts.append(f"Error: {e.get('message', str(e))}")
        if not failure_parts:
            failure_parts.append("Simulation failed — unknown cause")

        failure_reason = "; ".join(failure_parts)
        log.info("reflection_start", protocol_id=pid, failure=failure_reason)

        # Build reflection prompt
        import json
        protocol_json = json.dumps({
            "title":        protocol.get("title",""),
            "description":  protocol.get("description",""),
            "steps":        protocol.get("steps",[]),
            "reagents":     protocol.get("reagents",[]),
            "equipment":    protocol.get("equipment",[]),
            "safety_level": protocol.get("safety_level","safe"),
            "safety_notes": protocol.get("safety_notes",[]),
        }, indent=2)

        user_prompt = f"""The following AuroLab protocol failed simulation.

FAILURE REASON: {failure_reason}

ORIGINAL PROTOCOL:
{protocol_json}

TELEMETRY:
- Commands executed before failure: {telemetry.get('commands_executed', '?')}
- Tip changes: {telemetry.get('tip_changes', 0)}
- Volume aspirated: {telemetry.get('volume_aspirated_ul', 0):.1f} µL
- Collision detected: {collision}

Please:
1. Diagnose the root cause in 1-2 sentences
2. List the specific corrections needed (as a JSON array of strings under "corrections")
3. Output the complete corrected protocol in the same JSON schema
4. Add a "reflection_note" field explaining the key change

Return only valid JSON with this structure:
{{
  "diagnosis": "...",
  "corrections": ["...", "..."],
  "reflection_note": "...",
  "title": "...",
  "description": "...",
  "steps": [...],
  "reagents": [...],
  "equipment": [...],
  "safety_level": "...",
  "safety_notes": [...],
  "confidence_score": 0.0
}}"""

        # Call LLM
        try:
            raw = self._llm._call_with_retry(REFLECTION_SYSTEM, user_prompt)
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            log.error("reflection_llm_failed", error=str(exc))
            return ReflectionResult(
                original_protocol_id=pid,
                success=False,
                failure_reason=failure_reason,
                diagnosis=f"LLM reflection failed: {exc}",
                reflection_ms=elapsed,
            )

        # Parse response
        try:
            import re
            # Strip markdown fences if present
            clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`")
            data  = json.loads(clean)
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            return ReflectionResult(
                original_protocol_id=pid,
                success=False,
                failure_reason=failure_reason,
                diagnosis=f"Failed to parse LLM reflection output: {exc}",
                reflection_ms=elapsed,
            )

        diagnosis   = data.get("diagnosis", "No diagnosis provided")
        corrections = data.get("corrections", [])

        # Build revised protocol
        import uuid
        revised = {
            "protocol_id":      str(uuid.uuid4()),
            "title":            data.get("title", protocol.get("title","")) + " (Revised)",
            "description":      data.get("description", protocol.get("description","")),
            "steps":            data.get("steps", protocol.get("steps",[])),
            "reagents":         data.get("reagents", protocol.get("reagents",[])),
            "equipment":        data.get("equipment", protocol.get("equipment",[])),
            "safety_level":     data.get("safety_level", protocol.get("safety_level","safe")),
            "safety_notes":     data.get("safety_notes", protocol.get("safety_notes",[])),
            "confidence_score": data.get("confidence_score", 0.7),
            "generation_ms":    (time.perf_counter() - t0) * 1000,
            "model_used":       getattr(self._llm, "_model", "reflection"),
            "reflection_note":  data.get("reflection_note",""),
            "parent_protocol_id": pid,
        }

        # Re-simulate
        revised_passed = False
        try:
            from services.execution_service.core.orchestrator import execute_protocol
            from services.execution_service.core.isaac_sim_bridge import SimMode
            mode_map = {"mock": SimMode.MOCK, "pybullet": SimMode.PYBULLET, "live": SimMode.LIVE}
            mode = mode_map.get(sim_mode, SimMode.MOCK)
            plan = execute_protocol(revised, sim_mode=mode)
            revised_passed = plan.simulation_result is not None and plan.simulation_result.passed
            log.info("reflection_sim_complete",
                     passed=revised_passed,
                     protocol_id=revised["protocol_id"])
        except Exception as exc:
            log.warning("reflection_sim_failed", error=str(exc))

        elapsed = (time.perf_counter() - t0) * 1000
        log.info("reflection_complete",
                 original_id=pid,
                 revised_id=revised["protocol_id"],
                 diagnosis=diagnosis[:80],
                 sim_passed=revised_passed,
                 elapsed_ms=round(elapsed, 1))

        return ReflectionResult(
            original_protocol_id=pid,
            success=revised_passed,
            failure_reason=failure_reason,
            diagnosis=diagnosis,
            corrections=corrections,
            revised_protocol=revised,
            revised_sim_passed=revised_passed,
            reflection_ms=elapsed,
            attempt_count=1,
        )

    def suggest_optimisations(
        self, protocol: dict, reward: float, reward_components: dict
    ) -> list[str]:
        """
        When a protocol passes but has low reward, suggest improvements.
        Returns list of plain-text suggestions.
        """
        if reward >= 0.85:
            return []

        weak = sorted(reward_components.items(), key=lambda x: x[1])[:2]
        weak_str = ", ".join(f"{k} ({v:.2f})" for k, v in weak)

        prompt = f"""A lab protocol achieved reward {reward:.3f}/1.0.
Weakest components: {weak_str}

Protocol: {protocol.get('title','')}
Steps: {len(protocol.get('steps',[]))}

Suggest 3 specific, actionable improvements to increase the reward score.
Focus on the weakest components.
Return as a JSON array of strings: ["suggestion 1", "suggestion 2", "suggestion 3"]"""

        try:
            raw = self._llm._call_with_retry(
                "You are an expert lab automation optimisation assistant. Return only a JSON array.",
                prompt
            )
            import json, re
            clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`")
            return json.loads(clean)
        except Exception:
            # Fallback heuristics
            suggestions = []
            for component, score in weak:
                if component == "speed" and score < 0.7:
                    suggestions.append("Parallelise independent incubation and centrifuge steps to reduce total run time")
                elif component == "accuracy" and score < 0.7:
                    suggestions.append("Add intermediate mixing steps to improve reagent homogeneity")
                elif component == "waste" and score < 0.7:
                    suggestions.append("Consolidate tip changes — use multi-dispense to reduce tip consumption")
                elif component == "safety" and score < 0.7:
                    suggestions.append("Add explicit reagent disposal and decontamination steps")
            return suggestions[:3]