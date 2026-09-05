"""Print the raw event log of the newest (or given) session, one line per event.

uv run python -m e2e.dump_events [session_id]
"""

import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main(session_id: str | None) -> None:
    d = (
        f"data/sessions/{session_id}"
        if session_id
        else max(glob.glob("data/sessions/*"), key=os.path.getmtime)
    )
    print(d)
    with open(d + "/events.jsonl", encoding="utf-8") as fh:
        lines = fh.readlines()
    for line in lines:
        e = json.loads(line)
        t = e.get("event")
        if t == "frame":
            continue
        if t == "utterance":
            print(f"[{e.get('ts', 0):6.1f}] {e.get('speaker')} {e.get('text')}")
        else:
            e.pop("wall_time", None)
            print(f"   {t} {json.dumps(e, ensure_ascii=False)[:200]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
