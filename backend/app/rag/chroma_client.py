"""Persistent Chroma client wrapper.

The Chroma store lives on disk at `CHROMA_PERSIST_DIR` (default: backend/chroma_db).
We use Chroma's default embedding function (ONNX all-MiniLM-L6-v2, ~80 MB on first
download) so the system has zero outbound API dependencies for the vector layer.
"""
from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions

from app.core.config import get_settings

COLLECTION_NAME = "compliance_rules"


def get_client() -> ClientAPI:
    persist_dir = Path(get_settings().chroma_persist_dir).resolve()
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def get_embedding_function():
    return embedding_functions.DefaultEmbeddingFunction()


def get_or_create_collection(client: ClientAPI | None = None) -> Collection:
    client = client or get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def reset_collection(client: ClientAPI | None = None) -> Collection:
    client = client or get_client()
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    return get_or_create_collection(client)
