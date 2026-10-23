"""The memory tool backend: works on a real folder, refuses anything outside it."""

import os

import pytest

from mind.memory_tool import MemoryStore

ESCAPES = [
    "/etc/passwd",
    "/memories/../secrets.txt",
    "/memories/people/../../outside.md",
    "/memories/..",
    "/memories/%2e%2e/x",          # not decoded, so it's just an odd (allowed?) name -> must stay inside
    "/memoriesX/evil.md",
    "memories/relative.md",
    "/memories/a\\..\\b.md",
    "/memories/nul\x00.md",
    "/memories/.history/peek.md",
    "",
]


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "memories"
    s = MemoryStore(root)
    (tmp_path / "secrets.txt").write_text("top secret")
    return s


@pytest.mark.parametrize("path", ESCAPES)
def test_path_traversal_rejected(store, tmp_path, path):
    text, is_error = store.run({"command": "create", "path": path, "file_text": "pwned"})
    if path == "/memories/%2e%2e/x":
        # a literal folder called "%2e%2e" inside the root is harmless
        assert not is_error and (store.root / "%2e%2e" / "x").read_text() == "pwned"
        return
    assert is_error, f"{path!r} should be refused, got {text!r}"
    assert (tmp_path / "secrets.txt").read_text() == "top secret"
    assert not (tmp_path / "outside.md").exists()
    for cmd in ({"command": "view", "path": path},
                {"command": "delete", "path": path},
                {"command": "str_replace", "path": path, "old_str": "a", "new_str": "b"}):
        assert store.run(cmd)[1], f"{cmd} should be refused"


def test_rename_cannot_escape(store, tmp_path):
    store.run({"command": "create", "path": "/memories/a.md", "file_text": "x"})
    _, is_error = store.run({"command": "rename", "old_path": "/memories/a.md", "new_path": "/memories/../a.md"})
    assert is_error and (store.root / "a.md").exists() and not (tmp_path / "a.md").exists()


def test_symlink_pointing_outside_is_refused(store, tmp_path):
    os.symlink(tmp_path, store.root / "link")
    text, is_error = store.run({"command": "view", "path": "/memories/link/secrets.txt"})
    assert is_error and "outside" in text


def test_normal_use_and_backups(store):
    assert store.run({"command": "create", "path": "/memories/people/sam.md", "file_text": "# Sam\nlikes: dinosaurs\n"}) \
        == ("Saved /memories/people/sam.md.", False)
    text, err = store.run({"command": "view", "path": "/memories/people/sam.md"})
    assert not err and "dinosaurs" in text
    assert store.run({"command": "str_replace", "path": "/memories/people/sam.md",
                      "old_str": "dinosaurs", "new_str": "dinosaurs and space"})[1] is False
    assert store.run({"command": "insert", "path": "/memories/people/sam.md", "insert_line": 1,
                      "insert_text": "age: 8"})[1] is False
    listing, _ = store.run({"command": "view", "path": "/memories"})
    assert "/memories/people/sam.md" in listing and ".history" not in listing
    assert store.run({"command": "delete", "path": "/memories/people/sam.md"})[1] is False
    backups = list((store.root / ".history").iterdir())
    assert len(backups) >= 3, "every overwrite/delete keeps the old version"
    assert store.run({"command": "delete", "path": "/memories"})[1] is True


def test_seed_does_not_overwrite(store, tmp_path):
    template = tmp_path / "template"
    template.mkdir()
    (template / "INDEX.md").write_text("template index")
    store.run({"command": "create", "path": "/memories/INDEX.md", "file_text": "Nick's edits"})
    store.seed_from(template)
    assert store.read_text("/memories/INDEX.md") == "Nick's edits"


def test_tool_param_is_the_anthropic_memory_tool(store):
    assert store.to_dict() == {"type": "memory_20250818", "name": "memory"}
