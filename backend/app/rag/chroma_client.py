"""Persistent Chroma client wrapper.

Two collections:

- `compliance_rules` — the 17 hand-written, English rule summaries. Embedded
  with Chroma's default `all-MiniLM-L6-v2` (~80 MB ONNX). Stable citation
  index for the Analyst.

- `compliance_corpus` — the chunked primary sources from
  `backend/legal_documents/` (EU PDFs in English, ANSVSA orders in Romanian).
  Embedded with `paraphrase-multilingual-MiniLM-L12-v2` (~250 MB on first
  download) so English Analyst queries can retrieve Romanian passages.

Both stores live on disk at `CHROMA_PERSIST_DIR` (default: backend/chroma_db).
"""
from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions

from app.core.config import get_settings

COLLECTION_NAME = "compliance_rules"
CORPUS_COLLECTION_NAME = "compliance_corpus"

MULTILINGUAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def get_client() -> ClientAPI:
    persist_dir = Path(get_settings().chroma_persist_dir).resolve()
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def get_embedding_function():
    return embedding_functions.DefaultEmbeddingFunction()


def get_multilingual_embedding_function():
    """Sentence-transformers multilingual embedder.

    Lazy-instantiates the model the first time it's called; subsequent calls
    in the same process re-use it. The first call also triggers a one-time
    ~250 MB download into the HuggingFace cache.
    """
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=MULTILINGUAL_MODEL,
    )


def get_or_create_collection(client: ClientAPI | None = None) -> Collection:
    client = client or get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def get_or_create_corpus_collection(client: ClientAPI | None = None) -> Collection:
    client = client or get_client()
    return client.get_or_create_collection(
        name=CORPUS_COLLECTION_NAME,
        embedding_function=get_multilingual_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def reset_collection(client: ClientAPI | None = None) -> Collection:
    client = client or get_client()
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    return get_or_create_collection(client)


def reset_corpus_collection(client: ClientAPI | None = None) -> Collection:
    client = client or get_client()
    try:
        client.delete_collection(CORPUS_COLLECTION_NAME)
    except Exception:
        pass
    return get_or_create_corpus_collection(client)
