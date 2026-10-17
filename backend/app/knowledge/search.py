"""F16 rule & policy Q&A retrieval: Vertex AI Search over the official source pages, with an offline fallback.

* VertexSearch — Discovery Engine `servingConfigs.search` (REST, ADC) when VERTEX_SEARCH_SERVING_CONFIG is set.
* LocalSearch  — BM25 over knowledge/text/*.txt (same documents) for mock mode and local runs.
* Neither      — explain_rule falls back to the playbook's rules_text only.

Search results are only used to explain and cite; rule facts (amounts, days, dates) always come from the playbook,
and the co-pilot post-check never treats snippet numbers as verified values.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from pathlib import Path
from typing import Protocol

from ..config import get_settings

log = logging.getLogger("recoverai.knowledge")
_TOKEN = re.compile(r"[a-z0-9₹%]+|[\u0900-\u097F]+", re.I)
_STOP = set("the a an and or of to in for on is are be by with your you it this that from as at was were will can has have not".split())
SEARCH_TIMEOUT_S = 4.0


class Searcher(Protocol):
    name: str

    def search(self, query: str, country: str | None = None, k: int = 2) -> list[dict]: ...


def _tokens(text: str) -> list[str]:
    return [t for t in (m.group(0).lower() for m in _TOKEN.finditer(text)) if t not in _STOP and len(t) > 1]


class LocalSearch:
    name = "local"

    def __init__(self, knowledge_dir: str | Path, min_score: float = 2.5):
        self.dir = Path(knowledge_dir)
        manifest = json.loads((self.dir / "sources.json").read_text(encoding="utf-8"))
        self.passages: list[dict] = []
        for src in manifest["sources"]:
            text = (self.dir / src["text"]).read_text(encoding="utf-8")
            body = text.split("\n\n", 1)[1] if "\n\n" in text else text
            buf = ""
            for para in [p.strip() for p in body.split("\n") if p.strip()]:
                buf = f"{buf} {para}".strip()
                if len(buf) >= 500:
                    self._add(src, buf)
                    buf = ""
            if buf:
                self._add(src, buf)
        self.df: dict[str, int] = {}
        for p in self.passages:
            for t in set(p["tokens"]):
                self.df[t] = self.df.get(t, 0) + 1
        self.avg = sum(len(p["tokens"]) for p in self.passages) / max(1, len(self.passages))
        self.min_score = min_score

    def _add(self, src: dict, text: str) -> None:
        self.passages.append({"src": src, "text": text, "tokens": _tokens(text + " " + " ".join(src.get("topics") or []))})

    def search(self, query: str, country: str | None = None, k: int = 2) -> list[dict]:
        q = set(_tokens(query))
        n = len(self.passages)
        scored = []
        for p in self.passages:
            if country and p["src"].get("country") not in (country, None):
                continue
            tf: dict[str, int] = {}
            for t in p["tokens"]:
                if t in q:
                    tf[t] = tf.get(t, 0) + 1
            s = 0.0
            for t, f in tf.items():
                idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(p["tokens"]) / self.avg))
            if s >= self.min_score:
                scored.append((s, p))
        scored.sort(key=lambda x: -x[0])
        out, seen = [], set()
        for s, p in scored:
            if p["src"]["url"] in seen:
                continue
            seen.add(p["src"]["url"])
            out.append({"title": p["src"]["title"], "url": p["src"]["url"], "publisher": p["src"].get("publisher"),
                        "snippet": p["text"][:400], "score": round(s, 2)})
            if len(out) >= k:
                break
        return out


def _clean_snippet(text: str) -> str:
    """Vertex snippets are HTML (<b> highlights, &nbsp;, &#39;): plain text with collapsed whitespace."""
    import html

    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or "")).replace("\xa0", " ")).strip()


class VertexSearch:
    name = "vertex"

    def __init__(self, serving_config: str, relevance: str = "LOW"):
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.session = AuthorizedSession(creds)
        self.serving_config = serving_config
        self.relevance = relevance

    def search(self, query: str, country: str | None = None, k: int = 2) -> list[dict]:
        body = {"query": query[:500], "pageSize": 6, "relevanceThreshold": self.relevance,
                "contentSearchSpec": {"snippetSpec": {"returnSnippet": True}}}
        r = self.session.post(f"https://discoveryengine.googleapis.com/v1/{self.serving_config}:search", json=body,
                              timeout=SEARCH_TIMEOUT_S)
        r.raise_for_status()
        out, seen = [], set()
        for res in r.json().get("results", []):
            doc = res.get("document", {})
            sd, dd = doc.get("structData") or {}, doc.get("derivedStructData") or {}
            if country and sd.get("country") and sd["country"] != country:
                continue
            url = sd.get("url") or dd.get("link")
            if not url or url in seen:
                continue
            seen.add(url)
            snip = " ".join(_clean_snippet(s.get("snippet", "")) for s in dd.get("snippets") or [])
            out.append({"title": sd.get("title") or dd.get("title") or url, "url": url, "publisher": sd.get("publisher"),
                        "snippet": snip.strip()[:400]})
            if len(out) >= k:
                break
        return out


_searcher: Searcher | None = None
_resolved = False


def get_searcher() -> Searcher | None:
    global _searcher, _resolved
    if not _resolved:
        s = get_settings()
        try:
            if s.vertex_search_serving_config:
                _searcher = VertexSearch(s.vertex_search_serving_config)
            elif (Path(s.knowledge_dir) / "sources.json").exists():
                _searcher = LocalSearch(s.knowledge_dir)
        except Exception:  # noqa: BLE001
            log.exception("knowledge search unavailable; playbook text only")
            _searcher = None
        _resolved = True
    return _searcher


def set_searcher(s: Searcher | None) -> None:
    global _searcher, _resolved
    _searcher, _resolved = s, True


def search_sources(query: str, country: str | None, k: int = 2) -> list[dict]:
    """Never raises; [] means "no result passed the relevance threshold" → playbook text only."""
    s = get_searcher()
    if not s or not query.strip():
        return []
    t0 = time.perf_counter()
    try:
        res = s.search(query, country, k)
    except Exception as e:  # noqa: BLE001
        log.warning("knowledge search failed", extra={"step": "vertex_search", "err": str(e)[:200]})
        return []
    log.info("knowledge search", extra={"step": "vertex_search", "backend": s.name, "hits": len(res),
                                        "latencyMs": int((time.perf_counter() - t0) * 1000)})
    return res
