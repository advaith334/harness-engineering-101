"""Connection handling for Neon, with the three things that actually bite.

  1. register_vector() on EVERY new connection — AND wrap the list in Vector().
     register_vector teaches psycopg how to READ a vector back; it does not make
     a bare Python list adapt on the way in. A plain list binds as float8[] and
     you get "operator does not exist: vector <=> double precision[]". Always
     pass Vector(values). This module re-exports it so callers can't forget.
  2. prepare_threshold=None. Neon's pooled endpoints are PgBouncer in transaction
     mode; psycopg3 starts using server-side prepared statements after the 5th
     execution of a query, and ingest then fails PARTWAY THROUGH — the confusing
     kind of failure where the first few hundred rows worked.
  3. Connect with retry. Neon autosuspends after ~5 minutes idle, so the first
     query after a pause can time out while the compute wakes.

POOLING. The first version of this opened a fresh connection per operation. Against
a remote database that is a TLS handshake every time, and the 15-question eval took
over six minutes with the work itself being milliseconds. A pool fixes it while
keeping connections short-lived from the caller's point of view: `check` validates a
connection before handing it out, so a link dropped during a Neon autosuspend is
replaced rather than returned broken.
"""

import time
from contextlib import contextmanager
from pathlib import Path

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from config import DATABASE_URL, MAX_RETRIES

__all__ = ["connect", "bootstrap", "build_indexes", "Vector"]

HERE = Path(__file__).parent


_POOL: ConnectionPool | None = None


def _configure(conn) -> None:
    """Runs ONCE per physical connection, including pool replacements.

    register_vector costs ~3.5s against a remote database — it is a catalog
    lookup for the type OID, several round trips. Calling it per borrow rather
    than per physical connection was making a 15-question eval take seven
    minutes with the actual work being milliseconds. Measure before you assume
    the network is the problem.
    """
    try:
        register_vector(conn)          # see note 1 above
    except psycopg.ProgrammingError:
        pass                           # extension not created yet — bootstrap path


def _pool() -> ConnectionPool:
    global _POOL
    if _POOL is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is unset — run ./setup_neon.sh or fill in .env")
        _POOL = ConnectionPool(
            DATABASE_URL,
            min_size=1, max_size=8,
            kwargs={"prepare_threshold": None},   # see note 2 above
            configure=_configure,
            check=ConnectionPool.check_connection,  # drop dead links from autosuspend
            timeout=30,
            open=True,
        )
    return _POOL


@contextmanager
def connect(require_vector: bool = True):
    """A connection with pgvector registered. Retries through a Neon cold start.

    `require_vector=False` is for the one call that has to happen BEFORE the
    extension exists — bootstrap() creating it. Registering the vector adapter
    against a database with no `vector` type raises, so bootstrap opts out.
    """
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with _pool().connection() as conn:
                # No register_vector here on purpose — see _configure.
                yield conn
            return
        except psycopg.OperationalError as e:      # compute waking from autosuspend
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not reach Neon after {MAX_RETRIES} tries: {last}")


def apply_sql_file(name: str, require_vector: bool = True) -> None:
    """Run one of the .sql files next to this module. Both are idempotent."""
    sql = (HERE / name).read_text()
    with connect(require_vector=require_vector) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print(f"  applied {name}")


def bootstrap() -> None:
    # schema.sql is what CREATEs the extension, so it cannot require it first.
    apply_sql_file("schema.sql", require_vector=False)
    _reset_pool()   # connections opened before the extension existed can't bind vectors


def _reset_pool() -> None:
    """Drop pooled connections so _configure re-runs with the extension present."""
    global _POOL
    if _POOL is not None:
        _POOL.close()
        _POOL = None


def build_indexes() -> None:
    apply_sql_file("indexes.sql")


# --- smoke test: the first thing to run against a new database ---------------
if __name__ == "__main__":
    import random

    with connect(require_vector=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        print("postgres:", cur.fetchone()[0].split(",")[0])
        cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
        row = cur.fetchone()
        print("pgvector:", row[0] if row else "NOT INSTALLED (run bootstrap first)")

    bootstrap()

    # Prove the round trip: insert a real vector, get it back by cosine distance.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE _smoke (id int, embedding vector(1024));
        """)
        vec = Vector([random.random() for _ in range(1024)])
        cur.execute("INSERT INTO _smoke VALUES (1, %s)", (vec,))
        cur.execute("SELECT id, embedding <=> %s AS distance FROM _smoke", (vec,))
        rid, dist = cur.fetchone()
        print(f"vector round trip: id={rid} self-distance={dist:.6f} (expect ~0)")
        assert dist < 1e-6, "cosine distance to self should be zero"

    build_indexes()
    print("\nOK — schema, extension, vector binding and indexes all good.")
