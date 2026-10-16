"""
aurolab/services/translation_service/core/chunker.py

Structure-aware chunking for lab protocol PDFs.

Strategy:
  1. Heading-anchored sections  — group text under its nearest heading
  2. Table integrity            — tables are never split; stored as atomic chunks
  3. Sliding window fallback    — long sections get overlapping sub-chunks
  4. Token budget               — every chunk guaranteed ≤ max_tokens (for embed model)
  5. Rich metadata              — section title, doc type, page range, position ratio

This metadata is what enables precise filtered RAG queries later
(e.g. "retrieve only from 'Materials' sections of 'protocol' docs").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

import tiktoken
import structlog

from .pdf_parser import BlockType, ContentBlock, ParsedDocument

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_MAX_TOKENS      = 512   # fits comfortably in embed model context (512 or 256)
DEFAULT_OVERLAP_TOKENS  = 64    # overlap between sliding-window sub-chunks
DEFAULT_MIN_CHARS       = 60    # discard text chunks shorter than this (noise)
TABLE_MIN_CHARS         = 10    # tables are kept even when short — a 3-row table is always meaningful

_TOKENIZER = tiktoken.get_encoding("cl100k_base")  # shared with most embed models


def _count_tokens(text: str) -> int:
    return len(_TOKENIZER.encode(text, disallowed_special=()))


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    tokens = _TOKENIZER.encode(text, disallowed_special=())
    return _TOKENIZER.decode(tokens[:max_tokens])


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """
    One unit of retrieval. Carries enough metadata for:
      - filtered search (doc_type, section_title, page_range)
      - provenance display (source, pages)
      - quality scoring (position_ratio, heading_depth)
    """
    text: str
    chunk_id: str                 # deterministic: sha256(doc)[:8]-{index}
    source: str                   # original PDF filename
    sha256: str                   # parent document hash
    doc_type: str                 # "protocol" | "SOP" | "paper" | "unknown"
    section_title: str | None     # nearest heading above this chunk
    page_start: int
    page_end: int
    position_ratio: float         # 0.0 (start) → 1.0 (end) within doc
    chunk_index: int
    total_chunks_in_doc: int = 0  # set after all chunks produced
    is_table: bool = False
    token_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_chroma_metadata(self) -> dict:
        """Serialize to ChromaDB-compatible flat dict (all values must be str/int/float/bool)."""
        return {
            "source":          self.source,
            "sha256":          self.sha256,
            "doc_type":        self.doc_type,
            "section_title":   self.section_title or "",
            "page_start":      self.page_start,
            "page_end":        self.page_end,
            "position_ratio":  round(self.position_ratio, 4),
            "chunk_index":     self.chunk_index,
            "is_table":        self.is_table,
            "token_count":     self.token_count,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sliding_window_split(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Split long text into overlapping sub-chunks within token budget."""
    tokens = _TOKENIZER.encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return [text]

    chunks = []
    step = max_tokens - overlap_tokens
    for start in range(0, len(tokens), step):
        window = tokens[start : start + max_tokens]
        chunks.append(_TOKENIZER.decode(window))
        if start + max_tokens >= len(tokens):
            break
    return chunks


def _heading_depth(text: str) -> int:
    """Rough heading hierarchy: numbered headings get depth from dot count."""
    m = re.match(r"^(\d+(?:\.\d+)*)", text.strip())
    if m:
        return m.group(1).count(".") + 1
    return 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_document(
    doc: ParsedDocument,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[Chunk]:
    """
    Convert a ParsedDocument into retrieval-ready Chunks.

    The algorithm:
    1. Walk blocks in page order.
    2. When a HEADING is encountered, flush accumulated text as a section chunk,
       then start a new section under this heading.
    3. TABLE blocks are always emitted as standalone atomic chunks.
    4. At end-of-document, flush remaining accumulated text.
    5. Any section chunk exceeding max_tokens is further split with sliding window.
    6. Assign chunk IDs and position ratios.
    """
    chunks: list[Chunk] = []
    doc_prefix = doc.sha256[:8]
    total_blocks = len(doc.blocks)

    current_heading: str | None = doc.title
    current_page_start: int = 1
    accumulated: list[ContentBlock] = []

    def flush_section(up_to_page: int) -> None:
        nonlocal current_page_start
        if not accumulated:
            return

        section_text = "\n\n".join(b.content for b in accumulated).strip()
        if len(section_text) < min_chars:
            accumulated.clear()
            return

        pages = [b.page_number for b in accumulated]
        p_start = min(pages)
        p_end = max(pages)

        # Position in document
        first_idx = doc.blocks.index(accumulated[0]) if accumulated[0] in doc.blocks else 0
        pos_ratio = first_idx / max(total_blocks - 1, 1)

        sub_texts = _sliding_window_split(section_text, max_tokens, overlap_tokens)

        for sub in sub_texts:
            sub = sub.strip()
            if len(sub) < min_chars:
                continue
            idx = len(chunks)
            chunks.append(Chunk(
                text=sub,
                chunk_id=f"{doc_prefix}-{idx:04d}",
                source=doc.source_path,
                sha256=doc.sha256,
                doc_type=doc.doc_type,
                section_title=current_heading,
                page_start=p_start,
                page_end=p_end,
                position_ratio=pos_ratio,
                chunk_index=idx,
                token_count=_count_tokens(sub),
            ))

        accumulated.clear()
        current_page_start = up_to_page

    for block in doc.blocks:
        if block.block_type == BlockType.TABLE:
            # Flush current section first
            flush_section(block.page_number)

            table_text = block.content.strip()
            if len(table_text) >= TABLE_MIN_CHARS:
                idx = len(chunks)
                table_tokens = _count_tokens(table_text)
                # Tables that exceed budget get truncated (not split — splitting a table destroys context)
                if table_tokens > max_tokens:
                    table_text = _truncate_to_tokens(table_text, max_tokens)
                    log.warning("table_truncated", source=doc.source_path, page=block.page_number)
                chunks.append(Chunk(
                    text=table_text,
                    chunk_id=f"{doc_prefix}-{idx:04d}",
                    source=doc.source_path,
                    sha256=doc.sha256,
                    doc_type=doc.doc_type,
                    section_title=current_heading,
                    page_start=block.page_number,
                    page_end=block.page_number,
                    position_ratio=doc.blocks.index(block) / max(total_blocks - 1, 1),
                    chunk_index=idx,
                    is_table=True,
                    token_count=_count_tokens(table_text),
                ))

        elif block.block_type == BlockType.HEADING:
            flush_section(block.page_number)
            current_heading = block.content
            current_page_start = block.page_number
            # Prepend heading to next section for context
            accumulated.append(block)

        else:
            accumulated.append(block)

    flush_section(doc.page_count)

    # Back-fill total_chunks_in_doc
    total = len(chunks)
    for c in chunks:
        c.total_chunks_in_doc = total

    log.info("chunking_complete",
             source=doc.source_path,
             total_chunks=total,
             tables=sum(1 for c in chunks if c.is_table),
             avg_tokens=round(sum(c.token_count for c in chunks) / max(total, 1)))

    return chunks


def chunk_documents(
    docs: Sequence[ParsedDocument],
    **kwargs,
) -> list[Chunk]:
    """Batch chunking for multiple documents."""
    all_chunks = []
    for doc in docs:
        all_chunks.extend(chunk_document(doc, **kwargs))
    return all_chunks