"""
core/batch_generator.py

Batch protocol generation for AuroLab.

Given one instruction, generates N protocol variants by varying:
  - Temperature (±2°C from standard)
  - Volume (±20% from standard)
  - Number of replicates / samples
  - Incubation time (±10 min from standard)
  - LLM temperature (controls creativity/determinism)

Each variant is independently generated, simulated, and scored.
The batch is ranked by composite score = confidence × safety × sim_pass.

Used by: dashboard/pages/18_batch.py
API:     POST /api/v1/batch/generate
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Ranking weights
RANK_WEIGHTS = {
    "confidence":  0.40,
    "safety":      0.30,
    "sim_pass":    0.20,
    "step_count":  0.10,   # prefer fewer steps (efficiency)
}

SAFETY_SCORES = {"safe": 1.0, "caution": 0.8, "warning": 0.5,
                 "hazardous": 0.1, "blocked": 0.0}


@dataclass
class BatchVariant:
    variant_id:     str
    index:          int
    protocol:       dict
    sim_result:     dict | None    = None
    composite_score:float          = 0.0
    rank:           int            = 0
    generation_ms:  float          = 0.0
    variation_desc: str            = ""   # what was varied

    def to_dict(self) -> dict:
        return {
            "variant_id":      self.variant_id,
            "index":           self.index,
            "protocol":        self.protocol,
            "sim_result":      self.sim_result,
            "composite_score": round(self.composite_score, 4),
            "rank":            self.rank,
            "generation_ms":   round(self.generation_ms, 1),
            "variation_desc":  self.variation_desc,
        }


@dataclass
class BatchResult:
    batch_id:    str
    instruction: str
    n_requested: int
    n_succeeded: int
    variants:    list[BatchVariant] = field(default_factory=list)
    total_ms:    float              = 0.0
    best_variant_id: str           = ""

    def to_dict(self) -> dict:
        return {
            "batch_id":        self.batch_id,
            "instruction":     self.instruction,
            "n_requested":     self.n_requested,
            "n_succeeded":     self.n_succeeded,
            "variants":        [v.to_dict() for v in self.variants],
            "total_ms":        round(self.total_ms, 1),
            "best_variant_id": self.best_variant_id,
        }


def _score_variant(protocol: dict, sim_result: dict | None) -> float:
    """Compute composite ranking score for a protocol variant."""
    conf      = float(protocol.get("confidence_score", 0))
    safety_lv = protocol.get("safety_level", "safe")
    safety_s  = SAFETY_SCORES.get(safety_lv, 0.5)
    sim_pass  = 1.0 if (sim_result and sim_result.get(
        "passed", sim_result.get("simulation_passed", False))) else 0.0
    n_steps   = len(protocol.get("steps", []))
    step_s    = max(0.0, 1.0 - (n_steps - 5) * 0.05)  # 5 steps = 1.0, penalty > 5

    return (
        RANK_WEIGHTS["confidence"] * conf +
        RANK_WEIGHTS["safety"]     * safety_s +
        RANK_WEIGHTS["sim_pass"]   * sim_pass +
        RANK_WEIGHTS["step_count"] * step_s
    )


def _make_variation(
    base_instruction: str,
    variant_index: int,
    base_params: dict,
) -> tuple[str, str]:
    """
    Return (modified_instruction, variation_description) for a variant.
    Introduces small, scientifically valid parameter perturbations.
    """
    variations = [
        # idx 0 — baseline (no change)
        (base_instruction, "Baseline — no parameter changes"),

        # idx 1 — increase sample count
        (
            _replace_numbers(base_instruction,
                {"8": "12", "16": "24", "24": "32", "4": "8"}),
            "Increased sample count (+50%)"
        ),

        # idx 2 — higher incubation temperature
        (
            _replace_numbers(base_instruction,
                {"37°C": "42°C", "37 degrees": "42 degrees",
                 "37C": "42C", "37 C": "42 C"}),
            "Elevated incubation temperature (37→42°C)"
        ),

        # idx 3 — extended incubation time
        (
            _replace_numbers(base_instruction,
                {"30 min": "45 min", "30 minutes": "45 minutes",
                 "1 hour": "2 hours", "15 min": "20 min"}),
            "Extended incubation time (+50%)"
        ),

        # idx 4 — reduced volumes (cost optimisation)
        (
            base_instruction + " Use half the standard reagent volumes.",
            "Reduced volumes — cost optimisation"
        ),

        # idx 5 — increased volumes (sensitivity)
        (
            base_instruction + " Use double the standard reagent volumes for higher sensitivity.",
            "Increased volumes — sensitivity optimisation"
        ),

        # idx 6 — add replicates
        (
            base_instruction + " Include 3 technical replicates for each sample.",
            "Added 3 technical replicates"
        ),

        # idx 7 — room temperature variant
        (
            _replace_numbers(base_instruction,
                {"37°C": "22°C", "37C": "22C", "37 C": "22 C",
                 "37 degrees": "22 degrees (room temperature)"}),
            "Room temperature variant (22°C)"
        ),

        # idx 8 — minimal protocol
        (
            base_instruction + " Use the minimum validated reagent volumes and shortest validated incubation times.",
            "Minimal protocol — minimum time and reagents"
        ),

        # idx 9 — high-throughput 384-well
        (
            base_instruction.replace("96-well", "384-well")
                            .replace("96 well", "384 well")
            + (" Use 384-well format for higher throughput."
               if "384" not in base_instruction else ""),
            "High-throughput 384-well format"
        ),
    ]

    idx = variant_index % len(variations)
    return variations[idx]


def _replace_numbers(text: str, replacements: dict) -> str:
    """Replace substrings in text, case-insensitive."""
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


class BatchGenerator:
    """
    Generates and ranks N protocol variants for a single instruction.
    Requires LLMEngine + RAGEngine + optionally an execution orchestrator.
    """

    def __init__(
        self,
        llm_engine:      Any,
        rag_engine:      Any,
        orchestrator:    Any   = None,
        sim_mode:        str   = "mock",
    ) -> None:
        self._llm     = llm_engine
        self._rag     = rag_engine
        self._orch    = orchestrator
        self._sim_mode = sim_mode

    def generate_batch(
        self,
        instruction:   str,
        n_variants:    int   = 5,
        top_k_chunks:  int   = 5,
        doc_type:      str | None = None,
        run_sim:       bool  = True,
    ) -> BatchResult:
        """
        Generate n_variants protocol variants for the given instruction.

        Args:
            instruction:  Base NL instruction.
            n_variants:   How many variants to generate (2–10).
            top_k_chunks: RAG chunks to retrieve per variant.
            doc_type:     Optional document type filter.
            run_sim:      Whether to run physics simulation on each variant.

        Returns:
            BatchResult with all variants ranked by composite score.
        """
        n_variants  = max(2, min(10, n_variants))
        batch_id    = str(uuid.uuid4())
        t0          = time.perf_counter()
        variants: list[BatchVariant] = []

        log.info("batch_start", batch_id=batch_id, n=n_variants, instruction=instruction[:60])

        for i in range(n_variants):
            variant_id = str(uuid.uuid4())
            t_variant  = time.perf_counter()

            # Build the varied instruction
            varied_instruction, variation_desc = _make_variation(instruction, i, {})

            # Retrieve context
            try:
                retrieval = self._rag.retrieve(
                    varied_instruction, top_k=top_k_chunks,
                    doc_type_filter=doc_type)
                chunks = retrieval.chunks
            except Exception as exc:
                log.warning("batch_rag_failed", variant=i, error=str(exc))
                chunks = []

            # Build context block
            context_parts = []
            for j, chunk in enumerate(chunks, 1):
                sec = chunk.section_title or ""
                context_parts.append(
                    f"<source id='SOURCE_{j}' file='{chunk.source}' "
                    f"section='{sec}' "
                    f"page='{chunk.page_start}'>"
                    f"\n{chunk.text}\n</source>"
                )
            context_block = "\n\n".join(context_parts) if context_parts else "<no_sources/>"

            # Generate protocol
            try:
                from services.translation_service.core.llm_engine import _build_system_prompt, _build_user_prompt
                system = _build_system_prompt()
                user   = _build_user_prompt(varied_instruction, context_block)
                raw    = self._llm._call_with_retry(system, user)

                import json, re
                clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`")
                data  = json.loads(clean)

                # Build protocol dict
                steps = []
                for s in data.get("steps", []):
                    steps.append({
                        "step_number":        s.get("step_number", len(steps)+1),
                        "instruction":        s.get("instruction", ""),
                        "duration_seconds":   s.get("duration_seconds"),
                        "temperature_celsius":s.get("temperature_celsius"),
                        "volume_ul":          s.get("volume_ul"),
                        "citations":          s.get("citations", ["GENERAL"]),
                        "safety_note":        s.get("safety_note"),
                    })

                sources = [
                    {"source_id": f"SOURCE_{j}", "filename": c.source,
                     "section": c.section_title or "", "page_start": c.page_start,
                     "score": c.score}
                    for j, c in enumerate(chunks, 1)
                ]

                protocol = {
                    "protocol_id":      variant_id,
                    "title":            data.get("title", f"Variant {i+1}"),
                    "description":      data.get("description", ""),
                    "steps":            steps,
                    "reagents":         data.get("reagents", []),
                    "equipment":        data.get("equipment", []),
                    "safety_level":     data.get("safety_level", "safe"),
                    "safety_notes":     data.get("safety_notes", []),
                    "confidence_score": float(data.get("confidence_score", 0.7)),
                    "generation_ms":    (time.perf_counter()-t_variant)*1000,
                    "model_used":       getattr(self._llm, "_model", "unknown"),
                    "sources_used":     sources,
                    "batch_id":         batch_id,
                    "variant_index":    i,
                    "varied_instruction": varied_instruction,
                }

            except Exception as exc:
                log.warning("batch_gen_failed", variant=i, error=str(exc))
                continue

            # Simulate if orchestrator available
            sim_result = None
            if run_sim and self._orch is not None:
                try:
                    from services.execution_service.core.isaac_sim_bridge import SimMode
                    mode_map = {"mock": SimMode.MOCK, "pybullet": SimMode.PYBULLET}
                    mode = mode_map.get(self._sim_mode, SimMode.MOCK)
                    plan = self._orch(protocol, sim_mode=mode)
                    if plan.simulation_result:
                        sr = plan.simulation_result
                        sim_result = {
                            "passed":             sr.passed,
                            "simulation_passed":  sr.passed,
                            "commands_executed":  sr.commands_executed,
                            "collision_detected": sr.collision_detected,
                            "physics_engine":     self._sim_mode,
                        }
                except Exception as exc:
                    log.warning("batch_sim_failed", variant=i, error=str(exc))

            score = _score_variant(protocol, sim_result)
            gen_ms = (time.perf_counter() - t_variant) * 1000

            variants.append(BatchVariant(
                variant_id=variant_id, index=i,
                protocol=protocol, sim_result=sim_result,
                composite_score=score, generation_ms=gen_ms,
                variation_desc=variation_desc,
            ))
            log.info("variant_generated", index=i, score=round(score,3),
                     title=protocol.get("title","")[:40])

        # Rank variants
        variants.sort(key=lambda v: v.composite_score, reverse=True)
        for rank, v in enumerate(variants, 1):
            v.rank = rank

        best_id = variants[0].variant_id if variants else ""
        total_ms = (time.perf_counter() - t0) * 1000

        log.info("batch_complete", batch_id=batch_id,
                 n_succeeded=len(variants),
                 best_score=round(variants[0].composite_score, 3) if variants else 0,
                 total_ms=round(total_ms, 1))

        return BatchResult(
            batch_id=batch_id, instruction=instruction,
            n_requested=n_variants, n_succeeded=len(variants),
            variants=variants, total_ms=total_ms,
            best_variant_id=best_id,
        )