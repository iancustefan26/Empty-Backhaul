"""CLI: ingest the primary-source legal corpus into Chroma.

The corpus is everything under `backend/legal_documents/` — EU regulations
as PDFs and Romanian ANSVSA orders as .txt. Chunks are embedded with the
multilingual model `paraphrase-multilingual-MiniLM-L12-v2` (auto-downloaded
on first run, ~250 MB).

    python -m scripts.ingest_corpus                     # upsert all sources
    python -m scripts.ingest_corpus --reset             # wipe + re-ingest
    python -m scripts.ingest_corpus --dry-run           # parse + chunk only
    python -m scripts.ingest_corpus --source eu.852-2004
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.rag.ingest import ingest_corpus  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest the legal_documents/ corpus into Chroma's compliance_corpus collection.",
    )
    parser.add_argument("--reset", action="store_true",
                        help="Delete the collection before inserting.")
    parser.add_argument("--source", action="append", dest="sources", metavar="SOURCE_ID",
                        help="Limit to one source (repeatable). E.g. --source eu.852-2004")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + chunk only; do not write to Chroma.")
    args = parser.parse_args()

    summary = ingest_corpus(reset=args.reset, only=args.sources, dry_run=args.dry_run)

    label = "[dry-run] " if args.dry_run else ""
    print(f"{label}Ingested {summary['ingested']} chunks from {len(summary['per_source'])} sources.")
    if summary["per_source"]:
        width = max(len(sid) for sid in summary["per_source"])
        for sid, count in sorted(summary["per_source"].items()):
            print(f"  {sid.ljust(width)}  {count:>4} chunks")
    if summary["skipped"]:
        print("Skipped:")
        for sid, reason in summary["skipped"].items():
            print(f"  {sid}  -- {reason}")
    if not args.dry_run and summary.get("collection_count") is not None:
        print(f"Collection now contains {summary['collection_count']} documents.")


if __name__ == "__main__":
    main()
