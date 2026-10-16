"""
aurolab/services/execution_service/core/robot_commands.py

Typed domain model for lab robot actions.

Every protocol step ultimately becomes one or more RobotCommand instances.
This is the contract between the translation layer and the simulation/execution layer.

Design principles:
  - All physical quantities are typed (no raw floats)
  - Workspace coordinates are always explicit (no implicit "current position")
  - Every command carries enough metadata for collision detection and audit
  - Commands are serialisable to JSON for Isaac Sim bridge transport
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Physical quantity types
# ---------------------------------------------------------------------------

class Vec3(BaseModel):
    """3D position in robot workspace (mm from origin)."""
    x: float
    y: float
    z: float

    def __repr__(self) -> str:
        return f"Vec3({self.x:.1f}, {self.y:.1f}, {self.z:.1f})"

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.z]


class LabwarePosition(BaseModel):
    """Logical labware address — deck slot + well."""
    deck_slot: int = Field(ge=1, le=12, description="OT-2 style deck slot 1–12")
    well: str | None = Field(default=None, description="e.g. 'A1', 'B3'")
    labware_type: str = Field(default="generic", description="e.g. '96_well_plate', 'tube_rack'")

    @field_validator("well")
    @classmethod
    def well_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper().strip()
        if not v:
            return None
        return v


# ---------------------------------------------------------------------------
# Command types
# ---------------------------------------------------------------------------

class CommandType(str, Enum):
    # Liquid handling
    ASPIRATE        = "aspirate"
    DISPENSE        = "dispense"
    MIX             = "mix"
    BLOW_OUT        = "blow_out"

    # Tip management
    PICK_UP_TIP     = "pick_up_tip"
    DROP_TIP        = "drop_tip"
    CHANGE_TIP      = "change_tip"

    # Plate/labware movement
    MOVE_TO         = "move_to"
    MOVE_PLATE      = "move_plate"

    # Instrument operations
    CENTRIFUGE      = "centrifuge"
    INCUBATE        = "incubate"
    SHAKE           = "shake"
    HEAT_COOL       = "heat_cool"
    SEAL_PLATE      = "seal_plate"
    UNSEAL_PLATE    = "unseal_plate"

    # Measurement
    READ_ABSORBANCE = "read_absorbance"
    READ_FLUORESCENCE = "read_fluorescence"
    WEIGH           = "weigh"

    # Safety / control
    PAUSE           = "pause"
    HOME            = "home"
    EMERGENCY_STOP  = "emergency_stop"


# ---------------------------------------------------------------------------
# Base command
# ---------------------------------------------------------------------------

class RobotCommand(BaseModel):
    """
    Base class for all robot commands.
    Every command has an index (position in sequence), type, duration estimate,
    and optional notes for the audit log.
    """
    command_index: int
    command_type: CommandType
    protocol_step_ref: int          # which ProtocolStep this came from
    estimated_duration_s: float = 0.0
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_wire(self) -> dict:
        """Serialise for ZMQ transport to Isaac Sim bridge."""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Liquid handling commands
# ---------------------------------------------------------------------------

class AspirateCommand(RobotCommand):
    command_type: CommandType = CommandType.ASPIRATE
    volume_ul: float = Field(gt=0, le=1000)
    source: LabwarePosition
    flow_rate_ul_s: float = Field(default=150.0, gt=0)
    z_offset_mm: float = Field(default=1.0, description="Height above well bottom")

    @field_validator("volume_ul")
    @classmethod
    def volume_in_range(cls, v: float) -> float:
        if v > 1000:
            raise ValueError(f"Aspirate volume {v}µL exceeds pipette max (1000µL)")
        return v


class DispenseCommand(RobotCommand):
    command_type: CommandType = CommandType.DISPENSE
    volume_ul: float = Field(gt=0, le=1000)
    destination: LabwarePosition
    flow_rate_ul_s: float = Field(default=150.0, gt=0)
    z_offset_mm: float = Field(default=1.0)
    blow_out: bool = False


class MixCommand(RobotCommand):
    command_type: CommandType = CommandType.MIX
    volume_ul: float = Field(gt=0, le=1000)
    repetitions: int = Field(default=3, ge=1, le=20)
    location: LabwarePosition
    flow_rate_ul_s: float = Field(default=200.0, gt=0)


# ---------------------------------------------------------------------------
# Tip management
# ---------------------------------------------------------------------------

class PickUpTipCommand(RobotCommand):
    command_type: CommandType = CommandType.PICK_UP_TIP
    tip_rack_slot: int = Field(ge=1, le=12)
    tip_type: str = Field(default="300ul")


class DropTipCommand(RobotCommand):
    command_type: CommandType = CommandType.DROP_TIP
    waste_slot: int = Field(default=12)
    home_after: bool = True


class ChangeTipCommand(RobotCommand):
    """Convenience: drop current tip + pick up fresh one."""
    command_type: CommandType = CommandType.CHANGE_TIP
    tip_rack_slot: int = Field(ge=1, le=12)
    waste_slot: int = Field(default=12)


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

class MoveToCommand(RobotCommand):
    command_type: CommandType = CommandType.MOVE_TO
    destination: LabwarePosition | Vec3
    speed_mm_s: float = Field(default=400.0, gt=0, le=600.0)


class MovePlateCommand(RobotCommand):
    command_type: CommandType = CommandType.MOVE_PLATE
    source_slot: int = Field(ge=1, le=12)
    destination_slot: int = Field(ge=1, le=12)
    labware_type: str = "96_well_plate"

    @model_validator(mode="after")
    def slots_differ(self) -> "MovePlateCommand":
        if self.source_slot == self.destination_slot:
            raise ValueError("Source and destination slots must differ")
        return self


# ---------------------------------------------------------------------------
# Instrument operations
# ---------------------------------------------------------------------------

class CentrifugeCommand(RobotCommand):
    command_type: CommandType = CommandType.CENTRIFUGE
    speed_rpm: int = Field(ge=100, le=30000)
    duration_s: float = Field(gt=0)
    temperature_celsius: float | None = None
    acceleration: str = Field(default="max", pattern=r"^(max|slow|medium)$")


class IncubateCommand(RobotCommand):
    command_type: CommandType = CommandType.INCUBATE
    temperature_celsius: float = Field(ge=-80.0, le=120.0)
    duration_s: float = Field(gt=0)
    slot: int = Field(ge=1, le=12)
    humidity_percent: float | None = None
    co2_percent: float | None = None


class ShakeCommand(RobotCommand):
    command_type: CommandType = CommandType.SHAKE
    speed_rpm: int = Field(ge=100, le=3000)
    duration_s: float = Field(gt=0)
    slot: int = Field(ge=1, le=12)
    orbit_mm: float = Field(default=3.0)


class HeatCoolCommand(RobotCommand):
    command_type: CommandType = CommandType.HEAT_COOL
    target_celsius: float = Field(ge=-80.0, le=120.0)
    slot: int = Field(ge=1, le=12)
    hold_duration_s: float | None = None
    ramp_rate_c_per_min: float = Field(default=5.0, gt=0)


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

class ReadAbsorbanceCommand(RobotCommand):
    command_type: CommandType = CommandType.READ_ABSORBANCE
    wavelength_nm: int = Field(ge=200, le=1100)
    slot: int = Field(ge=1, le=12)
    reference_wavelength_nm: int | None = None
    num_flashes: int = Field(default=6, ge=1)


# ---------------------------------------------------------------------------
# Control
# ---------------------------------------------------------------------------

class PauseCommand(RobotCommand):
    command_type: CommandType = CommandType.PAUSE
    duration_s: float | None = None   # None = wait for user confirmation
    reason: str = ""


class HomeCommand(RobotCommand):
    command_type: CommandType = CommandType.HOME
    axes: list[str] = Field(default_factory=lambda: ["all"])


# ---------------------------------------------------------------------------
# Execution plan
# ---------------------------------------------------------------------------

class ExecutionStatus(str, Enum):
    PENDING        = "pending"
    VALIDATED      = "validated"
    SIM_PASSED     = "sim_passed"
    SIM_FAILED     = "sim_failed"
    RUNNING        = "running"
    COMPLETED      = "completed"
    ABORTED        = "aborted"
    COLLISION      = "collision"


class ValidationError(BaseModel):
    command_index: int
    command_type: str
    error_code: str
    message: str
    severity: str = "error"    # "warning" | "error" | "critical"
    auto_corrected: bool = False
    correction_applied: str | None = None


class SimulationResult(BaseModel):
    """Result from one Isaac Sim execution attempt."""
    passed: bool
    collision_detected: bool = False
    collision_at_command: int | None = None
    collision_description: str | None = None
    telemetry: dict[str, Any] = Field(default_factory=dict)
    sim_duration_s: float = 0.0
    frames_simulated: int = 0


class ExecutionPlan(BaseModel):
    """
    The final output of the execution layer.
    A fully validated, simulation-checked sequence of robot commands
    ready for physical execution or further review.
    """
    plan_id: str
    protocol_id: str
    protocol_title: str
    commands: list[RobotCommand]
    status: ExecutionStatus = ExecutionStatus.PENDING
    validation_errors: list[ValidationError] = Field(default_factory=list)
    simulation_result: SimulationResult | None = None
    estimated_total_duration_s: float = 0.0
    created_at: float = 0.0

    @property
    def is_executable(self) -> bool:
        critical = [e for e in self.validation_errors if e.severity == "critical" and not e.auto_corrected]
        return (
            self.status in (ExecutionStatus.VALIDATED, ExecutionStatus.SIM_PASSED)
            and len(critical) == 0
        )

    @property
    def command_count(self) -> int:
        return len(self.commands)

    def summary(self) -> dict:
        type_counts: dict[str, int] = {}
        for cmd in self.commands:
            type_counts[cmd.command_type.value] = type_counts.get(cmd.command_type.value, 0) + 1
        return {
            "plan_id":           self.plan_id,
            "protocol_id":       self.protocol_id,
            "status":            self.status.value,
            "command_count":     self.command_count,
            "command_breakdown": type_counts,
            "estimated_mins":    round(self.estimated_total_duration_s / 60, 1),
            "validation_errors": len(self.validation_errors),
            "sim_passed":        self.simulation_result.passed if self.simulation_result else None,
            "is_executable":     self.is_executable,
        }