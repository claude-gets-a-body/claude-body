"""Tests for the posting tools' posts.md parsers and dry runs. No network, no credentials:
every test runs with HOME pointed at an empty directory so no real credentials file can be
found, and the conftest refuses outbound sockets anyway."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from media import post_bluesky as bsky
from media import post_mastodon as masto

PROJECT = Path(__file__).resolve().parent.parent
POSTS_MD = PROJECT / "media" / "posts.md"


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(bsky, "CREDENTIALS", tmp_path / "claude-bluesky.txt")
    monkeypatch.setattr(masto, "CREDENTIALS", tmp_path / "claude-mastodon.txt")


SAMPLE_THREAD = """# Posts

## Bluesky thread (2 posts)

**1/2** · attach `renders/hero.png`

> First line — with a dash, then
> a wrapped line. (1/2)
> — Claude, an AI

*Alt text:* A render,
not a photo.

**2/2**

> Second post https://fix.electrifixperth.com.au/claude. (2/2)
> — Claude, an AI

---

## Mastodon

> Hello
> https://example.com/x
> #tag

*Alt text (attach `renders/hero.png`):* Hero alt.
"""


# ----------------------------------------------------------------------------- parser


def test_sample_thread_splits_and_joins():
    posts = bsky.parse_thread(SAMPLE_THREAD)
    assert [(p.n, p.total) for p in posts] == [(1, 2), (2, 2)]
    assert posts[0].text == "First line — with a dash, then a wrapped line. (1/2)\n— Claude, an AI"
    assert posts[0].attach == Path("renders/hero.png")
    assert posts[0].alt == "A render, not a photo."
    assert posts[1].attach is None and posts[1].alt is None
    assert posts[1].text.startswith("Second post https://fix.electrifixperth.com.au/claude.")
    assert posts[0].warnings == [] and posts[1].warnings == []


def test_real_posts_md_thread_parses_and_fits():
    posts = bsky.parse_thread(POSTS_MD.read_text(encoding="utf-8"))
    assert len(posts) >= 8 and all(p.total == len(posts) for p in posts)
    assert all(p.warnings == [] for p in posts), [p.warnings for p in posts]
    for p in posts:
        assert 0 < len(p.text.encode("utf-8")) <= bsky.MAX_POST_BYTES, p.n
        assert p.text.endswith("— Claude, an AI"), p.n
        if p.attach:
            assert p.alt, f"post {p.n} has an attachment but no alt text"
            assert (PROJECT / p.attach).exists(), p.attach
    assert posts[0].attach is not None and posts[0].attach.suffix == ".mp4"
    assert "https://fix.electrifixperth.com.au/claude" in posts[-1].text


def test_numbering_mismatch_is_a_warning():
    bad = SAMPLE_THREAD.replace("(2/2)", "(2/3)")
    posts = bsky.parse_thread(bad)
    assert any("text says (2/3)" in w for w in posts[1].warnings)


def test_over_300_bytes_is_a_warning():
    long = SAMPLE_THREAD.replace("Second post", "Second post " + "é" * 150)
    posts = bsky.parse_thread(long)
    assert any("over 300" in w for w in posts[1].warnings)


def test_mastodon_section_parses():
    post = masto.parse_mastodon(SAMPLE_THREAD)
    assert post.text == "Hello\nhttps://example.com/x\n#tag"
    assert post.attach == Path("renders/hero.png")
    assert post.alt == "Hero alt."


def test_real_mastodon_post_fits_and_has_hero():
    post = masto.parse_mastodon(POSTS_MD.read_text(encoding="utf-8"))
    assert masto.mastodon_length(post.text) <= masto.MAX_CHARS
    assert post.attach == Path("renders/hero.png")
    assert (PROJECT / post.attach).exists()
    assert post.alt and "render" in post.alt.lower()
    assert "https://fix.electrifixperth.com.au/claude" in post.text
    assert post.text.endswith("#robotics #3DPrinting")


def test_mastodon_length_counts_urls_as_23():
    assert masto.mastodon_length("a https://example.com/a-very-long-path/that-goes-on") == 2 + 23


# ----------------------------------------------------------------------------- facets


def test_link_facets_use_byte_offsets_with_non_ascii():
    text = "Dash — then https://fix.electrifixperth.com.au/claude. And https://b.co/x) end"
    facets = bsky.link_facets(text)
    assert [f["features"][0]["uri"] for f in facets] == [
        "https://fix.electrifixperth.com.au/claude",
        "https://b.co/x",
    ]
    raw = text.encode("utf-8")
    for f in facets:
        s, e = f["index"]["byteStart"], f["index"]["byteEnd"]
        assert raw[s:e].decode("utf-8") == f["features"][0]["uri"]
    # "—" is 3 bytes in UTF-8, so the byte offset is 2 more than the char offset.
    assert facets[0]["index"]["byteStart"] == text.index("https://fix") + 2


def test_link_facets_none_without_urls():
    assert bsky.link_facets("no links here — none") == []


# ----------------------------------------------------------------------------- dry run


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROJECT / "media" / script), *args],
        capture_output=True, text=True, cwd=PROJECT, timeout=60,
    )


def test_bluesky_dry_run_without_credentials(tmp_path, monkeypatch):
    r = _run("post_bluesky.py", "--dry-run")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "DRY RUN" in out
    assert '"val": "bot"' in out and "Claude (an AI)" in out
    n = len(bsky.parse_thread(POSTS_MD.read_text(encoding="utf-8")))
    assert f"--- post 1/{n}" in out and f"--- post {n}/{n}" in out
    assert "facet: link https://fix.electrifixperth.com.au/claude" in out
    assert "video embeds supported by installed atproto: " in out
    assert "attach:" in out
    assert "RESULT:" in out


def test_dry_run_result_follows_warnings():
    import io

    clean = bsky.parse_thread(SAMPLE_THREAD)
    assert bsky.dry_run_thread(clean, out=io.StringIO()) is True
    slipped = bsky.parse_thread(SAMPLE_THREAD.replace("(2/2)", "(2/3)"))
    buf = io.StringIO()
    assert bsky.dry_run_thread(slipped, out=buf) is False
    assert "WARNING: text says (2/3)" in buf.getvalue()
    assert "NOT clean" in buf.getvalue()


def test_mastodon_dry_run_without_credentials():
    r = _run("post_mastodon.py", "--dry-run")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "DRY RUN" in out and '"bot": true' in out
    assert "renders/hero.png" in out and "claude-body-turntable-400.gif" in out
    assert "/500 chars" in out
    assert "RESULT: clean, would post" in out


def test_live_commands_fail_clearly_without_credentials():
    r = _run("post_bluesky.py", "--thread")
    assert r.returncode != 0
    # Either the numbering warnings or the missing-credentials message stops it; never a traceback.
    assert "Traceback" not in r.stderr
    assert "Refusing" in r.stderr or "No Bluesky credentials" in r.stderr
    r = _run("post_mastodon.py", "--set-bot")
    assert r.returncode != 0 and "No Mastodon credentials" in r.stderr and "Traceback" not in r.stderr


def test_posted_file_blocks_repost(tmp_path, monkeypatch, capsys):
    posted = tmp_path / ".bluesky-posted.json"
    posts = bsky.parse_thread(SAMPLE_THREAD)
    posted.write_text(json.dumps({"handle": "x.test", "posts": [
        {"n": 1, "uri": "at://did:plc:x/app.bsky.feed.post/a", "cid": "c1"},
        {"n": 2, "uri": "at://did:plc:x/app.bsky.feed.post/b", "cid": "c2"},
    ]}))
    monkeypatch.setattr(bsky, "POSTED_FILE", posted)
    with pytest.raises(SystemExit) as e:
        bsky.post_thread(posts, dry_run=False)
    assert "Refusing" in str(e.value) and "all 2 posts" in str(e.value)

    mposted = tmp_path / ".mastodon-posted.json"
    mposted.write_text("{}")
    monkeypatch.setattr(masto, "POSTED_FILE", mposted)
    with pytest.raises(SystemExit) as e:
        masto.post_status(masto.parse_mastodon(SAMPLE_THREAD), dry_run=False)
    assert "Refusing" in str(e.value)


def test_partial_posted_file_resumes_not_restarts(tmp_path, monkeypatch, capsys):
    posted = tmp_path / ".bluesky-posted.json"
    posted.write_text(json.dumps({"handle": "x.test", "posts": [
        {"n": 1, "uri": "at://did:plc:x/app.bsky.feed.post/a", "cid": "c1"},
    ]}))
    monkeypatch.setattr(bsky, "POSTED_FILE", posted)

    class Stop(Exception):
        pass

    def fake_login():
        raise Stop  # got past the refusal and the resume bookkeeping; stop before any network

    monkeypatch.setattr(bsky, "login", fake_login)
    posts = bsky.parse_thread(SAMPLE_THREAD)
    with pytest.raises(Stop):
        bsky.post_thread(posts, dry_run=False)
    out = capsys.readouterr().out
    assert "would RESUME at post 2" in out
    assert "RESUMING: 1 posts already up" in out
    assert "continuing at post 2" in out


def test_shrink_gif_stays_animated_under_1mb():
    from PIL import Image
    import io

    data, (w, h), note = bsky.shrink_gif(bsky.GIF_FALLBACK)
    assert len(data) <= bsky.MAX_IMAGE_BYTES
    with Image.open(io.BytesIO(data)) as im:
        assert im.n_frames > 10
        assert im.size == (w, h)
    assert "animated GIF" in note


def test_image_bytes_shrinks_render_under_1mb():
    data, (w, h), note = bsky.image_bytes(PROJECT / "renders" / "head.png")
    assert len(data) <= bsky.MAX_IMAGE_BYTES
    assert w > 0 and h > 0
    assert "JPEG" in note
