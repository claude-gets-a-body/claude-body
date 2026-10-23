"""Claude's memory: plain markdown files that Nick can open and edit.

This is the backend for Anthropic's memory tool (`memory_20250818`). Claude sends
commands such as {"command": "view", "path": "/memories/house.md"}; we carry them
out on a real folder on disk (MindConfig.memory_dir).

Claude only ever sees paths that start with /memories. Every path is checked
before anything is touched:
  - must be /memories or start with /memories/
  - no "..", no backslashes, no NUL bytes, no hidden parts (".history" is ours)
  - after resolving symlinks it must still be inside the memory folder
Anything else is refused with a ToolError, which the engine turns into an
`is_error` tool result so Claude sees the reason.

When a file is overwritten or deleted, the old version is copied to
<memory_dir>/.history/ first, so nothing Nick wrote can be lost by a bad edit.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from anthropic.lib.tools import BetaAbstractMemoryTool, ToolError

PREFIX = "/memories"
HISTORY_DIR = ".history"
MAX_FILE_BYTES = 200_000


class MemoryStore(BetaAbstractMemoryTool):
    def __init__(self, root: str | Path):
        super().__init__()
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ path safety
    def resolve(self, path: str) -> Path:
        """Turn a /memories/... path into a real path inside self.root, or refuse."""
        if not isinstance(path, str) or not path:
            raise ToolError("A path is required.")
        if "\x00" in path or "\\" in path:
            raise ToolError(f"Invalid characters in path {path!r}.")
        if path != PREFIX and not path.startswith(PREFIX + "/"):
            raise ToolError(f"Paths must start with {PREFIX}/ (got {path!r}).")
        relative = path[len(PREFIX):].strip("/")
        parts = [p for p in relative.split("/") if p not in ("", ".")]
        for part in parts:
            if part == "..":
                raise ToolError(f"'..' is not allowed in memory paths ({path!r}).")
            if part.startswith("."):
                raise ToolError(f"Hidden names are not allowed in memory paths ({path!r}).")
        full = self.root.joinpath(*parts) if parts else self.root
        resolved = full.resolve()   # follows symlinks
        if resolved != self.root and self.root not in resolved.parents:
            raise ToolError(f"{path!r} is outside the memory folder.")
        return resolved

    def _shown(self, real: Path) -> str:
        rel = real.relative_to(self.root).as_posix()
        return PREFIX if rel == "." else f"{PREFIX}/{rel}"

    def _backup(self, real: Path) -> None:
        if not real.is_file():
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = self.root / HISTORY_DIR / f"{real.relative_to(self.root).as_posix().replace('/', '__')}.{stamp}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(real, dest)

    @staticmethod
    def _write(real: Path, text: str) -> None:
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise ToolError(f"File too large (limit {MAX_FILE_BYTES} bytes). Split it up.")
        real.parent.mkdir(parents=True, exist_ok=True)
        tmp = real.with_name(f".tmp-{os.getpid()}-{real.name}")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, real)

    # ------------------------------------------------------- helpers for us
    def read_text(self, path: str, default: str = "") -> str:
        real = self.resolve(path)
        return real.read_text(encoding="utf-8") if real.is_file() else default

    def write_text(self, path: str, text: str) -> None:
        """Overwrite a file (keeping a backup). Used by the nightly job."""
        real = self.resolve(path)
        self._backup(real)
        self._write(real, text)

    def seed_from(self, template_dir: str | Path) -> None:
        """First run: copy the template files in, without overwriting anything."""
        template = Path(template_dir)
        if not template.is_dir():
            return
        for src in template.rglob("*"):
            if src.is_file() and not any(p.startswith(".") for p in src.relative_to(template).parts):
                dest = self.root / src.relative_to(template)
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)

    # ------------------------------------------------ memory tool commands
    def view(self, command) -> str:
        real = self.resolve(command.path)
        if not real.exists():
            raise ToolError(f"{command.path} does not exist.")
        if real.is_dir():
            lines = [f"Files in {self._shown(real)}:"]
            for item in sorted(real.rglob("*")):
                rel_parts = item.relative_to(real).parts
                if any(p.startswith(".") for p in rel_parts) or len(rel_parts) > 2:
                    continue
                suffix = "/" if item.is_dir() else f"  ({item.stat().st_size} bytes)"
                lines.append(f"  {self._shown(item)}{suffix}")
            return "\n".join(lines)
        text = real.read_text(encoding="utf-8")
        all_lines = text.split("\n")
        start, end = 1, len(all_lines)
        view_range = getattr(command, "view_range", None)
        if view_range and len(view_range) == 2:
            start = max(1, view_range[0])
            end = len(all_lines) if view_range[1] == -1 else min(view_range[1], len(all_lines))
        numbered = [f"{n:6d}\t{all_lines[n - 1]}" for n in range(start, end + 1)]
        return f"{command.path}:\n" + "\n".join(numbered)

    def create(self, command) -> str:
        real = self.resolve(command.path)
        if real == self.root or real.is_dir():
            raise ToolError(f"{command.path} is a folder, not a file.")
        self._backup(real)
        self._write(real, command.file_text)
        return f"Saved {command.path}."

    def str_replace(self, command) -> str:
        real = self.resolve(command.path)
        if not real.is_file():
            raise ToolError(f"{command.path} does not exist.")
        text = real.read_text(encoding="utf-8")
        count = text.count(command.old_str)
        if count == 0:
            raise ToolError(f"The text to replace was not found in {command.path}.")
        if count > 1:
            raise ToolError(f"The text to replace appears {count} times in {command.path}; make it unique.")
        self._backup(real)
        self._write(real, text.replace(command.old_str, command.new_str))
        return f"Edited {command.path}."

    def insert(self, command) -> str:
        real = self.resolve(command.path)
        if not real.is_file():
            raise ToolError(f"{command.path} does not exist.")
        lines = real.read_text(encoding="utf-8").split("\n")
        if not 0 <= command.insert_line <= len(lines):
            raise ToolError(f"insert_line must be between 0 and {len(lines)}.")
        lines.insert(command.insert_line, command.insert_text.rstrip("\n"))
        self._backup(real)
        self._write(real, "\n".join(lines))
        return f"Inserted into {command.path}."

    def delete(self, command) -> str:
        real = self.resolve(command.path)
        if real == self.root:
            raise ToolError("The /memories folder itself cannot be deleted.")
        if real.is_file():
            self._backup(real)
            real.unlink()
        elif real.is_dir():
            for f in real.rglob("*"):
                if f.is_file():
                    self._backup(f)
            shutil.rmtree(real)
        else:
            raise ToolError(f"{command.path} does not exist.")
        return f"Deleted {command.path} (a copy is kept in .history)."

    def rename(self, command) -> str:
        old = self.resolve(command.old_path)
        new = self.resolve(command.new_path)
        if not old.exists():
            raise ToolError(f"{command.old_path} does not exist.")
        if new.exists():
            raise ToolError(f"{command.new_path} already exists.")
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
        return f"Renamed {command.old_path} to {command.new_path}."

    def run(self, tool_input: dict) -> tuple[str, bool]:
        """Run one memory command for the engine. Returns (text, is_error)."""
        try:
            return str(self.call(tool_input)), False
        except ToolError as e:
            return str(e), True
        except (OSError, UnicodeDecodeError, AttributeError, TypeError) as e:
            return f"Memory error: {e}", True
