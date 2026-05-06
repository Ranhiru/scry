import os
from pathlib import Path

import pytest

from tools.dsl_indexer import manifest as manifest_mod
from tools.dsl_indexer.manifest import FileEntry, classify, empty_manifest, hash_file, serialize


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture
def repo_root(tmp_path, monkeypatch):
    repos_dir = tmp_path / "repos"
    monkeypatch.setattr(manifest_mod, "REPOS_DIR", repos_dir)
    monkeypatch.setattr(manifest_mod, "REPO_TYPE_MAP", {"acme": "spec"})
    repos_dir.mkdir()
    repo = repos_dir / "acme"
    repo.mkdir()
    return repo


def test_classify_added(repo_root):
    f = repo_root / "docs" / "intro.md"
    _write(f, "hello world")
    diff = classify([f], empty_manifest())
    assert len(diff.added) == 1
    assert diff.added[0] == f
    assert not diff.modified and not diff.unchanged and not diff.deleted


def test_classify_unchanged_via_stat(repo_root):
    f = repo_root / "a.md"
    _write(f, "stable content")
    entry = manifest_mod.build_entry(f, ["chunk-1"])
    manifest = serialize({entry.rel_path: entry})

    diff = classify([f], manifest)
    assert len(diff.unchanged) == 1
    assert diff.unchanged[0].chunk_ids == ["chunk-1"]
    assert not diff.modified and not diff.added and not diff.deleted


def test_classify_touched_but_unchanged(repo_root):
    f = repo_root / "a.md"
    _write(f, "stable content")
    entry = manifest_mod.build_entry(f, ["chunk-1"])
    manifest = serialize({entry.rel_path: entry})

    # Bump mtime without changing content.
    new_mtime = entry.mtime_ns + 5_000_000_000
    os.utime(f, ns=(new_mtime, new_mtime))

    diff = classify([f], manifest)
    assert len(diff.unchanged) == 1
    assert diff.unchanged[0].chunk_ids == ["chunk-1"]
    # The unchanged entry should reflect the refreshed mtime.
    assert diff.unchanged[0].mtime_ns == new_mtime


def test_classify_modified(repo_root):
    f = repo_root / "a.md"
    _write(f, "v1")
    entry = manifest_mod.build_entry(f, ["chunk-old"])
    manifest = serialize({entry.rel_path: entry})

    _write(f, "v2 different content")
    diff = classify([f], manifest)
    assert len(diff.modified) == 1
    old_entry, path = diff.modified[0]
    assert old_entry.chunk_ids == ["chunk-old"]
    assert path == f
    assert not diff.unchanged and not diff.added and not diff.deleted


def test_classify_deleted(repo_root):
    f = repo_root / "ghost.md"
    _write(f, "soon to vanish")
    entry = manifest_mod.build_entry(f, ["chunk-x", "chunk-y"])
    manifest = serialize({entry.rel_path: entry})
    f.unlink()

    diff = classify([], manifest)
    assert len(diff.deleted) == 1
    assert diff.deleted[0].chunk_ids == ["chunk-x", "chunk-y"]


def test_hash_file_deterministic(repo_root):
    f = repo_root / "a.txt"
    _write(f, "abc")
    assert hash_file(f) == hash_file(f)


def test_diff_has_changes(repo_root):
    f = repo_root / "a.md"
    _write(f, "x")
    diff = classify([f], empty_manifest())
    assert diff.has_changes
    diff = classify([], empty_manifest())
    assert not diff.has_changes


def test_file_entry_round_trip():
    entry = FileEntry(
        repo="acme",
        repo_type="spec",
        rel_path="acme/x.md",
        size=10,
        mtime_ns=1_000,
        sha256="abc",
        chunk_ids=["c1", "c2"],
    )
    other = FileEntry.from_dict(entry.to_dict())
    assert other == entry
