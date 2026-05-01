"""Mock-document generation for Romanian backhaul handovers.

Each function returns a JSON-serialisable dict shaped like the Romanian /
European document it represents. These are paraphrases sufficient for a
thesis demo, not legally compliant artefacts.
"""
from app.documents.cmr import build_cmr_document
from app.documents.sanitization import build_sanitization_document

__all__ = ["build_cmr_document", "build_sanitization_document"]
