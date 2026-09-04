"""Dump a session's events.jsonl as a readable timeline. Usage: python _dump_session.py [session_id]"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
root = Path("data/sessions")
folder = (
    root / sys.argv[1]
    if len(sys.argv) > 1
    else max(root.iterdir(), key=lambda p: p.stat().st_mtime)
)
print(folder.name)
for line in (folder / "events.jsonl").read_text("utf-8").splitlines():
    o = json.loads(line)
    kind = o["event"]
    if kind == "utterance":
        print(f"[{o['ts']:6.1f}] {o['speaker']} ({len(o['text'])}字) {o['text'][:90]}")
    elif kind == "frame":
        print(f"[{o['ts']:6.1f}]   FRAME {o['reason']} scene={o['scene_seq']}")
    elif kind == "tool":
        print(f"          tool {o['tool']}")
    elif kind == "echo_dropped":
        print(f"[{o['ts']:6.1f}]   ECHO_DROPPED {o['text'][:60]}")
    elif kind == "closed":
        print(
            f"CLOSED {o['reason']} elapsed={o['elapsed']:.0f}s audio={o['audio_chunks']} frames={o['frames']}"
        )
