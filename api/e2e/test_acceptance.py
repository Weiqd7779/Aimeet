"""pytest entry point: `AIMEET_E2E=1 uv run pytest e2e -v` (needs the API running with
LIVE_PROVIDER=openai). Skipped by default so the unit suite stays free and offline."""

import asyncio
import os

import pytest

from e2e.harness import run_scenario
from e2e.judge import grade
from e2e.run import load_scenarios

pytestmark = pytest.mark.skipif(
    os.environ.get("AIMEET_E2E") != "1", reason="set AIMEET_E2E=1 to run live acceptance tests"
)


@pytest.mark.parametrize("scenario", load_scenarios([]), ids=lambda s: s.id)
def test_scenario(scenario) -> None:
    result = asyncio.run(run_scenario(scenario))
    verdict = asyncio.run(grade(result))
    failures = [f"{name}: {detail}" for name, ok, detail in verdict.checks if not ok]
    assert not failures, "\n".join(failures)
