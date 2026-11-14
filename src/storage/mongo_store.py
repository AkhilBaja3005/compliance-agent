"""MongoDB Atlas: Vector Search, LangGraph checkpointer and `audit_history` longitudinal tracking.

Live when MONGODB_URI is set and reachable. Otherwise an in-memory store with the same interface is used
(optionally persisted to AEGIS_HISTORY_FILE) and vector search falls back to local BM25 + hashing embeddings.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from datetime import datetime, timezone
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from src.schemas.findings import ComplianceFinding

log = logging.getLogger(__name__)
RULES, ARTIFACTS, HISTORY = "regulatory_rules", "tenant_artifacts", "audit_history"
RULES_INDEX, ARTIFACTS_INDEX = "regulatory_rules_vector", "tenant_artifacts_vector"
EMBED_DIM = 384


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class _MemCollection:
    """Tiny pymongo-like collection (equality filters only) used when Atlas is not configured."""

    def __init__(self, persist_path: str | None = None):
        self.docs: list[dict] = []
        self.path = persist_path
        if persist_path and os.path.isfile(persist_path):
            try:
                self.docs = [self._load(d) for d in json.load(open(persist_path, encoding="utf-8"))]
            except Exception:
                self.docs = []

    @staticmethod
    def _load(d):
        for k, v in list(d.items()):
            if isinstance(v, str) and k.endswith("_at"):
                try:
                    d[k] = datetime.fromisoformat(v)
                except ValueError:
                    pass
        return d

    def _save(self):
        if self.path:
            json.dump(self.docs, open(self.path, "w", encoding="utf-8"), default=lambda o: o.isoformat(), indent=1)

    @staticmethod
    def _match(doc, flt):
        return all(doc.get(k) == v for k, v in flt.items())

    def find(self, flt=None, *_, **__):
        return [dict(d) for d in self.docs if self._match(d, flt or {})]

    def find_one(self, flt=None, *_, **__):
        return next(iter(self.find(flt)), None)

    def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if self._match(d, flt):
                d.update(update.get("$set", {}))
                self._save()
                return
        if upsert:
            self.docs.append({**flt, **update.get("$set", {})})
            self._save()

    def insert_many(self, docs):
        self.docs.extend(dict(d) for d in docs)
        self._save()

    def delete_many(self, flt):
        self.docs = [d for d in self.docs if not self._match(d, flt)]
        self._save()

    def create_search_index(self, *_a, **_k):  # pragma: no cover - atlas only
        return None


class MongoComplianceStore:
    def __init__(self, uri: str | None = None, db_name: str | None = None, client: Any = None, embedder: Any = None):
        self.uri = uri if uri is not None else os.getenv("MONGODB_URI")
        self.db_name = db_name or os.getenv("MONGODB_DB_NAME") or os.getenv("MONGODB_DATABASE") or "aegis_compliance"
        self.checkpoint_collection = os.getenv("MONGODB_CHECKPOINT_COLLECTION", "langgraph_checkpoints")
        self.error: str | None = None
        self.client = None
        self.db = None
        self.is_atlas = False
        self._embedder = embedder
        self._lock = threading.RLock()
        self._mem: dict[str, _MemCollection] = {}
        if client is not None or self.uri:
            try:
                if client is None:
                    from pymongo import MongoClient

                    client = MongoClient(self.uri, serverSelectionTimeoutMS=int(os.getenv("MONGODB_TIMEOUT_MS", "5000")))
                    client.admin.command("ping")
                self.client, self.db, self.is_atlas = client, client[self.db_name], True
                self.ensure_indexes()
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                log.warning("MongoDB unavailable (%s); using in-memory fallback", self.error)

    # ------------------------------------------------------------------ plumbing
    @property
    def embedder(self):
        if self._embedder is None:
            from src.regulatory_rag.tier_b_index import _make_embedder

            self._embedder = _make_embedder()
        return self._embedder

    def _col(self, name: str):
        if self.is_atlas:
            return self.db[name]
        with self._lock:
            if name not in self._mem:
                path = os.getenv("AEGIS_HISTORY_FILE") if name == HISTORY else None
                self._mem[name] = _MemCollection(path)
            return self._mem[name]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in row] for row in self.embedder.encode(texts)]

    def ensure_indexes(self) -> None:
        if not self.is_atlas:
            return
        try:
            from pymongo.operations import SearchIndexModel

            for col, name, filt in ((RULES, RULES_INDEX, []), (ARTIFACTS, ARTIFACTS_INDEX, ["tenant_id"])):
                fields = [{"type": "vector", "path": "embedding", "numDimensions": EMBED_DIM, "similarity": "cosine"}]
                fields += [{"type": "filter", "path": f} for f in filt]
                try:
                    self.db[col].create_search_index(SearchIndexModel(definition={"fields": fields}, name=name, type="vectorSearch"))
                except Exception as exc:  # already exists / not Atlas-search capable
                    log.debug("vector index %s: %s", name, exc)
        except Exception as exc:  # pragma: no cover
            log.debug("ensure_indexes skipped: %s", exc)

    def describe(self) -> dict:
        return {"mode": "atlas" if self.is_atlas else "memory", "database": self.db_name if self.is_atlas else None, "error": self.error}

    # ------------------------------------------------------------------ vector indexes
    def index_rules(self, rules: dict) -> None:
        items = list(rules.values())
        if not items:
            return
        embs = self.embed([f"{r.reference}. {r.title}. {r.text}" for r in items])
        col = self._col(RULES)
        for r, e in zip(items, embs):
            col.update_one({"rule_id": r.rule_id}, {"$set": {
                "rule_id": r.rule_id, "jurisdiction": r.jurisdiction, "reference": r.reference, "title": r.title,
                "text": r.text, "sha256_hash": r.sha256_hash, "linkup_source_url": r.linkup_source_url, "embedding": e}}, upsert=True)

    def index_pdf_chunks(self, chunks: list[Any]) -> int:
        """Indexes parsed PDF chunks into MongoDB Atlas and local collection."""
        if not chunks:
            return 0
        texts = [c.text if hasattr(c, "text") else c.get("text", "") for c in chunks]
        embs = self.embed(texts)
        count = 0
        for chunk, emb in zip(chunks, embs):
            d = chunk.to_dict() if hasattr(chunk, "to_dict") else dict(chunk)
            d["embedding"] = emb
            tenant_id = d.get("tenant_id", "global_regulations")
            target_col = self._col(RULES) if tenant_id == "global_regulations" else self._col(ARTIFACTS)
            flt = {"chunk_id": d["chunk_id"]} if "chunk_id" in d else {"sha256_hash": d["sha256_hash"]}
            target_col.update_one(flt, {"$set": d}, upsert=True)
            count += 1
        return count

    def search_regulatory_knowledge(
        self, query: str, jurisdiction: str | None = None, top_k: int = 5
    ) -> list[dict[str, Any]]:
        """Unified search across regulatory rules and ingested PDFs with Atlas vector + local hybrid fallback."""
        query_emb = self.embed([query])[0]

        # 1. Try Atlas Vector Search if connected
        if self.is_atlas:
            try:
                pipe: list[dict[str, Any]] = [
                    {
                        "$vectorSearch": {
                            "index": RULES_INDEX,
                            "path": "embedding",
                            "queryVector": query_emb,
                            "numCandidates": max(50, top_k * 10),
                            "limit": top_k * 2,
                        }
                    },
                    {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
                ]
                docs = list(self.db[RULES].aggregate(pipe))
                if jurisdiction:
                    docs = [d for d in docs if not d.get("jurisdiction") or d.get("jurisdiction") == jurisdiction]
                if docs:
                    return docs[:top_k]
            except Exception as exc:
                log.warning("$vectorSearch(search_regulatory_knowledge) failed: %s; using local fallback", exc)

        # 2. Local BM25 + cosine fallback
        docs = [d for d in self._col(RULES).find({}) if d.get("embedding") or d.get("text")]
        if jurisdiction:
            docs = [d for d in docs if not d.get("jurisdiction") or d.get("jurisdiction") == jurisdiction]
        if not docs:
            return []

        from src.regulatory_rag.tier_b_index import _tokens
        q_toks = _tokens(query)
        bm_scores = np.asarray(
            BM25Okapi([_tokens(d.get("text", "") + " " + d.get("title", "")) for d in docs]).get_scores(q_toks),
            dtype=np.float32,
        )
        embs = [d.get("embedding") or self.embed([d.get("text", "")])[0] for d in docs]
        cos_scores = np.asarray(embs, dtype=np.float32) @ np.asarray(query_emb, dtype=np.float32)

        norm = lambda x: (x - x.min()) / (x.max() - x.min()) if x.max() > x.min() else np.zeros_like(x)
        fused = 0.5 * norm(bm_scores) + 0.5 * norm(cos_scores)

        ranked = []
        for i in np.argsort(-fused)[:top_k]:
            if not math.isnan(fused[i]):
                d = {k: v for k, v in docs[i].items() if k != "embedding"}
                d["score"] = float(fused[i])
                ranked.append(d)
        return ranked

    def index_tenant_artifacts(self, ix) -> int:
        docs = []
        rows = ([("slice", s.slice_id, s.locator, s.sha256_hash, s.code_snippet) for s in ix.slices]
                + [("card", c.module_id, c.exact_locator, c.sha256_hash, c.system_prompt + " " + " ".join(c.capability_tags)) for c in ix.cards]
                + [("chunk", d.chunk_id, d.locator, d.sha256_hash, d.text) for d in ix.chunks])
        if rows:
            embs = self.embed([r[4][:2000] for r in rows])
            docs = [{"tenant_id": ix.tenant_id, "artifact_id": a, "kind": k, "locator": loc, "sha256_hash": h,
                     "text": t[:2000], "embedding": e} for (k, a, loc, h, t), e in zip(rows, embs)]
        col = self._col(ARTIFACTS)
        col.delete_many({"tenant_id": ix.tenant_id})
        if docs:
            col.insert_many(docs)
        return len(docs)

    def search_rules(self, query: str, k: int = 3) -> list[tuple[str, float]] | None:
        """Atlas `$vectorSearch` over regulatory_rules; None when unavailable (caller falls back to local hybrid)."""
        if not self.is_atlas:
            return None
        try:
            pipe = [{"$vectorSearch": {"index": RULES_INDEX, "path": "embedding", "queryVector": self.embed([query])[0],
                                       "numCandidates": max(100, k * 20), "limit": max(k * 5, 15)}},
                    {"$project": {"_id": 0, "rule_id": 1, "score": {"$meta": "vectorSearchScore"}}}]
            # the collection also holds ingested PDF chunks (no rule_id): keep only statutory rules here, PDF passages come via search_regulatory_knowledge
            return [(d["rule_id"], float(d["score"])) for d in self.db[RULES].aggregate(pipe) if d.get("rule_id")][:k]
        except Exception as exc:
            log.warning("$vectorSearch(regulatory_rules) failed: %s", exc)
            return None

    def search_artifacts(self, tenant_id: str, query: str, k: int = 3) -> list[dict]:
        """Tenant-scoped semantic search; `$vectorSearch` on Atlas, local BM25 + cosine fallback otherwise."""
        if self.is_atlas:
            try:
                pipe = [{"$vectorSearch": {"index": ARTIFACTS_INDEX, "path": "embedding", "queryVector": self.embed([query])[0],
                                           "numCandidates": max(50, k * 10), "limit": k, "filter": {"tenant_id": tenant_id}}},
                        {"$project": {"_id": 0, "embedding": 0, "score": {"$meta": "vectorSearchScore"}}}]
                return list(self.db[ARTIFACTS].aggregate(pipe))
            except Exception as exc:
                log.warning("$vectorSearch(tenant_artifacts) failed: %s; local fallback", exc)
        docs = [d for d in self._col(ARTIFACTS).find({"tenant_id": tenant_id}) if d.get("embedding")]
        if not docs:
            return []
        from src.regulatory_rag.tier_b_index import _tokens

        bm = np.asarray(BM25Okapi([_tokens(d["text"]) for d in docs]).get_scores(_tokens(query)), dtype=np.float32)
        cos = np.asarray([d["embedding"] for d in docs], dtype=np.float32) @ np.asarray(self.embed([query])[0], dtype=np.float32)
        norm = lambda x: (x - x.min()) / (x.max() - x.min()) if x.max() > x.min() else np.zeros_like(x)
        fused = 0.5 * norm(bm) + 0.5 * norm(cos)
        return [{**{k2: v for k2, v in docs[i].items() if k2 != "embedding"}, "score": float(fused[i])}
                for i in np.argsort(-fused)[:k] if not math.isnan(fused[i])]

    # ------------------------------------------------------------------ checkpointer
    def checkpointer(self):
        """(saver, kind): MongoDBSaver on Atlas, else in-process MemorySaver."""
        if self.is_atlas:
            try:
                from langgraph.checkpoint.mongodb import MongoDBSaver

                return MongoDBSaver(self.client, db_name=self.db_name, checkpoint_collection_name=self.checkpoint_collection), "mongodb"
            except Exception as exc:
                log.warning("MongoDBSaver unavailable (%s); using MemorySaver", exc)
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver(), "memory"

    # ------------------------------------------------------------------ audit_history
    def apply_history(self, company_name: str, findings: list[ComplianceFinding]) -> tuple[list[ComplianceFinding], list[str]]:
        """Tag findings NEW / RECURRING / RESOLVED with first_seen_at using audit_history keyed by (company_name, finding_id)."""
        col, now, out, seen = self._col(HISTORY), _utcnow(), [], set()
        resolved: list[str] = []
        for f in findings:
            seen.add(f.finding_id)
            key = {"company_name": company_name, "finding_id": f.finding_id}
            doc = col.find_one(key)
            first = _aware(doc.get("first_seen_at")) if doc else None
            if f.status != "PASS":
                hs = "RECURRING" if doc else "NEW"
                first = first or now
                col.update_one(key, {"$set": {**key, "state": "OPEN", "first_seen_at": first, "last_seen_at": now,
                                              "status": f.status, "title": f.title,
                                              "runs": (doc.get("runs", 0) if doc else 0) + 1}}, upsert=True)
            elif doc and doc.get("state") == "OPEN":
                hs = "RESOLVED"
                col.update_one(key, {"$set": {"state": "RESOLVED", "resolved_at": now, "last_seen_at": now, "status": "PASS"}})
                resolved.append(f.finding_id)
            else:
                hs, first = ("RESOLVED" if doc else "NEW"), (first or now)
            out.append(f.model_copy(update={"history_status": hs, "first_seen_at": first}))
        for d in col.find({"company_name": company_name, "state": "OPEN"}):
            if d["finding_id"] not in seen:  # no longer raised at all (e.g. check no longer applicable)
                col.update_one({"company_name": company_name, "finding_id": d["finding_id"]},
                               {"$set": {"state": "RESOLVED", "resolved_at": now}})
                resolved.append(d["finding_id"])
        return out, resolved

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass


_STORE: MongoComplianceStore | None = None
_LOCK = threading.Lock()


def get_compliance_store() -> MongoComplianceStore:
    global _STORE
    with _LOCK:
        if _STORE is None:
            _STORE = MongoComplianceStore()
        return _STORE


def set_compliance_store(store: MongoComplianceStore | None) -> None:
    global _STORE
    with _LOCK:
        _STORE = store


def reset_compliance_store() -> MongoComplianceStore:
    set_compliance_store(None)
    return get_compliance_store()
