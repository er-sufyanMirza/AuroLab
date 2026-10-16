"""
aurolab/services/translation_service/core/pdf_parser.py

Dual-strategy PDF parser for lab protocol documents.
Strategy 1: PyMuPDF  — fast, precise; best for digital PDFs with clean text layers.
Strategy 2: Unstructured — layout-aware; handles scanned PDFs, multi-column, tables.

ParsedDocument carries all extracted structure so downstream chunkers
can make context-aware decisions (e.g. keep table rows together).
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class BlockType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    METADATA = "metadata"


@dataclass
class ContentBlock:
    """Atomic unit of parsed content. Preserves semantic type for smart chunking."""
    block_type: BlockType
    content: str                  # raw text of this block
    page_number: int
    bbox: tuple[float, float, float, float] | None = None  # (x0, y0, x1, y1)
    font_size: float | None = None
    is_bold: bool = False
    table_data: list[list[str]] | None = None  # populated only for TABLE blocks
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.content.split())


@dataclass
class ParsedDocument:
    """Full structured output from parsing one PDF."""
    source_path: str
    sha256: str
    page_count: int
    title: str | None
    authors: list[str]
    doc_type: str                 # "protocol", "paper", "SOP", "datasheet", "unknown"
    blocks: list[ContentBlock]
    raw_text: str                 # full concatenated text (fallback)
    parse_strategy: str           # "pymupdf" | "unstructured"
    parse_warnings: list[str] = field(default_factory=list)

    @property
    def text_blocks(self) -> list[ContentBlock]:
        return [b for b in self.blocks if b.block_type in (BlockType.TEXT, BlockType.LIST_ITEM)]

    @property
    def tables(self) -> list[ContentBlock]:
        return [b for b in self.blocks if b.block_type == BlockType.TABLE]

    @property
    def headings(self) -> list[ContentBlock]:
        return [b for b in self.blocks if b.block_type == BlockType.HEADING]


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

_HEADING_PATTERNS = re.compile(
    r"^(?:\d+\.?\s+|[A-Z][A-Z\s]{3,}$|(?:abstract|introduction|methods?|"
    r"materials?|protocol|procedure|results?|discussion|conclusion|references?))",
    re.IGNORECASE,
)

_LIST_PATTERNS = re.compile(r"^\s*(?:\d+[.)]\s+|[-•*]\s+|[a-z][.)]\s+)")

_PROTOCOL_KEYWORDS = {"protocol", "procedure", "reagent", "pipette", "centrifuge",
                       "incubate", "vortex", "aliquot", "assay", "pcr", "bca", "elisa"}
_SOP_KEYWORDS      = {"standard operating procedure", "sop", "work instruction"}
_PAPER_KEYWORDS    = {"abstract", "introduction", "doi", "journal", "keywords"}


def _classify_doc_type(text: str) -> str:
    lower = text[:3000].lower()
    if any(k in lower for k in _SOP_KEYWORDS):
        return "SOP"
    if sum(1 for k in _PROTOCOL_KEYWORDS if k in lower) >= 3:
        return "protocol"
    if any(k in lower for k in _PAPER_KEYWORDS):
        return "paper"
    return "unknown"


def _is_heading(span_text: str, font_size: float, avg_font_size: float, is_bold: bool) -> bool:
    stripped = span_text.strip()
    if not stripped or len(stripped) > 120:
        return False
    size_ratio = font_size / avg_font_size if avg_font_size else 1.0
    return (
        (size_ratio >= 1.15 or is_bold)
        and bool(_HEADING_PATTERNS.match(stripped))
    )


# ---------------------------------------------------------------------------
# Strategy 1: PyMuPDF parser
# ---------------------------------------------------------------------------

def _parse_with_pymupdf(pdf_bytes: bytes, source_path: str) -> ParsedDocument | None:
    """
    Attempt high-fidelity extraction using PyMuPDF.
    Returns None if the document has insufficient text (likely scanned).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_count = doc.page_count
    blocks: list[ContentBlock] = []
    all_text_parts: list[str] = []
    font_sizes: list[float] = []

    # First pass: collect font sizes for heading detection
    for page in doc:
        for block in page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("size"):
                        font_sizes.append(span["size"])

    avg_font_size = (sum(font_sizes) / len(font_sizes)) if font_sizes else 12.0

    # Second pass: structured extraction
    for page_num, page in enumerate(doc, start=1):
        page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in page_dict["blocks"]:
            if block.get("type") == 1:  # image block — skip (future: vision layer)
                continue

            block_text_parts: list[str] = []
            max_font_size: float = 0.0
            any_bold: bool = False

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    txt = span.get("text", "").strip()
                    if not txt:
                        continue
                    block_text_parts.append(txt)
                    size = span.get("size", avg_font_size)
                    flags = span.get("flags", 0)
                    is_bold_span = bool(flags & 2**4)  # bold flag
                    if size > max_font_size:
                        max_font_size = size
                    if is_bold_span:
                        any_bold = True

            if not block_text_parts:
                continue

            combined = " ".join(block_text_parts).strip()
            if not combined:
                continue

            all_text_parts.append(combined)
            bbox = block.get("bbox")

            if _is_heading(combined, max_font_size, avg_font_size, any_bold):
                btype = BlockType.HEADING
            elif _LIST_PATTERNS.match(combined):
                btype = BlockType.LIST_ITEM
            else:
                btype = BlockType.TEXT

            blocks.append(ContentBlock(
                block_type=btype,
                content=combined,
                page_number=page_num,
                bbox=tuple(bbox) if bbox else None,
                font_size=max_font_size,
                is_bold=any_bold,
            ))

        # Table extraction via find_tables (PyMuPDF ≥ 1.23)
        try:
            tabs = page.find_tables()
            for tab in tabs.tables:
                rows = tab.extract()
                if not rows:
                    continue
                flat = "\n".join(" | ".join(str(c) for c in row if c) for row in rows)
                blocks.append(ContentBlock(
                    block_type=BlockType.TABLE,
                    content=flat,
                    page_number=page_num,
                    table_data=[[str(c) for c in row] for row in rows],
                ))
        except Exception as e:  # noqa: BLE001
            log.debug("table_extraction_skipped", page=page_num, reason=str(e))

    doc.close()
    raw_text = "\n\n".join(all_text_parts)

    # Quality gate: if < 200 words extracted, this PDF probably needs Unstructured
    if len(raw_text.split()) < 200 and page_count > 1:
        log.info("pymupdf_insufficient_text", word_count=len(raw_text.split()))
        return None

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    doc_type = _classify_doc_type(raw_text)

    # Best-effort title extraction (largest text on page 1)
    title = None
    page1_headings = [b for b in blocks if b.page_number == 1 and b.block_type == BlockType.HEADING]
    if page1_headings:
        title = max(page1_headings, key=lambda b: b.font_size or 0).content[:200]

    return ParsedDocument(
        source_path=source_path,
        sha256=sha256,
        page_count=page_count,
        title=title,
        authors=[],  # populated by metadata extractor
        doc_type=doc_type,
        blocks=blocks,
        raw_text=raw_text,
        parse_strategy="pymupdf",
    )


# ---------------------------------------------------------------------------
# Strategy 2: Unstructured fallback
# ---------------------------------------------------------------------------

def _parse_with_unstructured(pdf_bytes: bytes, source_path: str) -> ParsedDocument:
    """
    Layout-aware fallback using Unstructured.
    Handles: multi-column, scanned PDFs (OCR), complex tables.
    """
    from unstructured.partition.pdf import partition_pdf

    with io.BytesIO(pdf_bytes) as buf:
        elements = partition_pdf(
            file=buf,
            strategy="hi_res",          # OCR-capable
            infer_table_structure=True,  # structured table extraction
            include_page_breaks=True,
        )

    blocks: list[ContentBlock] = []
    all_text: list[str] = []
    current_page = 1

    for el in elements:
        el_type = type(el).__name__
        page = getattr(el.metadata, "page_number", current_page) or current_page
        current_page = page
        text = str(el).strip()

        if not text:
            continue

        all_text.append(text)

        if el_type in ("Title", "Header"):
            btype = BlockType.HEADING
        elif el_type in ("ListItem",):
            btype = BlockType.LIST_ITEM
        elif el_type in ("Table",):
            btype = BlockType.TABLE
        elif el_type in ("FigureCaption", "Caption"):
            btype = BlockType.CAPTION
        else:
            btype = BlockType.TEXT

        blocks.append(ContentBlock(
            block_type=btype,
            content=text,
            page_number=page,
            metadata={"element_type": el_type},
        ))

    raw_text = "\n\n".join(all_text)
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    doc_type = _classify_doc_type(raw_text)

    title = next(
        (b.content[:200] for b in blocks if b.block_type == BlockType.HEADING), None
    )

    return ParsedDocument(
        source_path=source_path,
        sha256=sha256,
        page_count=current_page,
        title=title,
        authors=[],
        doc_type=doc_type,
        blocks=blocks,
        raw_text=raw_text,
        parse_strategy="unstructured",
        parse_warnings=["Used Unstructured fallback — possible layout complexity or scanned PDF"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_pdf(pdf_bytes: bytes, source_path: str = "unknown") -> ParsedDocument:
    """
    Parse a PDF using dual-strategy cascade.
    Tries PyMuPDF first (fast); falls back to Unstructured if quality is insufficient.

    Args:
        pdf_bytes:   Raw bytes of the PDF file.
        source_path: Original filename or S3 key for traceability.

    Returns:
        ParsedDocument with structured blocks and metadata.

    Raises:
        ValueError: If parsing fails with both strategies.
    """
    log.info("parse_pdf_start", source=source_path, size_kb=len(pdf_bytes) // 1024)

    try:
        result = _parse_with_pymupdf(pdf_bytes, source_path)
        if result is not None:
            log.info("parse_pdf_complete", strategy="pymupdf",
                     blocks=len(result.blocks), doc_type=result.doc_type)
            return result
    except Exception as exc:  # noqa: BLE001
        log.warning("pymupdf_failed", error=str(exc))

    try:
        result = _parse_with_unstructured(pdf_bytes, source_path)
        log.info("parse_pdf_complete", strategy="unstructured",
                 blocks=len(result.blocks), doc_type=result.doc_type)
        return result
    except Exception as exc:
        log.error("unstructured_failed", error=str(exc))
        raise ValueError(f"Both parse strategies failed for {source_path}: {exc}") from exc


def parse_pdf_file(path: str | Path) -> ParsedDocument:
    """Convenience wrapper for local file paths."""
    path = Path(path)
    return parse_pdf(path.read_bytes(), source_path=str(path))