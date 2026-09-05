"""Print a session's transcript next to its synthesis report. Usage: python -m e2e.dump_report [id]"""

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
    if o["event"] == "utterance":
        print(f"[{o['ts']:5.1f}] {o['speaker']} {o['text']}")
report_path = folder / "report.json"
if not report_path.exists():
    print("(no report)")
    raise SystemExit
r = json.loads(report_path.read_text("utf-8"))["report"]
print("\n--- summary ---\n" + r["summary"])
print("\n--- key_facts ---")
for f in r["key_facts"]:
    print(f"{f['category']:11s} {f['fact']}\n            quote: {f['quote']}")
print("\n--- decisions ---")
for d in r["decision_table"]:
    print(f"{d['topic']} -> {d['chosen']} [{d['status']}] {d['rationale'][:120]}")
print("\n--- open / uncertain ---")
print(r["open_questions"])
print(r["uncertainties"])
print("\n--- PRD ---\n" + r["prd_markdown"])
print("\n--- work items ---")
for w in r["work_items"]:
    print(f"* {w['title']}\n{w['body_markdown']}\n")
print("\n--- pages ---")
for p in r.get("scenes", []):
    print(f"p{p['seq'] + 1} {p['title']}: {p['summary']}")
