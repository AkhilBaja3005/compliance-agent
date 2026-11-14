"""Full knowledge sync: statutory rules + chosen folders + web pages (+ optional remote document sources) into the vector store.

Used by `aegis sync-laws`, `aegis sync-daemon`, the API scheduler and POST /laws/ingest. Everything it ingests becomes regulatory
knowledge under tenant `global_regulations`. Sources are tracked by sha256 in the `sync_sources` registry, so a run only re-embeds
what changed, replaces a changed source's chunks (no stale passages), and removes the chunks of files that disappeared.
Folder paths and URLs come only from trusted configuration (CLI flags or the config file), never from API request bodies.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import socket
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from src.schemas.artifacts import sha256_text

log = logging.getLogger("aegis.sync")
GLOBAL = "global_regulations"
MAX_PAGE_BYTES = 25 * 1024 * 1024


@dataclass
class FolderSource:
    path: str
    jurisdiction: str = "EU_AI_ACT"
    category: str = "REGULATORY_DOC"


@dataclass
class UrlSource:
    url: str
    jurisdiction: str = "EU_AI_ACT"
    category: str = "REGULATORY_WEB"


@dataclass
class SyncConfig:
    folders: list[FolderSource] = field(default_factory=list)
    urls: list[UrlSource] = field(default_factory=list)
    remote_docs_tenant: str | None = None  # set to ingest the sources configured by env (Notion, Jira, ...) into this tenant


@dataclass
class SourceResult:
    source: str
    status: str  # new | updated | unchanged | removed | error
    chunks: int = 0
    detail: str = ""


@dataclass
class SyncReport:
    started_at: str
    rules_total: int = 0
    rule_changes: int = 0
    rules_version: str = ""
    sources: list[SourceResult] = field(default_factory=list)
    moved_legacy_chunks: int = 0

    @property
    def errors(self) -> list[SourceResult]:
        return [s for s in self.sources if s.status == "error"]


def load_config(path: str | os.PathLike | None = None) -> SyncConfig:
    """YAML/JSON config: `folders: [{path, jurisdiction, category}]`, `urls: [{url, jurisdiction, category}]`. Path from arg, GRAPHITE_SYNC_CONFIG, or ./sync_sources.yaml."""
    import json

    import yaml

    p = Path(path or os.getenv("GRAPHITE_SYNC_CONFIG") or "sync_sources.yaml")
    if not p.is_file():
        return SyncConfig()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) if p.suffix in {".yml", ".yaml"} else json.loads(p.read_text(encoding="utf-8"))
    raw = raw or {}
    base = p.resolve().parent
    return SyncConfig(
        folders=[FolderSource(str((base / f["path"]).resolve()) if not Path(f["path"]).is_absolute() else f["path"], f.get("jurisdiction", "EU_AI_ACT"), f.get("category", "REGULATORY_DOC"))
                 for f in raw.get("folders", [])],
        urls=[UrlSource(u["url"], u.get("jurisdiction", "EU_AI_ACT"), u.get("category", "REGULATORY_WEB")) for u in raw.get("urls", [])],
        remote_docs_tenant=raw.get("remote_docs_tenant"))


# ------------------------------------------------------------------ safe fetching
def _public_host(host: str, resolver=socket.getaddrinfo) -> bool:
    try:
        infos = resolver(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return bool(infos)


def fetch_url(url: str, client: httpx.Client | None = None, resolver=socket.getaddrinfo, max_redirects: int = 4) -> tuple[bytes, str]:
    """GET an https URL (no private/loopback targets, redirects re-validated, size capped). Returns (body, content-type)."""
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": "aegis-regulatory-sync/1.0"})
    try:
        for _ in range(max_redirects + 1):
            u = urlparse(url)
            if u.scheme != "https" or not u.hostname or u.username or u.password:
                raise ValueError("only https URLs without credentials are allowed")
            if not _public_host(u.hostname, resolver):
                raise ValueError(f"host {u.hostname} is not a public address")
            r = client.get(url)
            if r.status_code in {301, 302, 303, 307, 308} and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            r.raise_for_status()
            if len(r.content) > MAX_PAGE_BYTES:
                raise ValueError("response too large")
            return r.content, r.headers.get("content-type", "").split(";")[0].strip().lower()
        raise ValueError("too many redirects")
    finally:
        if own:
            client.close()


# ------------------------------------------------------------------ chunk builders
def _doc_chunk_dicts(doc_chunks, jurisdiction: str, category: str, source_url: str | None = None) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [{"chunk_id": c.chunk_id, "filename": c.doc_name, "page_number": c.line_range[0], "section_title": c.section_header, "text": c.text,
             "exact_locator": c.locator, "sha256_hash": c.sha256_hash, "tenant_id": GLOBAL, "jurisdiction": jurisdiction, "source_type": category,
             **({"source_url": source_url, "fetched_at": now} if source_url else {})} for c in doc_chunks]


def _pdf_chunk_dicts(path: Path, jurisdiction: str, category: str, name: str | None = None, source_url: str | None = None) -> list[dict]:
    from src.edge_extractors.pdf_ingestor import ingest_pdf_file

    out = []
    for c in ingest_pdf_file(pdf_path=path, jurisdiction=jurisdiction, tenant_id=GLOBAL, doc_category=category):
        d = c.to_dict()
        if name:
            d["exact_locator"] = d["exact_locator"].replace(d["filename"], name)
            d["filename"] = name
        if source_url:
            d["source_url"] = source_url
        out.append(d)
    return out


def _apply_source(store, key: str, sha: str, build, label: str, force: bool = False) -> SourceResult:
    """Skip when unchanged; otherwise drop the old chunks, embed the new ones and record the hash."""
    prev = store.source_get(key)
    if prev and prev.get("sha256") == sha and not force:
        return SourceResult(label, "unchanged", prev.get("chunks", 0))
    chunks = build()
    if prev:
        store.source_drop(key)
    n = store.index_document_chunks(chunks, source_key=key)
    store.source_put(key, sha, chunks=n, label=label)
    return SourceResult(label, "updated" if prev else "new", n)


# ------------------------------------------------------------------ sources
def sync_folder(store, src: FolderSource) -> list[SourceResult]:
    from src.edge_extractors.code_scanner import SKIP_DIRS
    from src.edge_extractors.doc_parser import DOC_SUFFIXES, parse_document

    root = Path(src.path)
    if not root.is_dir():
        return [SourceResult(src.path, "error", detail="folder not found")]
    results, seen = [], set()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith(".") or set(p.relative_to(root).parts[:-1]) & SKIP_DIRS or p.suffix.lower() not in DOC_SUFFIXES:
            continue
        key, rel = f"file:{p.resolve()}", p.relative_to(root).as_posix()
        seen.add(key)
        try:
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            build = (lambda p=p, rel=rel: _pdf_chunk_dicts(p, src.jurisdiction, src.category, name=rel)) if p.suffix.lower() == ".pdf" else \
                (lambda p=p, rel=rel: _doc_chunk_dicts(parse_document(p, rel, GLOBAL), src.jurisdiction, src.category))
            results.append(_apply_source(store, key, sha, build, f"{root.name}/{rel}"))
        except Exception as exc:
            results.append(SourceResult(f"{root.name}/{rel}", "error", detail=f"{type(exc).__name__}: {str(exc)[:140]}"))
    for key in store.source_keys(f"file:{root.resolve()}/"):  # files deleted since the last run
        if key not in seen:
            store.source_drop(key)
            results.append(SourceResult(key.removeprefix("file:"), "removed"))
    return results


def sync_url(store, src: UrlSource, client: httpx.Client | None = None, resolver=socket.getaddrinfo) -> SourceResult:
    from src.edge_extractors.doc_formats import html_to_text
    from src.edge_extractors.doc_parser import parse_text

    try:
        body, ctype = fetch_url(src.url, client, resolver)
        sha = hashlib.sha256(body).hexdigest()
        host_name = (urlparse(src.url).hostname or "") + urlparse(src.url).path

        def build():
            if ctype == "application/pdf" or src.url.lower().endswith(".pdf"):
                with tempfile.TemporaryDirectory() as td:
                    p = Path(td) / (Path(urlparse(src.url).path).name or "document.pdf")
                    p.write_bytes(body)
                    return _pdf_chunk_dicts(p, src.jurisdiction, src.category, name=host_name, source_url=src.url)
            text = body.decode("utf-8", errors="replace")
            if "html" in ctype or text.lstrip().lower().startswith(("<!doctype", "<html")):
                text = html_to_text(text)
            if len(text.strip()) < 200:
                raise ValueError("page returned almost no text (blocked, login wall, or JavaScript-only content)")
            return _doc_chunk_dicts(parse_text(text, host_name, GLOBAL, is_md=True), src.jurisdiction, src.category, src.url)
        return _apply_source(store, f"url:{src.url}", sha, build, src.url)
    except Exception as exc:
        return SourceResult(src.url, "error", detail=f"{type(exc).__name__}: {str(exc)[:160]}")


def sync_remote_docs(store, tenant: str) -> list[SourceResult]:
    """Index documents from the env-configured remote sources (Notion, Jira, Slack, ...) into one tenant. Never the global tenant."""
    from src.connectors.doc_sources import collect, sources_from_env

    if tenant == GLOBAL:
        return [SourceResult("remote documents", "error", detail="refusing to index private remote documents into the shared global tenant")]
    chunks, statuses = collect(sources_from_env(), tenant)
    out = [SourceResult(f"remote:{st.source}", "error" if st.errors else "updated", st.documents, "; ".join(st.errors)) for st in statuses]
    if chunks:
        key = f"remote:{tenant}"
        store._col("tenant_artifacts").delete_many({"tenant_id": tenant, "source_key": key})
        rows = [{"chunk_id": c.chunk_id, "filename": c.doc_name, "page_number": c.line_range[0], "section_title": c.section_header, "text": c.text,
                 "exact_locator": c.locator, "sha256_hash": c.sha256_hash, "tenant_id": tenant, "jurisdiction": "COMPANY", "source_type": "COMPANY_DOC"} for c in chunks]
        store.index_pdf_chunks(rows, source_key=key)
    return out


# ------------------------------------------------------------------ orchestration
def run_full_sync(cfg: SyncConfig | None = None, deep_linkup: bool = True, store=None, client: httpx.Client | None = None, resolver=socket.getaddrinfo) -> SyncReport:
    from src.law_sync import get_store, sync_now
    from src.law_sync.linkup_scout import get_scout
    from src.regulatory_rag.tier_a_rules import active_frameworks
    from src.storage import get_compliance_store

    cfg = cfg if cfg is not None else load_config()
    store = store or get_compliance_store()
    rep = SyncReport(started_at=datetime.now(timezone.utc).isoformat())

    # 1. statutory rules: feed + Linkup citations + review gate (via sync_now), then embed into the vector store
    scout = get_scout()
    res = sync_now() if (deep_linkup or not scout.enabled) else _sync_without_linkup()
    rep.rule_changes, rep.rules_version = len(res.changes), res.new_version
    fw = active_frameworks()
    rules = {k: r for k, r in get_store().snapshot().items() if fw is None or str(r.jurisdiction) in fw}
    store.index_rules(rules)
    rep.rules_total = len(rules)
    rep.moved_legacy_chunks = store.migrate_legacy_pdf_chunks()

    # 2. folders, 3. web pages, 4. remote document sources
    for f in cfg.folders:
        rep.sources += sync_folder(store, f)
    for u in cfg.urls:
        rep.sources.append(sync_url(store, u, client, resolver))
    if cfg.remote_docs_tenant:
        rep.sources += sync_remote_docs(store, cfg.remote_docs_tenant)
    for s in rep.errors:
        log.warning("sync source failed", extra={"event": "sync_error"})
    return rep


def _sync_without_linkup():
    from src.law_sync.fetcher import fetch_remote_rules
    from src.law_sync.store import get_store

    rules, source = fetch_remote_rules()
    return get_store().apply(rules, source)


_ = sha256_text  # re-exported for tests
