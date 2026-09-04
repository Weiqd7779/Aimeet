"""Check that the LLM judge is not a rubber stamp.

Takes a real passing run (A8 by default: its criteria cover both speaker and content),
corrupts it in ways the product must never do, and requires the judge to FAIL each
corrupted copy while still PASSING the original.

uv run python -m e2e.calibrate            # runs A8 once, then judges 1 good + 3 bad copies
uv run python -m e2e.calibrate A3         # note: A3's criteria only cover speakers/order,
                                          # so content corruptions are *allowed* to pass
"""

import asyncio
import copy
import re
import sys

from e2e.harness import RunResult
from e2e.judge import Verdict, llm_judge
from e2e.run import load_scenarios, run_scenario


def _lines(result: RunResult) -> list[dict]:
    """Every place a transcript line lives (live events + persisted record)."""
    live = [e["payload"] for e in result.events if e["type"] == "transcript"]
    stored = (result.record or {}).get("utterances", [])
    return live + stored


def _swap_speakers(result: RunResult) -> RunResult:
    bad = copy.deepcopy(result)
    for line in _lines(bad):
        line["speaker"] = "與會者" if line["speaker"] == "我" else "我"
    return bad


NUMBER = re.compile(r"[零一二三四五六七八九十百千萬0-9,.]{2,}")  # a quantity, not 「一下」


def _drop_a_number(result: RunResult) -> RunResult:
    """Corrupt the longest number in the transcript (e.g. 一百五十塊 -> 塊)."""
    bad = copy.deepcopy(result)
    candidates = [
        (m.group(0), line["text"]) for line in _lines(bad) for m in NUMBER.finditer(line["text"])
    ]
    if not candidates:
        return bad
    number, target = max(candidates, key=lambda item: len(item[0]))
    for line in _lines(bad):
        if line["text"] == target:
            line["text"] = target.replace(number, "", 1)
    return bad


def _drop_last_line(result: RunResult) -> RunResult:
    bad = copy.deepcopy(result)
    indexes = [i for i, e in enumerate(bad.events) if e["type"] == "transcript"]
    if indexes:
        dropped = bad.events.pop(indexes[-1])["payload"]["id"]
        if bad.record:
            bad.record["utterances"] = [u for u in bad.record["utterances"] if u["id"] != dropped]
    return bad


CORRUPTIONS = {
    "swapped speakers": _swap_speakers,
    "missing digit": _drop_a_number,
    "missing last line": _drop_last_line,
}


async def main(scenario_id: str) -> int:
    scenario = load_scenarios([scenario_id])[0]
    print(f"running {scenario.id} for a baseline ...", flush=True)
    good = await run_scenario(scenario)
    failures = 0

    verdict = Verdict(scenario.id, True)
    await llm_judge(good, verdict)
    print(f"  original -> {'PASS' if verdict.passed else 'FAIL'}: {verdict.checks[-1][2]}")
    failures += not verdict.passed

    for name, corrupt in CORRUPTIONS.items():
        verdict = Verdict(scenario.id, True)
        await llm_judge(corrupt(good), verdict)
        caught = not verdict.passed
        print(
            f"  {name:18s} -> judge said {'FAIL (good)' if caught else 'PASS (BAD!)'}: "
            f"{verdict.checks[-1][2]}"
        )
        failures += not caught
    print(f"\n{'judge calibrated' if not failures else f'{failures} calibration failure(s)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "A8")))
