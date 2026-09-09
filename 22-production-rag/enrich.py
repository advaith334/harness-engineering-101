"""Metadata creation — deterministic first, LLM only where it earns its keep.

The instinct is to run an LLM over every chunk. On this corpus that is ~36 calls;
on a real one it is tens of thousands, re-paid every time you touch the chunker.

So enrichment happens at the SECTION level and child chunks inherit it, and results
are cached by sha256 of the section text — re-chunking is then free, and a re-ingest
after editing one document only re-enriches that document's sections.

Deterministic metadata (heading path, token count, has_code, doc_type) is computed
for free and is never wrong. The LLM is asked only for what it is uniquely good at:
a summary, the entities named, and the questions the section actually answers.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

import mistral
from chunking import Chunk, Document

CACHE_PATH = Path(__file__).parent / ".enrich_cache.json"


# Flat, all-required, list[str] rather than nested objects — `chat.parse` emits a
# strict schema and rejects much more than plain JSON mode would.
class SectionFacts(BaseModel):
    summary: str = Field(description="One sentence describing what this section covers.")
    entities: list[str] = Field(description="Products, services, error codes, plan names mentioned.")
    questions_answered: list[str] = Field(description="Up to 3 questions this section answers.")


SYSTEM = (
    "You extract retrieval metadata from a documentation section. Be literal: only "
    "name entities that actually appear. Questions must be answerable from this "
    "section alone."
)


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=1))


def _section_text(chunks: list[Chunk]) -> str:
    return "\n\n".join(c.content for c in chunks)


def enrich_document(doc: Document, chunks: list[Chunk]) -> dict[int, dict]:
    """Returns {chunk.ordinal: metadata dict}. Never raises — degrades instead."""
    cache = _load_cache()

    sections: dict[str, list[Chunk]] = {}
    for c in chunks:
        sections.setdefault(c.section_key, []).append(c)

    def facts_for(key: str) -> dict:
        text = _section_text(sections[key])
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest in cache:
            return cache[digest]
        parsed = mistral.parse(SectionFacts, SYSTEM, text[:6000], small=True)
        facts = parsed.model_dump() if parsed else {
            "summary": "", "entities": [], "questions_answered": []}
        if parsed:
            cache[digest] = facts
        return facts

    keys = list(sections)
    with ThreadPoolExecutor(max_workers=4) as pool:   # bounded: rate limits are real
        section_facts = dict(zip(keys, pool.map(facts_for, keys)))

    _save_cache(cache)

    out: dict[int, dict] = {}
    for c in chunks:
        facts = section_facts[c.section_key]
        out[c.ordinal] = {
            # deterministic — always correct, costs nothing
            "heading_path": c.heading_path,
            "doc_type": doc.doc_type,
            "product": doc.product,
            "service": doc.service,
            "has_code": c.has_code,
            "has_table": c.has_table,
            "token_count": c.token_count,
            # LLM-derived — inherited from the section, may be empty offline
            "summary": facts["summary"],
            "entities": facts["entities"],
            "questions_answered": facts["questions_answered"],
        }
    return out
