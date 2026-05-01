"""Ingest the compliance rule corpus into the Chroma vector store."""
from __future__ import annotations

from app.rag.chroma_client import get_or_create_collection, reset_collection
from app.rag.compliance_rules import COMPLIANCE_RULES


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
    out: list[dict] = []
    for i in range(len(res["ids"][0])):
        out.append({
            "id": res["ids"][0][i],
            "text": res["documents"][0][i],
            "metadata": res["metadatas"][0][i],
            "distance": res["distances"][0][i],
        })
    return out
