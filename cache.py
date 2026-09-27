"""
cache.py
--------
Result cache for /analyzeContour requests, backed by SQLite.

Why a cache at all: DEM interpolation + D8 flow accumulation (terrain.py)
is the most expensive part of a request. Villages re-upload the same
contour map repeatedly while a field officer tunes footprint/slope
parameters one value at a time, and dashboards may poll the same
site+params combination on a schedule. Caching the full JSON response
against a hash of (file bytes + analysis parameters) turns all of those
repeat calls into a single indexed lookup instead of a full re-run of
terrain.py + pond_finder.py.

Design notes (CSD: Caching, Database Indexing / Query Optimization):
- `request_hash` is a SHA-256 digest of the uploaded file bytes plus the
  sorted analysis parameters, so identical (file, params) pairs collide
  and different ones don't -- this is the cache key.
- `request_hash` is declared PRIMARY KEY, so SQLite maintains a unique
  B-tree index on it automatically: a cache hit is an O(log n) index
  seek, not a table scan, even as the cache grows.
- A second, explicit index on `created_at` supports the cache's eviction
  query (`purge_older_than`), which would otherwise be a full table scan
  every time it ran.
- This module only knows about hashing/storing/retrieving opaque JSON
  strings -- it has no idea what a DEM or a pond candidate is, so it can
  be reused by any endpoint that wants a "compute once, look up after"
  cache (kept modular from terrain.py / pond_finder.py).
"""

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

# Overridable via environment variable for persistent storage path.
DB_PATH = Path(os.environ.get("POND_CACHE_DB_PATH", Path(__file__).parent / "analysis_cache.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_cache (
    request_hash TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_created_at
    ON analysis_cache (created_at);
"""


@contextmanager
def _connect(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def make_key(file_bytes: bytes, params: dict) -> str:
    """Deterministic cache key for a given upload + analysis parameters."""
    hasher = hashlib.sha256()
    hasher.update(file_bytes)
    hasher.update(json.dumps(params, sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()


def get(request_hash: str, db_path: Path = DB_PATH) -> dict | None:
    """Return the cached response dict, or None on a cache miss."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT response_json FROM analysis_cache WHERE request_hash = ?",
            (request_hash,),
        ).fetchone()
    return json.loads(row[0]) if row else None


def set(request_hash: str, response: dict, db_path: Path = DB_PATH) -> None:
    """Store (or overwrite) a response under the given cache key."""
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO analysis_cache (request_hash, response_json, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(request_hash) DO UPDATE SET
                   response_json = excluded.response_json,
                   created_at = excluded.created_at""",
            (request_hash, json.dumps(response), time.time()),
        )


def purge_older_than(max_age_seconds: float, db_path: Path = DB_PATH) -> int:
    """Evict cache rows older than max_age_seconds. Uses the created_at index."""
    cutoff = time.time() - max_age_seconds
    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM analysis_cache WHERE created_at < ?", (cutoff,)
        )
        return cur.rowcount


def stats(db_path: Path = DB_PATH) -> dict:
    """Small helper for a /cacheStats admin endpoint or tests."""
    with _connect(db_path) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM analysis_cache").fetchone()
    return {"entries": count, "db_path": str(db_path)}
