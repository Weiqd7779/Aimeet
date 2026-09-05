"""Print utterances from the last N sessions.

uv run python -m e2e.dump_latest [n]
"""

import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main(n: int = 5) -> None:
    dirs = sorted(glob.glob("data/sessions/*"), key=os.path.getmtime)
    for d in dirs[-n:]:
        print("---", d)
        path = d + "/events.jsonl"
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                e = json.loads(line)
                if e.get("event") == "utterance":
                    print(f"[{e.get('ts', 0):6.1f}] {e.get('speaker')} {e.get('text')}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
