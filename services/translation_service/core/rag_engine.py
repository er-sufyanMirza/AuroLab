"""
aurolab/services/translation_service/core/rag_engine.py

Production RAG engine for AuroLab.

Retrieval pipeline:
  1. HyDE query expansion   — embed a hypothetical answer for richer query vectors
  2. Dense retrieval         — ChromaDB cosine similarity search
  3. Sparse retrieval        — BM25 over the same candidate pool
  4. Fusion scoring          — RRF (Reciprocal Rank Fusion) merges dense + sparse
  5. Cross-encoder reranking — FlashRank refines top candidates
  6. Metadata filtering      — optional doc_type / section_title constraints
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import chromadb
import structlog
from groq import Groq
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from flashrank import Ranker, RerankRequest

from .chunker import Chunk

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EMBED_MODEL_NAME    = "sentence-transformers/all-MiniLM-L6-v2"  # 384-dim, fast
CHROMA_COLLECTION   = "aurolab_protocols"
RERANKER_MODEL      = "ms-marco-MiniLM-L-12-v2"
TOP_K_DENSE         = 20    # candidates from dense retrieval
TOP_K_SPARSE        = 20    # candidates from BM25
TOP_K_RERANK        = 5     # final chunks passed to LLM context
RRF_K               = 60    # RRF constant (standard value)
HYDE_MAX_TOKENS     = 256   # hypothetical answer length


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    source: str
    section_title: str | None
    doc_type: str
    page_start: int
    page_end: int
    score: float
    rank: int


@dataclass
class RetrievalResult:
    query: str
    expanded_query: str | None
    chunks: list[RetrievedChunk]
    retrieval_ms: float
    strategy: str   # "hybrid_reranked" | "dense_only" | "fallback_raw"


# ---------------------------------------------------------------------------
# RAG Engine
# ---------------------------------------------------------------------------

class AurolabRAGEngine:
    """
    Singleton-friendly RAG engine. Initialise once at startup, reuse per request.
    """

    def __init__(
        self,
        chroma_host: str = "localhost",
        chroma_port: int = 8000,
        persist_path: str | None = "./data/chroma",
        embed_model: str = EMBED_MODEL_NAME,
        groq_api_key: str | None = None,
        use_hyde: bool = True,
        use_reranker: bool = True,
    ) -> None:
        log.info("rag_engine_init_start")

        # Embedding model
        self._embedder = SentenceTransformer(embed_model)
        log.info("embedder_loaded", model=embed_model)

        # ChromaDB — prefer persistent local if no host given
        if persist_path and not os.getenv("CHROMA_HOST"):
            self._chroma = chromadb.PersistentClient(path=persist_path)
        else:
            self._chroma = chromadb.HttpClient(host=chroma_host, port=chroma_port)

        self._collection = self._chroma.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        log.info("chroma_connected", collection=CHROMA_COLLECTION)

        # Groq for HyDE
        self._groq = Groq(api_key=groq_api_key or os.environ["GROQ_API_KEY"])
        self._use_hyde = use_hyde

        # Reranker
        self._use_reranker = use_reranker
        if use_reranker:
            self._reranker = Ranker(model_name=RERANKER_MODEL, cache_dir="/tmp/flashrank")
            log.info("reranker_loaded", model=RERANKER_MODEL)

        log.info("rag_engine_ready", hyde=use_hyde, reranker=use_reranker)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_chunks(self, chunks: list[Chunk], batch_size: int = 64) -> dict[str, int]:
        """
        Embed and store chunks in ChromaDB.
        Skips duplicates by chunk_id (idempotent).
        Returns ingestion stats.
        """
        if not chunks:
            return {"added": 0, "skipped": 0}

        # Check existing IDs to avoid re-embedding
        existing_ids: set[str] = set()
        try:
            existing = self._collection.get(ids=[c.chunk_id for c in chunks])
            existing_ids = set(existing["ids"])
        except Exception:  # noqa: BLE001
            pass

        new_chunks = [c for c in chunks if c.chunk_id not in existing_ids]
        if not new_chunks:
            log.info("ingest_all_duplicates", skipped=len(chunks))
            return {"added": 0, "skipped": len(chunks)}

        added = 0
        for i in range(0, len(new_chunks), batch_size):
            batch = new_chunks[i : i + batch_size]
            texts = [c.text for c in batch]

            embeddings = self._embedder.encode(
                texts,
                batch_size=32,
                show_progress_bar=False,
                normalize_embeddings=True,
            ).tolist()

            self._collection.add(
                ids=[c.chunk_id for c in batch],
                documents=texts,
                embeddings=embeddings,
                metadatas=[c.to_chroma_metadata() for c in batch],
            )
            added += len(batch)

        log.info("ingest_complete", added=added, skipped=len(existing_ids))
        return {"added": added, "skipped": len(existing_ids)}

    # ------------------------------------------------------------------
    # Retrieval: HyDE expansion
    # ------------------------------------------------------------------

    def _hyde_expand(self, query: str) -> str:
        """
        Hypothetical Document Embeddings (HyDE).
        Generate a plausible lab protocol excerpt for the query,
        then embed that instead of the bare query.
        This dramatically improves retrieval for technical queries.
        """
        try:
            system = (
                "You are an expert lab scientist. Given a user query about a lab protocol, "
                "write a concise, realistic protocol excerpt (2-4 sentences) that would "
                "answer the query. Write only the excerpt — no preamble."
            )
            resp = self._groq.chat.completions.create(
                model="llama3-8b-8192",   # smaller model is fine for expansion
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": query},
                ],
                max_tokens=HYDE_MAX_TOKENS,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("hyde_failed", error=str(exc))
            return query  # graceful fallback to original query

    # ------------------------------------------------------------------
    # Retrieval: Dense
    # ------------------------------------------------------------------

    def _dense_retrieve(
        self,
        query_text: str,
        top_k: int,
        where: dict | None = None,
    ) -> list[dict]:
        query_vec = self._embedder.encode(
            query_text,
            normalize_embeddings=True,
        ).tolist()

        kwargs: dict[str, Any] = {
            "query_embeddings": [query_vec],
            "n_results": min(top_k, self._collection.count() or 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)

        candidates = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            candidates.append({
                "text": doc,
                "metadata": meta,
                "score": 1.0 - dist,  # cosine distance → similarity
            })
        return candidates

    # ------------------------------------------------------------------
    # Retrieval: Sparse (BM25 over dense candidates)
    # ------------------------------------------------------------------

    def _bm25_reorder(
        self,
        query: str,
        candidates: list[dict],
    ) -> list[dict]:
        """Apply BM25 over the dense candidate pool (no separate index needed)."""
        if len(candidates) < 3:
            return candidates

        tokenized_corpus = [c["text"].lower().split() for c in candidates]
        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(query.lower().split())

        for c, s in zip(candidates, scores):
            c["bm25_score"] = float(s)

        return candidates

    # ------------------------------------------------------------------
    # Retrieval: Reciprocal Rank Fusion
    # ------------------------------------------------------------------

    @staticmethod
    def _rrf_fuse(
        dense_ranked: list[dict],
        bm25_ranked: list[dict],
        k: int = RRF_K,
    ) -> list[dict]:
        """Merge dense + BM25 rankings using Reciprocal Rank Fusion."""
        chunk_scores: dict[str, float] = {}

        # Dense ranking
        dense_sorted = sorted(dense_ranked, key=lambda x: x["score"], reverse=True)
        for rank, item in enumerate(dense_sorted):
            cid = item["metadata"].get("sha256", "") + item["text"][:40]
            chunk_scores[cid] = chunk_scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            item["_rrf_id"] = cid

        # BM25 ranking
        bm25_sorted = sorted(bm25_ranked, key=lambda x: x.get("bm25_score", 0), reverse=True)
        for rank, item in enumerate(bm25_sorted):
            cid = item["metadata"].get("sha256", "") + item["text"][:40]
            chunk_scores[cid] = chunk_scores.get(cid, 0.0) + 1.0 / (k + rank + 1)

        # Re-sort by RRF score and deduplicate
        seen: set[str] = set()
        fused: list[dict] = []
        all_items = {i["_rrf_id"]: i for i in dense_ranked if "_rrf_id" in i}

        for cid, _ in sorted(chunk_scores.items(), key=lambda x: x[1], reverse=True):
            if cid not in seen and cid in all_items:
                all_items[cid]["rrf_score"] = chunk_scores[cid]
                fused.append(all_items[cid])
                seen.add(cid)

        return fused

    # ------------------------------------------------------------------
    # Retrieval: Cross-encoder reranking
    # ------------------------------------------------------------------

    def _rerank(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        if not self._use_reranker or len(candidates) <= top_k:
            return candidates[:top_k]

        passages = [{"id": i, "text": c["text"]} for i, c in enumerate(candidates)]
        request = RerankRequest(query=query, passages=passages)
        results = self._reranker.rerank(request)

        reranked = []
        for r in results[:top_k]:
            # FlashRank returns either an object with .id/.score
            # or a dict with ["id"]/["score"] depending on version
            rid   = int(r["id"]    if isinstance(r, dict) else r.id)
            score = float(r["score"] if isinstance(r, dict) else r.score)
            original = candidates[rid]
            original["rerank_score"] = score
            reranked.append(original)

        return reranked

    # ------------------------------------------------------------------
    # Public: retrieve
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = TOP_K_RERANK,
        doc_type_filter: str | None = None,
        section_filter: str | None = None,
    ) -> RetrievalResult:
        """
        Full pipeline: HyDE → dense → BM25 fusion → rerank → top-k.

        Args:
            query:             Natural language user query.
            top_k:             Number of chunks to return.
            doc_type_filter:   Restrict to "protocol", "SOP", "paper", etc.
            section_filter:    Restrict to chunks from a specific section title substring.

        Returns:
            RetrievalResult with ranked chunks and timing info.
        """
        t0 = time.perf_counter()

        # Build ChromaDB where clause
        where_clause: dict | None = None
        conditions = []
        if doc_type_filter:
            conditions.append({"doc_type": {"$eq": doc_type_filter}})
        if section_filter:
            conditions.append({"section_title": {"$contains": section_filter}})
        if len(conditions) == 1:
            where_clause = conditions[0]
        elif len(conditions) > 1:
            where_clause = {"$and": conditions}

        # 1. HyDE expansion
        expanded_query = None
        retrieval_query = query
        if self._use_hyde and self._collection.count() > 0:
            expanded_query = self._hyde_expand(query)
            retrieval_query = expanded_query
            log.debug("hyde_expanded", original=query[:80], expanded=expanded_query[:80])

        # 2. Dense retrieval
        dense_candidates = self._dense_retrieve(retrieval_query, TOP_K_DENSE, where_clause)
        if not dense_candidates:
            # Fallback: retrieve without filter
            log.warning("empty_dense_results_with_filter", filter=where_clause)
            dense_candidates = self._dense_retrieve(retrieval_query, TOP_K_DENSE, None)

        # 3. BM25 over candidates
        bm25_candidates = self._bm25_reorder(query, dense_candidates.copy())

        # 4. RRF fusion
        fused = self._rrf_fuse(dense_candidates, bm25_candidates)

        # 5. Rerank
        final = self._rerank(query, fused, top_k)

        elapsed_ms = (time.perf_counter() - t0) * 1000

        retrieved = [
            RetrievedChunk(
                chunk_id=c["metadata"].get("sha256", "")[:8],
                text=c["text"],
                source=c["metadata"].get("source", "unknown"),
                section_title=c["metadata"].get("section_title") or None,
                doc_type=c["metadata"].get("doc_type", "unknown"),
                page_start=c["metadata"].get("page_start", 0),
                page_end=c["metadata"].get("page_end", 0),
                score=c.get("rerank_score", c.get("rrf_score", c.get("score", 0.0))),
                rank=rank,
            )
            for rank, c in enumerate(final, start=1)
        ]

        log.info("retrieval_complete",
                 query_chars=len(query),
                 chunks_returned=len(retrieved),
                 elapsed_ms=round(elapsed_ms, 1),
                 strategy="hybrid_reranked" if self._use_reranker else "hybrid")

        return RetrievalResult(
            query=query,
            expanded_query=expanded_query,
            chunks=retrieved,
            retrieval_ms=round(elapsed_ms, 1),
            strategy="hybrid_reranked" if self._use_reranker else "hybrid",
        )

    # ------------------------------------------------------------------
    # Collection stats (for /health endpoint)
    # ------------------------------------------------------------------

    def collection_stats(self) -> dict:
        count = self._collection.count()
        return {
            "collection": CHROMA_COLLECTION,
            "total_chunks": count,
            "embed_model": EMBED_MODEL_NAME,
            "hyde_enabled": self._use_hyde,
            "reranker_enabled": self._use_reranker,
        }