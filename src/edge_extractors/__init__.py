"""Tri-modal deterministic index: code slices + behavioural cards + document chunks (+ assertions, deps, systems)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.schemas.artifacts import (
    AISystemRecord,
    ASTSlice,
    BehavioralCapabilityCard,
    ComplianceAssertion,
    DependencyFact,
    DocumentChunk,
)

from .code_scanner import classify_endpoint
from .doc_parser import extract_assertions, parse_documents

META_FILES = ("company.json", "metadata.json")
HIGH_RISK_SECTORS = {"finance", "healthcare", "hr", "education", "insurance", "legal", "law_enforcement", "migration"}


@dataclass
class TriModalIndex:
    tenant_id: str
    company_name: str
    sector: str
    commercial: bool = True
    slices: list[ASTSlice] = field(default_factory=list)
    cards: list[BehavioralCapabilityCard] = field(default_factory=list)
    chunks: list[DocumentChunk] = field(default_factory=list)
    assertions: list[ComplianceAssertion] = field(default_factory=list)
    dependencies: list[DependencyFact] = field(default_factory=list)
    py_files: list[str] = field(default_factory=list)
    uses_local_model: bool = False
    systems: list[AISystemRecord] = field(default_factory=list)
    system_map: dict[str, str] = field(default_factory=dict)  # artifact_id -> system_id
    commit_sha: str | None = None
    code_origin: str = "local"
    docs_origin: str = "local"
    doc_pages: int = 0
    lang_files: dict[str, int] = field(default_factory=dict)
    unscanned: dict[str, int] = field(default_factory=dict)
    infra_facts: list[dict] = field(default_factory=list)
    source_statuses: list[dict] = field(default_factory=list)
    fairness_outcomes: dict | None = None
    diff_base: str | None = None
    diff_files: list[str] | None = None  # diff mode: only these changed files were scanned for code
    data_assets: list[dict] = field(default_factory=list)

    # ---- artifact registry used by Gate 1 (artifact_id -> (locator, sha256, tenant))
    def artifact_registry(self) -> dict[str, tuple[str, str, str]]:
        reg: dict[str, tuple[str, str, str]] = {}
        for s in self.slices:
            reg[s.slice_id] = (s.locator, s.sha256_hash, s.tenant_id)
        for c in self.cards:
            reg[c.module_id] = (c.exact_locator, c.sha256_hash, c.tenant_id)
        for d in self.chunks:
            reg[d.chunk_id] = (d.locator, d.sha256_hash, d.tenant_id)
        for dep in self.dependencies:
            reg[dep.dep_id] = (dep.locator, dep.sha256_hash, dep.tenant_id)
        for a in self.data_assets:
            reg[a["asset_id"]] = (f"{a['path']}:1-1", a["sha256_hash"], a["tenant_id"])
        return reg

    def artifact_text(self) -> dict[str, str]:
        txt: dict[str, str] = {}
        for s in self.slices:
            txt[s.slice_id] = s.code_snippet
        for c in self.cards:
            txt[c.module_id] = c.system_prompt + " " + " ".join(c.capability_tags)
        for d in self.chunks:
            txt[d.chunk_id] = d.text
        for dep in self.dependencies:
            txt[dep.dep_id] = dep.snippet
        return txt

    def system_of(self, artifact_id: str) -> AISystemRecord | None:
        sid = self.system_map.get(artifact_id)
        return next((s for s in self.systems if s.system_id == sid), None)

    @property
    def has_code(self) -> bool:
        return bool(self.py_files)

    @property
    def has_docs(self) -> bool:
        return bool(self.chunks)


_SECTOR_HINTS = [
    ("finance", r"\b(credit|loan|bank\w*|fintech|lending|underwrit\w*|mortgage|score)\b"),
    ("healthcare", r"\b(patient|clinical|clinician|medical|hospital|nhs|triage|diagnos\w*)\b"),
    ("hr", r"\b(recruit\w*|candidate|hiring|employment|resume|cv screening)\b"),
    ("media", r"\b(voice|video|image generation|podcast|audio|content creation|text-to-speech)\b"),
]


def _load_meta(root: Path | None) -> dict:
    if root is None:
        return {}
    for name in META_FILES:
        p = root / name
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
    return {}


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if len(t) >= 4}


def build_systems(ix: TriModalIndex, declared) -> None:
    """Populate ix.systems (S1..S7) from code entry points and Confluence declarations."""
    code_sys = [s for s in ix.slices if s.is_entrypoint and (s.is_generation or s.is_decision or s.calls_ai_sdk)]
    code_sys.sort(key=lambda s: (s.file_path, s.start_line))
    systems: dict[str, AISystemRecord] = {}
    for d in declared:
        systems[d.system_id] = AISystemRecord(system_id=d.system_id, system_name=d.name, description=d.description,
                                              declared_in_docs=True, sector=ix.sector, tenant_id=ix.tenant_id)
    used: set[str] = set()
    # Multi-repo layout (>=2 top-level repo dirs holding AI entry points): one system per repo, not per route.
    tops = {sl.file_path.split("/")[0] for sl in code_sys if "/" in sl.file_path}
    by_repo = len(tops) >= 2
    repo_sid: dict[str, str] = {}
    for sl in code_sys:
        repo = sl.file_path.split("/")[0]
        toks = _tokens(repo) if by_repo else _tokens(sl.function_name) | _tokens(Path(sl.file_path).stem)
        sid = repo_sid.get(repo) if by_repo else None
        if sid is None:
            sid = next((k for k, rec in systems.items() if k not in used and (_tokens(rec.system_name) & toks)), None)
        if sid is None:
            free = [f"S{i}" for i in range(1, 8) if f"S{i}" not in systems]
            if not free:
                continue  # inventory is capped at S1..S7
            sid = free[0]
            systems[sid] = AISystemRecord(system_id=sid, system_name=(repo.replace("-", " ").replace("_", " ").title() if by_repo else sl.function_name.replace("_", " ").title()),
                                          sector=ix.sector, tenant_id=ix.tenant_id)
        used.add(sid)
        repo_sid[repo] = sid
        rec = systems[sid]
        rec.detected_in_code = True
        rec.locators.append(sl.locator)
        rec.endpoints += [u for u in sl.external_endpoints if u not in rec.endpoints]
        rec.hosting_regions = sorted(set(rec.hosting_regions) | set(sl.endpoint_regions.values()))
        caps = {c for c, v in [("generative", sl.is_generation), ("automated_decision", sl.is_decision),
                               ("external_ai_call", sl.calls_ai_sdk)] if v}
        rec.capabilities = sorted(set(rec.capabilities) | caps)
        card_id = f"{sl.file_path}::{sl.qualified_name or sl.function_name}"
        unfiltered = any("unfiltered_prompt" in c.capability_tags for c in ix.cards if c.module_id == card_id)
        if unfiltered:
            rec.risk_category = "PROHIBITED"
        elif sl.is_decision and ix.sector in HIGH_RISK_SECTORS:
            rec.risk_category = "HIGH_RISK"
        elif sl.is_generation and rec.risk_category not in {"PROHIBITED", "HIGH_RISK"}:
            rec.risk_category = "LIMITED_RISK"
        elif rec.risk_category == "UNKNOWN":
            rec.risk_category = "MINIMAL_RISK"
        ix.system_map[sl.slice_id] = sid
        ix.system_map[f"{sl.file_path}::{sl.qualified_name or sl.function_name}"] = sid
    for s in ix.slices:  # helpers inherit the system of their file's entry point
        if s.slice_id not in ix.system_map:
            sid = next((ix.system_map[e.slice_id] for e in code_sys if e.file_path == s.file_path and e.slice_id in ix.system_map), None)
            if sid:
                ix.system_map[s.slice_id] = sid
    for c in ix.cards:
        if c.module_id not in ix.system_map:
            file = c.module_id.split("::")[0]
            sid = next((ix.system_map[e.slice_id] for e in code_sys if e.file_path == file and e.slice_id in ix.system_map), None)
            if sid:
                ix.system_map[c.module_id] = sid
    if not systems:  # non-Python code (TS/JS): derive the system from biometric capability cards + product name in docs
        bio = [c for c in ix.cards if "biometric_identification" in c.capability_tags]
        if bio:
            title = next((m.group(1).strip() for c in ix.chunks if (m := re.match(r"\s*#\s+(.+)", c.text))), ix.company_name)
            systems["S1"] = AISystemRecord(
                system_id="S1", system_name=title[:60], description="One-to-many facial identity search", sector=ix.sector,
                tenant_id=ix.tenant_id, detected_in_code=True, declared_in_docs=True, capabilities=["biometric_identification"],
                locators=[c.exact_locator for c in bio[:6]],
                risk_category="PROHIBITED" if any("untargeted_acquisition" in c.capability_tags for c in ix.cards) else "HIGH_RISK")
    ix.systems = [systems[k] for k in sorted(systems)]


def build_index(company_dir: Path | str | None = None, tenant_id: str | None = None, *, github_source: str | Path | None = None,
                confluence_source: str | Path | None = None, space_key: str | None = None,
                github_token: str | None = None, doc_sources: list | None = None, data_sources: list | None = None,
                diff_base: str | None = None) -> TriModalIndex:
    """Build the tri-modal index.

    Sources: `github_source` (local dir or https://github.com/org/repo), `confluence_source` (local folder, or
    'cloud' for the live REST API). Defaults: `<company_dir>/github` and `<company_dir>/confluence` if present,
    otherwise the whole `company_dir` serves as both code and document source.
    """
    from src.connectors import scan_confluence_source, scan_github_source

    root = Path(company_dir) if company_dir else None
    tenant_id = tenant_id or (root.name if root else "tenant")
    meta = _load_meta(root)

    gh_src = github_source
    cf_src = confluence_source
    skip_top: set[str] = set()
    if root is not None:
        if gh_src is None:
            gh_src = root / "github" if (root / "github").is_dir() else root
        if cf_src is None and (root / "confluence").is_dir():
            cf_src = root / "confluence"
        if (root / "github").is_dir():
            skip_top.add("github")
        if (root / "confluence").is_dir():
            skip_top.add("confluence")
    gh = scan_github_source(gh_src, tenant_id, github_token, diff_base=diff_base) if gh_src is not None else None
    chunks: list[DocumentChunk] = []
    declared, pages, docs_origin = [], 0, "local"
    if cf_src is not None:
        cf = scan_confluence_source(cf_src, tenant_id, space_key)
        chunks += cf.chunks
        declared, pages, docs_origin = cf.systems, cf.pages, cf.origin
    if root is not None and (cf_src is None or skip_top):
        chunks += [c for c in parse_documents(root, tenant_id, skip_top) if c.chunk_id not in {x.chunk_id for x in chunks}]
    statuses: list[dict] = []
    if doc_sources is None and os.getenv("GRAPHITE_REMOTE_DOC_SOURCES", "").lower() == "true":
        from src.connectors.doc_sources import sources_from_env

        doc_sources = sources_from_env()
    if doc_sources:
        from src.connectors.doc_sources import collect

        remote, sts = collect(doc_sources, tenant_id)
        chunks += remote
        statuses = [vars(x) for x in sts]
    assertions = extract_assertions(chunks)
    if not declared:
        from src.connectors.confluence_connector import extract_system_declarations

        declared = extract_system_declarations(chunks)

    sector = str(meta.get("sector") or "").lower()
    if not sector:
        blob = " ".join(c.text for c in chunks)[:20000] + " " + (root.name if root else "")
        sector = "general"
        for name, pat in _SECTOR_HINTS:
            if re.search(pat, blob, re.I):
                sector = name
                break
    name = meta.get("company_name") or (root.name.replace("company_", "").replace("_", " ").title() if root else tenant_id)
    res = gh.result if gh else None
    ix = TriModalIndex(
        tenant_id=tenant_id, company_name=name, sector=sector, commercial=bool(meta.get("commercial", True)),
        slices=res.slices if res else [], cards=res.cards if res else [], chunks=chunks, assertions=assertions,
        dependencies=res.dependencies if res else [], py_files=res.py_files if res else [],
        uses_local_model=res.uses_local_model if res else False, commit_sha=gh.commit_sha if gh else None,
        code_origin=gh.origin if gh else "none", docs_origin=docs_origin, doc_pages=pages,
        lang_files=dict(res.lang_files) if res else {}, unscanned=dict(res.unscanned) if res else {},
        infra_facts=list(res.infra_facts) if res else [], source_statuses=statuses,
        diff_base=gh.diff_base if gh else None, diff_files=gh.diff_files if gh else None,
    )
    from dataclasses import asdict

    from .data_scanner import compute_fairness, scan_data

    assets = scan_data(root, tenant_id) if root is not None else []
    for ds in (data_sources or []):  # live read-only metadata sources (SQL information_schema, Unity Catalog, MongoDB)
        try:
            assets += ds.describe()
        except Exception as exc:
            ix.source_statuses.append({"source": getattr(ds, "name", "data"), "configured": True, "documents": 0, "errors": [f"{type(exc).__name__}: {str(exc)[:160]}"]})
    ix.data_assets = [asdict(a) for a in assets]
    ix.fairness_outcomes = compute_fairness(root) if root is not None else None
    build_systems(ix, declared)
    return ix


__all__ = ["TriModalIndex", "build_index", "classify_endpoint"]
