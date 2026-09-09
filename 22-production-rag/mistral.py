"""Every model call in this system goes through here — all of them Mistral SDK.

  embed()  -> client.embeddings.create(model="mistral-embed")
  parse()  -> client.chat.parse(response_format=PydanticModel)   [typed output]
  chat()   -> client.chat.complete(...)                          [free text]

Two things worth knowing.

`chat.parse` emits a STRICT JSON schema derived from your Pydantic model, so the
models in this project are flat and all-required — `list[str]`, not nested objects,
no Optional. Strict schemas reject a lot of otherwise ordinary Python types.

OFFLINE MODE: with no MISTRAL_API_KEY, embed() falls back to a deterministic
hash-based vector so the schema, the SQL, and the whole retrieval funnel remain
testable without a key. Those vectors carry NO semantic meaning — lexical retrieval
still works properly, dense retrieval is noise. Everything prints a loud warning and
`OFFLINE` is exported so callers can refuse to draw conclusions from a degraded run.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from typing import TypeVar

from pydantic import BaseModel

from config import (BIG_MODEL, EMBED_BATCH, EMBED_DIM, EMBED_MODEL, MAX_RETRIES,
                    MISTRAL_API_KEY, SMALL_MODEL)

OFFLINE = not MISTRAL_API_KEY
T = TypeVar("T", bound=BaseModel)

if not OFFLINE:
    from mistralai.client import Mistral
    client = Mistral(api_key=MISTRAL_API_KEY)
else:
    client = None
    print("!! MISTRAL_API_KEY unset — offline mode. Embeddings are deterministic "
          "pseudo-vectors with no semantic meaning; dense retrieval will be noise.")


def _retry(fn, *, what: str):
    """Exponential backoff. Ingest without this fails halfway through on a 429."""
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except Exception as e:                       # noqa: BLE001 — provider-agnostic
            if attempt == MAX_RETRIES - 1:
                raise
            wait = 2 ** attempt
            print(f"    {what} failed ({type(e).__name__}), retrying in {wait}s")
            time.sleep(wait)


# --- embeddings --------------------------------------------------------------

def _fake_embedding(text: str) -> list[float]:
    """Deterministic unit vector from a hash. Same text -> same vector, always."""
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(EMBED_DIM)]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(texts: list[str]) -> list[list[float]]:
    """Batched embeddings. Batching matters: one call per chunk is the usual
    reason an ingest that should take 20 seconds takes 10 minutes."""
    if OFFLINE:
        return [_fake_embedding(t) for t in texts]

    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i:i + EMBED_BATCH]
        resp = _retry(
            lambda: client.embeddings.create(model=EMBED_MODEL, inputs=batch),
            what=f"embed batch {i // EMBED_BATCH}",
        )
        out.extend(d.embedding for d in resp.data)

    for v in out:
        assert len(v) == EMBED_DIM, f"expected {EMBED_DIM} dims, got {len(v)}"
    return out


# --- typed output ------------------------------------------------------------

def parse(model_cls: type[T], system: str, user: str, *, small: bool = False) -> T | None:
    """Structured output via the SDK's own Pydantic integration.

    Returns None offline, or when the model produces something unparseable —
    callers must degrade rather than crash.
    """
    if OFFLINE:
        return None
    resp = _retry(lambda: client.chat.parse(
        model=SMALL_MODEL if small else BIG_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format=model_cls,
        temperature=0,
    ), what=f"parse {model_cls.__name__}")
    return resp.choices[0].message.parsed


# --- free text ---------------------------------------------------------------

def chat(system: str, user: str, *, small: bool = False, temperature: float = 0.0) -> str:
    if OFFLINE:
        return "[offline: no model output]"
    resp = _retry(lambda: client.chat.complete(
        model=SMALL_MODEL if small else BIG_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temperature,
    ), what="chat")
    return resp.choices[0].message.content
