"""
aurolab/services/vision_service/core/vision_engine.py

Vision engine for lab state detection.

Three backends, same interface:
  1. MOCK    — deterministic synthetic detections for testing (no model needed)
  2. GROQ    — Groq vision API (llama-4-scout / llama-4-maverick with vision)
  3. LLAVA   — local LLaVA model via Ollama (no cloud, GPU recommended)

Backend selection:
  AUROLAB_VISION_BACKEND=mock    (default, always works)
  AUROLAB_VISION_BACKEND=groq    (needs GROQ_API_KEY)
  AUROLAB_VISION_BACKEND=llava   (needs Ollama running locally)

All backends produce the same LabState output — the orchestrator
never needs to know which backend ran.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from enum import Enum
from io import BytesIO

import structlog

from .lab_state import (
    FillLevel, LabState, LabwareType, SlotDetection,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class VisionBackend(str, Enum):
    MOCK  = "mock"
    GROQ  = "groq"
    LLAVA = "llava"


BACKEND = VisionBackend(os.getenv("AUROLAB_VISION_BACKEND", "mock").lower())
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLAVA_MODEL = os.getenv("LLAVA_MODEL", "llava:13b")
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # Groq vision model

# Confidence threshold below which a detection is treated as UNKNOWN
CONFIDENCE_THRESHOLD = 0.45

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

DETECTION_SYSTEM_PROMPT = """You are a lab automation vision system. Analyse the image of a laboratory robot deck and identify what labware is present in each slot.

The deck has 12 slots arranged in a 3×4 grid (slots 1–12, left-to-right, bottom-to-top like a standard OT-2 deck).

For each slot you can see, respond ONLY with a JSON object — no preamble, no markdown:
{
  "slots": {
    "1": {
      "labware_type": "<one of: 96_well_plate, 384_well_plate, 24_well_plate, tube_rack_1.5ml, tube_rack_15ml, tube_rack_50ml, tip_rack_10ul, tip_rack_200ul, tip_rack_300ul, tip_rack_1000ul, reservoir_12_well, reservoir_1_well, plate_reader_slot, incubator_slot, waste_container, empty, unknown>",
      "confidence": <0.0 to 1.0>,
      "fill_level": "<full|high|medium|low|critical|empty|unknown>",
      "is_sealed": <true|false>,
      "notes": "<brief observation or null>"
    }
  },
  "overall_confidence": <0.0 to 1.0>,
  "warnings": ["<any safety or attention notes>"]
}

Only include slots you can actually see. If a slot is clearly empty, include it with labware_type "empty". If you cannot determine the content, use "unknown"."""


# ---------------------------------------------------------------------------
# Backend: Mock
# ---------------------------------------------------------------------------

# Standard lab setup used for mock detections
_MOCK_SCENARIOS: dict[str, dict[int, dict]] = {
    "bca_assay": {
        1:  {"labware_type": "96_well_plate",   "confidence": 0.97, "fill_level": "empty",  "is_sealed": False},
        2:  {"labware_type": "96_well_plate",   "confidence": 0.95, "fill_level": "empty",  "is_sealed": False},
        3:  {"labware_type": "plate_reader_slot","confidence": 0.99, "fill_level": "unknown","is_sealed": False},
        5:  {"labware_type": "tube_rack_1.5ml", "confidence": 0.91, "fill_level": "full",   "is_sealed": False},
        7:  {"labware_type": "incubator_slot",  "confidence": 0.99, "fill_level": "unknown","is_sealed": False},
        11: {"labware_type": "tip_rack_300ul",  "confidence": 0.98, "fill_level": "full",   "is_sealed": False},
        12: {"labware_type": "waste_container", "confidence": 0.99, "fill_level": "low",    "is_sealed": False},
    },
    "pcr": {
        1:  {"labware_type": "96_well_plate",   "confidence": 0.96, "fill_level": "empty",  "is_sealed": False},
        4:  {"labware_type": "tube_rack_1.5ml", "confidence": 0.88, "fill_level": "high",   "is_sealed": False},
        6:  {"labware_type": "reservoir_12_well","confidence": 0.93,"fill_level": "medium",  "is_sealed": False},
        10: {"labware_type": "tip_rack_10ul",   "confidence": 0.97, "fill_level": "full",   "is_sealed": False},
        11: {"labware_type": "tip_rack_200ul",  "confidence": 0.96, "fill_level": "high",   "is_sealed": False},
        12: {"labware_type": "waste_container", "confidence": 0.99, "fill_level": "medium", "is_sealed": False},
    },
    "low_tips_warning": {
        1:  {"labware_type": "96_well_plate",   "confidence": 0.97, "fill_level": "empty",  "is_sealed": False},
        11: {"labware_type": "tip_rack_300ul",  "confidence": 0.95, "fill_level": "critical","is_sealed": False},
        12: {"labware_type": "waste_container", "confidence": 0.99, "fill_level": "high",   "is_sealed": False},
    },
}


def _run_mock_detection(scenario: str = "bca_assay") -> LabState:
    scenario_data = _MOCK_SCENARIOS.get(scenario, _MOCK_SCENARIOS["bca_assay"])
    slots: dict[int, SlotDetection] = {}
    warnings: list[str] = []

    for slot_num in range(1, 13):
        if slot_num in scenario_data:
            d = scenario_data[slot_num]
            det = SlotDetection(
                slot=slot_num,
                labware_type=LabwareType(d["labware_type"]),
                confidence=d["confidence"],
                fill_level=FillLevel(d["fill_level"]),
                is_sealed=d.get("is_sealed", False),
                notes=d.get("notes"),
            )
            if det.needs_attention:
                warnings.append(
                    f"Slot {slot_num}: {det.labware_type.value} — "
                    f"{'low fill level' if det.fill_level == FillLevel.CRITICAL else 'low confidence detection'}"
                )
        else:
            det = SlotDetection(
                slot=slot_num,
                labware_type=LabwareType.EMPTY,
                confidence=0.99,
                fill_level=FillLevel.EMPTY,
            )
        slots[slot_num] = det

    confidences = [d.confidence for d in slots.values() if d.is_occupied]
    overall = sum(confidences) / len(confidences) if confidences else 0.0

    return LabState(
        snapshot_id=str(uuid.uuid4()),
        source="mock",
        slots=slots,
        overall_confidence=overall,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Backend: Groq vision
# ---------------------------------------------------------------------------

def _run_groq_detection(image_bytes: bytes, groq_api_key: str) -> LabState:
    """Use Groq's vision-capable model to analyse the lab image."""
    from groq import Groq

    client = Groq(api_key=groq_api_key)
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model=GROQ_VISION_MODEL,
        messages=[
            {"role": "system", "content": DETECTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type":      "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {
                        "type": "text",
                        "text": "Identify all labware on this robot deck. Return only JSON.",
                    },
                ],
            },
        ],
        max_tokens=1024,
        temperature=0.1,
    )

    raw = response.choices[0].message.content.strip()
    return _parse_vlm_response(raw, source="groq")


# ---------------------------------------------------------------------------
# Backend: LLaVA via Ollama
# ---------------------------------------------------------------------------

def _run_llava_detection(image_bytes: bytes) -> LabState:
    """Use local LLaVA model via Ollama."""
    import httpx

    b64 = base64.b64encode(image_bytes).decode("utf-8")

    response = httpx.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model":  LLAVA_MODEL,
            "prompt": DETECTION_SYSTEM_PROMPT + "\n\nAnalyse the lab deck image and return JSON only.",
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=120.0,
    )
    response.raise_for_status()
    raw = response.json().get("response", "")
    return _parse_vlm_response(raw, source="llava")


# ---------------------------------------------------------------------------
# VLM response parser
# ---------------------------------------------------------------------------

def _parse_vlm_response(raw: str, source: str) -> LabState:
    """
    Parse JSON response from any VLM backend into a typed LabState.
    Handles markdown fences and partial responses gracefully.
    """
    import re

    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        log.warning("vlm_no_json_found", raw_preview=raw[:200])
        return _empty_lab_state(source=source, warning="VLM returned no parseable JSON")

    try:
        data = json.loads(cleaned[start:end])
    except json.JSONDecodeError as exc:
        log.warning("vlm_json_parse_failed", error=str(exc))
        return _empty_lab_state(source=source, warning=f"JSON parse failed: {exc}")

    slots: dict[int, SlotDetection] = {}
    warnings: list[str] = list(data.get("warnings", []))

    for slot_str, slot_data in data.get("slots", {}).items():
        try:
            slot_num = int(slot_str)
            labware_raw = slot_data.get("labware_type", "unknown")
            try:
                labware = LabwareType(labware_raw)
            except ValueError:
                labware = LabwareType.UNKNOWN
                warnings.append(f"Slot {slot_num}: unrecognised labware type '{labware_raw}'")

            fill_raw = slot_data.get("fill_level", "unknown")
            try:
                fill = FillLevel(fill_raw)
            except ValueError:
                fill = FillLevel.UNKNOWN

            det = SlotDetection(
                slot=slot_num,
                labware_type=labware,
                confidence=float(slot_data.get("confidence", 0.5)),
                fill_level=fill,
                is_sealed=bool(slot_data.get("is_sealed", False)),
                notes=slot_data.get("notes"),
            )
            if det.needs_attention:
                warnings.append(
                    f"Slot {slot_num}: attention needed — "
                    f"{det.labware_type.value} confidence={det.confidence:.0%}"
                )
            slots[slot_num] = det
        except Exception as exc:  # noqa: BLE001
            log.warning("slot_parse_failed", slot=slot_str, error=str(exc))

    # Fill empty slots
    for s in range(1, 13):
        if s not in slots:
            slots[s] = SlotDetection(
                slot=s, labware_type=LabwareType.EMPTY,
                confidence=0.0, fill_level=FillLevel.UNKNOWN,
            )

    overall = float(data.get("overall_confidence", 0.5))

    return LabState(
        snapshot_id=str(uuid.uuid4()),
        source=source,
        slots=slots,
        overall_confidence=overall,
        raw_vlm_response=raw,
        warnings=warnings,
    )


def _empty_lab_state(source: str, warning: str = "") -> LabState:
    slots = {
        s: SlotDetection(slot=s, labware_type=LabwareType.UNKNOWN,
                         confidence=0.0, fill_level=FillLevel.UNKNOWN)
        for s in range(1, 13)
    }
    return LabState(
        snapshot_id=str(uuid.uuid4()),
        source=source,
        slots=slots,
        overall_confidence=0.0,
        warnings=[warning] if warning else [],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class VisionEngine:
    """
    Lab state detection engine.
    Single interface regardless of backend (mock / groq / llava).
    """

    def __init__(
        self,
        backend: VisionBackend = BACKEND,
        groq_api_key: str | None = None,
    ) -> None:
        self.backend = backend
        self._groq_key = groq_api_key or os.getenv("GROQ_API_KEY", "")
        self._last_state: LabState | None = None
        log.info("vision_engine_ready", backend=backend.value)

    def detect(
        self,
        image_bytes: bytes | None = None,
        mock_scenario: str = "bca_assay",
    ) -> LabState:
        """
        Run lab state detection on an image.

        Args:
            image_bytes:    Raw image bytes (JPEG/PNG). Required for groq/llava backends.
            mock_scenario:  Which mock scenario to use when backend=mock.
                            Options: "bca_assay", "pcr", "low_tips_warning"

        Returns:
            LabState with per-slot detections and confidence scores.
        """
        t0 = time.perf_counter()

        if self.backend == VisionBackend.MOCK:
            state = _run_mock_detection(mock_scenario)
        elif self.backend == VisionBackend.GROQ:
            if not image_bytes:
                raise ValueError("image_bytes required for groq backend")
            if not self._groq_key:
                raise ValueError("GROQ_API_KEY not set")
            state = _run_groq_detection(image_bytes, self._groq_key)
        elif self.backend == VisionBackend.LLAVA:
            if not image_bytes:
                raise ValueError("image_bytes required for llava backend")
            state = _run_llava_detection(image_bytes)
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

        elapsed = (time.perf_counter() - t0) * 1000
        self._last_state = state

        log.info("vision_detect_complete",
                 backend=self.backend.value,
                 occupied=len(state.occupied_slots()),
                 confidence=round(state.overall_confidence, 3),
                 warnings=len(state.warnings),
                 elapsed_ms=round(elapsed, 1))

        return state

    @property
    def last_state(self) -> LabState | None:
        return self._last_state

    def available_mock_scenarios(self) -> list[str]:
        return list(_MOCK_SCENARIOS.keys())