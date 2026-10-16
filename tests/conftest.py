"""
tests/conftest.py — pytest configuration for AuroLab.
Works on Windows with services/ layout.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Path setup: add project root so services.* resolves ──────────────────────
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db_path(tmp_path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture
def sample_protocol() -> dict:
    return {
        "protocol_id":     str(uuid.uuid4()),
        "title":           "BCA Protein Assay",
        "description":     "Standard BCA assay for protein quantification.",
        "steps": [
            {"step_number": 1,
             "instruction": "Pipette 50 µL BCA reagent from slot 1 well A1 to slot 2 well B1",
             "volume_ul": 50.0, "citations": ["SOURCE_1"], "safety_note": None,
             "duration_seconds": None, "temperature_celsius": None},
            {"step_number": 2,
             "instruction": "Incubate at 37°C for 30 minutes",
             "volume_ul": None, "citations": ["SOURCE_1"], "safety_note": None,
             "duration_seconds": 1800, "temperature_celsius": 37.0},
            {"step_number": 3,
             "instruction": "Read absorbance at 562 nm",
             "volume_ul": None, "citations": ["GENERAL"], "safety_note": None,
             "duration_seconds": 120, "temperature_celsius": None},
        ],
        "reagents":      ["BCA Reagent A", "BSA standard 2 mg/mL", "PBS"],
        "equipment":     ["96-well plate", "plate reader", "incubator", "P300 pipette"],
        "safety_level":  "safe",
        "safety_notes":  [],
        "sources_used":  [
            {"source_id": "SOURCE_1", "filename": "bca_manual.pdf",
             "section": "Protocol", "page_start": 5, "score": 0.95}
        ],
        "confidence_score": 0.92,
        "generation_ms":    1250.0,
        "model_used":       "llama-3.3-70b-versatile",
    }


@pytest.fixture
def sample_commands() -> list[dict]:
    return [
        {"command_type": "home",            "command_index": 0, "protocol_step_ref": 0},
        {"command_type": "pick_up_tip",     "command_index": 1, "protocol_step_ref": 1, "tip_rack_slot": 11},
        {"command_type": "aspirate",        "command_index": 2, "protocol_step_ref": 1,
         "volume_ul": 50.0, "source": {"deck_slot": 1}, "flow_rate_ul_s": 150.0},
        {"command_type": "dispense",        "command_index": 3, "protocol_step_ref": 1,
         "volume_ul": 50.0, "destination": {"deck_slot": 2}},
        {"command_type": "drop_tip",        "command_index": 4, "protocol_step_ref": 1},
        {"command_type": "incubate",        "command_index": 5, "protocol_step_ref": 2,
         "duration_s": 1800, "temperature_celsius": 37.0, "slot": 7},
        {"command_type": "read_absorbance", "command_index": 6, "protocol_step_ref": 3,
         "wavelength_nm": 562, "slot": 3},
        {"command_type": "home",            "command_index": 7, "protocol_step_ref": 3},
    ]


@pytest.fixture
def sample_plan(sample_commands) -> dict:
    return {
        "plan_id":        "plan-fixture-001",
        "protocol_id":    "test-proto-fixture",
        "protocol_title": "BCA Protein Assay",
        "estimated_mins": 45.0,
        "estimated_total_duration_s": 2700.0,
        "status":         "sim_passed",
        "command_count":  len(sample_commands),
        "command_breakdown": {
            "home": 2, "pick_up_tip": 1, "aspirate": 1,
            "dispense": 1, "drop_tip": 1, "incubate": 1, "read_absorbance": 1,
        },
        "validation_errors": 0,
        "sim_passed":    True,
        "is_executable": True,
        "commands":      sample_commands,
    }


@pytest.fixture
def sample_telemetry() -> dict:
    return {
        "commands_executed":         8,
        "tip_changes":               1,
        "total_volume_aspirated_ul": 50.0,
        "total_volume_dispensed_ul": 48.0,
        "total_distance_mm":         1200.0,
        "warnings":                  [],
        "physics_engine":            "mock_fallback",
    }


@pytest.fixture
def mock_rag_engine():
    engine = MagicMock()
    result = MagicMock()
    result.chunks = []
    result.retrieval_ms = 45.0
    engine.retrieve.return_value = result
    engine.collection_stats.return_value = {
        "collection": "aurolab_protocols", "total_chunks": 0,
        "embed_model": "all-MiniLM-L6-v2",
        "hyde_enabled": False, "reranker_enabled": False,
    }
    engine.ingest_chunks.return_value = {"added": 5, "skipped": 0}
    return engine


@pytest.fixture
def mock_llm_engine(mock_rag_engine):
    valid_json = json.dumps({
        "title": "BCA Protein Assay", "description": "Standard BCA assay.",
        "reagents": ["BCA Reagent A", "BSA standard"],
        "equipment": ["96-well plate", "plate reader"],
        "steps": [
            {"step_number": 1, "instruction": "Pipette 25 µL into each well.",
             "duration_seconds": None, "temperature_celsius": None,
             "volume_ul": 25.0, "citations": ["SOURCE_1"], "safety_note": None},
            {"step_number": 2, "instruction": "Incubate at 37°C for 30 min.",
             "duration_seconds": 1800, "temperature_celsius": 37.0,
             "volume_ul": None, "citations": ["SOURCE_1"], "safety_note": None},
        ],
        "safety_notes": [], "confidence_score": 0.88,
    })
    engine = MagicMock()
    engine.generate.return_value = valid_json
    engine._call_with_retry.return_value = valid_json
    engine._model = "llama-3.3-70b-versatile"
    engine.rag_engine = mock_rag_engine
    return engine


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "integration: end-to-end integration tests")
    config.addinivalue_line("markers", "pybullet: requires pybullet installed")
    config.addinivalue_line("markers", "live_api: requires real Groq API key")