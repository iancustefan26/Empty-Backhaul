"""Manifest of primary legal sources under `backend/legal_documents/`.

Each entry is a discrete ingestible source: one PDF or one .txt file. Adding a
new regulation = appending one entry here. The `id` is also the citation
prefix used for chunk IDs (`{id}.chunk-{NNNN}`) — keep it short and stable.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import BACKEND_DIR

LEGAL_ROOT = BACKEND_DIR / "legal_documents"


@dataclass(frozen=True)
class CorpusSource:
    id: str               # short stable identifier, used as chunk-id prefix
    relative_path: str    # path under legal_documents/
    citation: str         # human-readable label rendered in UI / verdicts
    jurisdiction: str     # "EU" | "RO"
    language: str         # ISO-639-1 code
    kind: str             # "pdf" | "txt"

    @property
    def absolute_path(self) -> Path:
        return LEGAL_ROOT / self.relative_path


CORPUS_SOURCES: list[CorpusSource] = [
    # ---- EU regulations (English PDFs) ----
    CorpusSource(
        id="eu.852-2004",
        relative_path="euro-lex/852:2004_(EU Food Hygiene).pdf",
        citation="Regulation (EC) No 852/2004 — Hygiene of foodstuffs",
        jurisdiction="EU",
        language="en",
        kind="pdf",
    ),
    CorpusSource(
        id="eu.178-2002",
        relative_path="euro-lex/Reg_178-2002.pdf",
        citation="Regulation (EC) No 178/2002 — General Food Law",
        jurisdiction="EU",
        language="en",
        kind="pdf",
    ),
    CorpusSource(
        id="eu.haccp-guidance",
        relative_path="guidance_doc_haccp_en.pdf",
        citation="EU Commission Notice — HACCP guidance for food businesses",
        jurisdiction="EU",
        language="en",
        kind="pdf",
    ),
    # ---- Romanian ANSVSA orders (Romanian .txt) ----
    CorpusSource(
        id="ansvsa.ordin-100-2004.ordin",
        relative_path="ansvsa/Ordin 100-2004/textul_ordinului.txt",
        citation="ANSVSA Ordin 100/2004 — text",
        jurisdiction="RO",
        language="ro",
        kind="txt",
    ),
    CorpusSource(
        id="ansvsa.ordin-100-2004.norma",
        relative_path="ansvsa/Ordin 100-2004/norma-09-11-2004.txt",
        citation="ANSVSA Ordin 100/2004 — norma sanitar-veterinară",
        jurisdiction="RO",
        language="ro",
        kind="txt",
    ),
    CorpusSource(
        id="ansvsa.ordin-55-2010.ordin",
        relative_path="ansvsa/Ordin 55-2010/textul_ordinului.txt",
        citation="ANSVSA Ordin 55/2010 — text",
        jurisdiction="RO",
        language="ro",
        kind="txt",
    ),
    CorpusSource(
        id="ansvsa.ordin-55-2010.norma",
        relative_path="ansvsa/Ordin 55-2010/norma-14-06-2010.txt",
        citation="ANSVSA Ordin 55/2010 — norma sanitar-veterinară",
        jurisdiction="RO",
        language="ro",
        kind="txt",
    ),
    CorpusSource(
        id="ansvsa.ordin-134-2010.ordin",
        relative_path="ansvsa/Ordin 134-2010/textul_ordinului.txt",
        citation="ANSVSA Ordin 134/2010 — text",
        jurisdiction="RO",
        language="ro",
        kind="txt",
    ),
    CorpusSource(
        id="ansvsa.ordin-134-2010.norma",
        relative_path="ansvsa/Ordin 134-2010/norma-22-10-2010.txt",
        citation="ANSVSA Ordin 134/2010 — norma sanitar-veterinară",
        jurisdiction="RO",
        language="ro",
        kind="txt",
    ),
    CorpusSource(
        id="ansvsa.ordin-57-2010.ordin",
        relative_path="ansvsa/Ordin 57-2010/textul_ordinului.txt",
        citation="ANSVSA Ordin 57/2010 — text",
        jurisdiction="RO",
        language="ro",
        kind="txt",
    ),
    CorpusSource(
        id="ansvsa.ordin-57-2010.norma",
        relative_path="ansvsa/Ordin 57-2010/textul_normei_sanitare_veterinare.txt",
        citation="ANSVSA Ordin 57/2010 — norma sanitar-veterinară",
        jurisdiction="RO",
        language="ro",
        kind="txt",
    ),
]


def find_source(source_id: str) -> CorpusSource | None:
    return next((s for s in CORPUS_SOURCES if s.id == source_id), None)
