"""Re-run the reasoning layer over a recorded session (utterances + frames on disk).

Lets us check grounding changes against a real meeting without recording it again:
speech spans and frame timestamps come from the record, exactly as they happened.

uv run python -m e2e.replay <session_id> [--only 杯子 指甲剪]
"""

import asyncio
import json
import sys
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings
from app.live.reasoner import Reasoner

ROOT = Path("data/sessions")


async def main(session_id: str, only: list[str]) -> None:
    folder = ROOT / session_id
    record = json.loads((folder / "record.json").read_text("utf-8"))
    reasoner = Reasoner(
        AsyncOpenAI(api_key=settings.openai_api_key), settings.openai_reasoning_model
    )
    reasoner.context_provider = lambda: ""
    for frame in record["frames"]:
        path = folder / "frames" / f"{frame['id']}.jpg"
        if path.exists():
            reasoner.set_frame(frame["ts"], path.read_bytes(), frame["id"])
    print(
        f"{len(record['frames'])} frames loaded, ts {record['frames'][0]['ts']:.1f}..{record['frames'][-1]['ts']:.1f}"
    )

    events = [json.loads(l) for l in (folder / "events.jsonl").read_text("utf-8").splitlines()]
    utterances = [e for e in events if e["event"] == "utterance"]
    for u in utterances:
        if only and not any(k in u["text"] for k in only):
            reasoner._history.append((u["speaker"], u["text"]))
            continue
        # the old record has no speech end; approximate with wall-clock arrival gap
        ended = u["ts"] + min(8.0, max(2.0, len(u["text"]) * 0.25))
        calls = await reasoner.process(u["speaker"], u["text"], u["ts"], ended=ended)
        print(f"\n[{u['ts']:6.1f}] {u['speaker']} {u['text']}")
        for call in calls:
            if call.name == "create_anchor":
                a = call.args
                print(
                    f"   -> ANCHOR conf={a.get('confidence')} frame_ts={a.get('frame_ts', 0):.1f}\n"
                    f"      target: {a.get('target')}\n      obs: {str(a.get('observation'))[:140]}"
                )
            else:
                print(f"   -> {call.name} {json.dumps(call.args, ensure_ascii=False)[:120]}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = sys.argv[1:]
    only = args[args.index("--only") + 1 :] if "--only" in args else []
    session = (
        args[0]
        if args and args[0] != "--only"
        else max(ROOT.iterdir(), key=lambda p: p.stat().st_mtime).name
    )
    asyncio.run(main(session, only))
