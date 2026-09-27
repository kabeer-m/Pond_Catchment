"""
Unit tests for cache.py (SQLite-backed result cache + indexing).

CSD: Testing Strategy, exercising the Caching / DB Indexing module
directly against a throwaway on-disk SQLite file (never the real
analysis_cache.db), so tests can't corrupt real cached results.
"""

import time

import cache


def test_miss_then_hit(tmp_path):
    db_path = tmp_path / "test_cache.db"
    key = cache.make_key(b"file-bytes", {"top_n": 5})

    assert cache.get(key, db_path=db_path) is None  # miss

    cache.set(key, {"candidate_count": 2}, db_path=db_path)
    assert cache.get(key, db_path=db_path) == {"candidate_count": 2}  # hit


def test_different_params_produce_different_keys():
    key_a = cache.make_key(b"same-file", {"top_n": 5})
    key_b = cache.make_key(b"same-file", {"top_n": 10})
    assert key_a != key_b


def test_same_file_and_params_produce_the_same_key():
    key_a = cache.make_key(b"same-file", {"top_n": 5, "ranking": "flatness"})
    key_b = cache.make_key(b"same-file", {"ranking": "flatness", "top_n": 5})
    assert key_a == key_b  # key order in the dict must not matter


def test_purge_older_than_evicts_stale_rows(tmp_path):
    db_path = tmp_path / "test_cache.db"
    key = cache.make_key(b"old-file", {})
    cache.set(key, {"ok": True}, db_path=db_path)

    # Nothing older than a very large window -> nothing purged.
    assert cache.purge_older_than(10_000, db_path=db_path) == 0

    time.sleep(0.05)
    # Everything older than 0 seconds -> the row we just inserted is purged.
    assert cache.purge_older_than(0, db_path=db_path) == 1
    assert cache.get(key, db_path=db_path) is None
