"""Read + chunk legal documents into Chroma-ready payloads.

`load_text` extracts plain text from a TXT or PDF source. `chunk_text` runs a
recursive character splitter (chunk_size ≈ 900 chars, overlap ≈ 120) and
attaches stable IDs and per-chunk metadata. A lightweight section detector
records the article number when a chunk begins at an "Art." / "Article" /
"Articolul" heading, which makes citations more useful in the UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.corpus_sources import CorpusSource

DEFAULT_CHUNK_SIZE = 900
DEFAULT_OVERLAP = 120

# Article-heading patterns. Matched at chunk start to enrich metadata.
# Examples: "Art. 5", "Article 14(2)", "Articolul 3.", "ARTICOLUL II".
_ARTICLE_PATTERNS = [
    re.compile(r"^\s*Article\s+([IVX]+|\d+[A-Za-z]?(?:\([0-9a-z]+\))?)", re.IGNORECASE),
    re.compile(r"^\s*Art(?:icolul)?\.?\s+([IVX]+|\d+[A-Za-z]?)", re.IGNORECASE),
]

# Recursive splitter separators, ordered most → least preferred.
_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: dict


def load_text(source: CorpusSource) -> str:
    if source.kind == "txt":
        return _load_txt(source)
    if source.kind == "pdf":
        return _load_pdf(source)
    raise ValueError(f"unsupported source kind: {source.kind!r}")


def _load_txt(source: CorpusSource) -> str:
    return source.absolute_path.read_text(encoding="utf-8", errors="replace")


def _load_pdf(source: CorpusSource) -> str:
    # Lazy import so non-PDF flows don't pay the import cost.
    from pypdf import PdfReader

    reader = PdfReader(str(source.absolute_path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # pypdf occasionally chokes on malformed pages
            continue
    return "\n\n".join(parts)


def chunk_text(
    source: CorpusSource,
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    text = _normalize_whitespace(text)
    if not text.strip():
        return []

    raw_chunks = _split_recursive(text, chunk_size, overlap)
    out: list[Chunk] = []
    for i, body in enumerate(raw_chunks):
        article = _detect_article(body)
        meta = {
            "source_id": source.id,
            "citation": source.citation,
            "jurisdiction": source.jurisdiction,
            "language": source.language,
            "file_path": str(source.relative_path),
        }
        if article:
            meta["article"] = article
        out.append(Chunk(
            id=f"{source.id}.chunk-{i:04d}",
            text=body,
            metadata=meta,
        ))
    return out


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _normalize_whitespace(text: str) -> str:
    # Collapse 3+ blank lines to 2; strip trailing spaces per line.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _detect_article(chunk: str) -> str | None:
    head = chunk.lstrip()[:120]
    for pat in _ARTICLE_PATTERNS:
        m = pat.match(head)
        if m:
            return m.group(1)
    return None


def _split_recursive(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Greedy recursive splitter — splits on the largest separator that keeps
    pieces ≤ `chunk_size`, then re-glues with the chosen separator and
    re-splits anything still too long. Adds `overlap` chars of carry-over
    between consecutive chunks for retrieval continuity.
    """
    pieces = _recursive(text, chunk_size, _SEPARATORS)
    pieces = [p.strip() for p in pieces if p.strip()]
    if overlap <= 0 or len(pieces) <= 1:
        return pieces
    return _apply_overlap(pieces, overlap)


def _recursive(text: str, chunk_size: int, separators: list[str]) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    sep = separators[0]
    rest = separators[1:] or [""]
    if sep == "":
        # Hard split by character window.
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    splits = text.split(sep)
    out: list[str] = []
    buf = ""
    for piece in splits:
        candidate = buf + (sep if buf else "") + piece
        if len(candidate) <= chunk_size:
            buf = candidate
            continue
        if buf:
            out.append(buf)
            buf = ""
        if len(piece) <= chunk_size:
            buf = piece
        else:
            out.extend(_recursive(piece, chunk_size, rest))
    if buf:
        out.append(buf)
    return out


def _apply_overlap(pieces: list[str], overlap: int) -> list[str]:
    out: list[str] = [pieces[0]]
    for prev, cur in zip(pieces, pieces[1:]):
        tail = prev[-overlap:] if len(prev) > overlap else prev
        out.append(f"{tail} {cur}".strip())
    return out
