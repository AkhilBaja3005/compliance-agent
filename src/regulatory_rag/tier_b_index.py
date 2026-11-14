"""Tier B: hybrid BM25 + dense retriever over the live law index (optional Databricks adapter)."""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from src.law_sync import get_store
from src.law_sync.store import LawStore
from src.schemas.regulatory import RegulatoryRule

log = logging.getLogger(__name__)
_TOK = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOK.findall(text.lower())


def _rule_doc(r: RegulatoryRule) -> str:
    return f"{r.reference}. {r.title}. {r.text} {' '.join(r.keywords)}"


class HashingEmbedder:
    """Deterministic offline dense embedder (feature hashing of uni+bi-grams, L2 normalised)."""

    dim = 384

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = _tokens(t)
            for gram in toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]:
                h = hash_str(gram)
                out[i, h % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


def hash_str(s: str) -> int:
    import hashlib

    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)


def _make_embedder():
    if os.getenv("USE_SENTENCE_TRANSFORMERS", "false").lower() == "true":
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(os.getenv("ST_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))

            class _ST:
                def encode(self, texts):
                    return np.asarray(model.encode(texts, normalize_embeddings=True), dtype=np.float32)

            return _ST()
        except Exception as exc:
            log.warning("sentence-transformers unavailable (%s); using hashing embedder", exc)
    return HashingEmbedder()


@dataclass
class Hit:
    rule: RegulatoryRule
    score: float


class _Snapshot:
    def __init__(self, rules: dict[str, RegulatoryRule], embedder):
        self.rules = list(rules.values())
        self.docs = [_rule_doc(r) for r in self.rules]
        self.bm25 = BM25Okapi([_tokens(d) for d in self.docs])
        self.emb = embedder.encode(self.docs)


class HybridRetriever:
    """BM25 + dense, fused by weighted normalised scores. Re-indexes atomically on law updates."""

    def __init__(self, store: LawStore | None = None, alpha: float = 0.5, *, local_only: bool = False):
        self.store = store or get_store()
        self.alpha = alpha
        self.local_only = local_only
        self.embedder = HashingEmbedder() if local_only else _make_embedder()
        self._lock = threading.Lock()
        self._snap = _Snapshot(self.store.snapshot(), self.embedder)
        self.indexed_version = self.store.version
        self.store.add_listener(lambda s: self.reindex())
        self._databricks = None if local_only else _maybe_databricks()

    def reindex(self) -> None:
        snap = _Snapshot(self.store.snapshot(), self.embedder)  # build fully, then swap
        with self._lock:
            self._snap = snap
            self.indexed_version = self.store.version

    def retrieve(self, query: str, k: int = 3) -> list[Hit]:
        if self._databricks is not None:
            try:
                hits = self._databricks.retrieve(query, k, self.store)
                if hits:
                    return hits
            except Exception as exc:
                log.warning("Databricks Vector Search failed (%s); falling back to local index", exc)
        hits = [] if self.local_only else self._mongo_hits(query, k)
        if hits:
            return hits
        with self._lock:
            snap = self._snap
        bm = np.asarray(snap.bm25.get_scores(_tokens(query)), dtype=np.float32)
        dense = snap.emb @ self.embedder.encode([query])[0]

        def norm(x):
            rng = float(x.max() - x.min())
            return (x - x.min()) / rng if rng > 0 else np.zeros_like(x)

        fused = self.alpha * norm(bm) + (1 - self.alpha) * norm(dense)
        order = np.argsort(-fused)[:k]
        return [Hit(snap.rules[i], float(fused[i])) for i in order if not math.isnan(fused[i])]


    def _mongo_hits(self, query: str, k: int) -> list[Hit]:
        """MongoDB Atlas `$vectorSearch` over regulatory_rules (primary); [] -> local BM25 + hashing fallback."""
        try:
            from src.storage import get_compliance_store

            cs = get_compliance_store()
            if not cs.is_atlas:
                return []
            res = cs.search_rules(query, k)
            return [Hit(r, sc) for rid, sc in (res or []) if (r := self.store.get(rid)) is not None]
        except Exception as exc:
            log.warning("Atlas vector search unavailable (%s); local fallback", exc)
            return []

    def search_regulatory_knowledge(self, query: str, jurisdiction: str | None = None, top_k: int = 5) -> list[dict]:
        """Searches unified regulatory knowledge (including ingested PDF passages)."""
        if self.local_only:
            return []
        from src.storage import get_compliance_store
        cs = get_compliance_store()
        return cs.search_regulatory_knowledge(query, jurisdiction=jurisdiction, top_k=top_k)


class DatabricksVectorSearchAdapter:
    """Optional Databricks Vector Search / Unity Catalog adapter (USE_DATABRICKS=true)."""

    def __init__(self):
        from databricks.vector_search.client import VectorSearchClient  # type: ignore

        self.client = VectorSearchClient(workspace_url=os.getenv("DATABRICKS_HOST"),
                                         personal_access_token=os.getenv("DATABRICKS_TOKEN"))
        self.index = self.client.get_index(endpoint_name=os.environ["DATABRICKS_VS_ENDPOINT"],
                                           index_name=os.environ["DATABRICKS_VS_INDEX"])  # catalog.schema.index

    def retrieve(self, query: str, k: int, store: LawStore) -> list[Hit]:
        res = self.index.similarity_search(query_text=query, columns=["rule_id"], num_results=k)
        rows = res.get("result", {}).get("data_array", [])
        hits = []
        for row in rows:
            rule = store.get(row[0])
            if rule:
                hits.append(Hit(rule, float(row[-1])))
        return hits


def _maybe_databricks():
    if os.getenv("USE_DATABRICKS", "false").lower() != "true":
        return None
    try:
        return DatabricksVectorSearchAdapter()
    except Exception as exc:
        log.warning("USE_DATABRICKS=true but adapter unavailable (%s); using local hybrid index", exc)
        return None


_RETRIEVER: HybridRetriever | None = None
_RLOCK = threading.Lock()


def get_retriever() -> HybridRetriever:
    """Return a retriever bound to the *current* store (rebuilds if the store was reset)."""
    global _RETRIEVER
    with _RLOCK:
        store = get_store()
        if _RETRIEVER is None or _RETRIEVER.store is not store:
            _RETRIEVER = HybridRetriever(store)
        return _RETRIEVER
