from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.services.chat_context_policy import ContextTemperature

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
_DENYLIST = (
    "w1",
    "w2",
    "w3",
    "w4",
    "w5",
    "w6",
    "w7",
    "weight aliases",
)


@dataclass(frozen=True)
class DocSection:
    source: str
    heading_path: str
    body: str

    def to_prompt_excerpt(self, max_words: int = 100) -> str:
        words = self.body.split()
        clipped = " ".join(words[:max_words]).strip()
        if len(words) > max_words:
            clipped += " ..."
        return f"[{self.source}] {self.heading_path}\n{clipped}"


@dataclass(frozen=True)
class _ScoredSection:
    section: DocSection
    tokens: tuple[str, ...]


class DocsIndex:
    def __init__(self, sections: list[_ScoredSection]) -> None:
        self._sections = sections
        df: dict[str, int] = {}
        for sec in sections:
            for tok in set(sec.tokens):
                df[tok] = df.get(tok, 0) + 1
        self._idf: dict[str, float] = {}
        n = max(len(sections), 1)
        for tok, count in df.items():
            self._idf[tok] = math.log(1 + (n / (1 + count)))

    def search(self, query: str, k: int = 2, min_score: float = 0.8) -> list[DocSection]:
        q_tokens = tuple(_tokenize(query))
        if not q_tokens:
            return []
        scored: list[tuple[float, DocSection]] = []
        q_set = set(q_tokens)
        for sec in self._sections:
            overlap = q_set.intersection(sec.tokens)
            if not overlap:
                continue
            score = sum(self._idf.get(tok, 0.0) for tok in overlap)
            if score >= min_score:
                scored.append((score, sec.section))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [section for _, section in scored[:k]]


_CACHE: dict[str, DocsIndex] = {}


def _tokenize(text: str) -> Iterable[str]:
    for m in _TOKEN_RE.finditer((text or "").lower()):
        token = m.group(0)
        if len(token) >= 2:
            yield token


def _parse_sections(path: Path, source_prefix: str) -> list[DocSection]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines = raw.splitlines()
    current_h2 = "Overview"
    current_h3 = ""
    buff: list[str] = []
    sections: list[DocSection] = []

    def flush() -> None:
        if not buff:
            return
        body = "\n".join(buff).strip()
        buff.clear()
        if not body:
            return
        lower = body.lower()
        if any(term in lower for term in _DENYLIST):
            return
        heading = current_h2 if not current_h3 else f"{current_h2} > {current_h3}"
        sections.append(
            DocSection(
                source=f"{source_prefix}/{path.name}",
                heading_path=heading,
                body=body,
            )
        )

    for line in lines:
        m = _HEADING_RE.match(line.strip())
        if m:
            flush()
            level, title = m.group(1), m.group(2).strip()
            if level == "##":
                current_h2 = title
                current_h3 = ""
            else:
                current_h3 = title
            continue
        buff.append(line)
    flush()
    return sections


def _collect_docs(repo_root: Path, test_problem_id: str | None, temperature: ContextTemperature) -> list[Path]:
    docs: list[Path] = sorted((repo_root / "docs" / "user").glob("*.md"))
    if temperature in {"warm", "hot"}:
        problem_id = str(test_problem_id or "").strip().lower()
        if problem_id:
            module_docs_dir = repo_root / f"{problem_id}_problem" / "docs" / "user"
            docs.extend(sorted(module_docs_dir.glob("*.md")))
    return docs


def load_docs_index(repo_root: Path, test_problem_id: str | None, temperature: ContextTemperature) -> DocsIndex:
    key = f"{repo_root.resolve()}::{test_problem_id or ''}::{temperature}"
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    sections: list[_ScoredSection] = []
    for path in _collect_docs(repo_root, test_problem_id, temperature):
        source_prefix = "docs/user"
        if "_problem" in path.as_posix():
            source_prefix = "module-docs/user"
        for section in _parse_sections(path, source_prefix=source_prefix):
            tokens = tuple(_tokenize(f"{section.heading_path}\n{section.body}"))
            if tokens:
                sections.append(_ScoredSection(section=section, tokens=tokens))
    index = DocsIndex(sections)
    _CACHE[key] = index
    return index


def search_reference_excerpts(
    *,
    repo_root: Path,
    user_text: str,
    test_problem_id: str | None,
    temperature: ContextTemperature,
    max_items: int = 2,
) -> list[str]:
    index = load_docs_index(repo_root, test_problem_id=test_problem_id, temperature=temperature)
    hits = index.search(user_text, k=max_items)
    return [hit.to_prompt_excerpt() for hit in hits]
