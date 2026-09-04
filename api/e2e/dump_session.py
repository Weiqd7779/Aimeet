"""Dump a session as a readable timeline. Usage: python -m e2e.dump_session [session_id]"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
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
        print(f"[{o['ts']:6.1f}]   FRAME {o['reason']} scene={o['scene_seq']} {o['id'][:8]}")
    elif kind == "tool":
        print(f"          tool {o['tool']}")
    elif kind == "echo_dropped":
        print(f"[{o['ts']:6.1f}]   ECHO_DROPPED {o['text'][:60]}")
    elif kind == "stt_rejected":
        print(f"[{o['ts']:6.1f}]   STT_REJECTED ({o['why']}) {o['text'][:60]}")
    elif kind == "closed":
        print(
            f"CLOSED {o['reason']} elapsed={o['elapsed']:.0f}s "
            f"audio={o['audio_chunks']} frames={o['frames']}"
        )

record = json.loads((folder / "record.json").read_text("utf-8"))
frames = {f["id"]: f for f in record["frames"]}
if record["grounded_events"]:
    print("\n--- grounded events ---")
for g in record["grounded_events"]:
    f = frames.get(g["frame_id"], {})
    print(
        f"[{g['ts']:6.1f}] {g['speaker']} conf={g['confidence']}\n"
        f"   said:   {g['utterance']}\n"
        f"   target: {g['target']}\n"
        f"   obs:    {g['observation'][:140]}\n"
        f"   frame:  ts={f.get('ts', '?')} reason={f.get('reason', '?')} {g['frame_id'][:8]}"
    )
