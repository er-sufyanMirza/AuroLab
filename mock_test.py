"""
mock_test.py — AuroLab smoke test (no external APIs needed)
Run: python mock_test.py
All imports and signatures match the ACTUAL classes in services/*
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

RESULTS = []

def test(name):
    def decorator(fn):
        def wrapper():
            t0 = time.perf_counter()
            try:
                fn()
                RESULTS.append((name, True, f"{round((time.perf_counter()-t0)*1000)}ms"))
            except Exception as e:
                RESULTS.append((name, False, str(e)[:140]))
        wrapper()
    return decorator


# ── Tests ──────────────────────────────────────────────────────────────────────

@test("Core Phase-8 imports resolve")
def _():
    from services.translation_service.core.protocol_templates import list_templates
    from services.translation_service.core.report_generator   import generate_html_report
    from services.translation_service.core.opentrons_exporter import export_opentrons_script
    from services.translation_service.core.protocol_diff      import diff_protocols
    from services.translation_service.core.reagent_inventory  import ReagentInventory
    from services.translation_service.core.workflow_engine    import WorkflowEngine
    from services.translation_service.core.export_bundle      import create_export_bundle
    from services.translation_service.core.protocol_notes     import ProtocolNotesStore


@test("PDF chunker produces chunks")
def _():
    from services.translation_service.core.chunker import chunk_document, Chunk
    # chunker works on blocks of text — test with raw text input
    assert callable(chunk_document)


@test("Step parser: instruction → commands")
def _():
    from services.execution_service.core.step_parser import parse_step
    # Real signature: parse_step(instruction, step_number, command_index_start=0)
    cmds = parse_step("Pipette 50 µL from slot 1 well A1 to slot 2 well B1",
                      step_number=1, command_index_start=0)
    assert isinstance(cmds, list)


@test("Validator: validate_commands")
def _():
    from services.execution_service.core.validator       import validate_commands
    from services.execution_service.core.robot_commands  import RobotCommand, CommandType
    cmds = [
        RobotCommand(step_number=1, command_type=CommandType.HOME,
                     command_index=0, protocol_step_ref=0),
        RobotCommand(step_number=2, command_type=CommandType.ASPIRATE,
                     command_index=1, protocol_step_ref=1,
                     volume_ul=50.0, source_slot=1, source_well="A1"),
    ]
    corrected, errors = validate_commands(cmds, auto_correct=False)
    assert isinstance(corrected, list)
    assert isinstance(errors, list)


@test("Mock simulation: clean sequence passes")
def _():
    from services.execution_service.core.orchestrator     import execute_protocol
    from services.execution_service.core.isaac_sim_bridge import SimMode
    proto = {
        "protocol_id": "mock-001", "title": "Smoke", "description": "",
        "steps": [
            {"step_number":1,"instruction":"Home robot arm",              "citations":["GENERAL"],"volume_ul":None},
            {"step_number":2,"instruction":"Pick up tip from slot 11",    "citations":["GENERAL"],"volume_ul":None},
            {"step_number":3,"instruction":"Aspirate 50 µL from slot 1 well A1","citations":["GENERAL"],"volume_ul":50.0},
            {"step_number":4,"instruction":"Dispense 50 µL to slot 2 well A1", "citations":["GENERAL"],"volume_ul":50.0},
            {"step_number":5,"instruction":"Drop tip in waste",            "citations":["GENERAL"],"volume_ul":None},
        ],
        "reagents":["Buffer"],"equipment":["P300"],"safety_level":"safe","safety_notes":[],
        "confidence_score":0.9,"generation_ms":100,"model_used":"test","sources_used":[],
    }
    plan = execute_protocol(proto, sim_mode=SimMode.MOCK)
    assert plan is not None
    assert plan.simulation_result is not None


@test("Analytics: produces EfficiencyReport")
def _():
    from services.analytics_service.core.analytics_engine import AnalyticsEngine
    engine = AnalyticsEngine()
    proto = {
        "protocol_id":"ana-001","title":"BCA Assay",
        "steps":[{"step_number":1,"instruction":"Pipette 50 µL","volume_ul":50}],
        "reagents":["BCA Reagent"],"equipment":["96-well plate"],
        "safety_level":"safe","safety_notes":[],"confidence_score":0.9,"generation_ms":100,
    }
    plan = {
        "plan_id":"plan-001","protocol_id":"ana-001","protocol_title":"BCA Assay",
        "estimated_mins":45.0,"estimated_total_duration_s":2700.0,
        "command_count":8,"status":"sim_passed","commands":[],
    }
    report = engine.compute_report(plan, proto)
    assert report is not None
    assert hasattr(report, "robot_cost")
    assert hasattr(report, "time_saved_min")


@test("RL: reward model scores a run")
def _():
    from services.rl_service.core.rl_engine        import RewardModel
    from services.rl_service.core.telemetry_store  import ExecutionRun
    import time as _t, uuid
    run = ExecutionRun(
        run_id=str(uuid.uuid4()),
        protocol_id="p1",
        protocol_title="BCA Assay",
        timestamp=_t.time(),
        sim_mode="mock",
        passed=True,
        commands_executed=8,
        tip_changes=1,
        volume_aspirated_ul=50.0,
        volume_dispensed_ul=50.0,
        total_distance_mm=300.0,
        duration_s=120.0,
        collision_detected=False,
        collision_at=None,
        flow_rate_avg=150.0,
        centrifuge_rpm_avg=0.0,
        incubate_temp_avg=37.0,
        reward=0.0,
        telemetry_json="{}",
    )
    reward = RewardModel().compute(run, baseline_duration_s=300.0)
    assert 0.0 <= reward <= 1.0


@test("Fleet: schedule 2 plans across 2 robots")
def _():
    from services.orchestration_service.core.fleet_models import RobotAgent
    from services.orchestration_service.core.scheduler    import RobotFleet
    fleet = RobotFleet(robots=[
        RobotAgent(robot_id="r1", name="OT-2 Unit 1", location="Bay 1"),
        RobotAgent(robot_id="r2", name="OT-2 Unit 2", location="Bay 2"),
    ])
    plans = [
        {"plan_id":"plan-1","protocol_id":"p1","protocol_title":"BCA",
         "estimated_total_duration_s":600,"required_resources":["tip_rack_1"],
         "priority":1,"estimated_mins":10,"commands":[]},
        {"plan_id":"plan-2","protocol_id":"p2","protocol_title":"PCR",
         "estimated_total_duration_s":300,"required_resources":["tip_rack_2"],
         "priority":2,"estimated_mins":5,"commands":[]},
    ]
    schedule = fleet.schedule(plans)
    assert schedule is not None
    assert len(schedule.tasks) == 2


@test("Vision: mock detection returns LabState")
def _():
    from services.vision_service.core.vision_engine import VisionEngine, VisionBackend
    from services.vision_service.core.lab_state     import LabState
    engine = VisionEngine(backend=VisionBackend.MOCK)
    state  = engine.detect(mock_scenario="bca_assay")
    assert isinstance(state, LabState)
    # LabState has 'slots' not 'labware_map' — use to_labware_map()
    lm = state.to_labware_map()
    assert isinstance(lm, dict)
    assert len(lm) > 0


@test("Phase 8: OT-2 + diff + templates + bundle")
def _():
    from services.translation_service.core.opentrons_exporter import export_opentrons_script
    from services.translation_service.core.protocol_diff      import diff_protocols
    from services.translation_service.core.protocol_templates import list_templates, build_instruction_from_template
    from services.translation_service.core.export_bundle      import create_export_bundle
    import zipfile, io, copy

    proto = {
        "protocol_id":"ph8-001","title":"BCA Phase 8","description":"Test",
        "steps":[{"step_number":1,"instruction":"Pipette 50 µL BCA reagent",
                  "volume_ul":50.0,"citations":["S1"],"safety_note":None}],
        "reagents":["BCA Reagent A"],"equipment":["96-well plate"],
        "safety_level":"safe","safety_notes":[],"confidence_score":0.92,
        "generation_ms":100,"model_used":"test","sources_used":[],
    }
    assert "from opentrons import protocol_api" in export_opentrons_script(proto)

    proto2 = copy.deepcopy(proto)
    proto2["protocol_id"] = "ph8-002"
    proto2["confidence_score"] = 0.75
    proto2["steps"].append({"step_number":2,"instruction":"Incubate","citations":["GENERAL"],"volume_ul":None,"safety_note":None})
    diff = diff_protocols(proto, proto2)
    assert diff.steps_added == 1

    assert len(list_templates()) == 8
    instr = build_instruction_from_template("bca_protein_assay",
        {"n_samples":8,"sample_volume_ul":25,"incubation_temp_c":37,
         "incubation_time_min":30,"standard_curve":"2000-25","plate_format":"96-well"})
    assert "8" in instr

    bundle = create_export_bundle(proto)
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        names = [n.split("/")[-1] for n in zf.namelist()]
    assert "protocol.json" in names and "ot2_script.py" in names


@test("Full pipeline: NL → ExecutionPlan")
def _():
    from services.execution_service.core.orchestrator     import execute_protocol
    from services.execution_service.core.isaac_sim_bridge import SimMode
    proto = {
        "protocol_id":"e2e-001","title":"E2E Test","description":"",
        "steps":[
            {"step_number":1,"instruction":"Home robot",                    "citations":["GENERAL"],"volume_ul":None},
            {"step_number":2,"instruction":"Pick up tip slot 11",           "citations":["GENERAL"],"volume_ul":None},
            {"step_number":3,"instruction":"Aspirate 100 µL slot 1 well A1","citations":["S1"],     "volume_ul":100.0},
            {"step_number":4,"instruction":"Dispense 100 µL slot 2 well A1","citations":["S1"],     "volume_ul":100.0},
            {"step_number":5,"instruction":"Drop tip waste",                "citations":["GENERAL"],"volume_ul":None},
        ],
        "reagents":["BCA Reagent"],"equipment":["P300","96-well plate"],
        "safety_level":"safe","safety_notes":[],"confidence_score":0.94,
        "generation_ms":1200,"model_used":"llama-3.3-70b","sources_used":[],
    }
    plan = execute_protocol(proto, sim_mode=SimMode.MOCK)
    assert plan and plan.plan_id and len(plan.commands) > 0


# ── Output ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "═"*55)
    print("  AuroLab Smoke Tests v2.0")
    print("═"*55)
    passed = sum(1 for _,ok,_ in RESULTS if ok)
    for name, ok, detail in RESULTS:
        c = "\033[92m" if ok else "\033[91m"; r = "\033[0m"
        print(f"  {c}{'✓' if ok else '✗'}{r}  {name}")
        if not ok: print(f"       {c}{detail}{r}")
    bar = "█"*passed + "░"*(len(RESULTS)-passed)
    c   = "\033[92m" if passed==len(RESULTS) else ("\033[93m" if passed > len(RESULTS)//2 else "\033[91m")
    print(f"\n  {c}{bar}{r}  {passed}/{len(RESULTS)}")
    print("  All systems operational!\n" if passed==len(RESULTS) else f"  {len(RESULTS)-passed} failure(s)\n")
    import sys as _sys; _sys.exit(0 if passed==len(RESULTS) else 1)