"""Every tunable in one place — models, vector dimension, and the k at each funnel stage.

A retrieval funnel is defined by its narrowing ratios. Having them scattered across
three modules is how you end up reranking 8 candidates down to 8.
"""

import os
from pathlib import Path

# --- env ---------------------------------------------------------------------
# Minimal .env loader; avoids a python-dotenv dependency for four lines of work.
_ENV = Path(__file__).parent / ".env"
if _ENV.exists():
    for line in _ENV.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

DATABASE_URL = os.environ.get("DATABASE_URL", "")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")

# --- models (all Mistral) ----------------------------------------------------
EMBED_MODEL = "mistral-embed"
EMBED_DIM = 1024          # mistral-embed is fixed at 1024; ingest asserts this
BIG_MODEL = "mistral-medium-latest"    # planner, synthesis
SMALL_MODEL = "mistral-small-latest"   # rerank, enrichment, judge — high volume, cheap

# --- chunking ----------------------------------------------------------------
MAX_CHUNK_TOKENS = 400    # ~1600 chars; big enough to hold a whole procedure step
CHUNK_OVERLAP_TOKENS = 60 # overlap applies only WITHIN a section, never across headings

# --- the funnel's narrowing ratios -------------------------------------------
PREFILTER_FLOOR = 15      # below this many candidates, relax the filter and re-run
CANDIDATES_PER_ARM = 20   # top-N each of the 3 retrieval arms contributes to fusion
FUSED_K = 24              # survivors of reciprocal rank fusion
RERANK_KEEP = 8           # what the reranker hands to assembly
ASSEMBLY_TOKEN_BUDGET = 6000   # hard cap on assembled context

RRF_K = 60                # the standard RRF constant

# --- ingest ------------------------------------------------------------------
EMBED_BATCH = 32
MAX_RETRIES = 5
