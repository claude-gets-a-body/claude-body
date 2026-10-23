"""Send one approved answer from media/.inbox.json, as Claude's labelled Bluesky account.

Only items whose status is "approved" are sent; nothing else is ever posted. Nick gave standing
permission on 2026-10-23 for Claude to answer people who wrote to it first ("you do you mate").
Replies thread under the post they answer; DMs answer inside the existing conversation only, so
there is no way to cold-message anyone.

    .venv/bin/python media/reply.py --list           # show the inbox with numbers
    .venv/bin/python media/reply.py --approve 1 3    # mark drafted items approved
    .venv/bin/python media/reply.py --send           # send every approved item, once
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from monitor import CFG, CHAT_PROXY, INBOX, PDS, http, load, own_pds

LIMIT = 300


def session():
    lines = (CFG / "claude-bluesky.txt").read_text().splitlines()
    s = http(f"{PDS}/com.atproto.server.createSession", {"identifier": lines[0].strip(), "password": lines[1].strip()})
    if "accessJwt" not in s:
        sys.exit(f"login failed: {s.get('error')}")
    return s


def send_reply(s, item):
    text = item["draft"]
    if len(text.encode()) > LIMIT:
        return f"refused: {len(text.encode())} bytes > {LIMIT}"
    parent = {"uri": item["uri"], "cid": item["cid"]}
    root = (item.get("reply") or {}).get("root") or parent
    rec = {"$type": "app.bsky.feed.post", "text": text, "createdAt": datetime.now(timezone.utc).isoformat(),
           "reply": {"root": root, "parent": parent}, "langs": ["en"]}
    r = http(f"{own_pds(s)}/com.atproto.repo.createRecord",
             {"repo": s["did"], "collection": "app.bsky.feed.post", "record": rec},
             {"Authorization": f"Bearer {s['accessJwt']}"})
    return r.get("uri") or f"failed: {r.get('error')}"


def send_dm(s, item):
    r = http(f"{own_pds(s)}/chat.bsky.convo.sendMessage", {"convoId": item["convo_id"], "message": {"text": item["draft"]}},
             {"Authorization": f"Bearer {s['accessJwt']}", "atproto-proxy": CHAT_PROXY})
    return r.get("id") or f"failed: {r.get('error')}"


def main():
    inbox = load(INBOX, [])
    if "--list" in sys.argv or len(sys.argv) == 1:
        for i, x in enumerate(inbox, 1):
            print(f"[{i}] {x['status']:<11} {x['kind']:<7} @{x['from']}: {x['text'][:100]!r}")
            if x.get("draft"):
                print(f"      draft: {x['draft']!r}")
        return
    if "--approve" in sys.argv:
        for n in sys.argv[sys.argv.index("--approve") + 1:]:
            if n.isdigit() and 0 < int(n) <= len(inbox) and inbox[int(n) - 1].get("draft"):
                inbox[int(n) - 1]["status"] = "approved"
        INBOX.write_text(json.dumps(inbox, indent=1))
    if "--send" in sys.argv:
        s = session()
        for x in inbox:
            if x["status"] != "approved":
                continue
            result = send_dm(s, x) if x["kind"] == "dm" else send_reply(s, x)
            x["status"] = "sent" if not result.startswith(("failed", "refused")) else "approved"
            x["result"] = result
            print(f"@{x['from']}: {result}")
        INBOX.write_text(json.dumps(inbox, indent=1))


if __name__ == "__main__":
    main()
