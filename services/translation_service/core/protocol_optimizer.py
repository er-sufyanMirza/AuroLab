"""
core/protocol_optimizer.py

Multi-objective protocol optimiser for AuroLab.
Given a base protocol, generates 3 alternative variants optimised for:
  1. SPEED    — minimise total execution time
  2. COST     — minimise reagent and tip consumption
  3. GREEN    — minimise plastic waste and energy usage

Each variant is a real, fully-formed protocol that the LLM regenerates
with an objective-specific prompt. The result is a 4-protocol comparison
(original + 3 variants) with trade-off analysis.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
import structlog

log = structlog.get_logger(__name__)


SPEED_SYSTEM = """You are an expert lab automation engineer optimising protocols for SPEED.
Your goal: minimise total execution time while maintaining protocol validity and safety.

Speed optimisation strategies:
- Parallelise independent steps (e.g. pipette while centrifuge runs)
- Reduce incubation times to validated minimum (cite source if you shorten a step)
- Use larger pipette volumes where possible to reduce transfer count
- Combine serial transfers into multi-dispense operations
- Skip redundant mixing steps if the assay allows
- Use faster centrifuge speeds if validated

Constraints: Do NOT compromise safety. Do NOT skip validation steps.
Output the same JSON schema as the original protocol.
Add "optimisation_objective": "speed" and "optimisation_notes": "..." to the output."""

COST_SYSTEM = """You are an expert lab automation engineer optimising protocols for COST.
Your goal: minimise total reagent cost and consumable usage.

Cost optimisation strategies:
- Reduce sample volumes to validated minimum (cite your source)
- Use microplate format instead of individual tubes where possible
- Reduce number of washes if validated
- Use cheaper equivalent reagents (cite equivalence)
- Reduce tip changes by batching similar transfers
- Scale down reaction volumes to the minimum validated size
- Use lower-cost alternatives (Bradford instead of BCA, etc.) only if validated

Constraints: Maintain assay sensitivity and specificity. Do NOT compromise results.
Output the same JSON schema. Add "optimisation_objective": "cost" and "optimisation_notes": "..."."""

GREEN_SYSTEM = """You are an expert lab automation engineer optimising protocols for SUSTAINABILITY.
Your goal: minimise plastic waste, energy consumption, and chemical waste.

Green optimisation strategies:
- Reduce tip usage through tip-washing steps where validated
- Minimise volumes to reduce plastic-backed filter tips
- Use reusable glassware where possible
- Reduce number of plate washes (less buffer waste)
- Use room temperature incubations instead of heated where possible
- Reduce centrifuge time and speed (less energy)
- Combine steps to reduce number of disposable tubes

Constraints: Maintain data quality and safety. Cite any protocol modification.
Output the same JSON schema. Add "optimisation_objective": "green" and "optimisation_notes": "..."."""


@dataclass
class OptimisedVariant:
    objective:          str    # "speed" | "cost" | "green"
    protocol:           dict
    optimisation_notes: str    = ""
    estimated_time_min: float  = 0.0
    estimated_cost_usd: float  = 0.0
    estimated_plastic_g:float  = 0.0
    generation_ms:      float  = 0.0
    success:            bool   = True
    error:              str    = ""

    def to_dict(self) -> dict:
        return {
            "objective":           self.objective,
            "protocol":            self.protocol,
            "optimisation_notes":  self.optimisation_notes,
            "estimated_time_min":  round(self.estimated_time_min, 1),
            "estimated_cost_usd":  round(self.estimated_cost_usd, 4),
            "estimated_plastic_g": round(self.estimated_plastic_g, 2),
            "generation_ms":       round(self.generation_ms, 1),
            "success":             self.success,
            "error":               self.error,
        }


@dataclass
class OptimisationResult:
    original_protocol_id: str
    variants:             list[OptimisedVariant] = field(default_factory=list)
    tradeoff_analysis:    str                     = ""
    total_ms:             float                   = 0.0

    def to_dict(self) -> dict:
        return {
            "original_protocol_id": self.original_protocol_id,
            "variants":             [v.to_dict() for v in self.variants],
            "tradeoff_analysis":    self.tradeoff_analysis,
            "total_ms":             round(self.total_ms, 1),
        }


# Simple heuristics to estimate metrics from a protocol dict
def _estimate_time(protocol: dict) -> float:
    """Estimate total run time in minutes from protocol steps."""
    total_s = 0.0
    for step in protocol.get("steps", []):
        dur = step.get("duration_seconds")
        if dur:
            total_s += float(dur)
        else:
            # Estimate from instruction keywords
            inst = step.get("instruction","").lower()
            if "incubat" in inst:   total_s += 1800
            elif "centrifug" in inst: total_s += 300
            elif "wash" in inst:    total_s += 60
            elif "pipett" in inst:  total_s += 30
            else:                   total_s += 45
    return max(total_s / 60.0, 1.0)


def _estimate_cost(protocol: dict) -> float:
    """Rough reagent cost estimate from step count and volumes."""
    volumes  = sum(s.get("volume_ul", 50) or 50 for s in protocol.get("steps",[]))
    tips     = sum(1 for s in protocol.get("steps",[])
                   if any(k in s.get("instruction","").lower()
                          for k in ["pipette","aspirate","transfer","dispense"]))
    reagents = len(protocol.get("reagents", []))
    return round(tips * 0.003 + volumes * 0.0001 + reagents * 0.05, 4)


def _estimate_plastic(protocol: dict) -> float:
    """Estimate plastic waste in grams from tip count."""
    tips = sum(1 for s in protocol.get("steps",[])
               if any(k in s.get("instruction","").lower()
                      for k in ["pipette","aspirate","transfer","dispense"]))
    return round(tips * 0.08, 2)   # ~0.08g per 300µL tip


class ProtocolOptimiser:
    """
    Generates multi-objective protocol variants using LLM.
    Requires an AurolabLLMEngine instance.
    """

    def __init__(self, llm_engine: Any) -> None:
        self._llm = llm_engine

    def optimise(self, protocol: dict) -> OptimisationResult:
        """
        Generate speed, cost, and green variants of a protocol.
        Returns OptimisationResult with all 3 variants + trade-off analysis.
        """
        t0  = time.perf_counter()
        pid = protocol.get("protocol_id", "unknown")

        variants = []
        for objective, system_prompt in [
            ("speed", SPEED_SYSTEM),
            ("cost",  COST_SYSTEM),
            ("green", GREEN_SYSTEM),
        ]:
            variant = self._generate_variant(protocol, objective, system_prompt)
            variants.append(variant)
            log.info("variant_generated", objective=objective,
                     success=variant.success, ms=round(variant.generation_ms))

        # Trade-off analysis
        tradeoff = self._analyse_tradeoffs(protocol, variants)

        total_ms = (time.perf_counter() - t0) * 1000
        return OptimisationResult(
            original_protocol_id=pid,
            variants=variants,
            tradeoff_analysis=tradeoff,
            total_ms=total_ms,
        )

    def _generate_variant(
        self, protocol: dict, objective: str, system_prompt: str
    ) -> OptimisedVariant:
        t0 = time.perf_counter()
        try:
            import json, re, uuid

            user_prompt = f"""Optimise this protocol for {objective.upper()}.

Original protocol:
{json.dumps({'title': protocol.get('title',''), 'description': protocol.get('description',''),
             'steps': protocol.get('steps',[]), 'reagents': protocol.get('reagents',[]),
             'equipment': protocol.get('equipment',[])}, indent=2)}

Return optimised protocol JSON with the same schema plus:
  "optimisation_objective": "{objective}"
  "optimisation_notes": "what you changed and why"
  "confidence_score": 0.0-1.0"""

            raw   = self._llm._call_with_retry(system_prompt, user_prompt)
            clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`")
            data  = json.loads(clean)

            revised = {
                "protocol_id":           str(uuid.uuid4()),
                "title":                 data.get("title", protocol.get("title","")) + f" [{objective.upper()}]",
                "description":           data.get("description", protocol.get("description","")),
                "steps":                 data.get("steps", protocol.get("steps",[])),
                "reagents":              data.get("reagents", protocol.get("reagents",[])),
                "equipment":             data.get("equipment", protocol.get("equipment",[])),
                "safety_level":          data.get("safety_level", protocol.get("safety_level","safe")),
                "safety_notes":          data.get("safety_notes", protocol.get("safety_notes",[])),
                "confidence_score":      float(data.get("confidence_score", 0.75)),
                "generation_ms":         (time.perf_counter() - t0) * 1000,
                "model_used":            getattr(self._llm, "_model", "unknown"),
                "optimisation_objective":objective,
                "optimisation_notes":    data.get("optimisation_notes",""),
                "parent_protocol_id":    protocol.get("protocol_id",""),
            }

            return OptimisedVariant(
                objective=objective,
                protocol=revised,
                optimisation_notes=data.get("optimisation_notes",""),
                estimated_time_min=_estimate_time(revised),
                estimated_cost_usd=_estimate_cost(revised),
                estimated_plastic_g=_estimate_plastic(revised),
                generation_ms=(time.perf_counter()-t0)*1000,
                success=True,
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            log.error("variant_generation_failed", objective=objective, error=str(exc))
            return OptimisedVariant(
                objective=objective,
                protocol=protocol,
                optimisation_notes="",
                estimated_time_min=_estimate_time(protocol),
                estimated_cost_usd=_estimate_cost(protocol),
                estimated_plastic_g=_estimate_plastic(protocol),
                generation_ms=elapsed,
                success=False,
                error=str(exc),
            )

    def _analyse_tradeoffs(
        self, original: dict, variants: list[OptimisedVariant]
    ) -> str:
        """Generate a plain-text trade-off summary."""
        orig_time    = _estimate_time(original)
        orig_cost    = _estimate_cost(original)
        orig_plastic = _estimate_plastic(original)

        lines = ["Trade-off summary:"]
        for v in variants:
            if not v.success:
                lines.append(f"  {v.objective.upper()}: optimisation failed")
                continue
            t_delta = v.estimated_time_min - orig_time
            c_delta = v.estimated_cost_usd - orig_cost
            p_delta = v.estimated_plastic_g - orig_plastic
            t_str = f"{abs(t_delta):.0f}min {'faster' if t_delta<0 else 'slower'}"
            c_str = f"${abs(c_delta):.4f} {'cheaper' if c_delta<0 else 'more expensive'}"
            p_str = f"{abs(p_delta):.2f}g {'less' if p_delta<0 else 'more'} plastic"
            lines.append(f"  {v.objective.upper()}: {t_str}, {c_str}, {p_str}")

        # Simple recommendation
        best_time    = min(variants, key=lambda v: v.estimated_time_min)
        best_cost    = min(variants, key=lambda v: v.estimated_cost_usd)
        best_plastic = min(variants, key=lambda v: v.estimated_plastic_g)
        lines += [
            "",
            f"Best for speed:       {best_time.objective.upper()} variant",
            f"Best for cost:        {best_cost.objective.upper()} variant",
            f"Most sustainable:     {best_plastic.objective.upper()} variant",
        ]
        return "\n".join(lines)