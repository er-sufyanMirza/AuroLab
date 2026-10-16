"""
aurolab/services/vision_service/core/lab_state.py

Typed domain model for lab bench state as perceived by the vision layer.

LabState is the typed equivalent of DEFAULT_LABWARE_MAP from Phase 3.
It replaces the static dict with a live, confidence-scored snapshot of
what is actually on the deck right now.

Every detection carries:
  - labware_type: what the model thinks is in this slot
  - confidence:   0.0–1.0, how sure the model is
  - fill_level:   for tip racks and reagent tubes, how full
  - is_sealed:    whether the plate has a seal/lid
  - notes:        free-text observations from the VLM

LabState.to_labware_map() converts back to the dict[int, str] format
that IsaacSimBridge.MockWorkspaceTracker expects — keeping Phase 3
completely unchanged while upgrading what feeds it.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Labware catalogue
# ---------------------------------------------------------------------------

class LabwareType(str, Enum):
    PLATE_96_WELL        = "96_well_plate"
    PLATE_384_WELL       = "384_well_plate"
    PLATE_24_WELL        = "24_well_plate"
    TUBE_RACK_1_5ML      = "tube_rack_1.5ml"
    TUBE_RACK_15ML       = "tube_rack_15ml"
    TUBE_RACK_50ML       = "tube_rack_50ml"
    TIP_RACK_10UL        = "tip_rack_10ul"
    TIP_RACK_200UL       = "tip_rack_200ul"
    TIP_RACK_300UL       = "tip_rack_300ul"
    TIP_RACK_1000UL      = "tip_rack_1000ul"
    RESERVOIR_12_WELL    = "reservoir_12_well"
    RESERVOIR_1_WELL     = "reservoir_1_well"
    PLATE_READER_SLOT    = "plate_reader_slot"
    INCUBATOR_SLOT       = "incubator_slot"
    CENTRIFUGE_SLOT      = "centrifuge_slot"
    WASTE_CONTAINER      = "waste_container"
    EMPTY                = "empty"
    UNKNOWN              = "unknown"


class FillLevel(str, Enum):
    FULL      = "full"       # >80%
    HIGH      = "high"       # 60–80%
    MEDIUM    = "medium"     # 30–60%
    LOW       = "low"        # 10–30%
    CRITICAL  = "critical"   # <10% — warn before execution
    EMPTY     = "empty"      # 0%
    UNKNOWN   = "unknown"    # could not determine


# ---------------------------------------------------------------------------
# Per-slot detection
# ---------------------------------------------------------------------------

class SlotDetection(BaseModel):
    """What the vision model detected in one deck slot."""
    slot: int = Field(ge=1, le=12)
    labware_type: LabwareType = LabwareType.UNKNOWN
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    fill_level: FillLevel = FillLevel.UNKNOWN
    is_sealed: bool = False
    well_count: int | None = None          # populated for plates
    colour: str | None = None              # e.g. "clear", "amber", "blue"
    notes: str | None = None
    bounding_box: dict[str, float] | None = None  # {x, y, w, h} in image coords

    @property
    def is_occupied(self) -> bool:
        return self.labware_type not in (LabwareType.EMPTY, LabwareType.UNKNOWN)

    @property
    def needs_attention(self) -> bool:
        """True if fill level is critical or detection confidence is low."""
        return (
            self.fill_level == FillLevel.CRITICAL
            or (self.is_occupied and self.confidence < 0.5)
        )

    def to_labware_str(self) -> str:
        """Convert to the string format expected by MockWorkspaceTracker."""
        return self.labware_type.value


# ---------------------------------------------------------------------------
# Full lab state
# ---------------------------------------------------------------------------

class LabState(BaseModel):
    """
    Complete snapshot of the lab bench as perceived by the vision layer.
    Replaces DEFAULT_LABWARE_MAP in IsaacSimBridge.
    """
    snapshot_id: str
    captured_at: float = Field(default_factory=time.time)
    source: str = "mock"              # "mock" | "llava" | "cosmos" | "manual"
    slots: dict[int, SlotDetection] = Field(default_factory=dict)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    image_width: int | None = None
    image_height: int | None = None
    raw_vlm_response: str = ""        # kept for debugging
    warnings: list[str] = Field(default_factory=list)

    def to_labware_map(self) -> dict[int, str]:
        """
        Convert to dict[int, str] format for IsaacSimBridge.MockWorkspaceTracker.
        Only includes occupied slots above confidence threshold.
        """
        return {
            slot: det.to_labware_str()
            for slot, det in self.slots.items()
            if det.is_occupied and det.confidence >= 0.3
        }

    def get_slot(self, slot: int) -> SlotDetection | None:
        return self.slots.get(slot)

    def occupied_slots(self) -> list[int]:
        return [s for s, d in self.slots.items() if d.is_occupied]

    def attention_slots(self) -> list[int]:
        """Slots that need operator attention before execution."""
        return [s for s, d in self.slots.items() if d.needs_attention]

    def tip_rack_slots(self) -> list[int]:
        tip_types = {
            LabwareType.TIP_RACK_10UL,
            LabwareType.TIP_RACK_200UL,
            LabwareType.TIP_RACK_300UL,
            LabwareType.TIP_RACK_1000UL,
        }
        return [s for s, d in self.slots.items() if d.labware_type in tip_types]

    def summary(self) -> dict[str, Any]:
        return {
            "snapshot_id":        self.snapshot_id,
            "source":             self.source,
            "captured_at":        self.captured_at,
            "overall_confidence": round(self.overall_confidence, 3),
            "occupied_slots":     self.occupied_slots(),
            "attention_needed":   self.attention_slots(),
            "tip_racks":          self.tip_rack_slots(),
            "warnings":           self.warnings,
            "slot_count":         len(self.slots),
        }