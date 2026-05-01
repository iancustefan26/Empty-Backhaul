"""CLI: rebuild the Chroma compliance-rule collection.

    python -m scripts.ingest_rules            # upsert (preserves existing)
    python -m scripts.ingest_rules --reset    # delete + recreate the collection
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.rag.ingest import ingest_rules  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest compliance rules into Chroma.")
    parser.add_argument("--reset", action="store_true",
                        help="Delete the collection before inserting.")
    args = parser.parse_args()

    summary = ingest_rules(reset=args.reset)
    print(f"Ingested {summary['ingested']} rules. "
          f"Collection now contains {summary['collection_count']} documents.")


if __name__ == "__main__":
    main()
