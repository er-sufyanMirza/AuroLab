"""
services/translation_service/core/document_loader.py

Document loading layer — validates, deduplicates, and routes PDF files
to the appropriate parser strategy before handing off to the chunker.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import structlog

# Import ParsedDocument and parse_pdf at module level.
# Try every possible path — whichever one works depending on how the project is run.
try:
    from .pdf_parser import ParsedDocument, parse_pdf
except ImportError:
    try:
        from services.translation_service.core.pdf_parser import ParsedDocument, parse_pdf
    except ImportError:
        try:
            from core.pdf_parser import ParsedDocument, parse_pdf  # type: ignore
        except ImportError:
            # Last resort — define stubs so module loads even without PyMuPDF
            ParsedDocument = None   # type: ignore
            parse_pdf = None        # type: ignore

log = structlog.get_logger(__name__)

MAX_FILE_SIZE_MB   = 50
ALLOWED_EXTENSIONS = {".pdf"}


class DocumentLoadError(Exception):
    def __init__(self, message: str, code: str = "LOAD_ERROR") -> None:
        super().__init__(message)
        self.code = code


def _validate_file(filename: str, file_bytes: bytes, max_mb: float = MAX_FILE_SIZE_MB) -> None:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentLoadError(f"Unsupported file type: {ext}.", code="INVALID_EXTENSION")
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > max_mb:
        raise DocumentLoadError(f"File too large: {size_mb:.1f} MB (max {max_mb} MB).", code="FILE_TOO_LARGE")
    if not file_bytes.startswith(b"%PDF"):
        raise DocumentLoadError("Not a valid PDF (missing %PDF header).", code="INVALID_PDF_HEADER")


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_document(filename: str, file_bytes: bytes, source_label: str | None = None):
    """Validate and parse a PDF. Returns ParsedDocument."""
    if parse_pdf is None:
        raise RuntimeError("pdf_parser not available — check PyMuPDF is installed: pip install pymupdf")

    _validate_file(filename, file_bytes)
    sha256 = _compute_sha256(file_bytes)

    log.info("document_loading", filename=filename,
             size_kb=round(len(file_bytes) / 1024, 1), sha256=sha256[:8])

    doc = parse_pdf(file_bytes, source_path=filename)
    doc.sha256 = sha256

    log.info("document_loaded", filename=filename,
             pages=doc.page_count, blocks=len(doc.blocks), strategy=doc.parse_strategy)
    return doc


def load_document_from_path(file_path):
    """Load a document from a local file path."""
    path = Path(file_path)
    if not path.exists():
        raise DocumentLoadError(f"File not found: {file_path}", code="FILE_NOT_FOUND")
    return load_document(path.name, path.read_bytes())


def is_duplicate(sha256: str, registry) -> bool:
    existing = registry.get_by_sha256(sha256)
    return existing is not None