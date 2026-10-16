"""
services/translation_service/core/translation_service.py

TranslationService — the primary orchestration facade for Phase 1.

Ties together:
  - AurolabRAGEngine    (retrieval)
  - AurolabLLMEngine    (generation + citation injection)
  - ProtocolManager     (storage + search)
  - DocumentLoader      (upload + validation)

This is the single object that FastAPI routers talk to.
It keeps routers thin and keeps the business logic testable.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from .llm_engine import AurolabLLMEngine, GeneratedProtocol
from .rag_engine import AurolabRAGEngine
from .registry import DocumentRegistry
from .protocol_manager import ProtocolManager
from .document_loader import load_document, DocumentLoadError
from .chunker import chunk_document

log = structlog.get_logger(__name__)


class TranslationService:
    """
    Orchestrates the full RAG + generation pipeline.

    Instantiated once in main.py lifespan and injected into app.state.
    All methods are synchronous — FastAPI runs them in a thread pool
    via run_in_executor (handled at the router level with asyncio).
    """

    def __init__(
        self,
        rag_engine: AurolabRAGEngine,
        llm_engine: AurolabLLMEngine,
        registry: DocumentRegistry,
        protocol_manager: ProtocolManager | None = None,
    ) -> None:
        self._rag      = rag_engine
        self._llm      = llm_engine
        self._registry = registry
        self._protos   = protocol_manager or ProtocolManager()

    # ------------------------------------------------------------------
    # Document ingestion
    # ------------------------------------------------------------------

    def ingest_pdf(
        self,
        filename: str,
        file_bytes: bytes,
    ) -> dict[str, Any]:
        """
        Validate, parse, chunk, embed, and register a PDF document.

        Returns:
            dict with keys: doc_id, sha256, pages, chunks_added,
                            chunks_skipped, already_exists
        """
        # Load and validate
        doc = load_document(filename, file_bytes)

        # Deduplication check
        existing = self._registry.get_by_sha256(doc.sha256)
        if existing:
            log.info("document_duplicate", sha256=doc.sha256[:8], filename=filename)
            return {
                "doc_id":        existing.get("doc_id", ""),
                "sha256":        doc.sha256,
                "pages":         doc.page_count,
                "chunks_added":  0,
                "chunks_skipped":0,
                "already_exists":True,
            }

        # Chunk
        chunks = chunk_document(doc)
        if not chunks:
            return {
                "doc_id":        "",
                "sha256":        doc.sha256,
                "pages":         doc.page_count,
                "chunks_added":  0,
                "chunks_skipped":0,
                "already_exists":False,
                "warning":       "No chunks extracted — check PDF content",
            }

        # Embed and store in ChromaDB
        ingest_result = self._rag.ingest_chunks(chunks)

        # Register document
        doc_id = self._registry.register(
            source_path=filename,
            sha256=doc.sha256,
            page_count=doc.page_count,
            title=doc.title or filename,
            doc_type=doc.doc_type,
            chunk_count=ingest_result.get("added", 0),
        )

        log.info("document_ingested",
                 doc_id=doc_id,
                 filename=filename,
                 pages=doc.page_count,
                 chunks=ingest_result.get("added", 0))

        return {
            "doc_id":        doc_id,
            "sha256":        doc.sha256,
            "pages":         doc.page_count,
            "chunks_added":  ingest_result.get("added", 0),
            "chunks_skipped":ingest_result.get("skipped", 0),
            "already_exists":False,
        }

    # ------------------------------------------------------------------
    # Protocol generation
    # ------------------------------------------------------------------

    def generate_protocol(
        self,
        instruction: str,
        protocol_id: str | None = None,
    ) -> GeneratedProtocol:
        """
        Generate a validated, citation-injected protocol from a NL instruction.

        Args:
            instruction:  Natural language lab instruction.
            protocol_id:  Optional ID to assign. Auto-generated if None.

        Returns:
            GeneratedProtocol — typed, validated, stored in protocol manager.
        """
        import uuid
        pid = protocol_id or str(uuid.uuid4())

        t0 = time.perf_counter()
        protocol = self._llm.generate(instruction=instruction, protocol_id=pid)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

        log.info("protocol_generated",
                 protocol_id=pid,
                 title=protocol.title,
                 steps=len(protocol.steps),
                 elapsed_ms=elapsed_ms,
                 confidence=round(protocol.confidence_score, 2))

        # Store
        self._protos.save(protocol)
        return protocol

    # ------------------------------------------------------------------
    # Protocol retrieval
    # ------------------------------------------------------------------

    def get_protocol(self, protocol_id: str) -> dict | None:
        return self._protos.get(protocol_id)

    def search_protocols(
        self,
        query: str = "",
        safety_level: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Returns (results, total_count)."""
        results = self._protos.search(query=query, safety_level=safety_level,
                                       limit=limit, offset=offset)
        total   = self._protos.total(query=query, safety_level=safety_level)
        return results, total

    def delete_protocol(self, protocol_id: str) -> bool:
        return self._protos.delete(protocol_id)

    def export_protocol(
        self,
        protocol_id: str,
        fmt: str = "json",
    ) -> str | None:
        """Export protocol as 'json' or 'markdown'."""
        if fmt == "markdown":
            return self._protos.export_markdown(protocol_id)
        return self._protos.export_json(protocol_id)

    def history_summary(self, limit: int = 20) -> list[dict]:
        return self._protos.history_summary(limit=limit)

    # ------------------------------------------------------------------
    # RAG stats
    # ------------------------------------------------------------------

    def collection_stats(self) -> dict:
        return self._rag.collection_stats()

    def document_list(self) -> list[dict]:
        return self._registry.list_all()