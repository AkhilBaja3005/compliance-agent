"""Linkup live scout: deep `sourcedAnswer` searches that attach verified source URLs to regulatory rules."""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.schemas.regulatory import RegulatoryRule

log = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 6 * 3600

# Targeted live-update queries (others fall back to a generic per-rule query)
RULE_QUERIES: dict[str, str] = {
    "EU_AI_ACT:Art.5": "EU AI Act Article 5 prohibited AI practices latest guidance including non-consensual intimate imagery (NCII), harmful manipulation and hate content",
    "EU_AI_ACT:Art.50": "EU AI Act Article 50(1) and 50(2) transparency obligations machine-readable marking watermark deadlines 2 August 2026 and 2 December 2026 transitional period",
    "EU_AI_ACT:AnnexIII": "EU AI Act Annex III high-risk use cases latest amendments digital omnibus",
    "UK_GDPR_ICO:DUAA.ADM": "UK Data (Use and Access) Act 2025 automated decision-making Article 22A-22D ICO guidance contestability",
    "UK_GDPR_ICO:Art.22": "ICO automated decision-making and profiling guidance Data (Use and Access) Act 2025 human intervention",
    "UK_DSIT:Ofcom.OSA": "Ofcom Online Safety Act generative AI chatbots illegal content duties guidance",
    "UK_COPYRIGHT_TDM:CDPA.s29A": "UK copyright text and data mining exception commercial AI training consultation outcome",
}
_CACHE: dict[str, tuple[float, "LinkupCitation"]] = {}
_CACHE_LOCK = threading.Lock()


@dataclass
class LinkupCitation:
    query: str
    answer: str
    urls: list[str] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)

    @property
    def first_url(self) -> str | None:
        return self.urls[0] if self.urls else None

    @property
    def best_snippet(self) -> str:
        return (self.snippets[0] if self.snippets else self.answer)[:400]


class LinkupBase:
    """Shared Linkup access. Live only when LINKUP_API_KEY is set (or a client is injected)."""

    def __init__(self, api_key: str | None = None, client=None):
        self.api_key = api_key if api_key is not None else os.getenv("LINKUP_API_KEY")
        self._client = client
        self.calls = 0
        self.errors = 0

    @property
    def enabled(self) -> bool:
        return bool(self._client is not None or self.api_key)

    def _get_client(self):
        if self._client is None:
            from linkup import LinkupClient

            self._client = LinkupClient(api_key=self.api_key or os.environ["LINKUP_API_KEY"])
        return self._client

    def ask(self, query: str) -> LinkupCitation | None:
        if not self.enabled:
            return None
        now = time.time()
        with _CACHE_LOCK:
            hit = _CACHE.get(query)
            if hit and now - hit[0] < CACHE_TTL_SECONDS and self._client is None:
                return hit[1]
        try:
            self.calls += 1
            # Configurable depth (defaults to "standard" for speed and credit efficiency; supports "deep")
            depth = os.getenv("LINKUP_DEPTH", "standard")
            res = self._get_client().search(query=query, depth=depth, output_type="sourcedAnswer")
            sources = list(getattr(res, "sources", None) or [])
            cit = LinkupCitation(
                query=query, answer=str(getattr(res, "answer", "") or ""),
                urls=[s.url for s in sources if getattr(s, "url", None)],
                snippets=[getattr(s, "snippet", "") or "" for s in sources if getattr(s, "url", None)])
        except Exception as exc:  # network/auth/quota: degrade to offline behaviour, never fail the audit
            self.errors += 1
            log.warning("Linkup search failed (%s): %s", type(exc).__name__, exc)
            return None
        with _CACHE_LOCK:
            if self._client is None or not hasattr(self._client, "_aegis_no_cache"):
                _CACHE[query] = (now, cit)
        return cit


class LinkupRegulatoryScout(LinkupBase):
    def query_for(self, rule: RegulatoryRule) -> str:
        return RULE_QUERIES.get(rule.rule_id) or f"{rule.reference} {rule.title} official text and latest amendments"

    def enrich(self, rules: dict[str, RegulatoryRule]) -> dict[str, RegulatoryRule]:
        """Return a copy of `rules` where every rule with a verified Linkup source carries its citation."""
        if not self.enabled:
            return rules
        from concurrent.futures import ThreadPoolExecutor
        out, now = {}, datetime.now(timezone.utc)

        def _enrich_one(item: tuple[str, RegulatoryRule]) -> tuple[str, RegulatoryRule]:
            rid, rule = item
            cit = self.ask(self.query_for(rule))
            if cit and cit.first_url:
                rule = rule.model_copy(update={"linkup_source_url": cit.first_url, "linkup_snippet": cit.best_snippet,
                                               "linkup_verified_at": now})
            return rid, rule

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = ex.map(_enrich_one, rules.items())
            for rid, rule in results:
                out[rid] = rule
        return out


_SCOUT: LinkupRegulatoryScout | None = None


def get_scout() -> LinkupRegulatoryScout:
    return _SCOUT if _SCOUT is not None else LinkupRegulatoryScout()


def set_scout(scout: LinkupRegulatoryScout | None) -> None:
    global _SCOUT
    _SCOUT = scout


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
