"""STT A/B benchmark.

    uv run python -m bench.stt                 # all providers, 3 runs each
    uv run python -m bench.stt --runs 1 --providers gpt-live-transcribe
    uv run python -m bench.stt --items mx01 fast03

Writes bench/results/<timestamp>.md (summary + per-item) and .jsonl (raw records).
"""

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings
from app.live.audio import resample_pcm16
from bench.metrics import Score, score
from bench.providers import PROVIDERS, SttResult, transcribe
from e2e.harness import RATE, _trim

HERE = Path(__file__).parent
CACHE = HERE / ".cache"
RESULTS = HERE / "results"
VOICES = {"USER": "alloy", "REMOTE": "onyx"}


@dataclass
class Record:
    provider: str
    item_id: str
    category: str
    speaker: str
    run: int
    reference_text: str
    transcript: str
    first_partial_latency_ms: float | None
    final_latency_ms: float | None
    cer: float
    term_recall: float | None
    terms_missed: list[str]
    traditional: bool
    simplified_chars: list[str]
    substitutions: int
    deletions: int
    insertions: int
    finals: int
    error: str | None


async def tts(text: str, speaker: str, speed: float | None) -> bytes:
    CACHE.mkdir(exist_ok=True)
    voice = VOICES[speaker]
    key = hashlib.sha1(f"{voice}:{speed}:{text}".encode()).hexdigest()
    cached = CACHE / f"{key}.pcm"
    if cached.exists():
        return cached.read_bytes()
    kwargs = {"instructions": "語速明顯偏快，像趕時間的工程師在會議上講話。"} if speed else {}
    response = await AsyncOpenAI(api_key=settings.openai_api_key).audio.speech.create(
        model="gpt-4o-mini-tts", voice=voice, input=text, response_format="pcm", **kwargs
    )
    pcm = _trim(resample_pcm16(await response.aread(), source_rate=24_000, target_rate=RATE))
    cached.write_bytes(pcm)
    return pcm


def to_record(item: dict, run: int, result: SttResult, scored: Score) -> Record:
    return Record(
        provider=result.provider,
        item_id=item["id"],
        category=item["category"],
        speaker=item["speaker"],
        run=run,
        reference_text=item["text"],
        transcript=result.transcript,
        first_partial_latency_ms=result.first_partial_ms,
        final_latency_ms=result.final_ms,
        cer=scored.cer,
        term_recall=scored.term_recall,
        terms_missed=scored.terms_missed,
        traditional=scored.traditional,
        simplified_chars=scored.simplified_chars,
        substitutions=scored.substitutions,
        deletions=scored.deletions,
        insertions=scored.insertions,
        finals=result.finals,
        error=result.error,
    )


def load_records(path: Path) -> list[Record]:
    if not path.exists():
        return []
    return [
        Record(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def run_bench(
    providers: list[str], runs: int, item_ids: list[str], raw_path: Path
) -> list[Record]:
    """Append every record to `raw_path` as it completes; on rerun, skip successful
    (provider, item, run) triples and redo failed ones."""
    corpus = json.loads((HERE / "corpus.json").read_text(encoding="utf-8"))
    vocabulary: list[str] = corpus["vocabulary"]
    items = [i for i in corpus["items"] if not item_ids or i["id"] in item_ids]
    previous = load_records(raw_path)
    done = {(r.provider, r.item_id, r.run) for r in previous if not r.error and r.transcript}
    records = [r for r in previous if (r.provider, r.item_id, r.run) in done]
    for run in range(1, runs + 1):
        for item in items:
            todo = [p for p in providers if (p, item["id"], run) not in done]
            if not todo:
                continue
            pcm = await tts(item["text"], item["speaker"], item.get("speed"))
            results = await asyncio.gather(*(transcribe(p, pcm, vocabulary) for p in todo))
            for result in results:
                scored = score(item["text"], result.transcript, item.get("terms", []))
                record = to_record(item, run, result, scored)
                records.append(record)
                with raw_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
                flag = "ERR " if record.error else ""
                print(
                    f"[{run}] {item['id']:7} {result.provider:26} {flag}cer={record.cer:.2f} "
                    f"recall={record.term_recall if record.term_recall is not None else '-'} "
                    f"partial={_fmt(record.first_partial_latency_ms)} final={_fmt(record.final_latency_ms)} "
                    f"| {record.transcript[:60]}",
                    flush=True,
                )
    return records


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}ms"


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, round(q * (len(values) - 1)))
    return values[index]


def summarize(records: list[Record], providers: list[str]) -> str:
    lines = [
        "| Provider | 中文 CER (mean) | 術語 recall | 繁體率 | Partial p50 / p95 | Final p50 / p95 | 錯誤/空白 | $/min |",
        "|---|---|---|---|---|---|---|---|",
    ]
    price = {
        "gemini-3.5-transcribe-live": "~0.009",
        "gpt-live-transcribe": "0.017",
        "gpt-4o-mini-transcribe": "0.003",
    }
    for provider in providers:
        rows = [r for r in records if r.provider == provider]
        ok = [r for r in rows if not r.error and r.transcript]
        cer = statistics.mean(r.cer for r in ok) if ok else float("nan")
        recalls = [r.term_recall for r in ok if r.term_recall is not None]
        recall = statistics.mean(recalls) if recalls else float("nan")
        trad = sum(r.traditional for r in ok) / len(ok) if ok else float("nan")
        partials = [
            r.first_partial_latency_ms for r in ok if r.first_partial_latency_ms is not None
        ]
        finals = [r.final_latency_ms for r in ok if r.final_latency_ms is not None]
        failures = len(rows) - len(ok)
        lines.append(
            f"| {provider} | {cer:.1%} | {recall:.1%} | {trad:.0%} | "
            f"{_fmt(_pct(partials, 0.5))} / {_fmt(_pct(partials, 0.95))} ({len(partials)}/{len(ok)} 有 partial) | "
            f"{_fmt(_pct(finals, 0.5))} / {_fmt(_pct(finals, 0.95))} | {failures}/{len(rows)} | {price.get(provider, '?')} |"
        )

    lines += [
        "",
        "### 各類別 CER",
        "",
        "| 類別 | " + " | ".join(providers) + " |",
        "|---|" + "---|" * len(providers),
    ]
    for category in dict.fromkeys(r.category for r in records):
        cells = []
        for provider in providers:
            ok = [
                r
                for r in records
                if r.provider == provider
                and r.category == category
                and not r.error
                and r.transcript
            ]
            cells.append(f"{statistics.mean(r.cer for r in ok):.1%}" if ok else "-")
        lines.append(f"| {category} | " + " | ".join(cells) + " |")

    lines += ["", "### 術語漏辨（出現次數）", ""]
    for provider in providers:
        missed: dict[str, int] = {}
        for r in records:
            if r.provider == provider:
                for term in r.terms_missed:
                    missed[term] = missed.get(term, 0) + 1
        top = sorted(missed.items(), key=lambda kv: -kv[1])[:12]
        lines.append(f"- **{provider}**: " + (", ".join(f"{t}×{n}" for t, n in top) or "無"))
    return "\n".join(lines)


def render(records: list[Record], providers: list[str], runs: int) -> str:
    lines = [
        f"# STT A/B benchmark - {datetime.now().astimezone():%Y-%m-%d %H:%M}",
        "",
        f"- 語料：{len({r.item_id for r in records})} 句 × {runs} 次，TTS 合成（gpt-4o-mini-tts，alloy=USER / onyx=REMOTE），首尾靜音已裁切",
        "- VAD：各家 server 端自動 VAD（OpenAI `server_vad` 預設；Gemini Automatic）",
        "- 詞彙：同一份術語表（Gemini `custom_vocabulary` / gpt-live-transcribe `keywords` / gpt-4o-mini-transcribe `prompt`）",
        "- CER 比對前正規化：NFKC、簡→繁、中文數字→阿拉伯數字、去標點空白、小寫；「繁體率」另計",
        "- Partial latency = 語音開始 → 第一個 delta/interim；Final latency = 語音結束 → completed/final",
        "",
        "## 總表",
        "",
        summarize(records, providers),
        "",
        "## 逐句結果",
        "",
        "| run | id | provider | CER | recall | partial | final | transcript |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(records, key=lambda r: (r.item_id, r.provider, r.run)):
        text = (r.error or r.transcript).replace("|", "\\|")
        recall = "-" if r.term_recall is None else f"{r.term_recall:.0%}"
        lines.append(
            f"| {r.run} | {r.item_id} | {r.provider} | {r.cer:.2f} | {recall} | "
            f"{_fmt(r.first_partial_latency_ms)} | {_fmt(r.final_latency_ms)} | {text} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--providers", nargs="*", default=list(PROVIDERS))
    parser.add_argument("--items", nargs="*", default=[])
    parser.add_argument("--name", default=None, help="result name; reuse to resume a run")
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)
    stamp = args.name or f"{datetime.now().astimezone():%Y%m%d-%H%M%S}"
    raw_path = RESULTS / f"{stamp}.jsonl"
    records = asyncio.run(run_bench(args.providers, args.runs, args.items, raw_path))
    report = RESULTS / f"{stamp}.md"
    report.write_text(render(records, args.providers, args.runs), encoding="utf-8")
    print("\n" + summarize(records, args.providers))
    print(f"\nReport: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
