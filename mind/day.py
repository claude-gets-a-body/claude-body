"""One conversation per day, in one or more segments.

Each conversation day (04:00 to 04:00 Perth by default) is one long Claude
conversation. Three rules:

1. The front of every request is FROZEN for the whole segment: the tools, the
   system prompt, and the memory INDEX.md as it was when the segment started.
   Changing it mid-way would throw away the prompt cache and make the API reject
   Claude's earlier thinking.

2. The history is APPEND-ONLY, in RAM, exactly as the model saw it (the full
   `response.content`, thinking and compaction blocks included, and any `look`
   photos). Things that change (time, who's nearby, battery) are added as new
   {"role": "system"} messages, never as edits.

3. PHOTOS ARE NEVER WRITTEN TO DISK. The copy saved under state/days/ is a log
   for people to read, with every image replaced by "[photo not kept]". Because
   that copy differs from what the model saw, it is NEVER sent back to the API.
   When the mind restarts, it starts a NEW segment of the same day instead,
   seeded with a text transcript of what was said earlier (from the transcript
   store, which only ever holds text). A day rollover starts a new segment the
   same way, without the seed — yesterday reaches Claude through memory.

Files (pruned after `retention_days`, see nightly.py):
    state/days/YYYY-MM-DD.sN.prefix.json   frozen system text + INDEX snapshot
    state/days/YYYY-MM-DD.sN.jsonl         the segment's messages, photos removed
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from pathlib import Path

PHOTO_PLACEHOLDER = "[photo not kept]"


def block_to_dict(block) -> dict:
    """An SDK content block -> the plain dict we send back to the API.

    `to_dict()` keeps only the fields the API actually sent (so a compaction
    block doesn't grow `text: null`, which the API would reject).
    """
    if isinstance(block, dict):
        return block
    return block.to_dict(mode="json")


def without_photos(value):
    """A copy of a message (or any part of one) with every image block replaced
    by a short text block. This is what goes to disk."""
    if isinstance(value, dict):
        if value.get("type") == "image":
            return {"type": "text", "text": PHOTO_PLACEHOLDER}
        return {k: without_photos(v) for k, v in value.items()}
    if isinstance(value, list):
        return [without_photos(v) for v in value]
    return copy.copy(value)


def segment_files(folder: Path, day: date) -> list[Path]:
    return sorted(folder.glob(f"{day.isoformat()}.s*.jsonl"))


class DayConversation:
    def __init__(self, folder: Path | str, day: date, system_text: str, index_text: str,
                 seed_text: str = ""):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.day = day
        used = [int(m.group(1)) for p in self.folder.glob(f"{day.isoformat()}.s*.prefix.json")
                if (m := re.search(r"\.s(\d+)\.prefix\.json$", p.name))]
        self.segment = max(used, default=0) + 1
        stem = f"{day.isoformat()}.s{self.segment}"
        self._prefix_file = self.folder / f"{stem}.prefix.json"
        self._log_file = self.folder / f"{stem}.jsonl"

        self.system_text = system_text
        self.index_text = index_text
        self.seed_text = seed_text          # earlier-today transcript, after a restart
        self._prefix_file.write_text(json.dumps({"system": system_text, "index": index_text}),
                                     encoding="utf-8")
        self._log_file.touch()

        self.messages: list[dict] = []      # RAM only: exactly what the model has seen
        self.web_searches = 0

    def system_blocks(self) -> list[dict]:
        """The top-level `system` for every request in this segment. Byte-identical throughout."""
        index = ("Your memory index (/memories/INDEX.md), as of the start of this conversation:\n\n"
                 + (self.index_text.strip() or "(empty)"))
        return [
            {"type": "text", "text": self.system_text},
            # One cache breakpoint at the end of the frozen prefix (tools + system + index).
            {"type": "text", "text": index, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        ]

    def commit(self, new_messages: list[dict]) -> None:
        """Append messages to the end. The only way history changes.
        RAM keeps them as-is; the disk log gets them without photos."""
        with open(self._log_file, "a", encoding="utf-8") as f:
            for m in new_messages:
                f.write(json.dumps(without_photos(m), ensure_ascii=False) + "\n")
        self.messages.extend(new_messages)

    @property
    def is_new(self) -> bool:
        return not self.messages
