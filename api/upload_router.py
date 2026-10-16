"""
api/upload_router.py — PDF upload and ingestion endpoint for AuroLab.

POST /api/v1/documents/upload   — upload + ingest a PDF
GET  /api/v1/documents/         — list all indexed documents
GET  /api/v1/documents/status/{job_id} — poll ingestion status
DELETE /api/v1/documents/{sha256}      — remove document from KB
"""
from __future__ import annotations

import hashlib
import time
import uuid
from typing import Annotated

import structlog
from fastapi import (APIRouter, BackgroundTasks, File, HTTPException,
                     Request, UploadFile, status)
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])

MAX_FILE_SIZE_MB  = 50
ALLOWED_MIME_TYPES = {"application/pdf", "application/x-pdf"}


# ── Pydantic models ───────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    job_id:   str
    sha256:   str
    filename: str
    size_kb:  int
    status:   str
    message:  str = ""


# ── Dependency helpers ────────────────────────────────────────────────────────

def _get_rag(request: Request):
    return getattr(request.app.state, "rag_engine", None)

def _get_registry(request: Request):
    return getattr(request.app.state, "registry", None)


# ── Background ingestion ──────────────────────────────────────────────────────

async def _ingest_document(
    pdf_bytes: bytes,
    filename:  str,
    sha256:    str,
    job_id:    str,
    rag_engine,
    registry,
) -> None:
    """Parse → chunk → embed in background. Updates registry on completion."""
    try:
        # Lazy imports so the module loads even if fitz/chromadb not installed
        from services.translation_service.core.pdf_parser import parse_pdf
        from services.translation_service.core.chunker   import chunk_document

        registry.update_status(sha256, "processing")

        doc    = parse_pdf(pdf_bytes, source_path=filename)
        chunks = chunk_document(doc)

        log.info("background_chunk_complete", job_id=job_id, chunks=len(chunks))

        stats = rag_engine.ingest_chunks(chunks)

        registry.update_status(
            sha256, "ready",
            chunk_count=stats["added"] + stats.get("skipped", 0),
            page_count=doc.page_count,
            doc_type=doc.doc_type,
            ingested_at=time.time(),
        )
        log.info("ingestion_complete", job_id=job_id,
                 chunks_added=stats["added"], filename=filename)

    except Exception as exc:
        log.error("ingestion_failed", job_id=job_id, error=str(exc), exc_info=True)
        try:
            registry.update_status(sha256, "failed", error=str(exc))
        except Exception:
            pass


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a lab protocol PDF for ingestion",
)
async def upload_document(
    background_tasks: BackgroundTasks,
    request: Request,
    file: Annotated[UploadFile, File(description="PDF file to ingest (max 50MB)")],
) -> UploadResponse:

    rag_engine = _get_rag(request)
    registry   = _get_registry(request)

    if rag_engine is None or registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG engine not initialised — check GROQ_API_KEY and ChromaDB",
        )

    pdf_bytes = await file.read()
    size_mb   = len(pdf_bytes) / (1024 * 1024)

    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_FILE_SIZE_MB}MB limit ({size_mb:.1f}MB)",
        )

    # Optional MIME check — skip gracefully if python-magic not installed
    try:
        import magic
        mime = magic.from_buffer(pdf_bytes[:2048], mime=True)
        if mime not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Only PDF files accepted. Detected: {mime}",
            )
    except ImportError:
        pass  # python-magic not installed — accept the file

    sha256   = hashlib.sha256(pdf_bytes).hexdigest()
    job_id   = str(uuid.uuid4())
    filename = file.filename or "unknown.pdf"

    # Dedup check
    existing = registry.get(sha256)
    if existing and existing.get("status") == "ready":
        return UploadResponse(
            job_id=job_id, sha256=sha256, filename=filename,
            size_kb=len(pdf_bytes) // 1024, status="duplicate",
            message=f"Already indexed with {existing.get('chunk_count', 0)} chunks.",
        )

    # Register and queue
    registry.register(sha256, filename=filename)

    background_tasks.add_task(
        _ingest_document,
        pdf_bytes=pdf_bytes,
        filename=filename,
        sha256=sha256,
        job_id=job_id,
        rag_engine=rag_engine,
        registry=registry,
    )

    log.info("upload_accepted", job_id=job_id,
             sha256=sha256[:12], size_kb=len(pdf_bytes) // 1024)

    return UploadResponse(
        job_id=job_id, sha256=sha256, filename=filename,
        size_kb=len(pdf_bytes) // 1024, status="queued",
        message="Document queued for ingestion. Refresh in a few seconds.",
    )


@router.get("/", summary="List all indexed documents")
async def list_documents(request: Request) -> dict:
    registry = _get_registry(request)
    if registry is None:
        return {"documents": [], "total": 0}
    docs  = registry.list_all()
    items = [{"sha256": k, **v} for k, v in docs.items()]
    return {"documents": items, "total": len(items)}


@router.get("/status/{job_id}", summary="Poll ingestion status")
async def get_status(job_id: str, request: Request) -> dict:
    # Status is keyed by sha256, not job_id — return all docs as fallback
    registry = _get_registry(request)
    if registry is None:
        return {"status": "unknown"}
    return {"job_id": job_id, "documents": registry.list_all()}


@router.delete("/{sha256}", summary="Remove document from knowledge base")
async def delete_document(sha256: str, request: Request) -> dict:
    rag_engine = _get_rag(request)
    registry   = _get_registry(request)

    if registry is None:
        raise HTTPException(status_code=503, detail="Registry not available")

    existing = registry.get(sha256)
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove from ChromaDB
    if rag_engine is not None:
        try:
            rag_engine._collection.delete(where={"sha256": sha256})
            log.info("chroma_deleted", sha256=sha256[:12])
        except Exception as e:
            log.warning("chroma_delete_failed", error=str(e))

    registry.remove(sha256)
    return {"deleted": sha256, "filename": existing.get("filename", "")}