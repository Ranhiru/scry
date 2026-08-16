import pytest

from tools.workspace_config import _coerce_chunking


def test_defaults_when_absent():
    cfg = _coerce_chunking(None)
    assert cfg.default_profile == "text"
    assert cfg.resolve(".md")[0].strategy == "markdown"
    assert cfg.resolve(".py") == (cfg.profiles["code"], "python")
    # Unmapped extensions fall through to the default profile.
    assert cfg.resolve(".csproj") == (cfg.profiles["text"], None)


def test_partial_profile_override_keeps_other_defaults():
    cfg = _coerce_chunking({"profiles": {"code": {"target_size": 2000}}})
    profile = cfg.profiles["code"]
    assert profile.strategy == "code"
    assert profile.target_size == 2000
    assert profile.hard_max_size == 4000
    assert cfg.profiles["text"] == _coerce_chunking(None).profiles["text"]


def test_rules_replace_wholesale():
    cfg = _coerce_chunking({"rules": [{"extensions": [".rst"], "profile": "markdown"}]})
    assert cfg.resolve(".rst")[0].strategy == "markdown"
    assert cfg.resolve(".md")[0].strategy == "text"


@pytest.mark.parametrize(
    "raw",
    [
        ["not", "a", "mapping"],
        {"profiles": []},
        {"profiles": {"text": "nope"}},
        {"profiles": {"text": {"overlap_chars": 100}}},
        {"profiles": {"text": {"strategy": "tree_sitter"}}},
        {"profiles": {"text": {"target_size": 0}}},
        {"profiles": {"text": {"target_size": 1000, "hard_max_size": 500}}},
        {"profiles": {"text": {"target_size": 1000, "overlap": 1000}}},
        {"default_profile": "nope"},
        {"rules": {}},
        {"rules": [{"extensions": [".md"], "profile": "nope"}]},
        {"rules": [{"extensions": [".py"], "profile": "code"}]},
        {"rules": [{"extensions": [".md"], "profile": "markdown", "language": "python"}]},
        {"rules": [{"profile": "markdown"}]},
        {
            "rules": [
                {"extensions": [".md"], "profile": "markdown"},
                {"extensions": [".md"], "profile": "text"},
            ]
        },
    ],
)
def test_invalid_config_rejected(raw):
    with pytest.raises(ValueError):
        _coerce_chunking(raw)
