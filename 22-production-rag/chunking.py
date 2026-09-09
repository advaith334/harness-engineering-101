"""Structure-aware chunking — the part of RAG that decides everything downstream.

Fixed-size chunking is the default everywhere and it is quietly terrible on real
documents. It splits tables so a row arrives with no header, cuts code blocks in
half, and strips every chunk of the headings that said what it was about.

This module instead parses markdown into blocks, keeps atomic blocks (fenced code,
tables) whole, packs them into token-bounded chunks that never cross a heading
boundary, and stamps every chunk with its heading path.

No network, no LLM, no database — which is exactly why this is the one file with a
real self-test. Run it directly: `python chunking.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from config import CHUNK_OVERLAP_TOKENS, MAX_CHUNK_TOKENS


# --- token counting ----------------------------------------------------------
# Deliberately an approximation. An exact tokenizer would be a dependency and a
# download, and every threshold here is a soft target — being 8% off on a 400
# token budget changes nothing. Do NOT use this for billing or context limits.
def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# --- parsing -----------------------------------------------------------------

@dataclass
class Block:
    kind: str      # "text" | "code" | "table" | "heading"
    text: str
    level: int = 0     # heading level, 0 for non-headings

    @property
    def atomic(self) -> bool:
        """Blocks that must never be split, whatever the token budget says."""
        return self.kind in ("code", "table")


@dataclass
class Document:
    uri: str
    title: str
    doc_type: str
    product: str | None
    service: str | None
    effective_date: str | None
    version: str | None
    blocks: list[Block] = field(default_factory=list)
    raw: str = ""


FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE = re.compile(r"^```")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


def parse_document(path: Path) -> Document:
    raw = path.read_text()

    meta: dict[str, str] = {}
    body = raw
    if m := FRONT_MATTER.match(raw):
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        body = raw[m.end():]

    blocks: list[Block] = []
    buf: list[str] = []

    def flush_text() -> None:
        if buf and "".join(buf).strip():
            blocks.append(Block("text", "\n".join(buf).strip()))
        buf.clear()

    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        # fenced code: consume to the closing fence, never split
        if FENCE.match(line):
            flush_text()
            fence = [line]
            i += 1
            while i < len(lines) and not FENCE.match(lines[i]):
                fence.append(lines[i])
                i += 1
            if i < len(lines):
                fence.append(lines[i])       # closing fence
            blocks.append(Block("code", "\n".join(fence)))
            i += 1
            continue

        # table: consume every consecutive pipe row, never split
        if TABLE_ROW.match(line):
            flush_text()
            rows = []
            while i < len(lines) and TABLE_ROW.match(lines[i]):
                rows.append(lines[i])
                i += 1
            blocks.append(Block("table", "\n".join(rows)))
            continue

        if m := HEADING.match(line):
            flush_text()
            blocks.append(Block("heading", m.group(2).strip(), level=len(m.group(1))))
            i += 1
            continue

        buf.append(line)
        i += 1
    flush_text()

    return Document(
        uri=path.name,
        title=meta.get("title", path.stem),
        doc_type=meta.get("doc_type", "unknown"),
        product=meta.get("product"),
        service=meta.get("service"),
        effective_date=meta.get("effective_date"),
        version=meta.get("version"),
        blocks=blocks,
        raw=raw,
    )


# --- chunking ----------------------------------------------------------------

@dataclass
class Chunk:
    ordinal: int
    section_key: str      # chunks sharing this belong to one section
    heading_path: str     # "H1 > H2 > H3"
    content: str
    token_count: int
    has_code: bool
    has_table: bool

    @property
    def embed_text(self) -> str:
        """What actually gets embedded.

        The heading path is prepended so a chunk carries its own context. Without
        it, "Free 60, Pro 600" is an orphan row that matches nothing; with it, the
        chunk knows it is about API rate limits.
        """
        return f"{self.heading_path}\n\n{self.content}"


def chunk_document(doc: Document) -> list[Chunk]:
    chunks: list[Chunk] = []
    path: list[str] = []          # current heading stack
    pending: list[Block] = []     # blocks accumulating into the current chunk
    ordinal = 0

    def heading_path() -> str:
        return " > ".join(path) if path else doc.title

    def section_key() -> str:
        # Sections are H2-scoped: fine-grained enough to enrich cheaply, coarse
        # enough that parent-expansion returns something coherent.
        return f"{doc.uri}#{' > '.join(path[:2])}"

    def emit() -> None:
        nonlocal ordinal, pending
        if not pending:
            return
        content = "\n\n".join(b.text for b in pending).strip()
        if content:
            chunks.append(Chunk(
                ordinal=ordinal,
                section_key=section_key(),
                heading_path=heading_path(),
                content=content,
                token_count=est_tokens(content),
                has_code=any(b.kind == "code" for b in pending),
                has_table=any(b.kind == "table" for b in pending),
            ))
            ordinal += 1
        pending = []

    for block in doc.blocks:
        if block.kind == "heading":
            emit()                                 # never span a heading boundary
            path = path[: block.level - 1]
            while len(path) < block.level - 1:
                path.append("")
            path.append(block.text)
            continue

        budget = sum(est_tokens(b.text) for b in pending) + est_tokens(block.text)

        if budget > MAX_CHUNK_TOKENS and pending:
            carry = _overlap_blocks(pending)        # prose-only overlap
            emit()
            pending = carry

        pending.append(block)

        # A single atomic block bigger than the budget becomes its own chunk
        # rather than being split. An oversized whole table beats two useless halves.
        if block.atomic and est_tokens(block.text) > MAX_CHUNK_TOKENS:
            emit()

    emit()
    return chunks


def _overlap_blocks(pending: list[Block]) -> list[Block]:
    """Carry a little trailing prose into the next chunk for continuity.

    Only prose. Repeating a code block or a table wastes budget and produces
    duplicate content that the assembly step then has to dedupe.
    """
    carry: list[Block] = []
    total = 0
    for block in reversed(pending):
        if block.atomic:
            break
        total += est_tokens(block.text)
        carry.insert(0, block)
        if total >= CHUNK_OVERLAP_TOKENS:
            break
    return carry


def load_corpus(directory: Path) -> list[tuple[Document, list[Chunk]]]:
    out = []
    for path in sorted(directory.glob("*.md")):
        doc = parse_document(path)
        out.append((doc, chunk_document(doc)))
    return out


# --- self-test ---------------------------------------------------------------
# The invariants that matter. If any of these break, retrieval quality silently
# degrades in a way no eval will attribute to the chunker.
if __name__ == "__main__":
    corpus = load_corpus(Path(__file__).parent / "corpus")
    assert corpus, "no documents found"

    total = 0
    for doc, chunks in corpus:
        assert chunks, f"{doc.uri} produced no chunks"
        for c in chunks:
            # 1. Fenced code blocks are balanced — never cut in half.
            assert c.content.count("```") % 2 == 0, \
                f"{doc.uri} ordinal {c.ordinal}: split a fenced code block"

            # 2. A table fragment never arrives without its header separator.
            table_lines = [l for l in c.content.splitlines() if TABLE_ROW.match(l)]
            if table_lines:
                assert any(set(l.replace("|", "").strip()) <= set("-: ")
                           for l in table_lines), \
                    f"{doc.uri} ordinal {c.ordinal}: table rows without a header row"

            # 3. Every chunk knows where it came from.
            assert c.heading_path.strip(), f"{doc.uri} ordinal {c.ordinal}: empty heading path"
            assert c.content.strip(), f"{doc.uri} ordinal {c.ordinal}: empty content"
        total += len(chunks)

    oversized = [(d.uri, c.ordinal, c.token_count)
                 for d, cs in corpus for c in cs if c.token_count > MAX_CHUNK_TOKENS]

    print(f"{len(corpus)} documents -> {total} chunks")
    print(f"oversized (atomic blocks kept whole, by design): {len(oversized)}")
    for uri, o, t in oversized:
        print(f"    {uri} #{o}: {t} tokens")

    doc, chunks = corpus[0]
    print(f"\nsample from {doc.uri}:")
    for c in chunks[:3]:
        print(f"  [{c.ordinal}] {c.token_count:>3}tok  {c.heading_path}")
        print(f"       {c.content.splitlines()[0][:72]}")

    print("\nall chunking invariants hold")
