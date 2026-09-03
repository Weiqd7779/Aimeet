import re
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz.fuzz import partial_ratio


@dataclass(frozen=True)
class Chunk:
    id: str
    title: str
    type: str
    source: str
    text: str
    score: float = 0.0


FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _parse_document(path: Path) -> tuple[dict[str, str], str]:
    content = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(content)
    metadata: dict[str, str] = {}
    if match:
        for line in match.group(1).splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip().strip("\"'")
        content = content[match.end() :]
    return metadata, content.strip()


def _tokens(text: str) -> set[str]:
    normalized = text.lower()
    words = set(re.findall(r"[a-z0-9][a-z0-9_-]*", normalized))
    compact = re.sub(r"\s+", "", normalized)
    words.update(compact[index : index + 2] for index in range(max(0, len(compact) - 1)))
    return words


class KnowledgeStore:
    def __init__(self, docs_dir: Path | None = None) -> None:
        self.docs_dir = docs_dir or Path(__file__).parent / "docs"
        self._chunks = self._load()

    def _load(self) -> list[Chunk]:
        chunks: list[Chunk] = []
        for path in sorted(self.docs_dir.glob("*.md")):
            metadata, body = _parse_document(path)
            paragraphs = [
                paragraph.strip() for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()
            ]
            for index, paragraph in enumerate(paragraphs):
                chunks.append(
                    Chunk(
                        id=f"{metadata.get('id', path.stem)}-{index + 1}",
                        title=metadata.get("title", path.stem),
                        type=metadata.get("type", "spec"),
                        source=metadata.get("source", path.name),
                        text=paragraph,
                    )
                )
        return chunks

    def documents(self) -> list[dict[str, str]]:
        seen: dict[str, dict[str, str]] = {}
        for chunk in self._chunks:
            seen.setdefault(
                chunk.id.rsplit("-", 1)[0],
                {
                    "id": chunk.id.rsplit("-", 1)[0],
                    "title": chunk.title,
                    "type": chunk.type,
                    "source": chunk.source,
                },
            )
        return list(seen.values())

    def search(self, query: str, k: int = 5) -> list[Chunk]:
        if not query.strip():
            return []
        query_tokens = _tokens(query)
        results: list[Chunk] = []
        for chunk in self._chunks:
            text_tokens = _tokens(chunk.text)
            overlap = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
            fuzzy = partial_ratio(query.lower(), chunk.text.lower()) / 100
            score = overlap * 0.65 + fuzzy * 0.35
            if score > 0:
                results.append(Chunk(**{**chunk.__dict__, "score": score}))
        return sorted(results, key=lambda chunk: (-chunk.score, chunk.id))[:k]


store = KnowledgeStore()
