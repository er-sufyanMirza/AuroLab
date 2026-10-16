"""
scripts/run_eval.py

Run the AuroLab RAG evaluation harness and print a comparison table.

Usage:
    python scripts/run_eval.py
    python scripts/run_eval.py --qa-path data/eval/qa_set.jsonl --k 5
    python scripts/run_eval.py --variants A_dense_only C_full

After ingesting real PDFs, fill in the relevant_chunk_ids in qa_set.jsonl
by running:
    python scripts/run_eval.py --inspect-query "centrifuge speed BCA"
which will print the top-10 retrieved chunk IDs you can copy into the JSONL.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.translation_service.core.rag_engine import AurolabRAGEngine
from services.translation_service.core.retrieval_eval import EvalDataset, EvalHarness


def main() -> None:
    parser = argparse.ArgumentParser(description="AuroLab RAG Evaluation Harness")
    parser.add_argument("--qa-path",  default="data/eval/qa_set.jsonl",
                        help="Path to JSONL QA dataset")
    parser.add_argument("--k",        type=int, default=5,
                        help="Cutoff for @k metrics")
    parser.add_argument("--variants", nargs="+",
                        choices=["A_dense_only", "B_hybrid", "C_full"],
                        default=["A_dense_only", "B_hybrid", "C_full"],
                        help="Which pipeline variants to compare")
    parser.add_argument("--output",   default="data/eval/results.json",
                        help="Where to save the JSON report")
    parser.add_argument("--inspect-query", default=None,
                        help="Print top-10 chunk IDs for a given query (for building ground truth)")
    parser.add_argument("--chroma-path", default="./data/chroma",
                        help="Path to ChromaDB persistent storage")
    args = parser.parse_args()

    print("Initialising RAG engine...")
    engine = AurolabRAGEngine(
        persist_path=args.chroma_path,
        groq_api_key=os.environ.get("GROQ_API_KEY", "dummy"),
        use_hyde=True,
        use_reranker=True,
    )

    # Inspect mode: print chunk IDs for a query to build ground truth
    if args.inspect_query:
        print(f"\nTop-10 chunks for: '{args.inspect_query}'")
        result = engine.retrieve(args.inspect_query, top_k=10)
        for i, chunk in enumerate(result.chunks, 1):
            print(f"  {i:2d}. [{chunk.chunk_id}] {chunk.source} | {chunk.section_title} | score={chunk.score:.3f}")
            print(f"       {chunk.text[:100]}...")
        return

    # Normal eval mode
    dataset = EvalDataset.from_jsonl(args.qa_path)
    print(f"Loaded {len(dataset)} queries from {args.qa_path}")

    harness = EvalHarness(engine)
    report  = harness.run(dataset, k=args.k, variants=args.variants)

    report.print_table()
    report.save_json(args.output)
    print(f"\nFull report saved to: {args.output}")


if __name__ == "__main__":
    main()