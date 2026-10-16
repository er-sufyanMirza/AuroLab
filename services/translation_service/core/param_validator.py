"""
core/param_validator.py — Cross-validate generated protocol parameters against KB sources.
Flags discrepancies: "Source says 37°C but protocol uses 42°C".
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

@dataclass
class ParamDiscrepancy:
    step_number: int
    parameter: str
    generated_value: str
    source_value: str
    source_id: str
    severity: str  # "warning" | "info"
    message: str

@dataclass
class ValidationReport:
    protocol_id: str
    discrepancies: list[ParamDiscrepancy] = field(default_factory=list)
    validated_steps: int = 0
    total_steps: int = 0
    passed: bool = True

    def to_dict(self) -> dict:
        return {
            "protocol_id": self.protocol_id,
            "passed": self.passed,
            "validated_steps": self.validated_steps,
            "total_steps": self.total_steps,
            "discrepancy_count": len(self.discrepancies),
            "discrepancies": [
                {"step": d.step_number, "parameter": d.parameter,
                 "generated": d.generated_value, "source": d.source_value,
                 "source_id": d.source_id, "severity": d.severity,
                 "message": d.message}
                for d in self.discrepancies
            ],
        }

def _extract_temp(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*°?[Cc]", text)
    return float(m.group(1)) if m else None

def _extract_time_min(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|minute)", text)
    if m: return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hour|hr)", text)
    if m: return float(m.group(1)) * 60
    return None

def _extract_volume(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*[µu]L", text)
    return float(m.group(1)) if m else None

def validate_protocol_params(
    protocol: dict,
    source_chunks: list[dict],
    temp_tolerance: float = 3.0,
    time_tolerance_pct: float = 0.25,
    volume_tolerance_pct: float = 0.30,
) -> ValidationReport:
    """
    Cross-validate generated protocol parameters against retrieved source chunks.
    Flags temperature, time, and volume discrepancies beyond tolerance.
    """
    pid   = protocol.get("protocol_id", "")
    steps = protocol.get("steps", [])
    report = ValidationReport(protocol_id=pid, total_steps=len(steps))

    # Build source text lookup: source_id → chunk text
    source_map: dict[str, str] = {}
    for chunk in source_chunks:
        sid = chunk.get("source_id") or chunk.get("chunk_id", "")
        source_map[sid] = chunk.get("text", "")

    for step in steps:
        snum = step.get("step_number", 0)
        inst = step.get("instruction", "")
        cites = step.get("citations", [])
        validated = False

        for cite in cites:
            if cite == "GENERAL" or cite not in source_map:
                continue
            src_text = source_map[cite]
            validated = True

            # Temperature check
            gen_temp = step.get("temperature_celsius") or _extract_temp(inst)
            src_temp = _extract_temp(src_text)
            if gen_temp and src_temp and abs(gen_temp - src_temp) > temp_tolerance:
                report.discrepancies.append(ParamDiscrepancy(
                    step_number=snum, parameter="temperature",
                    generated_value=f"{gen_temp}°C", source_value=f"{src_temp}°C",
                    source_id=cite, severity="warning",
                    message=f"Step {snum}: generated {gen_temp}°C but source suggests {src_temp}°C (Δ={abs(gen_temp-src_temp):.1f}°C)"
                ))

            # Time check
            gen_s = step.get("duration_seconds")
            gen_min = (gen_s / 60) if gen_s else _extract_time_min(inst)
            src_min = _extract_time_min(src_text)
            if gen_min and src_min:
                pct_diff = abs(gen_min - src_min) / max(src_min, 1)
                if pct_diff > time_tolerance_pct:
                    report.discrepancies.append(ParamDiscrepancy(
                        step_number=snum, parameter="duration",
                        generated_value=f"{gen_min:.0f}min", source_value=f"{src_min:.0f}min",
                        source_id=cite, severity="info",
                        message=f"Step {snum}: generated {gen_min:.0f}min but source suggests {src_min:.0f}min ({pct_diff:.0%} difference)"
                    ))

            # Volume check
            gen_vol = step.get("volume_ul") or _extract_volume(inst)
            src_vol = _extract_volume(src_text)
            if gen_vol and src_vol:
                pct_diff = abs(gen_vol - src_vol) / max(src_vol, 1)
                if pct_diff > volume_tolerance_pct:
                    report.discrepancies.append(ParamDiscrepancy(
                        step_number=snum, parameter="volume",
                        generated_value=f"{gen_vol:.0f}µL", source_value=f"{src_vol:.0f}µL",
                        source_id=cite, severity="info",
                        message=f"Step {snum}: generated {gen_vol:.0f}µL but source suggests {src_vol:.0f}µL"
                    ))

        if validated:
            report.validated_steps += 1

    report.passed = not any(d.severity == "warning" for d in report.discrepancies)
    return report