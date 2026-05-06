import shutil
import subprocess
from pathlib import Path

import pytest

from tools.dsl_indexer import collect


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()

    monkeypatch.setattr(collect, "REPOS_DIR", repos_dir)
    monkeypatch.setattr(collect, "SOURCE_REPO_NAMES", ["acme"])

    repo = repos_dir / "acme"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    return repo


def test_gitignored_files_are_excluded(workspace):
    (workspace / "kept.md").write_text("kept")
    (workspace / "ignored.md").write_text("ignored")
    (workspace / ".gitignore").write_text("ignored.md\n")

    _git(workspace, "add", "kept.md", ".gitignore")
    _git(workspace, "commit", "-q", "-m", "init")

    files = collect.collect_source_files()
    names = {f.name for f in files}
    assert "kept.md" in names
    assert "ignored.md" not in names


def test_untracked_but_not_ignored_included(workspace):
    (workspace / "tracked.md").write_text("t")
    (workspace / ".gitignore").write_text("secret/\n")
    _git(workspace, "add", "tracked.md", ".gitignore")
    _git(workspace, "commit", "-q", "-m", "init")

    # Add a new untracked file that is NOT ignored.
    (workspace / "fresh.md").write_text("f")
    # And one that IS ignored.
    secret_dir = workspace / "secret"
    secret_dir.mkdir()
    (secret_dir / "leak.md").write_text("nope")

    files = collect.collect_source_files()
    names = {f.name for f in files}
    assert "tracked.md" in names
    assert "fresh.md" in names
    assert "leak.md" not in names


def test_nested_gitignore_respected(workspace):
    (workspace / "top.md").write_text("top")
    sub = workspace / "sub"
    sub.mkdir()
    (sub / ".gitignore").write_text("hidden.md\n")
    (sub / "shown.md").write_text("shown")
    (sub / "hidden.md").write_text("nope")
    _git(workspace, "add", "top.md", "sub/.gitignore", "sub/shown.md")
    _git(workspace, "commit", "-q", "-m", "init")

    files = collect.collect_source_files()
    names = {f.name for f in files}
    assert "top.md" in names
    assert "shown.md" in names
    assert "hidden.md" not in names
