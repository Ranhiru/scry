import pytest

from tools.dsl_indexer import embedding_cache


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(embedding_cache, "EMBEDDING_CACHE_PATH", tmp_path / "cache.sqlite")


def test_put_and_get_roundtrip():
    embedding_cache.put_many([("h1", [0.1, 0.2, 0.3])], model="m", dimension=3)
    out = embedding_cache.get_many(["h1", "missing"], model="m", dimension=3)
    assert "h1" in out
    assert out["h1"] == pytest.approx([0.1, 0.2, 0.3], rel=1e-6)
    assert "missing" not in out


def test_model_dimension_mismatch_skipped():
    embedding_cache.put_many([("h1", [0.5])], model="modelA", dimension=1)
    out = embedding_cache.get_many(["h1"], model="modelB", dimension=1)
    assert out == {}
    out = embedding_cache.get_many(["h1"], model="modelA", dimension=2)
    assert out == {}


def test_wipe_removes_all_rows():
    embedding_cache.put_many([("h1", [0.0]), ("h2", [1.0])], model="m", dimension=1)
    assert embedding_cache.row_count() == 2
    embedding_cache.wipe()
    assert embedding_cache.row_count() == 0


def test_gc_drops_unreferenced():
    embedding_cache.put_many([("keep", [0.0]), ("drop", [1.0])], model="m", dimension=1)
    removed = embedding_cache.gc(["keep"])
    assert removed == 1
    out = embedding_cache.get_many(["keep", "drop"], model="m", dimension=1)
    assert "keep" in out and "drop" not in out


def test_purge_stale_drops_mismatched_only():
    embedding_cache.put_many([("h1", [0.5])], model="modelA", dimension=1)
    embedding_cache.put_many([("h2", [0.6])], model="modelB", dimension=1)
    removed = embedding_cache.purge_stale(model="modelA", dimension=1)
    assert removed == 1
    assert embedding_cache.row_count() == 1


def test_hash_content_stable():
    assert embedding_cache.hash_content("abc") == embedding_cache.hash_content("abc")
    assert embedding_cache.hash_content("abc") != embedding_cache.hash_content("abd")
