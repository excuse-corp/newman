from __future__ import annotations

import json
import sys


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    event = str(payload.get("event", "unknown"))
    context = payload.get("context") or {}
    if event == "FileChanged":
        path = context.get("path", "")
        print(f"Example hook noticed file change: {path}")
        return 0
    tool = context.get("tool", "")
    if tool:
        print(f"Example hook handled {event} for {tool}")
    else:
        print(f"Example hook handled {event}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
