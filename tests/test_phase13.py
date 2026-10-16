"""
tests/test_phase13.py

Integration tests for Phase 1.3 — PDF parsing, chunking, and RAG retrieval.
Run with: pytest tests/test_phase13.py -v
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).parent.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import hashlib
from unittest.mock import MagicMock, patch

import pytest

# ── Dependency guard ──────────────────────────────────────────────────────────
import importlib as _il
_DEPS_OK = all(
    _il.util.find_spec(m) is not None
    for m in ["chromadb", "sentence_transformers"]
)
pytestmark = pytest.mark.skipif(
    not _DEPS_OK,
    reason="Requires chromadb + sentence-transformers — install full requirements.txt"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_blocks():
    from services.translation_service.core.pdf_parser import ContentBlock, BlockType
    return [
        ContentBlock(BlockType.HEADING,   "1. Materials",     page_number=1, font_size=14.0, is_bold=True),
        ContentBlock(BlockType.TEXT,
                     "BCA Reagent A and Reagent B. BSA standard at 2 mg/mL. PBS pH 7.4. 96-well plate.",
                     page_number=1),
        ContentBlock(BlockType.HEADING,   "2. Protocol",      page_number=2, font_size=14.0, is_bold=True),
        ContentBlock(BlockType.TEXT,
                     "Pipette 25 µL of sample into each well. "
                     "Add 200 µL of BCA Working Reagent. "
                     "Incubate at 37°C for 30 minutes. "
                     "Cool to room temperature. Measure absorbance at 562 nm.",
                     page_number=2),
        ContentBlock(BlockType.TEXT,
                     "Calculate protein concentration from the standard curve. "
                     "A260/A280 ratio should be 1.8 to 2.0 for pure protein.",
                     page_number=3),
    ]

def _make_parsed_doc():
    from services.translation_service.core.pdf_parser import ParsedDocument
    blocks = _make_blocks()
    raw_text = " ".join(b.content for b in blocks)
    return ParsedDocument(
        source_path="test_bca_protocol.pdf",
        sha256=hashlib.sha256(b"test_content").hexdigest(),
        page_count=3,
        title="BCA Protein Assay Protocol",
        authors=[],
        doc_type="protocol",
        blocks=blocks,
        raw_text=raw_text,
        parse_strategy="pymupdf",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PDF Parser Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPDFParser:

    def test_parsed_doc_construction(self):
        doc = _make_parsed_doc()
        assert doc.source_path == "test_bca_protocol.pdf"
        assert doc.doc_type == "protocol"
        assert doc.page_count == 3
        assert len(doc.blocks) == 5
        assert doc.sha256

    def test_parsed_doc_sections_have_text(self):
        doc = _make_parsed_doc()
        for block in doc.blocks:
            assert block.content
            assert len(block.content) > 0

    def test_parsed_doc_sha256_is_hex(self):
        doc = _make_parsed_doc()
        assert len(doc.sha256) == 64
        int(doc.sha256, 16)  # must be valid hex

    def test_parsed_doc_parse_strategy(self):
        doc = _make_parsed_doc()
        assert doc.parse_strategy in ("pymupdf", "unstructured", "fallback")


# ═══════════════════════════════════════════════════════════════════════════════
# Chunker Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestChunker:

    def test_chunk_returns_list(self):
        from services.translation_service.core.chunker import chunk_document
        doc = _make_parsed_doc()
        chunks = chunk_document(doc, max_tokens=300, overlap_tokens=30)
        assert isinstance(chunks, list)
        assert len(chunks) >= 1

    def test_chunks_have_text(self):
        from services.translation_service.core.chunker import chunk_document
        doc = _make_parsed_doc()
        chunks = chunk_document(doc, max_tokens=300, overlap_tokens=30)
        for chunk in chunks:
            assert chunk.text.strip(), "Chunk has empty text"

    def test_chunks_have_metadata(self):
        from services.translation_service.core.chunker import chunk_document
        doc = _make_parsed_doc()
        chunks = chunk_document(doc, max_tokens=300, overlap_tokens=30)
        for chunk in chunks:
            # Chunk stores metadata as direct fields, not in .metadata dict
            assert chunk.source == "test_bca_protocol.pdf"
            assert chunk.doc_type == "protocol"

    def test_chunk_size_respected(self):
        from services.translation_service.core.chunker import chunk_document
        doc = _make_parsed_doc()
        chunks = chunk_document(doc, max_tokens=150, overlap_tokens=20)
        for chunk in chunks:
            assert len(chunk.text) < 800, f"Chunk too large: {len(chunk.text)} chars"

    def test_smaller_chunks_produce_more_results(self):
        from services.translation_service.core.chunker import chunk_document
        doc = _make_parsed_doc()
        big = chunk_document(doc, max_tokens=1000, overlap_tokens=50)
        sml = chunk_document(doc, max_tokens=100,  overlap_tokens=10)
        assert len(sml) >= len(big)

    def test_sha256_in_metadata(self):
        from services.translation_service.core.chunker import chunk_document
        doc = _make_parsed_doc()
        chunks = chunk_document(doc, max_tokens=300, overlap_tokens=30)
        if chunks:
            # sha256 and source are direct Chunk fields
            assert chunks[0].sha256
            assert chunks[0].source

    def test_empty_doc_returns_empty_or_minimal(self):
        from services.translation_service.core.chunker   import chunk_document
        from services.translation_service.core.pdf_parser import ParsedDocument
        empty = ParsedDocument(
            source_path="empty.pdf",
            sha256=hashlib.sha256(b"empty").hexdigest(),
            page_count=1,
            title=None,
            authors=[],
            doc_type="protocol",
            blocks=[],
            raw_text="",
            parse_strategy="pymupdf",
        )
        chunks = chunk_document(empty, max_tokens=300, overlap_tokens=30)
        assert isinstance(chunks, list)


# ═══════════════════════════════════════════════════════════════════════════════
# Registry Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDocumentRegistry:

    def test_registry_is_importable(self):
        from services.translation_service.core.registry import DocumentRegistry
        assert DocumentRegistry

    def test_registry_tracks_documents(self, tmp_path):
        from services.translation_service.core.registry import DocumentRegistry
        reg = DocumentRegistry(str(tmp_path / "registry.json"))
        sha = hashlib.sha256(b"test_doc").hexdigest()
        # Not registered yet — get() returns None
        assert reg.get(sha) is None
        reg.register(sha, filename="test.pdf")
        # Now it should be registered
        assert reg.get(sha) is not None

    def test_registry_persists_across_instances(self, tmp_path):
        from services.translation_service.core.registry import DocumentRegistry
        path = str(tmp_path / "reg.json")
        sha  = hashlib.sha256(b"persist_test").hexdigest()
        reg1 = DocumentRegistry(path)
        reg1.register(sha, filename="doc.pdf")
        reg2 = DocumentRegistry(path)
        assert reg2.get(sha) is not None


# ═══════════════════════════════════════════════════════════════════════════════
# RAG Engine Tests (mocked)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRAGEngine:

    @patch("chromadb.PersistentClient")
    @patch("sentence_transformers.SentenceTransformer")
    def test_rag_engine_initialises(self, mock_st, mock_chroma):
        from services.translation_service.core.rag_engine import AurolabRAGEngine
        mock_coll = MagicMock()
        mock_coll.count.return_value = 0
        mock_coll.query.return_value = {
            "ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]
        }
        mock_chroma.return_value.get_or_create_collection.return_value = mock_coll
        mock_st.return_value.encode.return_value = [[0.1] * 384]

        # Actual signature: persist_path, groq_api_key, use_hyde, use_reranker
        engine = AurolabRAGEngine(
            persist_path="/tmp/test_chroma_1",
            groq_api_key="test_key",
            use_hyde=False,
            use_reranker=False,
        )
        assert engine is not None

    @patch("chromadb.PersistentClient")
    @patch("sentence_transformers.SentenceTransformer")
    def test_collection_stats_returns_dict(self, mock_st, mock_chroma):
        from services.translation_service.core.rag_engine import AurolabRAGEngine
        mock_coll = MagicMock()
        mock_coll.count.return_value = 42
        mock_chroma.return_value.get_or_create_collection.return_value = mock_coll
        mock_st.return_value.encode.return_value = [[0.1] * 384]

        engine = AurolabRAGEngine(
            persist_path="/tmp/test_chroma_2",
            groq_api_key="test_key",
            use_hyde=False,
            use_reranker=False,
        )
        stats = engine.collection_stats()
        assert isinstance(stats, dict)
        assert stats is not None

    @patch("chromadb.PersistentClient")
    @patch("sentence_transformers.SentenceTransformer")
    def test_retrieve_returns_result(self, mock_st, mock_chroma):
        from services.translation_service.core.rag_engine import AurolabRAGEngine
        mock_coll = MagicMock()
        mock_coll.count.return_value = 5
        mock_coll.query.return_value = {
            "ids":       [["chunk_1", "chunk_2"]],
            "documents": [["Pipette 50µL BCA reagent.", "Incubate at 37°C."]],
            "metadatas": [[
                {"source": "bca.pdf", "doc_type": "protocol",
                 "section_title": "Protocol", "page_start": 2, "sha256": "abc123"},
                {"source": "bca.pdf", "doc_type": "protocol",
                 "section_title": "Protocol", "page_start": 3, "sha256": "def456"},
            ]],
            "distances": [[0.12, 0.25]],
        }
        mock_chroma.return_value.get_or_create_collection.return_value = mock_coll
        mock_st.return_value.encode.return_value = [[0.1] * 384]

        engine = AurolabRAGEngine(
            persist_path="/tmp/test_chroma_3",
            groq_api_key="test_key",
            use_hyde=False,
            use_reranker=False,
        )
        result = engine.retrieve("Run a BCA protein assay", top_k=2)
        assert result is not None
        assert hasattr(result, "chunks") or isinstance(result, (list, dict))