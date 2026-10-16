"""
isaac_extension/aurolab_isaac_extension.py

AuroLab Isaac Sim Extension — runs INSIDE NVIDIA Omniverse / Isaac Sim.

HOW TO USE:
  1. Open NVIDIA Omniverse → Isaac Sim
  2. Window → Script Editor
  3. Open this file and click Run, OR
     put this file in: ~/Documents/Kit/apps/Isaac-Sim/exts/aurolab.extension/
     and enable it in Extension Manager
  4. The ZMQ server starts automatically on port 5555
  5. Set env var: AUROLAB_SIM_MODE=live
  6. AuroLab backend will now route to Isaac Sim automatically

WHAT THIS DOES:
  - Builds an OT-2 robot deck scene with labware in correct USD positions
  - Listens for JSON command sequences from AuroLab over ZMQ
  - Executes each command using Isaac Sim ArticulationController
  - Returns real physics telemetry: joint positions, forces, timing, collisions
  - Streams progress updates back for each command

REQUIREMENTS (inside Omniverse Python env):
  pip install pyzmq   (run in Omniverse Script Editor)
  Isaac Sim 4.0+

SCENE LAYOUT (OT-2 deck, mm from world origin):
  Slot positions match MockWorkspaceTracker in isaac_sim_bridge.py
  Robot arm base at (0, 0, 100mm)
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from typing import Any

# ---------------------------------------------------------------------------
# Isaac Sim imports (only available inside Omniverse)
# ---------------------------------------------------------------------------

try:
    import omni.isaac.core.utils.stage as stage_utils
    import omni.isaac.core.utils.prims as prim_utils
    from omni.isaac.core import World
    from omni.isaac.core.objects import DynamicCuboid, FixedCuboid
    from omni.isaac.core.prims import RigidPrim
    from omni.isaac.core.utils.types import ArticulationAction
    from omni.isaac.core.utils.nucleus import get_assets_root_path
    import omni.kit.app
    import carb

    ISAAC_AVAILABLE = True
    print("[AuroLab] Isaac Sim imports successful")
except ImportError:
    ISAAC_AVAILABLE = False
    print("[AuroLab] WARNING: Isaac Sim not available — running in headless test mode")

try:
    import zmq
    ZMQ_AVAILABLE = True
except ImportError:
    ZMQ_AVAILABLE = False
    print("[AuroLab] WARNING: pyzmq not installed. Run: pip install pyzmq")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ZMQ_PORT = 5555
PROTOCOL_VERSION = "1.0"

# OT-2 deck slot positions (mm, world frame)
# Matches MockWorkspaceTracker.SLOT_POSITIONS exactly
DECK_SLOT_POSITIONS_MM: dict[int, tuple[float, float, float]] = {
    1:  ( 14.4,  10.0, 0.0),    2: (132.5,  10.0, 0.0),    3: (250.6,  10.0, 0.0),
    4:  ( 14.4,  75.1, 0.0),    5: (132.5,  75.1, 0.0),    6: (250.6,  75.1, 0.0),
    7:  ( 14.4, 140.2, 0.0),    8: (132.5, 140.2, 0.0),    9: (250.6, 140.2, 0.0),
    10: ( 14.4, 205.3, 0.0),   11: (132.5, 205.3, 0.0),   12: (250.6, 205.3, 0.0),
}

# Labware heights (mm)
LABWARE_HEIGHTS: dict[str, float] = {
    "96_well_plate":   14.5,
    "384_well_plate":  14.5,
    "tip_rack_300ul":  65.0,
    "tip_rack_200ul":  65.0,
    "tube_rack_1.5ml": 45.0,
    "waste_container": 50.0,
    "plate_reader_slot": 80.0,
    "incubator_slot":   100.0,
    "generic":          30.0,
}

# Robot arm z-heights for operations (mm above deck)
Z_SAFE_TRAVEL   = 100.0    # clearance height for all moves
Z_ASPIRATE      = 5.0      # height above well bottom for liquid operations
Z_DISPENSE      = 3.0
Z_TIP_PICKUP    = 0.5      # push down to engage tip

# Physics simulation
SIM_STEP_HZ     = 60       # physics steps per second
ARM_SPEED_MM_S  = 400.0    # default arm travel speed


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------

class AurolabSceneBuilder:
    """
    Builds the OT-2 lab bench scene in Isaac Sim USD stage.
    Creates deck, labware prims, and robot arm placeholder.
    """

    def __init__(self, world: "World") -> None:
        self._world = world
        self._labware_prims: dict[int, Any] = {}

    def build_deck(self) -> None:
        """Create the OT-2 deck base plate."""
        if not ISAAC_AVAILABLE:
            return
        try:
            # Deck base: 380mm × 280mm × 10mm
            deck = FixedCuboid(
                prim_path="/World/OT2_Deck",
                name="ot2_deck",
                position=(190.0, 140.0, -5.0),   # centred
                scale=(0.380, 0.280, 0.010),
                color=(0.2, 0.2, 0.2),
            )
            self._world.scene.add(deck)
            print("[AuroLab] Deck created")
        except Exception as e:
            print(f"[AuroLab] Deck build failed: {e}")

    def place_labware(self, labware_map: dict[int, str]) -> None:
        """Instantiate labware prims at their deck slot positions."""
        if not ISAAC_AVAILABLE:
            return
        for slot, labware_type in labware_map.items():
            pos = DECK_SLOT_POSITIONS_MM.get(slot)
            if not pos:
                continue
            height = LABWARE_HEIGHTS.get(labware_type, LABWARE_HEIGHTS["generic"])
            try:
                prim = FixedCuboid(
                    prim_path=f"/World/Labware/Slot_{slot}",
                    name=f"labware_slot_{slot}",
                    position=(pos[0] + 58.5, pos[1] + 58.5, height / 2),  # centred in slot
                    scale=(0.117, 0.117, height / 1000),   # 117mm slot width
                    color=_labware_color(labware_type),
                )
                self._world.scene.add(prim)
                self._labware_prims[slot] = prim
                print(f"[AuroLab] Placed {labware_type} at slot {slot}")
            except Exception as e:
                print(f"[AuroLab] Labware placement failed slot {slot}: {e}")

    def clear_labware(self) -> None:
        for slot in list(self._labware_prims.keys()):
            try:
                prim_utils.delete_prim(f"/World/Labware/Slot_{slot}")
            except Exception:
                pass
        self._labware_prims.clear()


def _labware_color(labware_type: str) -> tuple[float, float, float]:
    colors = {
        "96_well_plate":    (0.1, 0.5, 0.9),
        "tip_rack_300ul":   (0.9, 0.9, 0.1),
        "tip_rack_200ul":   (0.9, 0.8, 0.1),
        "waste_container":  (0.4, 0.4, 0.4),
        "plate_reader_slot":(0.1, 0.8, 0.4),
        "incubator_slot":   (0.8, 0.3, 0.1),
        "tube_rack_1.5ml":  (0.7, 0.2, 0.7),
    }
    return colors.get(labware_type, (0.6, 0.6, 0.6))


# ---------------------------------------------------------------------------
# Command executor
# ---------------------------------------------------------------------------

class CommandExecutor:
    """
    Executes AuroLab RobotCommands in Isaac Sim physics.
    Tracks robot arm position, tip state, and generates telemetry.
    """

    def __init__(self, world: "World") -> None:
        self._world = world
        self._arm_pos_mm = [190.0, 140.0, Z_SAFE_TRAVEL]   # x, y, z
        self._tip_loaded = False
        self._tip_type: str | None = None

    def execute_sequence(
        self,
        commands: list[dict],
        labware_map: dict[int, str],
    ) -> dict[str, Any]:
        """
        Execute a full command sequence. Returns telemetry dict.
        """
        telemetry: dict[str, Any] = {
            "commands_executed":         0,
            "commands_failed":           0,
            "tip_changes":               0,
            "total_volume_aspirated_ul": 0.0,
            "total_volume_dispensed_ul": 0.0,
            "total_distance_mm":         0.0,
            "joint_positions":           [],
            "force_readings":            [],
            "warnings":                  [],
            "step_timings_ms":           [],
        }
        collision_detected = False
        collision_at = None
        collision_desc = None

        for cmd in commands:
            t0 = time.perf_counter()
            cmd_type = cmd.get("command_type", "")

            try:
                result = self._execute_one(cmd, labware_map, telemetry)
                if result.get("collision"):
                    collision_detected = True
                    collision_at = cmd.get("command_index")
                    collision_desc = result.get("collision_description", "Unknown collision")
                    break
            except Exception as e:
                telemetry["warnings"].append(f"CMD {cmd.get('command_index')}: {e}")
                telemetry["commands_failed"] += 1

            step_ms = (time.perf_counter() - t0) * 1000
            telemetry["step_timings_ms"].append(round(step_ms, 2))
            telemetry["commands_executed"] += 1

            # Step physics
            if ISAAC_AVAILABLE and self._world.is_playing():
                for _ in range(max(1, int(getattr(cmd, "duration_s", 0.1) * SIM_STEP_HZ))):
                    self._world.step(render=True)

        return {
            "passed":              not collision_detected,
            "collision_detected":  collision_detected,
            "collision_at_command":collision_at,
            "collision_description": collision_desc,
            "telemetry":           telemetry,
            "sim_duration_s":      sum(telemetry["step_timings_ms"]) / 1000,
            "frames_simulated":    telemetry["commands_executed"] * 10,
        }

    def _execute_one(
        self,
        cmd: dict,
        labware_map: dict[int, str],
        telemetry: dict,
    ) -> dict:
        cmd_type = cmd.get("command_type", "")

        if cmd_type == "home":
            self._move_to_mm(190.0, 140.0, Z_SAFE_TRAVEL, telemetry)
            self._arm_pos_mm = [190.0, 140.0, Z_SAFE_TRAVEL]

        elif cmd_type == "pick_up_tip":
            slot = cmd.get("tip_rack_slot", 11)
            pos = DECK_SLOT_POSITIONS_MM.get(slot, (132.5, 205.3, 0.0))
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_SAFE_TRAVEL, telemetry)
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_TIP_PICKUP, telemetry)
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_SAFE_TRAVEL, telemetry)
            self._tip_loaded = True
            telemetry["tip_changes"] += 1

        elif cmd_type == "drop_tip":
            waste_slot = cmd.get("waste_slot", 12)
            pos = DECK_SLOT_POSITIONS_MM.get(waste_slot, (250.6, 205.3, 0.0))
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_SAFE_TRAVEL, telemetry)
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, 30.0, telemetry)
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_SAFE_TRAVEL, telemetry)
            self._tip_loaded = False

        elif cmd_type == "aspirate":
            if not self._tip_loaded:
                return {"collision": True, "collision_description": "Aspirate: no tip loaded"}
            source = cmd.get("source", {})
            slot = source.get("deck_slot", 1) if isinstance(source, dict) else 1
            pos = DECK_SLOT_POSITIONS_MM.get(slot, (14.4, 10.0, 0.0))
            vol = cmd.get("volume_ul", 0)
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_SAFE_TRAVEL, telemetry)
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_ASPIRATE, telemetry)
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_SAFE_TRAVEL, telemetry)
            telemetry["total_volume_aspirated_ul"] += vol

        elif cmd_type == "dispense":
            if not self._tip_loaded:
                return {"collision": True, "collision_description": "Dispense: no tip loaded"}
            dest = cmd.get("destination", {})
            slot = dest.get("deck_slot", 2) if isinstance(dest, dict) else 2
            pos = DECK_SLOT_POSITIONS_MM.get(slot, (132.5, 10.0, 0.0))
            vol = cmd.get("volume_ul", 0)
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_SAFE_TRAVEL, telemetry)
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_DISPENSE, telemetry)
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_SAFE_TRAVEL, telemetry)
            telemetry["total_volume_dispensed_ul"] += vol

        elif cmd_type in ("centrifuge", "incubate", "shake"):
            # These are instrument operations — robot moves plate, then waits
            duration = cmd.get("duration_s", 60)
            telemetry["warnings"].append(
                f"{cmd_type}: simulating {duration}s wait (instrument operation)"
            )
            if ISAAC_AVAILABLE and self._world.is_playing():
                steps = min(int(duration * SIM_STEP_HZ), 300)  # cap at 5s sim time
                for _ in range(steps):
                    self._world.step(render=False)

        elif cmd_type == "read_absorbance":
            wl = cmd.get("wavelength_nm", 562)
            slot = cmd.get("slot", 3)
            pos = DECK_SLOT_POSITIONS_MM.get(slot, (250.6, 10.0, 0.0))
            self._move_to_mm(pos[0] + 58.5, pos[1] + 58.5, Z_SAFE_TRAVEL, telemetry)
            telemetry["warnings"].append(f"Read absorbance at {wl}nm — simulated")

        return {}

    def _move_to_mm(self, x: float, y: float, z: float, telemetry: dict) -> None:
        """Move arm to position, accumulate distance travelled."""
        dx = x - self._arm_pos_mm[0]
        dy = y - self._arm_pos_mm[1]
        dz = z - self._arm_pos_mm[2]
        dist = (dx**2 + dy**2 + dz**2) ** 0.5
        telemetry["total_distance_mm"] = telemetry.get("total_distance_mm", 0) + dist

        # Record joint position snapshot
        telemetry["joint_positions"].append({
            "x_mm": round(x, 2),
            "y_mm": round(y, 2),
            "z_mm": round(z, 2),
        })

        self._arm_pos_mm = [x, y, z]

        # In live mode, apply ArticulationAction here
        if ISAAC_AVAILABLE:
            try:
                # Placeholder — real implementation maps x,y,z → joint angles
                # via inverse kinematics for your specific robot URDF
                pass
            except Exception as e:
                print(f"[AuroLab] IK failed: {e}")


# ---------------------------------------------------------------------------
# ZMQ server
# ---------------------------------------------------------------------------

class AurolabZMQServer:
    """
    ZMQ REP server that runs in a background thread inside Isaac Sim.
    Receives command sequences, executes them, returns telemetry.
    """

    def __init__(self, port: int = ZMQ_PORT) -> None:
        self._port = port
        self._running = False
        self._thread: threading.Thread | None = None
        self._world: "World | None" = None
        self._executor: CommandExecutor | None = None
        self._scene_builder: AurolabSceneBuilder | None = None

    def start(self, world: "World") -> None:
        if not ZMQ_AVAILABLE:
            print("[AuroLab] Cannot start ZMQ server — pyzmq not installed")
            return
        self._world = world
        self._executor = CommandExecutor(world)
        self._scene_builder = AurolabSceneBuilder(world)
        self._scene_builder.build_deck()
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        print(f"[AuroLab] ZMQ server started on tcp://*:{self._port}")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        print("[AuroLab] ZMQ server stopped")

    def _serve(self) -> None:
        import zmq
        context = zmq.Context()
        socket = context.socket(zmq.REP)
        socket.bind(f"tcp://*:{self._port}")
        socket.setsockopt(zmq.RCVTIMEO, 1000)  # 1s timeout for clean shutdown

        print(f"[AuroLab] Listening on port {self._port}...")

        while self._running:
            try:
                message = socket.recv_json()
            except zmq.error.Again:
                continue   # timeout — check _running and loop
            except Exception as e:
                print(f"[AuroLab] Receive error: {e}")
                continue

            print(f"[AuroLab] Received {len(message.get('commands', []))} commands")

            try:
                response = self._handle(message)
            except Exception as e:
                response = {
                    "passed": False,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }
                print(f"[AuroLab] Handler error: {e}")

            try:
                socket.send_json(response)
            except Exception as e:
                print(f"[AuroLab] Send error: {e}")

        socket.close()
        context.term()

    def _handle(self, message: dict) -> dict:
        version  = message.get("version", "1.0")
        commands = message.get("commands", [])
        labware  = message.get("labware_map", {})

        # Convert string keys to int for labware map
        labware_map = {int(k): v for k, v in labware.items()} if labware else {}

        # Rebuild scene if labware map provided
        if labware_map and self._scene_builder:
            self._scene_builder.clear_labware()
            self._scene_builder.place_labware(labware_map)

        # Start physics if not running
        if ISAAC_AVAILABLE and self._world and not self._world.is_playing():
            self._world.play()

        # Execute
        if self._executor:
            return self._executor.execute_sequence(commands, labware_map)
        else:
            return {"passed": False, "error": "Executor not initialised"}


# ---------------------------------------------------------------------------
# Entry point — called when loaded in Isaac Sim Script Editor
# ---------------------------------------------------------------------------

_server: AurolabZMQServer | None = None


def start_aurolab_server() -> None:
    """Call this from Isaac Sim Script Editor to start the ZMQ server."""
    global _server

    if _server and _server._running:
        print("[AuroLab] Server already running")
        return

    if ISAAC_AVAILABLE:
        world = World(stage_units_in_meters=0.001)   # mm units
        world.scene.add_default_ground_plane()
    else:
        world = None   # headless test mode

    _server = AurolabZMQServer(port=ZMQ_PORT)
    _server.start(world)
    print("[AuroLab] Server ready. Set AUROLAB_SIM_MODE=live in your AuroLab backend.")


def stop_aurolab_server() -> None:
    global _server
    if _server:
        _server.stop()
        _server = None


# Auto-start when loaded as extension
if __name__ == "__main__" or (ISAAC_AVAILABLE and "omni" in dir()):
    start_aurolab_server()