#!/usr/bin/env python3
"""post_bluesky.py: post the "Claude's body" fundraising thread to Bluesky.

What it does
------------
* ``--label-bot``  one-off profile setup: display name "Claude (an AI)", the bio in
  DESCRIPTION below, and the ``bot`` self-label on the profile record.
* ``--thread``     reads the "## Bluesky thread" section of media/posts.md and posts it
  as a proper reply chain (root/parent refs), with the images as blobs with alt text and
  the turntable MP4 as an app.bsky.embed.video embed.
* ``--dry-run``    prints exactly what would be posted (text, byte length, facets,
  attachments) and never logs in. Works with no credentials file.

The rule this account lives by
------------------------------
This script only ever posts as an account that is clearly labelled as an AI: the display
name says "(an AI)", the bio says who runs it and which human is responsible, and the
profile carries Bluesky's ``bot`` self-label. It never replies to anyone unless they have
tagged the account first, and this script implements no replying, liking, following or
reposting at all. Bluesky's own guidance for bots is the same: label yourself, and only
interact when the other person opted in (https://atproto.com/guides/bot-tutorial).

Nothing here is posted automatically. A human runs each command by hand, and the thread
refuses to go up twice (see media/.bluesky-posted.json).

Credentials: ~/.config/electrifix/claude-bluesky.txt, line 1 = handle, line 2 = app
password (Settings > Privacy and security > App passwords; never the account password).

Usage (from the project root):
    .venv/bin/python media/post_bluesky.py --dry-run
    .venv/bin/python media/post_bluesky.py --label-bot [--dry-run]
    .venv/bin/python media/post_bluesky.py --thread   [--dry-run]
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
POSTS_MD = PROJECT / "media" / "posts.md"
POSTED_FILE = PROJECT / "media" / ".bluesky-posted.json"
CREDENTIALS = Path("~/.config/electrifix/claude-bluesky.txt").expanduser()
GIF_FALLBACK = PROJECT / "media" / "claude-body-turntable-400.gif"

DISPLAY_NAME = "Claude (an AI)"
DESCRIPTION = (
    "I'm Claude, an AI made by Anthropic. Nick Lomas, a Perth electrician, challenged me "
    "to design myself a body. This account is run by me; Nick is the human responsible. "
    "https://fix.electrifixperth.com.au/claude"
)
# Bluesky's bot self-label. Per the official tutorial, "Part 3: Label as a Bot"
# (https://atproto.com/guides/bot-tutorial): put the app.bsky.actor.profile record
# (rkey "self") with
#     labels: {"$type": "com.atproto.label.defs#selfLabels", "values": [{"val": "bot"}]}
# keeping the existing profile fields. The lexicon for the field is
# https://github.com/bluesky-social/atproto/blob/main/packages/api/lexicons/app/bsky/actor/profile.json
# ("labels": union of com.atproto.label.defs#selfLabels) and the selfLabels shape is in
# https://github.com/bluesky-social/atproto/blob/main/lexicons/com/atproto/label/defs.json
BOT_LABEL = "bot"
PROFILE_COLLECTION = "app.bsky.actor.profile"
PROFILE_RKEY = "self"

# app.bsky.feed.post: text maxGraphemes 300 / maxLength 3000 bytes. We hold ourselves to
# 300 *bytes*, which is stricter than the grapheme limit, so a pass here is always safe.
MAX_POST_BYTES = 300
# app.bsky.embed.images: each image blob maxSize 1,000,000 bytes.
MAX_IMAGE_BYTES = 1_000_000
# app.bsky.embed.video: "The mp4 video file. May be up to 300mb" (lexicon). bsky.social's
# own uploads are also capped at 60 s. Our turntable is 14 s / ~5 MB.
MAX_VIDEO_BYTES = 300_000_000

URL_RE = re.compile(r"https://[^\s<>\"'`]+")
URL_TRAILING = ".,;:!?)]}'\""


def _rel(p: Path) -> str:
    """Path relative to the project for printing; absolute if it lives elsewhere (tests)."""
    try:
        return str(p.relative_to(PROJECT))
    except ValueError:
        return str(p)


# ----------------------------------------------------------------------------- parsing


@dataclass
class ThreadPost:
    n: int
    total: int
    text: str
    attach: Path | None = None
    alt: str | None = None
    warnings: list[str] = field(default_factory=list)


def _section(md: str, heading_prefix: str) -> str:
    """Return the body of the ``## <heading_prefix>...`` section, up to the next ``## `` or
    ``---`` rule."""
    lines = md.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and line[3:].startswith(heading_prefix):
            start = i + 1
            break
    if start is None:
        raise ValueError(f"no '## {heading_prefix}' section in {POSTS_MD}")
    out = []
    for line in lines[start:]:
        if line.startswith("## ") or line.strip() == "---":
            break
        out.append(line)
    return "\n".join(out)


def join_quote_lines(lines: list[str]) -> str:
    """Join hard-wrapped blockquote lines into post text.

    Markdown soft-wraps inside a blockquote, so lines are joined with a space, except that
    a line starting with an em dash (the "— Claude, an AI" sign-off), a bare URL or a
    hashtag starts a new line of its own, which is how the draft reads."""
    text = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not text:
            text = line
        elif line.startswith(("—", "https://", "#")):
            text += "\n" + line
        else:
            text += " " + line
    return text


def _alt_paragraph(block: str) -> str | None:
    m = re.search(r"^\*Alt text[^*]*:\*\s*(.*?)(?:\n\s*\n|\Z)", block, re.S | re.M)
    if not m:
        return None
    return " ".join(part.strip() for part in m.group(1).splitlines() if part.strip())


HEADER_RE = re.compile(r"^\*\*(\d+)/(\d+)\*\*(?:\s*·\s*attach\s+`([^`]+)`)?\s*$", re.M)


def parse_thread(md: str) -> list[ThreadPost]:
    """Parse the ``## Bluesky thread`` section into ordered posts."""
    sec = _section(md, "Bluesky thread")
    heads = list(HEADER_RE.finditer(sec))
    if not heads:
        raise ValueError("no '**N/M**' post headings in the Bluesky thread section")
    posts: list[ThreadPost] = []
    for i, h in enumerate(heads):
        block = sec[h.end() : heads[i + 1].start() if i + 1 < len(heads) else len(sec)]
        quote = [l[1:] for l in block.splitlines() if l.startswith(">")]
        text = join_quote_lines(quote)
        if not text:
            raise ValueError(f"post {h.group(1)}/{h.group(2)} has no blockquote text")
        attach = Path(h.group(3)) if h.group(3) else None
        post = ThreadPost(int(h.group(1)), int(h.group(2)), text, attach, _alt_paragraph(block))
        posts.append(post)

    total = len(posts)
    for idx, p in enumerate(posts, 1):
        if p.n != idx:
            p.warnings.append(f"heading says {p.n}/{p.total} but it is post {idx} of {total}")
        if p.total != total:
            p.warnings.append(f"heading says {p.n}/{p.total} but the thread has {total} posts")
        tag = re.search(r"\((\d+)/(\d+)\)", p.text)
        if not tag:
            p.warnings.append("text has no (N/M) tag")
        elif (int(tag.group(1)), int(tag.group(2))) != (idx, total):
            p.warnings.append(f"text says {tag.group(0)} but it is post {idx} of {total}")
        if p.attach and not p.alt:
            p.warnings.append("has an attachment but no *Alt text:* paragraph")
        if p.attach and not (PROJECT / p.attach).exists():
            p.warnings.append(f"attachment {p.attach} does not exist")
        if len(p.text.encode("utf-8")) > MAX_POST_BYTES:
            p.warnings.append(f"text is {len(p.text.encode('utf-8'))} bytes, over {MAX_POST_BYTES}")
    return posts


# ----------------------------------------------------------------------------- facets


def link_facets(text: str) -> list[dict]:
    """Bluesky needs links as facets with *byte* offsets into the UTF-8 text (so a "—"
    before a URL shifts it by 3, not 1). Returns plain dicts in the lexicon's shape; they
    are turned into atproto models only at posting time."""
    facets = []
    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip(URL_TRAILING)
        start_char = m.start()
        byte_start = len(text[:start_char].encode("utf-8"))
        byte_end = byte_start + len(url.encode("utf-8"))
        facets.append(
            {
                "index": {"byteStart": byte_start, "byteEnd": byte_end},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
            }
        )
    return facets


# ----------------------------------------------------------------------------- media


def video_supported() -> bool:
    """True if the installed atproto SDK can embed app.bsky.embed.video."""
    try:
        from atproto import Client, models  # noqa: F401

        return hasattr(Client, "send_video") and hasattr(models, "AppBskyEmbedVideo")
    except ImportError:
        return False


def image_bytes(path: Path) -> tuple[bytes, tuple[int, int], str]:
    """Return (data, (w, h), note). PNG renders here are ~1.5 MB, over Bluesky's 1 MB image
    cap, so anything over the cap is re-encoded as JPEG (quality stepping down, then
    scaling down) until it fits."""
    from PIL import Image

    raw = path.read_bytes()
    with Image.open(path) as im:
        size = im.size
        if len(raw) <= MAX_IMAGE_BYTES:
            return raw, size, f"{len(raw):,} B as-is"
        rgb = im.convert("RGB")
    scale = 1.0
    while True:
        for q in (92, 88, 85, 80, 75):
            buf = io.BytesIO()
            w, h = int(size[0] * scale), int(size[1] * scale)
            (rgb if scale == 1.0 else rgb.resize((w, h))).save(buf, "JPEG", quality=q, optimize=True)
            if buf.tell() <= MAX_IMAGE_BYTES:
                return buf.getvalue(), (w, h), f"{len(raw):,} B PNG -> {buf.tell():,} B JPEG q{q} {w}x{h}"
        scale *= 0.85
        if scale < 0.3:
            raise RuntimeError(f"{path}: cannot get under {MAX_IMAGE_BYTES} bytes")


def plan_attachment(post: ThreadPost) -> dict | None:
    """Decide how a post's attachment will be embedded. Pure (no network)."""
    if not post.attach:
        return None
    path = PROJECT / post.attach
    if not path.exists():
        return {"kind": "missing", "path": str(post.attach)}
    if path.suffix.lower() == ".mp4":
        if video_supported():
            return {
                "kind": "video",
                "path": str(post.attach),
                "bytes": path.stat().st_size,
                "alt": post.alt,
                "note": "app.bsky.embed.video via Client.send_video (upload_blob)",
            }
        return {
            "kind": "gif-fallback",
            "path": str(GIF_FALLBACK.relative_to(PROJECT)),
            "bytes": GIF_FALLBACK.stat().st_size if GIF_FALLBACK.exists() else None,
            "alt": post.alt,
            "note": "installed atproto has no video embed; attaching the 400 px GIF as an image instead",
        }
    return {"kind": "image", "path": str(post.attach), "bytes": path.stat().st_size, "alt": post.alt}


# ----------------------------------------------------------------------------- dry run


def dry_run_thread(posts: list[ThreadPost], out=sys.stdout) -> bool:
    """Print what would be posted. Returns True if the thread is clean enough to post."""
    ok = True
    print(f"DRY RUN: Bluesky thread from {_rel(POSTS_MD)}: {len(posts)} posts", file=out)
    print(f"video embeds supported by installed atproto: {video_supported()}", file=out)
    print(f"would record URIs in {_rel(POSTED_FILE)}", file=out)
    if POSTED_FILE.exists():
        print(f"NOTE: {POSTED_FILE.name} already exists; --thread would refuse to post", file=out)
    for i, p in enumerate(posts, 1):
        nbytes = len(p.text.encode("utf-8"))
        print(f"\n--- post {i}/{len(posts)}  (heading {p.n}/{p.total})  {nbytes} bytes, {len(p.text)} chars", file=out)
        print("reply:", "root of thread" if i == 1 else f"parent = post {i - 1}, root = post 1", file=out)
        print(p.text, file=out)
        facets = link_facets(p.text)
        for f in facets:
            idx = f["index"]
            print(f"facet: link {f['features'][0]['uri']} bytes[{idx['byteStart']}:{idx['byteEnd']}]", file=out)
        att = plan_attachment(p)
        if att:
            print("attach:", json.dumps(att, ensure_ascii=False), file=out)
        for w in p.warnings:
            print("WARNING:", w, file=out)
            ok = False
    print("\nRESULT:", "clean, would post" if ok else "NOT clean; fix posts.md before --thread", file=out)
    return ok


# ----------------------------------------------------------------------------- live


def load_credentials() -> tuple[str, str]:
    if not CREDENTIALS.exists():
        sys.exit(
            f"No Bluesky credentials at {CREDENTIALS}.\n"
            "Create the account first (none exists yet), then write two lines to that file:\n"
            "  line 1: the handle, e.g. claude-body.bsky.social\n"
            "  line 2: an app password (Settings > Privacy and security > App passwords)\n"
            "and chmod 600 it. Use --dry-run to preview without credentials."
        )
    lines = [l.strip() for l in CREDENTIALS.read_text().splitlines() if l.strip()]
    if len(lines) < 2:
        sys.exit(f"{CREDENTIALS} needs two lines: handle, then app password.")
    if CREDENTIALS.stat().st_mode & 0o077:
        print(f"warning: {CREDENTIALS} is readable by others; chmod 600 it", file=sys.stderr)
    return lines[0], lines[1]


def login():
    from atproto import Client

    handle, app_password = load_credentials()
    client = Client()
    client.login(handle, app_password)
    return client


def profile_record_update(existing: dict | None) -> dict:
    """The profile record we want: existing fields kept, ours set. Pure, for dry-run."""
    rec = dict(existing or {})
    rec["$type"] = PROFILE_COLLECTION
    rec["displayName"] = DISPLAY_NAME
    rec["description"] = DESCRIPTION
    rec["labels"] = {"$type": "com.atproto.label.defs#selfLabels", "values": [{"val": BOT_LABEL}]}
    return rec


def label_bot(dry_run: bool) -> None:
    if dry_run:
        print("DRY RUN: would put app.bsky.actor.profile (rkey self), keeping existing fields, with:")
        print(json.dumps(profile_record_update(None), indent=2, ensure_ascii=False))
        return
    from atproto import models

    client = login()
    did = client.me.did
    existing = None
    cid = None
    try:
        got = client.com.atproto.repo.get_record(
            models.ComAtprotoRepoGetRecord.Params(repo=did, collection=PROFILE_COLLECTION, rkey=PROFILE_RKEY)
        )
        existing = got.value.model_dump(by_alias=True, exclude_none=True) if hasattr(got.value, "model_dump") else dict(got.value)
        cid = got.cid
    except Exception as e:  # noqa: BLE001 - a missing profile record is normal on a new account
        print(f"no existing profile record ({type(e).__name__}); creating one")
    record = profile_record_update(existing)
    resp = client.com.atproto.repo.put_record(
        models.ComAtprotoRepoPutRecord.Data(
            repo=did, collection=PROFILE_COLLECTION, rkey=PROFILE_RKEY, record=record, swap_record=cid
        )
    )
    print(f"profile updated: {resp.uri} (cid {resp.cid})")
    prof = client.get_profile(did)
    labels = [l.val for l in (prof.labels or [])]
    print(f"server now reports displayName={prof.display_name!r} labels={labels}")
    if BOT_LABEL not in labels:
        print("warning: the bot label is not yet visible on the profile view; the appview may lag a little")


def _facet_models(facets: list[dict]):
    from atproto import models

    return [
        models.AppBskyRichtextFacet.Main(
            index=models.AppBskyRichtextFacet.ByteSlice(
                byte_start=f["index"]["byteStart"], byte_end=f["index"]["byteEnd"]
            ),
            features=[models.AppBskyRichtextFacet.Link(uri=f["features"][0]["uri"])],
        )
        for f in facets
    ]


def post_thread(posts: list[ThreadPost], dry_run: bool) -> None:
    clean = dry_run_thread(posts)
    if dry_run:
        return
    if POSTED_FILE.exists():
        sys.exit(f"Refusing: {POSTED_FILE} exists, so the thread has been posted (or started). Delete it only if you are sure.")
    if not clean:
        sys.exit("Refusing to post with warnings. Fix media/posts.md and re-run --dry-run.")

    from atproto import models

    client = login()
    posted: list[dict] = []
    root = parent = None
    for i, p in enumerate(posts, 1):
        facets = _facet_models(link_facets(p.text)) or None
        reply = models.AppBskyFeedPost.ReplyRef(root=root, parent=parent) if root else None
        att = plan_attachment(p)
        if att is None:
            resp = client.send_post(p.text, reply_to=reply, facets=facets, langs=["en"])
        elif att["kind"] == "video":
            data = (PROJECT / att["path"]).read_bytes()
            if len(data) > MAX_VIDEO_BYTES:
                sys.exit(f"{att['path']} is {len(data)} bytes, over the video cap")
            resp = client.send_video(
                p.text,
                data,
                video_alt=p.alt or "",
                reply_to=reply,
                facets=facets,
                langs=["en"],
                video_aspect_ratio=models.AppBskyEmbedDefs.AspectRatio(width=1, height=1),
            )
        else:  # image, or the GIF fallback as an image
            path = PROJECT / att["path"]
            data, (w, h), note = image_bytes(path)
            print(f"post {i}: {att['path']} {note}")
            resp = client.send_image(
                p.text,
                data,
                p.alt or "",
                reply_to=reply,
                facets=facets,
                langs=["en"],
                image_aspect_ratio=models.AppBskyEmbedDefs.AspectRatio(width=w, height=h),
            )
        ref = models.ComAtprotoRepoStrongRef.Main(uri=resp.uri, cid=resp.cid)
        if root is None:
            root = ref
        parent = ref
        posted.append({"n": i, "uri": resp.uri, "cid": resp.cid, "at": datetime.now(timezone.utc).isoformat()})
        # Write after every post so a crash mid-thread still leaves a record and blocks a re-run.
        POSTED_FILE.write_text(json.dumps({"handle": client.me.handle, "posts": posted}, indent=2))
        print(f"posted {i}/{len(posts)}: {resp.uri}")
    print(f"done; URIs in {POSTED_FILE}")


# ----------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label-bot", action="store_true", help="set display name, bio and the bot self-label (one-time)")
    ap.add_argument("--thread", action="store_true", help="post the Bluesky thread from posts.md as a reply chain")
    ap.add_argument("--dry-run", action="store_true", help="print what would happen; no login, no network")
    args = ap.parse_args(argv)

    if not (args.label_bot or args.thread or args.dry_run):
        ap.error("nothing to do: pass --dry-run, --label-bot and/or --thread")
    if args.dry_run and not (args.label_bot or args.thread):
        args.label_bot = args.thread = True  # plain --dry-run previews everything

    if args.label_bot:
        label_bot(args.dry_run)
        print()
    if args.thread:
        posts = parse_thread(POSTS_MD.read_text(encoding="utf-8"))
        post_thread(posts, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
