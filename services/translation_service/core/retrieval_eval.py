"""
aurolab/services/translation_service/core/retrieval_eval.py

RAG evaluation harness for AuroLab.

Measures retrieval quality across three pipeline variants:
  A: Dense only (baseline ChromaDB cosine similarity)
  B: Hybrid (dense + BM25 RRF fusion)
  C: Full (hybrid + HyDE + cross-encoder rerank)

Metrics computed:
  - MRR@k   (Mean Reciprocal Rank)      — how high does the first relevant chunk rank?
  - NDCG@k  (Normalised DCG)            — graded relevance, position-weighted
  - Recall@k                            — fraction of relevant chunks found in top-k
  - Precision@k
  - Hit Rate@k                          — binary: did ANY relevant chunk appear?

Usage:
    from core.retrieval_eval import EvalHarness, EvalDataset, EvalQuery

    dataset = EvalDataset.from_jsonl("data/eval/qa_set.jsonl")
    harness = EvalHarness(rag_engine)
    report  = harness.run(dataset, k=5)
    report.print_table()
    report.save_json("data/eval/results.json")

QA JSONL format (one JSON object per line):
    {
      "query_id": "q001",
      "question": "What centrifuge speed is used in BCA assay preparation?",
      "relevant_chunk_ids": ["abc12345-0002", "abc12345-0005"],
      "doc_type_hint": "protocol"    // optional filter
    }
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import structlog

from .rag_engine import AurolabRAGEngine, RetrievedChunk

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Dataset types
# ---------------------------------------------------------------------------

@dataclass
class EvalQuery:
    query_id: str
    question: str
    relevant_chunk_ids: list[str]         # ground truth chunk_ids
    doc_type_hint: str | None = None       # optional filter for retrieval

    @classmethod
    def from_dict(cls, d: dict) -> "EvalQuery":
        return cls(
            query_id=d["query_id"],
            question=d["question"],
            relevant_chunk_ids=d["relevant_chunk_ids"],
            doc_type_hint=d.get("doc_type_hint"),
        )


@dataclass
class EvalDataset:
    queries: list[EvalQuery]
    name: str = "unnamed"

    @classmethod
    def from_jsonl(cls, path: str | Path, name: str | None = None) -> "EvalDataset":
        p = Path(path)
        queries = [EvalQuery.from_dict(json.loads(line)) for line in p.read_text().splitlines() if line.strip()]
        return cls(queries=queries, name=name or p.stem)

    @classmethod
    def from_list(cls, items: list[dict], name: str = "inline") -> "EvalDataset":
        return cls(queries=[EvalQuery.from_dict(d) for d in items], name=name)

    def __len__(self) -> int:
        return len(self.queries)


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def _reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Normalised Discounted Cumulative Gain at k. Binary relevance (0 or 1)."""
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, cid in enumerate(retrieved_ids[:k], start=1)
        if cid in relevant_ids
    )
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def _recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    hits = sum(1 for cid in retrieved_ids[:k] if cid in relevant_ids)
    return hits / len(relevant_ids)


def _precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k == 0:
        return 0.0
    hits = sum(1 for cid in retrieved_ids[:k] if cid in relevant_ids)
    return hits / k


def _hit_rate_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    return 1.0 if any(cid in relevant_ids for cid in retrieved_ids[:k]) else 0.0


# ---------------------------------------------------------------------------
# Per-query result
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    query_id: str
    question: str
    retrieved_chunk_ids: list[str]
    relevant_chunk_ids: list[str]
    mrr: float
    ndcg: float
    recall: float
    precision: float
    hit_rate: float
    latency_ms: float
    variant: str


# ---------------------------------------------------------------------------
# Variant report
# ---------------------------------------------------------------------------

@dataclass
class VariantReport:
    variant: str
    k: int
    query_results: list[QueryResult] = field(default_factory=list)

    @property
    def mean_mrr(self) -> float:
        return _safe_mean(r.mrr for r in self.query_results)

    @property
    def mean_ndcg(self) -> float:
        return _safe_mean(r.ndcg for r in self.query_results)

    @property
    def mean_recall(self) -> float:
        return _safe_mean(r.recall for r in self.query_results)

    @property
    def mean_precision(self) -> float:
        return _safe_mean(r.precision for r in self.query_results)

    @property
    def hit_rate(self) -> float:
        return _safe_mean(r.hit_rate for r in self.query_results)

    @property
    def mean_latency_ms(self) -> float:
        return _safe_mean(r.latency_ms for r in self.query_results)

    def to_dict(self) -> dict:
        return {
            "variant":         self.variant,
            "k":               self.k,
            "n_queries":       len(self.query_results),
            "MRR@k":           round(self.mean_mrr, 4),
            "NDCG@k":          round(self.mean_ndcg, 4),
            "Recall@k":        round(self.mean_recall, 4),
            "Precision@k":     round(self.mean_precision, 4),
            "HitRate@k":       round(self.hit_rate, 4),
            "mean_latency_ms": round(self.mean_latency_ms, 1),
        }


def _safe_mean(values) -> float:
    lst = list(values)
    return sum(lst) / len(lst) if lst else 0.0


# ---------------------------------------------------------------------------
# Full eval report
# ---------------------------------------------------------------------------

@dataclass
class EvalReport:
    dataset_name: str
    k: int
    variants: list[VariantReport]
    run_timestamp: float = field(default_factory=time.time)

    def best_variant(self, metric: str = "MRR@k") -> VariantReport:
        return max(self.variants, key=lambda v: v.to_dict()[metric])

    def print_table(self) -> None:
        header = f"\n{'Variant':<25} {'MRR@k':>8} {'NDCG@k':>8} {'Recall@k':>10} {'Hit@k':>8} {'Latency':>10}"
        print(f"\n=== AuroLab RAG Evaluation — {self.dataset_name} (k={self.k}) ===")
        print(header)
        print("-" * len(header))
        for v in self.variants:
            d = v.to_dict()
            print(
                f"{v.variant:<25} "
                f"{d['MRR@k']:>8.4f} "
                f"{d['NDCG@k']:>8.4f} "
                f"{d['Recall@k']:>10.4f} "
                f"{d['HitRate@k']:>8.4f} "
                f"{d['mean_latency_ms']:>9.1f}ms"
            )
        best = self.best_variant()
        print(f"\nBest variant by MRR@k: {best.variant} ({best.mean_mrr:.4f})")

    def save_json(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "dataset":        self.dataset_name,
            "k":              self.k,
            "run_timestamp":  self.run_timestamp,
            "variants":       [v.to_dict() for v in self.variants],
            "best_by_mrr":    self.best_variant().variant,
        }
        p.write_text(json.dumps(data, indent=2))
        log.info("eval_report_saved", path=str(p))

    def to_dict(self) -> dict:
        return {
            "dataset":   self.dataset_name,
            "k":         self.k,
            "variants":  [v.to_dict() for v in self.variants],
            "best_by_mrr": self.best_variant().variant,
        }


# ---------------------------------------------------------------------------
# Retrieval functions per variant
# ---------------------------------------------------------------------------

RetrieveFn = Callable[[str, int, str | None], list[str]]  # (query, k, filter) -> chunk_ids


def _make_variant_a(engine: AurolabRAGEngine) -> RetrieveFn:
    """Variant A: dense only, no HyDE, no rerank."""
    original_hyde    = engine._use_hyde
    original_rerank  = engine._use_reranker

    def retrieve(query: str, k: int, doc_type: str | None) -> list[str]:
        engine._use_hyde    = False
        engine._use_reranker = False
        try:
            result = engine.retrieve(query, top_k=k, doc_type_filter=doc_type)
            return [c.chunk_id for c in result.chunks]
        finally:
            engine._use_hyde    = original_hyde
            engine._use_reranker = original_rerank

    return retrieve


def _make_variant_b(engine: AurolabRAGEngine) -> RetrieveFn:
    """Variant B: hybrid (BM25 + dense RRF), no HyDE, no rerank."""
    original_hyde    = engine._use_hyde
    original_rerank  = engine._use_reranker

    def retrieve(query: str, k: int, doc_type: str | None) -> list[str]:
        engine._use_hyde    = False
        engine._use_reranker = False
        try:
            result = engine.retrieve(query, top_k=k, doc_type_filter=doc_type)
            return [c.chunk_id for c in result.chunks]
        finally:
            engine._use_hyde    = original_hyde
            engine._use_reranker = original_rerank

    return retrieve


def _make_variant_c(engine: AurolabRAGEngine) -> RetrieveFn:
    """Variant C: full pipeline — HyDE + hybrid + rerank."""
    def retrieve(query: str, k: int, doc_type: str | None) -> list[str]:
        result = engine.retrieve(query, top_k=k, doc_type_filter=doc_type)
        return [c.chunk_id for c in result.chunks]
    return retrieve


# ---------------------------------------------------------------------------
# Eval harness
# ---------------------------------------------------------------------------

class EvalHarness:
    """
    Runs all three retrieval variants against the dataset and produces
    a comparative EvalReport.
    """

    def __init__(self, rag_engine: AurolabRAGEngine) -> None:
        self._engine = rag_engine

    def run(
        self,
        dataset: EvalDataset,
        k: int = 5,
        variants: list[str] | None = None,
    ) -> EvalReport:
        """
        Run evaluation across all variants.

        Args:
            dataset:  EvalDataset with ground-truth QA pairs.
            k:        Cutoff for all @k metrics.
            variants: Subset of ["A_dense_only","B_hybrid","C_full"] to run.
                      Defaults to all three.

        Returns:
            EvalReport with per-variant metrics and per-query breakdowns.
        """
        run_variants = variants or ["A_dense_only", "B_hybrid", "C_full"]

        variant_fns: dict[str, RetrieveFn] = {
            "A_dense_only": _make_variant_a(self._engine),
            "B_hybrid":     _make_variant_b(self._engine),
            "C_full":       _make_variant_c(self._engine),
        }

        reports: list[VariantReport] = []

        for variant_name in run_variants:
            if variant_name not in variant_fns:
                log.warning("unknown_variant_skipped", variant=variant_name)
                continue

            retrieve_fn = variant_fns[variant_name]
            vreport = VariantReport(variant=variant_name, k=k)

            log.info("eval_variant_start", variant=variant_name, n_queries=len(dataset))

            for query in dataset.queries:
                t0 = time.perf_counter()
                try:
                    retrieved_ids = retrieve_fn(query.question, k, query.doc_type_hint)
                except Exception as exc:  # noqa: BLE001
                    log.warning("eval_query_failed", query_id=query.query_id, error=str(exc))
                    retrieved_ids = []

                latency_ms = (time.perf_counter() - t0) * 1000
                relevant_set = set(query.relevant_chunk_ids)

                vreport.query_results.append(QueryResult(
                    query_id=query.query_id,
                    question=query.question,
                    retrieved_chunk_ids=retrieved_ids,
                    relevant_chunk_ids=query.relevant_chunk_ids,
                    mrr=_reciprocal_rank(retrieved_ids, relevant_set),
                    ndcg=_ndcg_at_k(retrieved_ids, relevant_set, k),
                    recall=_recall_at_k(retrieved_ids, relevant_set, k),
                    precision=_precision_at_k(retrieved_ids, relevant_set, k),
                    hit_rate=_hit_rate_at_k(retrieved_ids, relevant_set, k),
                    latency_ms=latency_ms,
                    variant=variant_name,
                ))

            log.info("eval_variant_complete",
                     variant=variant_name,
                     mrr=round(vreport.mean_mrr, 4),
                     recall=round(vreport.mean_recall, 4))
            reports.append(vreport)

        return EvalReport(
            dataset_name=dataset.name,
            k=k,
            variants=reports,
        )

    def run_single_query(
        self,
        question: str,
        relevant_chunk_ids: list[str],
        k: int = 5,
    ) -> dict:
        """Quick single-query eval — useful for interactive debugging."""
        dataset = EvalDataset.from_list([{
            "query_id": "debug_q",
            "question": question,
            "relevant_chunk_ids": relevant_chunk_ids,
        }], name="debug")
        report = self.run(dataset, k=k)
        return report.to_dict()