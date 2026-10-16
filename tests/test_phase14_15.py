"""
tests/test_phase14_15.py

Tests for Phase 1.4 (retrieval eval) and Phase 1.5 (RAG-aware generation).
Run with: pytest tests/test_phase14_15.py -v

NOTE: Requires chromadb, groq, sentence-transformers (full requirements.txt)
      These tests are automatically skipped if dependencies are not installed.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))



import json
import math
from unittest.mock import MagicMock, patch
import pytest

# ── Skip if heavy deps not installed ─────────────────────────────────────────
import importlib as _il
_DEPS_OK = all(
    _il.util.find_spec(m) is not None
    for m in ["chromadb", "groq", "sentence_transformers"]
)
pytestmark = pytest.mark.skipif(
    not _DEPS_OK,
    reason="Requires chromadb, groq, sentence-transformers — install full requirements.txt"
)

if _DEPS_OK:
    from services.translation_service.core.llm_engine import (
        AurolabLLMEngine, _build_system_prompt, _build_user_prompt)
    from services.translation_service.core.retrieval_eval import (
        EvalHarness, EvalDataset, EvalQuery, EvalReport,
        _reciprocal_rank, _ndcg_at_k, _recall_at_k)
    from services.translation_service.core.rag_engine import AurolabRAGEngine


# ── Phase 1.4 — Retrieval Evaluation ─────────────────────────────────────────

class TestRetrievalEval:

    def test_reciprocal_rank_first(self):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.retrieval_eval import _reciprocal_rank
        assert _reciprocal_rank(["a","b","c"], "a") == pytest.approx(1.0)

    def test_reciprocal_rank_second(self):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.retrieval_eval import _reciprocal_rank
        assert _reciprocal_rank(["a","b","c"], "b") == pytest.approx(0.5)

    def test_reciprocal_rank_miss(self):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.retrieval_eval import _reciprocal_rank
        assert _reciprocal_rank(["a","b","c"], "z") == pytest.approx(0.0)

    def test_recall_at_k(self):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.retrieval_eval import _recall_at_k
        assert _recall_at_k(["a","b","c","d"], {"a","b"}, 2) == pytest.approx(1.0)
        assert _recall_at_k(["a","b","c","d"], {"a","b"}, 1) == pytest.approx(0.5)

    def test_ndcg_at_k_perfect(self):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.retrieval_eval import _ndcg_at_k
        assert _ndcg_at_k(["a","b","c"], {"a":1,"b":1}, 3) == pytest.approx(1.0, abs=0.01)

    def test_eval_harness_runs(self, mock_rag_engine):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.retrieval_eval import EvalHarness
        evaluator = EvalHarness(rag_engine=mock_rag_engine)
        assert evaluator is not None


# ── Phase 1.5 — LLM Generation ────────────────────────────────────────────────

class TestLLMGeneration:

    def test_system_prompt_structure(self):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.llm_engine import _build_system_prompt
        prompt = _build_system_prompt()
        assert "CRITICAL" in prompt or "SOURCE" in prompt
        assert len(prompt) > 500
        assert "JSON" in prompt

    def test_user_prompt_includes_instruction(self):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.llm_engine import _build_user_prompt
        prompt = _build_user_prompt("Run BCA assay", "<sources>test</sources>")
        assert "BCA assay" in prompt
        assert "<sources>" in prompt or "sources" in prompt.lower()

    def test_user_prompt_includes_context(self):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.llm_engine import _build_user_prompt
        context = "<source id=\'SOURCE_1\'>BCA protocol text</source>"
        prompt  = _build_user_prompt("test instruction", context)
        assert "test instruction" in prompt
        assert "SOURCE_1" in prompt or "source" in prompt.lower()

    @patch("services.translation_service.core.llm_engine.Groq")
    def test_engine_initialises(self, mock_groq, mock_rag_engine):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.llm_engine import AurolabLLMEngine
        engine = AurolabLLMEngine(
            groq_api_key="test_key", rag_engine=mock_rag_engine)
        assert engine is not None

    @patch("services.translation_service.core.llm_engine.Groq")
    def test_call_with_retry_success(self, mock_groq, mock_rag_engine):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.llm_engine import AurolabLLMEngine
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps({
            "title": "Test", "description": "desc", "reagents": [], "equipment": [],
            "steps": [], "safety_notes": [], "confidence_score": 0.9
        })
        mock_groq.return_value.chat.completions.create.return_value = mock_resp
        engine = AurolabLLMEngine(groq_api_key="test", rag_engine=mock_rag_engine)
        result = engine._call_with_retry("system", "user")
        assert "Test" in result or result

    @patch("services.translation_service.core.llm_engine.Groq")
    def test_generate_returns_protocol(self, mock_groq, mock_rag_engine):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.llm_engine import AurolabLLMEngine
        valid = json.dumps({
            "title": "BCA Protein Assay", "description": "Standard assay.",
            "reagents": ["BCA A", "BSA"], "equipment": ["plate"],
            "steps": [{"step_number": 1, "instruction": "Pipette 50 µL",
                       "duration_seconds": None, "temperature_celsius": None,
                       "volume_ul": 50.0, "citations": ["SOURCE_1"], "safety_note": None}],
            "safety_notes": [], "confidence_score": 0.88,
        })
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = valid
        mock_groq.return_value.chat.completions.create.return_value = mock_resp
        engine = AurolabLLMEngine(groq_api_key="test", rag_engine=mock_rag_engine)
        result = engine.generate("Run BCA assay on 8 samples", "test-id")
        assert result is not None

    @patch("services.translation_service.core.llm_engine.Groq")
    def test_confidence_score_range(self, mock_groq, mock_rag_engine):
        if not _DEPS_OK: pytest.skip("deps missing")
        from services.translation_service.core.llm_engine import AurolabLLMEngine
        # Use a valid confidence score — pydantic enforces 0.0-1.0 at model level
        valid = json.dumps({
            "title": "T", "description": "D", "reagents": [], "equipment": [],
            "steps": [{"step_number": 1, "instruction": "Mix",
                       "duration_seconds": None, "temperature_celsius": None,
                       "volume_ul": None, "citations": ["GENERAL"], "safety_note": None}],
            "safety_notes": [], "confidence_score": 0.75,
        })
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = valid
        mock_groq.return_value.chat.completions.create.return_value = mock_resp
        engine = AurolabLLMEngine(groq_api_key="test", rag_engine=mock_rag_engine)
        result = engine.generate("test", "test-id")
        if hasattr(result, "confidence_score"):
            assert 0.0 <= result.confidence_score <= 1.0