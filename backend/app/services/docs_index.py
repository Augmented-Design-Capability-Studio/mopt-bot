"""Reference-doc retrieval for the chat system prompt.

Two paths:
1. **Embeddings (preferred)** — when a Gemini API key is available, sections are
   embedded with `text-embedding-004` once per (repo, doc-content) and cached on
   disk under ``backend/.cache/docs_embeddings/<sha>.json``. Queries embed once
   per call and rank by cosine similarity. Robust to paraphrases and
   vocabulary mismatch.
2. **TF-IDF fallback** — bag-of-words IDF over heading + body. Used when no API
   key is provided (tests, offline dev) or when an embedding lookup fails. The
   fallback preserves the prior behaviour and keeps the in-process cache hot.

Both paths share the same denylist + section parsing so tests that pin
denylist behaviour don't have to change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.services.chat_context_policy import ContextTemperature

log = logging.getLogger(__name__)

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

_EMBEDDING_MODEL = "text-embedding-004"
_EMBEDDING_BATCH_SIZE = 64
_EMBEDDING_MIN_COSINE = 0.55


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


@dataclass(frozen=True)
class _EmbeddedSection:
    section: DocSection
    embedding: tuple[float, ...]


class DocsIndex:
    """TF-IDF index — keyword fallback when embeddings are unavailable."""

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


class EmbeddingDocsIndex:
    """Embedding-backed index — primary path when a Gemini key is configured."""

    def __init__(self, embedded: list[_EmbeddedSection]) -> None:
        self._embedded = embedded

    def search(
        self,
        query_embedding: tuple[float, ...],
        k: int = 2,
        min_score: float = _EMBEDDING_MIN_COSINE,
    ) -> list[DocSection]:
        if not query_embedding or not self._embedded:
            return []
        scored: list[tuple[float, DocSection]] = []
        q_norm = _vector_norm(query_embedding)
        if q_norm == 0.0:
            return []
        for entry in self._embedded:
            d_norm = _vector_norm(entry.embedding)
            if d_norm == 0.0:
                continue
            dot = sum(a * b for a, b in zip(query_embedding, entry.embedding))
            cosine = dot / (q_norm * d_norm)
            if cosine >= min_score:
                scored.append((cosine, entry.section))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [section for _, section in scored[:k]]


_TFIDF_CACHE: dict[str, DocsIndex] = {}
_EMBEDDING_CACHE: dict[str, EmbeddingDocsIndex] = {}


def _vector_norm(vec: Iterable[float]) -> float:
    return math.sqrt(sum(v * v for v in vec))


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


def _collect_sections(repo_root: Path, test_problem_id: str | None, temperature: ContextTemperature) -> list[DocSection]:
    out: list[DocSection] = []
    for path in _collect_docs(repo_root, test_problem_id, temperature):
        source_prefix = "docs/user"
        if "_problem" in path.as_posix():
            source_prefix = "module-docs/user"
        out.extend(_parse_sections(path, source_prefix=source_prefix))
    return out


def load_docs_index(repo_root: Path, test_problem_id: str | None, temperature: ContextTemperature) -> DocsIndex:
    """TF-IDF index loader (preserved for the no-key fallback path and tests)."""
    key = f"{repo_root.resolve()}::{test_problem_id or ''}::{temperature}"
    cached = _TFIDF_CACHE.get(key)
    if cached is not None:
        return cached

    sections: list[_ScoredSection] = []
    for section in _collect_sections(repo_root, test_problem_id, temperature):
        tokens = tuple(_tokenize(f"{section.heading_path}\n{section.body}"))
        if tokens:
            sections.append(_ScoredSection(section=section, tokens=tokens))
    index = DocsIndex(sections)
    _TFIDF_CACHE[key] = index
    return index


# --- Embedding path ----------------------------------------------------------


def _content_hash(sections: list[DocSection]) -> str:
    h = hashlib.sha256()
    for sec in sections:
        h.update(sec.source.encode("utf-8"))
        h.update(b"\x00")
        h.update(sec.heading_path.encode("utf-8"))
        h.update(b"\x00")
        h.update(sec.body.encode("utf-8"))
        h.update(b"\x01")
    h.update(_EMBEDDING_MODEL.encode("utf-8"))
    return h.hexdigest()


def _embedding_cache_dir(repo_root: Path) -> Path:
    return repo_root / "backend" / ".cache" / "docs_embeddings"


def _read_embedding_cache(cache_path: Path) -> list[_EmbeddedSection] | None:
    try:
        raw = cache_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    out: list[_EmbeddedSection] = []
    for entry in data:
        if not isinstance(entry, dict):
            return None
        try:
            section = DocSection(
                source=str(entry["source"]),
                heading_path=str(entry["heading_path"]),
                body=str(entry["body"]),
            )
            embedding = tuple(float(x) for x in entry["embedding"])
        except (KeyError, TypeError, ValueError):
            return None
        out.append(_EmbeddedSection(section=section, embedding=embedding))
    return out


def _write_embedding_cache(cache_path: Path, embedded: list[_EmbeddedSection]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    payload = [
        {
            "source": entry.section.source,
            "heading_path": entry.section.heading_path,
            "body": entry.section.body,
            "embedding": list(entry.embedding),
        }
        for entry in embedded
    ]
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, cache_path)
    except OSError as exc:
        log.warning("Failed to write embedding cache %s: %s", cache_path, exc)


def _embed_texts(
    *,
    api_key: str,
    texts: list[str],
    task_type: str,
) -> list[tuple[float, ...]] | None:
    """Embed a batch of texts via google-genai. Returns None on failure."""
    if not texts:
        return []
    try:
        from google import genai
        from google.genai import types as _types
    except ImportError:
        return None
    try:
        client = genai.Client(api_key=api_key)
    except Exception as exc:
        log.warning("Embedding client init failed (%s)", exc)
        return None

    out: list[tuple[float, ...]] = []
    try:
        for i in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
            batch = texts[i : i + _EMBEDDING_BATCH_SIZE]
            resp = client.models.embed_content(
                model=_EMBEDDING_MODEL,
                contents=batch,
                config=_types.EmbedContentConfig(task_type=task_type),
            )
            embeddings = getattr(resp, "embeddings", None) or []
            if len(embeddings) != len(batch):
                return None
            for emb in embeddings:
                values = getattr(emb, "values", None)
                if not values:
                    return None
                out.append(tuple(float(v) for v in values))
    except Exception as exc:
        log.warning("Embedding batch call failed (%s)", exc)
        return None
    return out


def _build_embedding_index(
    *,
    repo_root: Path,
    sections: list[DocSection],
    api_key: str,
) -> EmbeddingDocsIndex | None:
    if not sections:
        return EmbeddingDocsIndex([])
    digest = _content_hash(sections)
    cache_path = _embedding_cache_dir(repo_root) / f"{digest}.json"
    cached = _read_embedding_cache(cache_path)
    if cached is not None and len(cached) == len(sections):
        return EmbeddingDocsIndex(cached)

    payloads = [f"{sec.heading_path}\n\n{sec.body}" for sec in sections]
    vectors = _embed_texts(api_key=api_key, texts=payloads, task_type="RETRIEVAL_DOCUMENT")
    if vectors is None or len(vectors) != len(sections):
        return None
    embedded = [
        _EmbeddedSection(section=sec, embedding=vec)
        for sec, vec in zip(sections, vectors)
    ]
    _write_embedding_cache(cache_path, embedded)
    return EmbeddingDocsIndex(embedded)


def _load_embedding_index(
    *,
    repo_root: Path,
    test_problem_id: str | None,
    temperature: ContextTemperature,
    api_key: str,
) -> EmbeddingDocsIndex | None:
    sections = _collect_sections(repo_root, test_problem_id, temperature)
    cache_key = f"{repo_root.resolve()}::{test_problem_id or ''}::{temperature}::{_content_hash(sections)}"
    cached = _EMBEDDING_CACHE.get(cache_key)
    if cached is not None:
        return cached
    index = _build_embedding_index(
        repo_root=repo_root,
        sections=sections,
        api_key=api_key,
    )
    if index is None:
        return None
    _EMBEDDING_CACHE[cache_key] = index
    return index


def search_reference_excerpts(
    *,
    repo_root: Path,
    user_text: str,
    test_problem_id: str | None,
    temperature: ContextTemperature,
    max_items: int = 2,
    api_key: str | None = None,
) -> list[str]:
    """Return up to ``max_items`` reference excerpts relevant to ``user_text``.

    Prefers embedding search when ``api_key`` is provided; falls back to TF-IDF
    on any failure or when no key is configured. Tests and offline dev paths
    that omit ``api_key`` get the original keyword behaviour unchanged.
    """
    text = (user_text or "").strip()
    if not text:
        return []

    if api_key:
        try:
            embedding_index = _load_embedding_index(
                repo_root=repo_root,
                test_problem_id=test_problem_id,
                temperature=temperature,
                api_key=api_key,
            )
        except Exception:
            log.exception("Embedding index load failed; falling back to TF-IDF")
            embedding_index = None
        if embedding_index is not None:
            query_vec = _embed_texts(
                api_key=api_key,
                texts=[text],
                task_type="RETRIEVAL_QUERY",
            )
            if query_vec is not None and len(query_vec) == 1:
                hits = embedding_index.search(query_vec[0], k=max_items)
                if hits:
                    return [hit.to_prompt_excerpt() for hit in hits]
                # Empty hit-list is a valid result (no doc clears threshold).
                # Still preferable to the keyword path's noise.
                return []

    index = load_docs_index(repo_root, test_problem_id=test_problem_id, temperature=temperature)
    hits = index.search(text, k=max_items)
    return [hit.to_prompt_excerpt() for hit in hits]
