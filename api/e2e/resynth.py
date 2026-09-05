"""Force re-synthesis of a persisted session through the running API and print the report.

uv run python -m e2e.resynth <session_id>
"""

import sys

import httpx


def main(session_id: str) -> None:
    r = httpx.post(
        f"http://localhost:8000/sessions/{session_id}/synthesize", json={"force": True}, timeout=300
    )
    print(r.status_code)
    rep = r.json()["report"]
    print("--- topics ---")
    for t in rep.get("topics", []):
        print(f"  [{t['id']}] {t['title']} ({t['ts_start']}-{t['ts_end']}): {t['gist']}")
    print("--- summary ---")
    print(rep["summary"])
    print("--- facts ---")
    for f in rep["key_facts"]:
        print(f"  ({f.get('topic')}) [{f['category']}] {f['fact']}  <{f['resolved_date']}>")
        print(f"      quote: {f['quote']}")
    print("--- PRD ---")
    print(rep["prd_markdown"])
    print("--- mermaid ---")
    print(rep["mermaid"])
    print("--- notes ---")
    print(rep["open_questions"])
    print(rep["uncertainties"])
    print("--- work ---")
    for w in rep["work_items"]:
        print(w["title"])
        print(w["body_markdown"])


if __name__ == "__main__":
    main(sys.argv[1])
