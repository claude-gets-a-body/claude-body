"""The tools Claude is given (DESIGN.md §4.3).

The list is built once and never changes during a day: tools sit at the very
front of every request, so changing them would throw away the prompt cache and
invalidate Claude's earlier thinking. Order is fixed by this file.

Three kinds of tool:
  - BODY tools: the mind forwards them to the robot as a `tool_call` and waits
    for the `tool_result` (say, express, look, turn_to, go_to, approach, dock,
    sleep, stop). The body enforces the safety rules, not the mind.
  - MIND tools: run here on K8 (recall, house, timer, and the memory tool).
  - SERVER tool: web_search runs on Anthropic's side.
"""

from __future__ import annotations

MOODS = ["neutral", "happy", "curious", "thinking", "sad", "surprised", "sleepy", "confused", "listening"]

BODY_TOOL_NAMES = {"say", "express", "look", "turn_to", "go_to", "approach", "dock", "sleep", "stop"}
MIND_TOOL_NAMES = {"recall", "house", "timer", "memory"}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def client_tools() -> list[dict]:
    return [
        _tool("say",
              "Speak out loud right now, before you've finished the turn. Use it for things "
              "like \"On my way!\" before driving off. Your final reply is spoken anyway, so "
              "you don't need this for the answer itself.",
              {"text": {"type": "string", "description": "What to say. Plain spoken words, no markdown."},
               "voice_style": {"type": "string", "enum": ["normal", "quiet", "excited", "gentle"]}},
              ["text"]),
        _tool("express",
              "Show a feeling with your eyes, ears and chest light.",
              {"mood": {"type": "string", "enum": MOODS}},
              ["mood"]),
        _tool("look",
              "Raise your visor and take one photo, then lower the visor again. Only do this "
              "when someone wants you to see something, or when you need to see to do a task. "
              "The body refuses in no-look places and right after someone asked you to stop looking.",
              {"at": {"type": "string",
                      "description": "Where to point your head first: 'ahead', 'left', 'right', 'up', "
                                     "'down', 'speaker' (whoever spoke last), 'nearest' (the nearest "
                                     "person your lidar senses), or an angle in degrees (+ is to your "
                                     "left). Leave out to look where you're facing."}},
              []),
        _tool("turn_to",
              "Turn to face someone or something.",
              {"target": {"type": "string",
                          "description": "'speaker' (whoever spoke last, found by their voice), 'nearest' "
                                         "(the nearest person your lidar senses), or an angle in degrees "
                                         "(+ is to your left). You can't find people by name."}},
              ["target"]),
        _tool("go_to",
              "Drive to a named place on your map, e.g. 'kitchen'. Refused during quiet hours "
              "(9 pm to 7 am) and for keep-out places. Bedrooms are keep-out unless a parent has "
              "enabled one (sometimes only at certain times).",
              {"place": {"type": "string"}},
              ["place"]),
        _tool("approach",
              "Drive slowly towards whoever spoke to you last, found by the direction their voice "
              "came from, stopping about 1 m away. Ask them to speak first if they haven't just "
              "now. Refused during quiet hours.",
              {"person": {"type": "string", "description": "Optional: who you think it is, for your own notes."}},
              []),
        _tool("dock", "Drive back to your charging dock. Allowed in quiet hours too.", {}, []),
        _tool("sleep", "Lower your visor, close your eyes and rest. You can still hear the wake word.", {}, []),
        _tool("stop", "Stop moving immediately and cancel any drive.", {}, []),
        _tool("recall",
              "Search transcripts of earlier days for something that was said.",
              {"query": {"type": "string", "description": "Words to search for."}},
              ["query"]),
        _tool("house",
              "Read Home Assistant (read only: you can't switch anything). Ask about doors, "
              "windows, temperatures, weather, lights being on, and so on.",
              {"question": {"type": "string"},
               "entity_ids": {"type": "array", "items": {"type": "string"},
                              "description": "Optional exact entity ids, if you already know them."}},
              ["question"]),
        _tool("timer",
              "Set a reminder. When it's due you'll get a [timer] message and can go and say it.",
              {"minutes": {"type": "number", "description": "How many minutes from now (up to 1440)."},
               "note": {"type": "string", "description": "What to remind about."},
               "for_person": {"type": "string", "description": "Who it's for, if anyone."}},
              ["minutes", "note"]),
    ]


def all_tools(memory_tool_param: dict, web_search_max_uses: int) -> list[dict]:
    """Every tool, in a fixed order: our tools, the memory tool, web search."""
    return client_tools() + [
        memory_tool_param,
        {"type": "web_search_20260209", "name": "web_search", "max_uses": web_search_max_uses},
    ]


# ---------------------------------------------------------------------------
# The claude_code brain (mind/cc_brain.py) gets the same tools through an MCP
# server instead. Two differences:
#   - memory is an ordinary tool with an explicit schema (the Anthropic memory
#     tool type only exists on the API); it runs the same MemoryStore backend.
#   - there is no web_search: it would need Claude Code's built-in WebSearch,
#     and every built-in tool is switched off in that brain.
# ---------------------------------------------------------------------------
MEMORY_TOOL_FOR_MCP = _tool(
    "memory",
    "Read and write your memory: markdown files under /memories that the family can read and edit. "
    "Commands: view (a file or folder), create (path + file_text; overwrites), str_replace (path + "
    "old_str + new_str; old_str must be unique), insert (path + insert_line + insert_text), delete "
    "(path), rename (old_path + new_path). Paths always start with /memories/.",
    {"command": {"type": "string", "enum": ["view", "create", "str_replace", "insert", "delete", "rename"]},
     "path": {"type": "string"},
     "file_text": {"type": "string"},
     "old_str": {"type": "string"},
     "new_str": {"type": "string"},
     "insert_line": {"type": "integer"},
     "insert_text": {"type": "string"},
     "view_range": {"type": "array", "items": {"type": "integer"}},
     "old_path": {"type": "string"},
     "new_path": {"type": "string"}},
    ["command"],
)


def mcp_tools() -> list[dict]:
    return client_tools() + [MEMORY_TOOL_FOR_MCP]
