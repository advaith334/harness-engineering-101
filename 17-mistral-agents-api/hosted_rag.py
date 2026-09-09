"""Hosted RAG — upload documents to a library, give an agent the document_library tool.

This replaces folders 05 and 06 entirely: no chunking, no embedding calls, no vector
store, no reranker. Mistral ingests and retrieves.

Use it when you need RAG working in ten minutes. Build 05/06 by hand when you need
control over chunk boundaries, hybrid search, or reranking — i.e. when retrieval
quality is the thing you're optimizing.
"""

import os
import tempfile
from pathlib import Path

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


def sample_docs() -> list[Path]:
    d = Path(tempfile.mkdtemp(prefix="lib-"))
    (d / "refunds.md").write_text(
        "# Refunds\nMonthly plans: refundable within 14 days of a charge.\n"
        "Annual plans: refundable pro-rata within 30 days.\n")
    (d / "limits.md").write_text(
        "# Rate limits\nFree: 60 req/min. Pro: 600 req/min.\n"
        "Exceeding a limit returns HTTP 429 with Retry-After.\n")
    return list(d.iterdir())


if __name__ == "__main__":
    # 1. A library is the managed index.
    library = client.beta.libraries.create(
        name="support-kb",
        description="Customer-facing policy and product documentation.",
    )
    print("library:", library.id)

    # 2. Upload. Ingestion (parse -> chunk -> embed -> index) happens server-side.
    for path in sample_docs():
        with open(path, "rb") as fh:
            doc = client.beta.libraries.documents.upload(
                library_id=library.id,
                file={"file_name": path.name, "content": fh.read()},
            )
        print("  uploaded:", doc.name)

    # 3. An agent pointed at the library.
    agent = client.beta.agents.create(
        model=MODEL,
        name="support-kb-agent",
        instructions="Answer only from the document library. Cite the document. "
                     "If it isn't there, say so.",
        tools=[{"type": "document_library", "library_ids": [library.id]}],
    )

    for q in ["I'm on annual and cancelled after 3 weeks — refund?",
              "What happens if I exceed my rate limit?"]:
        convo = client.beta.conversations.start(agent_id=agent.id, inputs=q)
        print(f"\nQ: {q}")
        for entry in convo.outputs:
            print(f"  [{entry.type}] {str(entry)[:220]}")

# Note: ingestion is async. For real corpora poll
# client.beta.libraries.documents.status(library_id=..., document_id=...)
# before querying, or the first answers will come back empty.
