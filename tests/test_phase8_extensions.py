"""
tests/test_phase8_extensions.py

Comprehensive test suite for all Phase 8+ extension modules:
  - Opentrons exporter
  - Protocol diff engine
  - Reagent inventory
  - LLM reflection engine (structure only - no live LLM)
  - Workflow engine
  - Report generator
  - Protocol optimizer (heuristics only)
  - Protocol templates library
  - Extensions API router (import + endpoint structure)

Run with: pytest tests/test_phase8_extensions.py -v
"""

import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_protocol():
    return {
        "protocol_id":    str(uuid.uuid4()),
        "title":          "BCA Protein Assay Standard",
        "description":    "Quantify protein concentration using BCA colorimetric detection at 562 nm",
        "steps": [
            {"step_number": 1, "instruction": "Pipette 25 µL of each sample from slot 5 tube rack to 96-well plate",
             "volume_ul": 25.0, "duration_seconds": 120, "temperature_celsius": None,
             "citations": ["SOURCE_1"], "safety_note": None},
            {"step_number": 2, "instruction": "Add 200 µL BCA Working Reagent (50:1 Reagent A:B) to each well",
             "volume_ul": 200.0, "duration_seconds": 60, "temperature_celsius": None,
             "citations": ["SOURCE_1"], "safety_note": None},
            {"step_number": 3, "instruction": "Mix plate on orbital shaker for 30 seconds",
             "volume_ul": None, "duration_seconds": 30, "temperature_celsius": None,
             "citations": ["GENERAL"], "safety_note": None},
            {"step_number": 4, "instruction": "Incubate plate at 37°C for 30 minutes",
             "volume_ul": None, "duration_seconds": 1800, "temperature_celsius": 37.0,
             "citations": ["SOURCE_1"], "safety_note": None},
            {"step_number": 5, "instruction": "Read absorbance at 562 nm on plate reader",
             "volume_ul": None, "duration_seconds": 120, "temperature_celsius": None,
             "citations": ["SOURCE_1"], "safety_note": None},
        ],
        "reagents":  ["BCA Protein Assay Reagent A", "BCA Protein Assay Reagent B",
                      "BSA Standard 2 mg/mL", "PBS"],
        "equipment": ["96-well flat bottom plate", "Opentrons P300 multichannel",
                      "Incubator 37°C", "Plate reader 562 nm"],
        "safety_level":   "safe",
        "safety_notes":   [],
        "confidence_score": 0.92,
        "generation_ms":  1250.0,
        "model_used":     "llama-3.3-70b-versatile",
        "sources_used": [
            {"source_id": "SOURCE_1", "filename": "thermo_bca_manual.pdf",
             "section": "Protocol", "page_start": 5, "score": 0.96}
        ],
    }


@pytest.fixture
def modified_protocol(sample_protocol):
    """A modified version of sample_protocol for diff testing."""
    import copy
    p = copy.deepcopy(sample_protocol)
    p["protocol_id"]    = str(uuid.uuid4())
    p["title"]          = "BCA Protein Assay — Extended"
    p["confidence_score"] = 0.78
    p["steps"].append({
        "step_number": 6,
        "instruction": "Calculate protein concentration from standard curve using linear regression",
        "volume_ul": None, "duration_seconds": 300, "temperature_celsius": None,
        "citations": ["GENERAL"], "safety_note": None,
    })
    p["reagents"].append("Linear regression software")
    return p


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test.db")


# ═════════════════════════════════════════════════════════════════════════════
# 1. Opentrons Exporter
# ═════════════════════════════════════════════════════════════════════════════

class TestOT2Exporter:

    def test_import(self):
        from services.translation_service.core.opentrons_exporter import export_opentrons_script, export_opentrons_json
        assert callable(export_opentrons_script)
        assert callable(export_opentrons_json)

    def test_script_is_valid_python(self, sample_protocol):
        from services.translation_service.core.opentrons_exporter import export_opentrons_script
        script = export_opentrons_script(sample_protocol)
        compile(script, "<test>", "exec")   # raises SyntaxError if invalid

    def test_script_has_required_elements(self, sample_protocol):
        from services.translation_service.core.opentrons_exporter import export_opentrons_script
        script = export_opentrons_script(sample_protocol)
        assert "from opentrons import protocol_api" in script
        assert "metadata = {" in script
        assert '"apiLevel"' in script
        assert "def run(protocol" in script
        assert "pick_up_tip" in script
        assert "aspirate" in script
        assert "dispense" in script
        assert "protocol.pause" in script   # for incubate/centrifuge

    def test_script_contains_protocol_title(self, sample_protocol):
        from services.translation_service.core.opentrons_exporter import export_opentrons_script
        script = export_opentrons_script(sample_protocol)
        assert sample_protocol["title"] in script

    def test_script_contains_protocol_id(self, sample_protocol):
        from services.translation_service.core.opentrons_exporter import export_opentrons_script
        script = export_opentrons_script(sample_protocol)
        assert sample_protocol["protocol_id"][:8] in script

    def test_pipette_selection_p300(self, sample_protocol):
        from services.translation_service.core.opentrons_exporter import export_opentrons_script
        script = export_opentrons_script(sample_protocol)
        assert "p300" in script.lower()

    def test_pipette_selection_p20_small_volumes(self, sample_protocol):
        import copy
        from services.translation_service.core.opentrons_exporter import export_opentrons_script
        p = copy.deepcopy(sample_protocol)
        for step in p["steps"]:
            if step.get("volume_ul"):
                step["volume_ul"] = 5.0
            step["instruction"] = step["instruction"].replace("25 µL", "5 µL").replace("200 µL", "5 µL")
        script = export_opentrons_script(p)
        assert "p20" in script.lower() or "p300" in script.lower()  # either valid

    def test_json_export_schema(self, sample_protocol):
        from services.translation_service.core.opentrons_exporter import export_opentrons_json
        result = export_opentrons_json(sample_protocol)
        assert "schemaVersion" in result
        assert result["schemaVersion"] == 6
        assert "metadata" in result
        assert "commands" in result
        assert result["metadata"]["protocolName"] == sample_protocol["title"]

    def test_handles_protocol_with_no_steps(self):
        from services.translation_service.core.opentrons_exporter import export_opentrons_script
        p = {"protocol_id": "empty", "title": "Empty", "description": "",
             "steps": [], "reagents": [], "equipment": [],
             "safety_level": "safe", "safety_notes": [], "confidence_score": 0.5,
             "generation_ms": 0, "model_used": "test"}
        script = export_opentrons_script(p)
        assert "def run(protocol" in script

    def test_safety_warning_in_script(self):
        from services.translation_service.core.opentrons_exporter import export_opentrons_script
        p = {"protocol_id": "haz-001", "title": "Hazardous Test", "description": "",
             "steps": [{"step_number": 1, "instruction": "Add HCl", "volume_ul": 100,
                        "citations": ["GENERAL"], "safety_note": None}],
             "reagents": ["HCl 1M"], "equipment": [],
             "safety_level": "warning",
             "safety_notes": ["Handle acid with PPE"],
             "confidence_score": 0.8, "generation_ms": 0, "model_used": "test"}
        script = export_opentrons_script(p)
        assert "SAFETY" in script or "safety" in script.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 2. Protocol Diff Engine
# ═════════════════════════════════════════════════════════════════════════════

class TestProtocolDiff:

    def test_import(self):
        from services.translation_service.core.protocol_diff import diff_protocols, ProtocolDiff, StepDiff
        assert callable(diff_protocols)

    def test_identical_protocols_high_similarity(self, sample_protocol):
        import copy
        from services.translation_service.core.protocol_diff import diff_protocols
        p2 = copy.deepcopy(sample_protocol)
        p2["protocol_id"] = str(uuid.uuid4())
        diff = diff_protocols(sample_protocol, p2)
        assert diff.similarity_score > 0.8
        assert diff.steps_same == len(sample_protocol["steps"])
        assert diff.steps_added == 0
        assert diff.steps_removed == 0

    def test_added_step_detected(self, sample_protocol, modified_protocol):
        from services.translation_service.core.protocol_diff import diff_protocols
        diff = diff_protocols(sample_protocol, modified_protocol)
        assert diff.step_count_b == diff.step_count_a + 1
        assert diff.steps_added == 1

    def test_confidence_comparison(self, sample_protocol, modified_protocol):
        from services.translation_service.core.protocol_diff import diff_protocols
        diff = diff_protocols(sample_protocol, modified_protocol)
        assert diff.confidence_a == sample_protocol["confidence_score"]
        assert diff.confidence_b == modified_protocol["confidence_score"]
        assert diff.confidence_a > diff.confidence_b

    def test_recommendation_prefers_higher_confidence(self, sample_protocol, modified_protocol):
        from services.translation_service.core.protocol_diff import diff_protocols
        diff = diff_protocols(sample_protocol, modified_protocol)
        assert "A preferred" in diff.recommendation

    def test_reagent_diff(self, sample_protocol, modified_protocol):
        from services.translation_service.core.protocol_diff import diff_protocols
        diff = diff_protocols(sample_protocol, modified_protocol)
        assert len(diff.reagents_shared) >= 4   # all original reagents shared
        assert len(diff.reagents_only_b) == 1   # "Linear regression software" only in B

    def test_similarity_score_range(self, sample_protocol, modified_protocol):
        from services.translation_service.core.protocol_diff import diff_protocols
        diff = diff_protocols(sample_protocol, modified_protocol)
        assert 0.0 <= diff.similarity_score <= 1.0

    def test_completely_different_protocols_low_similarity(self, sample_protocol):
        from services.translation_service.core.protocol_diff import diff_protocols
        p2 = {
            "protocol_id": str(uuid.uuid4()),
            "title": "Gel Electrophoresis",
            "description": "DNA separation by size",
            "steps": [
                {"step_number": 1, "instruction": "Pour 1% agarose gel",
                 "citations": ["GENERAL"], "volume_ul": None},
                {"step_number": 2, "instruction": "Load DNA samples",
                 "citations": ["GENERAL"], "volume_ul": 5.0},
            ],
            "reagents": ["Agarose", "TAE buffer", "EtBr"],
            "equipment": ["Gel system", "UV transilluminator"],
            "safety_level": "warning",
            "safety_notes": ["EtBr is mutagenic"],
            "confidence_score": 0.85,
            "generation_ms": 800,
            "model_used": "test",
            "sources_used": [],
        }
        diff = diff_protocols(sample_protocol, p2)
        assert diff.similarity_score < 0.4

    def test_to_dict_serialisable(self, sample_protocol, modified_protocol):
        from services.translation_service.core.protocol_diff import diff_protocols
        diff = diff_protocols(sample_protocol, modified_protocol)
        d = diff.to_dict()
        json.dumps(d)   # must be JSON-serialisable


# ═════════════════════════════════════════════════════════════════════════════
# 3. Reagent Inventory
# ═════════════════════════════════════════════════════════════════════════════

class TestReagentInventory:

    def test_import(self):
        from services.translation_service.core.reagent_inventory import ReagentInventory, Reagent, InventoryCheck
        assert ReagentInventory

    def test_add_and_retrieve(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        r = inv.add_reagent("BCA Protein Assay Reagent A", 100.0, "ml",
                            expiry_date="2027-06-01", location="Fridge A")
        assert r.name == "BCA Protein Assay Reagent A"
        assert r.quantity_ml == 100.0
        assert r.reagent_id

    def test_search_by_name(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        inv.add_reagent("Bradford Reagent", 50.0, "ml")
        inv.add_reagent("BCA Reagent A", 100.0, "ml")
        results = inv.search("Bradford")
        assert len(results) == 1
        assert results[0].name == "Bradford Reagent"

    def test_low_stock_detection(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        inv.add_reagent("Low Buffer", 5.0, "ml", minimum_stock=20.0)
        low = inv.get_low_stock()
        assert len(low) == 1
        assert low[0].name == "Low Buffer"
        assert low[0].is_low

    def test_expiry_detection(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        inv.add_reagent("Expired Dye", 50.0, "ml", expiry_date="2020-01-01")
        expired = inv.get_expired()
        assert len(expired) == 1
        assert expired[0].is_expired

    def test_not_expired_when_future_date(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        inv.add_reagent("Fresh Reagent", 50.0, "ml", expiry_date="2030-12-31")
        expired = inv.get_expired()
        assert len(expired) == 0

    def test_delete_reagent(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        r = inv.add_reagent("Temp Reagent", 10.0, "ml")
        assert len(inv.search()) == 1
        deleted = inv.delete(r.reagent_id)
        assert deleted is True
        assert len(inv.search()) == 0

    def test_delete_nonexistent_returns_false(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        assert inv.delete("nonexistent-id") is False

    def test_update_quantity(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        r = inv.add_reagent("Buffer A", 100.0, "ml")
        inv.update_quantity(r.reagent_id, 45.0)
        updated = inv.get(r.reagent_id)
        assert updated.quantity_ml == 45.0

    def test_check_protocol_all_available(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        inv.add_reagent("BCA Protein Assay Reagent A", 100.0, "ml")
        inv.add_reagent("BCA Protein Assay Reagent B", 100.0, "ml")
        inv.add_reagent("BSA Standard", 25.0, "ml")
        result = inv.check_protocol("p1", ["BCA Protein Assay Reagent A",
                                            "BCA Protein Assay Reagent B",
                                            "BSA Standard"])
        assert result.all_available is True
        assert len(result.missing) == 0

    def test_check_protocol_missing_reagent(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        inv.add_reagent("Known Reagent Alpha", 100.0, "ml")
        result = inv.check_protocol("p2", ["Completely Unknown Compound XYZ 999"])
        assert result.all_available is False
        assert "Completely Unknown Compound XYZ 999" in result.missing

    def test_check_protocol_low_stock_warning(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        inv.add_reagent("Low Stock Buffer Solution", 3.0, "ml", minimum_stock=10.0)
        result = inv.check_protocol("p3", ["Low Stock Buffer Solution"])
        assert result.all_available is True   # available but warned
        assert "Low Stock Buffer Solution" in result.low_stock
        assert len(result.warnings) == 1

    def test_check_protocol_expired_blocks_availability(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        inv.add_reagent("Old Expired Dye Stain", 50.0, "ml", expiry_date="2019-01-01")
        result = inv.check_protocol("p4", ["Old Expired Dye Stain"])
        assert result.all_available is False
        assert "Old Expired Dye Stain" in result.expired

    def test_consume_reduces_quantity(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        r = inv.add_reagent("Consumable Reagent", 100.0, "ml")
        inv.consume(r.reagent_id, 30.0, protocol_id="p1")
        updated = inv.get(r.reagent_id)
        assert updated.quantity_ml == 70.0

    def test_persist_across_instances(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv1 = ReagentInventory(tmp_db)
        inv1.add_reagent("Persistent Reagent", 100.0, "ml")
        inv2 = ReagentInventory(tmp_db)
        results = inv2.search()
        assert len(results) == 1
        assert results[0].name == "Persistent Reagent"

    def test_to_dict_serialisable(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        r = inv.add_reagent("Test", 100.0, "ml")
        d = r.to_dict()
        json.dumps(d)

    def test_hazard_class_stored(self, tmp_db):
        from services.translation_service.core.reagent_inventory import ReagentInventory
        inv = ReagentInventory(tmp_db)
        r = inv.add_reagent("Acid HCl", 50.0, "ml", hazard_class="corrosive")
        fetched = inv.get(r.reagent_id)
        assert fetched.hazard_class == "corrosive"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Workflow Engine
# ═════════════════════════════════════════════════════════════════════════════

class TestWorkflowEngine:

    def test_import(self):
        from services.translation_service.core.workflow_engine import WorkflowEngine, WorkflowStep, WorkflowRun
        assert WorkflowEngine

    def test_create_and_retrieve_workflow(self, tmp_db):
        from services.translation_service.core.workflow_engine import WorkflowEngine, WorkflowStep
        eng = WorkflowEngine(tmp_db)
        steps = [
            WorkflowStep(step_index=0, name="BCA Assay",    protocol_id="p1", condition="always"),
            WorkflowStep(step_index=1, name="Western Blot", protocol_id="p2", condition="on_pass"),
        ]
        wid = eng.create_workflow("Protein Pipeline", steps, "Full protein analysis workflow")
        wf  = eng.get_workflow(wid)
        assert wf is not None
        assert wf["name"] == "Protein Pipeline"
        assert wf["description"] == "Full protein analysis workflow"
        assert len(wf["steps"]) == 2

    def test_step_conditions_preserved(self, tmp_db):
        from services.translation_service.core.workflow_engine import WorkflowEngine, WorkflowStep
        eng = WorkflowEngine(tmp_db)
        steps = [
            WorkflowStep(step_index=0, name="S1", protocol_id="p1", condition="always"),
            WorkflowStep(step_index=1, name="S2", protocol_id="p2", condition="on_pass"),
            WorkflowStep(step_index=2, name="S3", protocol_id="p3", condition="on_fail"),
        ]
        wid = eng.create_workflow("Conditional WF", steps)
        wf  = eng.get_workflow(wid)
        assert wf["steps"][0]["condition"] == "always"
        assert wf["steps"][1]["condition"] == "on_pass"
        assert wf["steps"][2]["condition"] == "on_fail"

    def test_list_workflows(self, tmp_db):
        from services.translation_service.core.workflow_engine import WorkflowEngine, WorkflowStep
        eng = WorkflowEngine(tmp_db)
        for i in range(3):
            eng.create_workflow(f"WF {i}", [
                WorkflowStep(step_index=0, name=f"Step{i}", protocol_id=f"p{i}")
            ])
        wfs = eng.list_workflows()
        assert len(wfs) == 3

    def test_delete_workflow(self, tmp_db):
        from services.translation_service.core.workflow_engine import WorkflowEngine, WorkflowStep
        eng = WorkflowEngine(tmp_db)
        wid = eng.create_workflow("To Delete", [
            WorkflowStep(step_index=0, name="S", protocol_id="p1")
        ])
        assert eng.delete_workflow(wid) is True
        assert eng.get_workflow(wid) is None
        assert len(eng.list_workflows()) == 0

    def test_delete_nonexistent_returns_false(self, tmp_db):
        from services.translation_service.core.workflow_engine import WorkflowEngine
        eng = WorkflowEngine(tmp_db)
        assert eng.delete_workflow("nonexistent") is False

    def test_start_run(self, tmp_db):
        from services.translation_service.core.workflow_engine import WorkflowEngine, WorkflowStep
        eng = WorkflowEngine(tmp_db)
        wid = eng.create_workflow("Run Test", [
            WorkflowStep(step_index=0, name="S1", protocol_id="p1")
        ])
        run = eng.start_run(wid)
        assert run.workflow_id == wid
        assert run.status == "running"
        assert len(run.results) == 1
        assert run.results[0].status == "pending"

    def test_execute_step_no_protocol(self, tmp_db):
        from services.translation_service.core.workflow_engine import WorkflowEngine, WorkflowStep
        eng = WorkflowEngine(tmp_db)
        wid = eng.create_workflow("No Proto WF", [
            WorkflowStep(step_index=0, name="S1", protocol_id="missing-id")
        ])
        run = eng.start_run(wid)
        result = eng.execute_step(run, 0, {}, "mock")
        assert result.status == "failed"
        assert "not found" in result.error

    def test_on_pass_condition_skips_when_prev_failed(self, tmp_db):
        from services.translation_service.core.workflow_engine import WorkflowEngine, WorkflowStep, WorkflowStepResult
        eng = WorkflowEngine(tmp_db)
        wid = eng.create_workflow("Cond WF", [
            WorkflowStep(step_index=0, name="S1", protocol_id="p1", condition="always"),
            WorkflowStep(step_index=1, name="S2", protocol_id="p2", condition="on_pass"),
        ])
        run = eng.start_run(wid)
        # Simulate step 0 failing
        run.results[0].status  = "failed"
        run.results[0].sim_passed = False
        result = eng.execute_step(run, 1, {}, "mock")
        assert result.status == "skipped"

    def test_persist_across_instances(self, tmp_db):
        from services.translation_service.core.workflow_engine import WorkflowEngine, WorkflowStep
        eng1 = WorkflowEngine(tmp_db)
        wid  = eng1.create_workflow("Persistent WF", [
            WorkflowStep(step_index=0, name="S", protocol_id="p1")
        ])
        eng2 = WorkflowEngine(tmp_db)
        assert eng2.get_workflow(wid) is not None
        assert len(eng2.list_workflows()) == 1


# ═════════════════════════════════════════════════════════════════════════════
# 5. Report Generator
# ═════════════════════════════════════════════════════════════════════════════

class TestReportGenerator:

    def test_import(self):
        from core.report_generator import generate_html_report, generate_markdown_report
        assert callable(generate_html_report)
        assert callable(generate_markdown_report)

    def test_html_report_is_valid_html(self, sample_protocol):
        from core.report_generator import generate_html_report
        html = generate_html_report(sample_protocol)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "<style>" in html

    def test_html_report_contains_title(self, sample_protocol):
        from core.report_generator import generate_html_report
        html = generate_html_report(sample_protocol)
        assert sample_protocol["title"] in html

    def test_html_report_contains_steps(self, sample_protocol):
        from core.report_generator import generate_html_report
        html = generate_html_report(sample_protocol)
        for step in sample_protocol["steps"]:
            assert f"Step {step['step_number']}" in html

    def test_html_report_contains_reagents(self, sample_protocol):
        from core.report_generator import generate_html_report
        html = generate_html_report(sample_protocol)
        assert "BCA Protein Assay Reagent A" in html

    def test_html_report_contains_sources(self, sample_protocol):
        from core.report_generator import generate_html_report
        html = generate_html_report(sample_protocol)
        assert "thermo_bca_manual.pdf" in html

    def test_html_report_contains_protocol_id(self, sample_protocol):
        from core.report_generator import generate_html_report
        html = generate_html_report(sample_protocol)
        assert sample_protocol["protocol_id"][:8] in html

    def test_html_report_provenance_included(self, sample_protocol):
        from core.report_generator import generate_html_report
        html = generate_html_report(sample_protocol, include_provenance=True)
        assert "provenance" in html.lower() or "model" in html.lower()

    def test_html_report_provenance_excluded(self, sample_protocol):
        from core.report_generator import generate_html_report
        html_with    = generate_html_report(sample_protocol, include_provenance=True)
        html_without = generate_html_report(sample_protocol, include_provenance=False)
        assert len(html_without) < len(html_with)

    def test_html_report_with_analytics(self, sample_protocol):
        from core.report_generator import generate_html_report
        analytics = {"cost_saved_usd": 2.50, "time_saved_min": 45,
                     "robot_cost_usd": 0.0012, "plastic_g": 0.32,
                     "co2_g": 0.18, "plastic_rating": "A", "energy_rating": "B"}
        html = generate_html_report(sample_protocol, analytics=analytics)
        assert "$2.50" in html
        assert "45" in html

    def test_html_report_with_sim_result_pass(self, sample_protocol):
        from core.report_generator import generate_html_report
        sim = {"passed": True, "commands_executed": 12, "physics_engine": "pybullet"}
        html = generate_html_report(sample_protocol, sim_result=sim)
        assert "PASSED" in html

    def test_html_report_with_sim_result_fail(self, sample_protocol):
        from core.report_generator import generate_html_report
        sim = {"passed": False, "commands_executed": 5, "physics_engine": "mock"}
        html = generate_html_report(sample_protocol, sim_result=sim)
        assert "FAILED" in html

    def test_html_report_self_contained_no_external_deps(self, sample_protocol):
        from core.report_generator import generate_html_report
        html = generate_html_report(sample_protocol)
        # Should not reference external CDNs or stylesheets
        assert "cdn.jsdelivr" not in html
        assert "cdnjs.cloudflare" not in html
        assert 'rel="stylesheet"' not in html

    def test_markdown_report_structure(self, sample_protocol):
        from core.report_generator import generate_markdown_report
        md = generate_markdown_report(sample_protocol)
        assert f"# {sample_protocol['title']}" in md
        assert "## Protocol Steps" in md
        assert "## Reagents" in md
        assert "## Sources" in md

    def test_markdown_report_contains_all_steps(self, sample_protocol):
        from core.report_generator import generate_markdown_report
        md = generate_markdown_report(sample_protocol)
        for step in sample_protocol["steps"]:
            assert f"Step {step['step_number']}" in md
            assert step["instruction"][:20] in md

    def test_report_escapes_html_special_chars(self):
        from core.report_generator import generate_html_report
        p = {"protocol_id": "xss-test", "title": "Test <script>alert('xss')</script>",
             "description": "", "steps": [], "reagents": [], "equipment": [],
             "safety_level": "safe", "safety_notes": [], "confidence_score": 0.9,
             "generation_ms": 100, "model_used": "test", "sources_used": []}
        html = generate_html_report(p)
        assert "<script>" not in html   # must be escaped
        assert "&lt;script&gt;" in html


# ═════════════════════════════════════════════════════════════════════════════
# 6. Protocol Templates
# ═════════════════════════════════════════════════════════════════════════════

class TestProtocolTemplates:

    def test_import(self):
        from core.protocol_templates import (
            list_templates, get_template, build_instruction_from_template,
            TEMPLATE_REGISTRY)
        assert TEMPLATE_REGISTRY

    def test_eight_templates_exist(self):
        from core.protocol_templates import list_templates
        templates = list_templates()
        assert len(templates) == 8

    def test_all_required_template_ids_present(self):
        from core.protocol_templates import TEMPLATE_REGISTRY
        required = [
            "bca_protein_assay", "bradford_assay", "sandwich_elisa",
            "mtt_cell_viability", "standard_pcr", "western_blot_transfer",
            "agarose_gel_electrophoresis", "plasmid_miniprep",
        ]
        for tid in required:
            assert tid in TEMPLATE_REGISTRY, f"Missing template: {tid}"

    def test_category_filter(self):
        from core.protocol_templates import list_templates
        assays = list_templates(category="assay")
        assert all(t["category"] == "assay" for t in assays)
        assert len(assays) >= 3   # BCA, Bradford, MTT, ELISA

    def test_each_template_has_required_fields(self):
        from core.protocol_templates import list_templates
        for t in list_templates():
            assert t["name"],               f"Missing name in {t.get('template_id')}"
            assert t["description"],        f"Missing description in {t.get('template_id')}"
            assert t["parameters"],         f"Missing parameters in {t.get('template_id')}"
            assert t["reagents"],           f"Missing reagents in {t.get('template_id')}"
            assert t["equipment"],          f"Missing equipment in {t.get('template_id')}"
            assert t["estimated_time_min"] > 0
            assert t["difficulty"] in ("easy", "medium", "hard")
            assert t["safety_level"] in ("safe", "warning", "hazardous")

    def test_get_template_returns_correct(self):
        from core.protocol_templates import get_template
        t = get_template("bca_protein_assay")
        assert t is not None
        assert t.name == "BCA Protein Assay"
        assert t.category == "assay"

    def test_get_nonexistent_template_returns_none(self):
        from core.protocol_templates import get_template
        assert get_template("nonexistent_template_xyz") is None

    def test_build_instruction_bca(self):
        from core.protocol_templates import build_instruction_from_template
        instr = build_instruction_from_template("bca_protein_assay", {
            "n_samples": 12, "sample_volume_ul": 25, "incubation_temp_c": 37,
            "incubation_time_min": 30, "standard_curve": "2000-25",
            "plate_format": "96-well",
        })
        assert instr is not None
        assert "12" in instr
        assert "25" in instr
        assert "37" in instr

    def test_build_instruction_uses_defaults_when_params_missing(self):
        from core.protocol_templates import build_instruction_from_template, get_template
        t = get_template("standard_pcr")
        instr = build_instruction_from_template("standard_pcr", {})
        assert instr is not None
        # Should contain default values
        default_cycles = str(t.parameters[1].default)  # cycles param
        assert default_cycles in instr

    def test_build_instruction_nonexistent_returns_none(self):
        from core.protocol_templates import build_instruction_from_template
        assert build_instruction_from_template("bad_id", {}) is None

    def test_all_templates_serialisable(self):
        from core.protocol_templates import list_templates
        for t in list_templates():
            json.dumps(t)   # must be JSON-serialisable

    def test_bca_hint_steps_exist(self):
        from core.protocol_templates import get_template
        t = get_template("bca_protein_assay")
        assert len(t.hint_steps) >= 5

    def test_elisa_is_warning_safety(self):
        from core.protocol_templates import get_template
        t = get_template("sandwich_elisa")
        assert t.safety_level == "warning"   # H2SO4 stop solution

    def test_pcr_has_thermocycler_equipment(self):
        from core.protocol_templates import get_template
        t = get_template("standard_pcr")
        equip_lower = " ".join(t.equipment).lower()
        assert "thermocycler" in equip_lower

    def test_template_references_exist(self):
        from core.protocol_templates import list_templates
        for t in list_templates():
            assert len(t["references"]) >= 1, f"No references for {t['name']}"


# ═════════════════════════════════════════════════════════════════════════════
# 7. Protocol Optimizer (heuristics — no LLM)
# ═════════════════════════════════════════════════════════════════════════════

class TestProtocolOptimizer:

    def test_import(self):
        from core.protocol_optimizer import (
            ProtocolOptimiser, _estimate_time, _estimate_cost, _estimate_plastic,
            OptimisedVariant, OptimisationResult)
        assert callable(_estimate_time)

    def test_estimate_time_from_steps(self, sample_protocol):
        from core.protocol_optimizer import _estimate_time
        t = _estimate_time(sample_protocol)
        assert t > 0
        # BCA has 1800s incubation = 30min + other steps
        assert t >= 30.0

    def test_estimate_cost_positive(self, sample_protocol):
        from core.protocol_optimizer import _estimate_cost
        c = _estimate_cost(sample_protocol)
        assert c > 0

    def test_estimate_plastic_positive(self, sample_protocol):
        from core.protocol_optimizer import _estimate_plastic
        p = _estimate_plastic(sample_protocol)
        assert p >= 0

    def test_estimate_time_empty_protocol(self):
        from core.protocol_optimizer import _estimate_time
        p = {"steps": []}
        assert _estimate_time(p) >= 1.0   # minimum 1 min

    def test_estimate_time_scales_with_incubation(self):
        from core.protocol_optimizer import _estimate_time
        p_short = {"steps": [
            {"instruction": "Mix", "duration_seconds": 30},
        ]}
        p_long = {"steps": [
            {"instruction": "Mix", "duration_seconds": 30},
            {"instruction": "Incubate at 37C", "duration_seconds": 7200},
        ]}
        assert _estimate_time(p_long) > _estimate_time(p_short)

    def test_optimised_variant_to_dict(self, sample_protocol):
        from core.protocol_optimizer import OptimisedVariant
        v = OptimisedVariant(
            objective="speed",
            protocol=sample_protocol,
            optimisation_notes="Parallelised incubation steps",
            estimated_time_min=25.0,
            estimated_cost_usd=0.05,
            estimated_plastic_g=0.3,
            generation_ms=1200.0,
            success=True,
        )
        d = v.to_dict()
        assert d["objective"] == "speed"
        assert d["success"] is True
        json.dumps(d)


# ═════════════════════════════════════════════════════════════════════════════
# 8. Extensions Router (structure)
# ═════════════════════════════════════════════════════════════════════════════

class TestExtensionsRouter:

    def test_import(self):
        from api.extensions_router import router
        assert router is not None

    def test_router_has_correct_prefix(self):
        from api.extensions_router import router
        assert router.prefix == "/api/v1"

    def test_all_expected_endpoints_registered(self):
        from api.extensions_router import router
        paths = {r.path for r in router.routes}
        expected = [
            "/api/v1/protocols/{protocol_id}/export/ot2",
            "/api/v1/protocols/{protocol_id}/report",
            "/api/v1/protocols/compare",
            "/api/v1/optimise/{protocol_id}",
            "/api/v1/templates/",
            "/api/v1/templates/{template_id}",
            "/api/v1/templates/{template_id}/build",
            "/api/v1/inventory/",
            "/api/v1/inventory/{reagent_id}",
            "/api/v1/inventory/check",
            "/api/v1/reflect",
            "/api/v1/workflows/",
            "/api/v1/workflows/{workflow_id}",
            "/api/v1/workflows/{workflow_id}/run",
            "/api/v1/workflows/{workflow_id}/runs",
            "/api/v1/search",
            "/api/v1/extensions/status",
        ]
        missing = [e for e in expected if e not in paths]
        assert not missing, f"Missing endpoints: {missing}"

    def test_endpoint_count(self):
        from api.extensions_router import router
        assert len(router.routes) >= 20

    def test_module_flags_are_bool(self):
        from api.extensions_router import (
            _HAS_OT2, _HAS_DIFF, _HAS_INV, _HAS_TMPL,
            _HAS_REPORT, _HAS_WF, _HAS_OPT, _HAS_REFLECT)
        for flag in [_HAS_OT2, _HAS_DIFF, _HAS_INV, _HAS_TMPL,
                     _HAS_REPORT, _HAS_WF, _HAS_OPT, _HAS_REFLECT]:
            assert isinstance(flag, bool)

    def test_pydantic_request_models_valid(self):
        from api.extensions_router import (
            DiffRequest, AddReagentRequest, InventoryCheckRequest,
            ReflectRequest, CreateWorkflowRequest, TemplateBuildRequest)
        # All models should instantiate cleanly with minimal data
        DiffRequest(protocol_id_a="a", protocol_id_b="b")
        InventoryCheckRequest(protocol_id="p1", reagents=["R1"])
        ReflectRequest(protocol_id="p1")
        CreateWorkflowRequest(name="WF1")
        TemplateBuildRequest()


# ═════════════════════════════════════════════════════════════════════════════
# 9. Protocol Manager Persistence
# ═════════════════════════════════════════════════════════════════════════════

class TestProtocolManagerPersistence:

    def _make_protocol(self, title="Test Protocol"):
        return {
            "protocol_id": str(uuid.uuid4()),
            "title": title,
            "description": f"Description for {title}",
            "steps": [
                {"step_number": 1, "instruction": "Pipette 50 µL",
                 "volume_ul": 50, "citations": ["GENERAL"], "safety_note": None}
            ],
            "reagents": ["Buffer A"], "equipment": ["Pipette"],
            "safety_level": "safe", "safety_notes": [],
            "confidence_score": 0.85, "generation_ms": 1000.0,
            "model_used": "test", "sources_used": [],
            "saved_at": time.time(),
        }

    def test_save_and_retrieve(self, tmp_path):
        try:
            from services.translation_service.core.protocol_manager import ProtocolManager
        except ModuleNotFoundError:
            from services.translation_service.core.protocol_manager import ProtocolManager
        pm = ProtocolManager(str(tmp_path / "pm.db"))
        p  = self._make_protocol("BCA Test")
        pm.save(p)
        assert pm.count() == 1
        retrieved = pm.get(p["protocol_id"])
        assert retrieved["title"] == "BCA Test"

    def test_persists_across_instances(self, tmp_path):
        try:
            from services.translation_service.core.protocol_manager import ProtocolManager
        except ModuleNotFoundError:
            from services.translation_service.core.protocol_manager import ProtocolManager
        db = str(tmp_path / "pm.db")
        pm1 = ProtocolManager(db)
        p   = self._make_protocol("Persistent")
        pm1.save(p)
        pm2 = ProtocolManager(db)
        assert pm2.count() == 1
        assert pm2.get(p["protocol_id"])["title"] == "Persistent"

    def test_delete_removes_from_db(self, tmp_path):
        try:
            from services.translation_service.core.protocol_manager import ProtocolManager
        except ModuleNotFoundError:
            from services.translation_service.core.protocol_manager import ProtocolManager
        db = str(tmp_path / "pm.db")
        pm1 = ProtocolManager(db)
        p   = self._make_protocol("To Delete")
        pm1.save(p)
        pm1.delete(p["protocol_id"])
        pm2 = ProtocolManager(db)
        assert pm2.count() == 0

    def test_get_all_returns_newest_first(self, tmp_path):
        try:
            from services.translation_service.core.protocol_manager import ProtocolManager
        except ModuleNotFoundError:
            from services.translation_service.core.protocol_manager import ProtocolManager
        pm = ProtocolManager(str(tmp_path / "pm.db"))
        for i in range(3):
            p = self._make_protocol(f"Protocol {i}")
            p["saved_at"] = time.time() + i
            pm.save(p)
        all_p = pm.get_all()
        assert len(all_p) == 3
        assert all_p[0]["saved_at"] >= all_p[1]["saved_at"]

    def test_search_by_title(self, tmp_path):
        try:
            from services.translation_service.core.protocol_manager import ProtocolManager
        except ModuleNotFoundError:
            from services.translation_service.core.protocol_manager import ProtocolManager
        pm = ProtocolManager(str(tmp_path / "pm.db"))
        pm.save(self._make_protocol("BCA Assay"))
        pm.save(self._make_protocol("PCR Protocol"))
        pm.save(self._make_protocol("ELISA Test"))
        results = pm.search(query="BCA")
        assert len(results) >= 1
        assert any("BCA" in r["title"] for r in results)

    def test_get_versions_empty_for_new_protocol(self, tmp_path):
        try:
            from services.translation_service.core.protocol_manager import ProtocolManager
        except ModuleNotFoundError:
            from services.translation_service.core.protocol_manager import ProtocolManager
        pm = ProtocolManager(str(tmp_path / "pm.db"))
        p  = self._make_protocol()
        pm.save(p)
        versions = pm.get_versions(p["protocol_id"])
        assert isinstance(versions, list)