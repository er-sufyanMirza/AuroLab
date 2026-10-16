"""
services/translation_service/core/protocol_diff.py

Protocol comparison and diff engine for AuroLab.
Compares two protocols side-by-side across all dimensions:
  - Steps (additions, removals, changes)
  - Reagents and equipment
  - Safety levels
  - Cost and time estimates
  - Confidence scores
  - Source citations

Used by the Compare dashboard page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepDiff:
    step_number:  int
    kind:         str   # "added" | "removed" | "changed" | "same"
    instruction_a: str  = ""
    instruction_b: str  = ""
    changes:      list[str] = field(default_factory=list)


@dataclass
class ProtocolDiff:
    protocol_id_a: str
    protocol_id_b: str
    title_a:       str
    title_b:       str

    # Scalar comparisons
    confidence_a:  float = 0.0
    confidence_b:  float = 0.0
    step_count_a:  int   = 0
    step_count_b:  int   = 0
    safety_a:      str   = "safe"
    safety_b:      str   = "safe"
    gen_ms_a:      float = 0.0
    gen_ms_b:      float = 0.0

    # List comparisons
    reagents_only_a:   list[str] = field(default_factory=list)
    reagents_only_b:   list[str] = field(default_factory=list)
    reagents_shared:   list[str] = field(default_factory=list)
    equipment_only_a:  list[str] = field(default_factory=list)
    equipment_only_b:  list[str] = field(default_factory=list)
    sources_a:         int = 0
    sources_b:         int = 0

    # Step-level diff
    step_diffs: list[StepDiff] = field(default_factory=list)
    steps_added:   int = 0
    steps_removed: int = 0
    steps_changed: int = 0
    steps_same:    int = 0

    # Derived
    similarity_score: float = 0.0   # 0–1, higher = more similar
    recommendation:   str   = ""    # which protocol to prefer and why

    def to_dict(self) -> dict:
        return {
            "protocol_id_a":    self.protocol_id_a,
            "protocol_id_b":    self.protocol_id_b,
            "title_a":          self.title_a,
            "title_b":          self.title_b,
            "confidence_a":     round(self.confidence_a, 3),
            "confidence_b":     round(self.confidence_b, 3),
            "step_count_a":     self.step_count_a,
            "step_count_b":     self.step_count_b,
            "safety_a":         self.safety_a,
            "safety_b":         self.safety_b,
            "gen_ms_a":         self.gen_ms_a,
            "gen_ms_b":         self.gen_ms_b,
            "reagents_only_a":  self.reagents_only_a,
            "reagents_only_b":  self.reagents_only_b,
            "reagents_shared":  self.reagents_shared,
            "equipment_only_a": self.equipment_only_a,
            "equipment_only_b": self.equipment_only_b,
            "sources_a":        self.sources_a,
            "sources_b":        self.sources_b,
            "step_diffs":       [
                {"step": d.step_number, "kind": d.kind,
                 "a": d.instruction_a, "b": d.instruction_b,
                 "changes": d.changes}
                for d in self.step_diffs
            ],
            "steps_added":      self.steps_added,
            "steps_removed":    self.steps_removed,
            "steps_changed":    self.steps_changed,
            "steps_same":       self.steps_same,
            "similarity_score": round(self.similarity_score, 3),
            "recommendation":   self.recommendation,
        }


def _normalise(text: str) -> str:
    """Lowercase + strip for fuzzy comparison."""
    return " ".join(text.lower().split())


def _step_similarity(a: str, b: str) -> float:
    """Simple token overlap similarity between two step instructions."""
    ta = set(_normalise(a).split())
    tb = set(_normalise(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _list_diff(a: list[str], b: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Return (only_in_a, only_in_b, in_both) for string lists (case-insensitive)."""
    na = {x.lower(): x for x in a}
    nb = {x.lower(): x for x in b}
    both    = [na[k] for k in na if k in nb]
    only_a  = [na[k] for k in na if k not in nb]
    only_b  = [nb[k] for k in nb if k not in na]
    return only_a, only_b, both


def diff_protocols(a: dict, b: dict) -> ProtocolDiff:
    """
    Compare two GeneratedProtocol dicts and return a ProtocolDiff.

    Args:
        a: First protocol dict.
        b: Second protocol dict.

    Returns:
        ProtocolDiff with all comparison results.
    """
    steps_a = a.get("steps", [])
    steps_b = b.get("steps", [])
    max_steps = max(len(steps_a), len(steps_b), 1)

    # ── Step diff ────────────────────────────────────────────────────────────
    step_diffs: list[StepDiff] = []
    for i in range(max_steps):
        sa = steps_a[i] if i < len(steps_a) else None
        sb = steps_b[i] if i < len(steps_b) else None

        if sa is None:
            step_diffs.append(StepDiff(
                step_number=i+1, kind="added",
                instruction_b=sb.get("instruction","")
            ))
        elif sb is None:
            step_diffs.append(StepDiff(
                step_number=i+1, kind="removed",
                instruction_a=sa.get("instruction","")
            ))
        else:
            ia = sa.get("instruction","")
            ib = sb.get("instruction","")
            sim = _step_similarity(ia, ib)
            changes = []
            if sa.get("volume_ul") != sb.get("volume_ul"):
                changes.append(f"volume: {sa.get('volume_ul')} → {sb.get('volume_ul')} µL")
            if sa.get("duration_seconds") != sb.get("duration_seconds"):
                da = sa.get("duration_seconds")
                db = sb.get("duration_seconds")
                changes.append(f"duration: {da}s → {db}s")
            if sa.get("temperature_celsius") != sb.get("temperature_celsius"):
                changes.append(f"temp: {sa.get('temperature_celsius')} → {sb.get('temperature_celsius')} °C")

            kind = "same" if sim > 0.8 and not changes else "changed"
            step_diffs.append(StepDiff(
                step_number=i+1, kind=kind,
                instruction_a=ia, instruction_b=ib, changes=changes
            ))

    added   = sum(1 for d in step_diffs if d.kind == "added")
    removed = sum(1 for d in step_diffs if d.kind == "removed")
    changed = sum(1 for d in step_diffs if d.kind == "changed")
    same    = sum(1 for d in step_diffs if d.kind == "same")

    # ── List diffs ────────────────────────────────────────────────────────────
    reag_a, reag_b, reag_both = _list_diff(
        a.get("reagents",[]), b.get("reagents",[]))
    equip_a, equip_b, _ = _list_diff(
        a.get("equipment",[]), b.get("equipment",[]))

    # ── Similarity score ──────────────────────────────────────────────────────
    step_sim   = same / max_steps
    conf_sim   = 1 - abs(a.get("confidence_score",0) - b.get("confidence_score",0))
    reagent_sim= len(reag_both) / max(len(set(a.get("reagents",[])) | set(b.get("reagents",[]))), 1)
    similarity = round((step_sim * 0.5 + conf_sim * 0.25 + reagent_sim * 0.25), 3)

    # ── Recommendation ────────────────────────────────────────────────────────
    reasons_a, reasons_b = [], []
    conf_a = a.get("confidence_score", 0)
    conf_b = b.get("confidence_score", 0)
    safety_order = {"safe": 0, "caution": 1, "warning": 2, "hazardous": 3}
    saf_a = safety_order.get(a.get("safety_level","safe"), 0)
    saf_b = safety_order.get(b.get("safety_level","safe"), 0)

    if conf_a > conf_b + 0.05:
        reasons_a.append(f"higher confidence ({conf_a:.0%} vs {conf_b:.0%})")
    elif conf_b > conf_a + 0.05:
        reasons_b.append(f"higher confidence ({conf_b:.0%} vs {conf_a:.0%})")

    if len(steps_a) < len(steps_b):
        reasons_a.append(f"fewer steps ({len(steps_a)} vs {len(steps_b)})")
    elif len(steps_b) < len(steps_a):
        reasons_b.append(f"fewer steps ({len(steps_b)} vs {len(steps_a)})")

    if saf_a < saf_b:
        reasons_a.append("safer classification")
    elif saf_b < saf_a:
        reasons_b.append("safer classification")

    if len(a.get("sources_used",[])) > len(b.get("sources_used",[])):
        reasons_a.append("more source citations")
    elif len(b.get("sources_used",[])) > len(a.get("sources_used",[])):
        reasons_b.append("more source citations")

    if reasons_a and len(reasons_a) >= len(reasons_b):
        rec = f"Protocol A preferred — {'; '.join(reasons_a)}"
    elif reasons_b:
        rec = f"Protocol B preferred — {'; '.join(reasons_b)}"
    else:
        rec = "Protocols are equivalent — choose based on reagent availability"

    return ProtocolDiff(
        protocol_id_a=a.get("protocol_id",""),
        protocol_id_b=b.get("protocol_id",""),
        title_a=a.get("title","Protocol A"),
        title_b=b.get("title","Protocol B"),
        confidence_a=conf_a,
        confidence_b=conf_b,
        step_count_a=len(steps_a),
        step_count_b=len(steps_b),
        safety_a=a.get("safety_level","safe"),
        safety_b=b.get("safety_level","safe"),
        gen_ms_a=a.get("generation_ms",0),
        gen_ms_b=b.get("generation_ms",0),
        reagents_only_a=reag_a,
        reagents_only_b=reag_b,
        reagents_shared=reag_both,
        equipment_only_a=equip_a,
        equipment_only_b=equip_b,
        sources_a=len(a.get("sources_used",[])),
        sources_b=len(b.get("sources_used",[])),
        step_diffs=step_diffs,
        steps_added=added,
        steps_removed=removed,
        steps_changed=changed,
        steps_same=same,
        similarity_score=similarity,
        recommendation=rec,
    )