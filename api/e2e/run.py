"""Run acceptance scenarios against a live API and write a markdown report.

uv run python -m e2e.run            # all scenarios
uv run python -m e2e.run A4 B1      # subset by id prefix
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from e2e.harness import RunResult, Scenario, run_scenario
from e2e.judge import Verdict, grade

SCENARIO_DIR = Path(__file__).with_name("scenarios")
RESULT_DIR = Path(__file__).with_name("results")


def load_scenarios(filters: list[str]) -> list[Scenario]:
    scenarios = [Scenario.load(path) for path in sorted(SCENARIO_DIR.glob("*.json"))]
    if filters:
        scenarios = [s for s in scenarios if any(s.id.startswith(f) for f in filters)]
    return scenarios


def render(rows: list[tuple[RunResult, Verdict]]) -> str:
    lines = [
        f"# E2E acceptance run - {datetime.now().astimezone():%Y-%m-%d %H:%M}",
        "",
        "| ID | 標題 | 結果 | 耗時 |",
        "|----|------|------|------|",
    ]
    for result, verdict in rows:
        status = "PASS" if verdict.passed else "FAIL"
        lines.append(
            f"| {verdict.scenario_id} | {result.scenario.title} | {status} | {result.duration:.0f}s |"
        )
    for result, verdict in rows:
        lines += ["", f"## {verdict.scenario_id} - {result.scenario.title}", ""]
        for name, ok, detail in verdict.checks:
            lines.append(f"- [{'x' if ok else ' '}] `{name}` {detail}".rstrip())
        lines += ["", "<details><summary>逐字稿與事件</summary>", "", "```json"]
        lines.append(
            json.dumps(
                {
                    "transcripts": result.transcripts,
                    "decisions": result.payloads("decision"),
                    "grounded_events": result.payloads("grounded_event"),
                    "alerts": result.payloads("alert"),
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        lines += ["```", "", "</details>"]
    return "\n".join(lines) + "\n"


async def run_all(filters: list[str]) -> list[tuple[RunResult, Verdict]]:
    rows: list[tuple[RunResult, Verdict]] = []
    for scenario in load_scenarios(filters):
        print(f"[{scenario.id}] {scenario.title} ...", flush=True)
        result = await run_scenario(scenario)
        verdict = await grade(result)
        for name, ok, detail in verdict.checks:
            print(f"    {'PASS' if ok else 'FAIL'} {name} {detail}".rstrip())
        print(f"  => {'PASS' if verdict.passed else 'FAIL'} ({result.duration:.0f}s)", flush=True)
        rows.append((result, verdict))
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    rows = asyncio.run(run_all(sys.argv[1:]))
    RESULT_DIR.mkdir(exist_ok=True)
    path = RESULT_DIR / f"{datetime.now().astimezone():%Y%m%d-%H%M%S}.md"
    path.write_text(render(rows), encoding="utf-8")
    failed = [v.scenario_id for _, v in rows if not v.passed]
    print(f"\n{len(rows) - len(failed)}/{len(rows)} passed. Report: {path}")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
