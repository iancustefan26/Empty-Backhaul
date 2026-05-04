"""Ingest the compliance rule corpus + the primary-source legal corpus into Chroma."""
from __future__ import annotations

from app.rag.chroma_client import (
    get_or_create_collection,
    get_or_create_corpus_collection,
    reset_collection,
    reset_corpus_collection,
)
from app.rag.compliance_rules import COMPLIANCE_RULES
from app.rag.corpus_sources import CORPUS_SOURCES, CorpusSource
from app.rag.loader import chunk_text, load_text


# ---------------------------------------------------------------------------
# Curated rule corpus (English, hand-written)
# ---------------------------------------------------------------------------

def ingest_rules(*, reset: bool = False) -> dict[str, int]:
    coll = reset_collection() if reset else get_or_create_collection()

    ids = [r["id"] for r in COMPLIANCE_RULES]
    documents = [r["text"] for r in COMPLIANCE_RULES]
    metadatas = [
        {
            "title": r["title"],
            "regulation": r["regulation"],
            "severity": r["severity"],
            "applies_to": r["applies_to"],
        }
        for r in COMPLIANCE_RULES
    ]

    coll.upsert(ids=ids, documents=documents, metadatas=metadatas)

    return {"collection_count": coll.count(), "ingested": len(ids)}


def query_rules(text: str, *, k: int = 5) -> list[dict]:
    """Return top-k similar rules for a free-form query, with metadata + similarity."""
    coll = get_or_create_collection()
    res = coll.query(query_texts=[text], n_results=k)
    return _flatten_query_result(res)


# ---------------------------------------------------------------------------
# Primary-source legal corpus (multilingual: EU PDFs + Romanian ANSVSA texts)
# ---------------------------------------------------------------------------

def ingest_corpus(
    *,
    reset: bool = False,
    only: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """Chunk the legal_documents/ tree into the `compliance_corpus` collection.

    Args:
        reset: if True, delete the collection and re-create empty before
            upserting. If False, upserts are idempotent: chunk IDs are stable
            so re-runs replace in place.
        only: optional list of source IDs to limit ingestion to (matches
            entries in `CORPUS_SOURCES`). Useful for re-ingesting one
            regulation after a manifest change.
        dry_run: if True, parse and chunk but do not touch Chroma. Returns
            the same per-source counts so you can preview the plan.
    """
    sources = _select_sources(only)

    per_source: dict[str, int] = {}
    skipped: dict[str, str] = {}
    all_ids: list[str] = []
    all_docs: list[str] = []
    all_meta: list[dict] = []

    for src in sources:
        if not src.absolute_path.exists():
            skipped[src.id] = "missing"
            continue
        text = load_text(src)
        chunks = chunk_text(src, text)
        if not chunks:
            skipped[src.id] = "empty"
            continue
        per_source[src.id] = len(chunks)
        all_ids.extend(c.id for c in chunks)
        all_docs.extend(c.text for c in chunks)
        all_meta.extend(c.metadata for c in chunks)

    result: dict[str, object] = {
        "per_source": per_source,
        "skipped": skipped,
        "ingested": len(all_ids),
        "dry_run": dry_run,
    }

    if dry_run or not all_ids:
        result["collection_count"] = 0 if dry_run else None
        return result

    coll = reset_corpus_collection() if reset else get_or_create_corpus_collection()
    # Chroma upsert tops out around a few thousand items per call; our corpus
    # is well under that, but batch defensively in case a future regulation
    # blows it up.
    batch = 256
    for i in range(0, len(all_ids), batch):
        coll.upsert(
            ids=all_ids[i : i + batch],
            documents=all_docs[i : i + batch],
            metadatas=all_meta[i : i + batch],
        )

    result["collection_count"] = coll.count()
    return result


def query_corpus(text: str, *, k: int = 3) -> list[dict]:
    """Return top-k similar primary-source excerpts for a free-form query."""
    coll = get_or_create_corpus_collection()
    res = coll.query(query_texts=[text], n_results=k)
    return _flatten_query_result(res)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _flatten_query_result(res: dict) -> list[dict]:
    out: list[dict] = []
    if not res.get("ids") or not res["ids"][0]:
        return out
    for i in range(len(res["ids"][0])):
        out.append({
            "id": res["ids"][0][i],
            "text": res["documents"][0][i],
            "metadata": res["metadatas"][0][i],
            "distance": res["distances"][0][i],
        })
    return out


def _select_sources(only: list[str] | None) -> list[CorpusSource]:
    if not only:
        return CORPUS_SOURCES
    wanted = set(only)
    selected = [s for s in CORPUS_SOURCES if s.id in wanted]
    missing = wanted - {s.id for s in selected}
    if missing:
        raise ValueError(f"unknown source ids: {sorted(missing)}")
    return selected
