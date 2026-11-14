"""Confluence connector: local Markdown/XHTML folder or Atlassian Cloud REST v2 -> DocumentChunk + ComplianceAssertion + S1..S7."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
import re
from dataclasses import dataclass, field
from pathlib import Path

import html2text
import httpx

from src.edge_extractors.doc_parser import extract_assertions, parse_text
from src.schemas.artifacts import ComplianceAssertion, DocumentChunk

LOCAL_SUFFIXES = {".md", ".markdown", ".txt", ".xhtml", ".html", ".htm", ".xml"}
_SYS_LINE = re.compile(r"^\W*(?:system\s+)?(S[1-7]|[A-Z]{2,6}-\d{1,3})\b\s*[:\-–—|)]\s*(?P<name>[^|\n:—–-][^|\n]*?)(?:\s*[-–—:]\s*(?P<desc>.+))?\s*$", re.I)
_SYS_ROW = re.compile(r"^\|\s*\**(S[1-7]|[A-Z]{2,6}-\d{1,3})\**\s*\|\s*([^|]+?)\s*\|(?:\s*([^|]*?)\s*\|)?", re.I)


@dataclass
class SystemDeclaration:
    system_id: str
    name: str
    description: str = ""
    source_chunk_id: str = ""


@dataclass
class ConfluenceScan:
    chunks: list[DocumentChunk] = field(default_factory=list)
    assertions: list[ComplianceAssertion] = field(default_factory=list)
    systems: list[SystemDeclaration] = field(default_factory=list)
    origin: str = "local"
    pages: int = 0


def xhtml_to_markdown(xhtml: str) -> str:
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_images = True
    h.protect_links = False
    h.unicode_snob = True
    return h.handle(xhtml)


def _is_markup(text: str, suffix: str) -> bool:
    return suffix in {".xhtml", ".html", ".htm", ".xml"} or bool(re.search(r"<(p|h[1-6]|ac:|table|ul)\b", text[:2000], re.I))


def extract_system_declarations(chunks: list[DocumentChunk]) -> list[SystemDeclaration]:
    found: dict[str, SystemDeclaration] = {}
    for ch in chunks:
        for line in ch.text.splitlines():
            ln = line.strip().lstrip("#*-• ").strip()
            m = _SYS_ROW.match(ln)
            if m:
                sid, name, desc = m.group(1).upper(), m.group(2).strip(" *`"), (m.group(3) or "").strip()
                if name.lower() in {"name", "system", "---"} or set(name) <= set("-: "):
                    continue
            else:
                m = _SYS_LINE.match(ln)
                if not m:
                    continue
                sid, name, desc = m.group(1).upper(), m.group("name").strip(" *`"), (m.group("desc") or "").strip()
            if sid not in found:
                found[sid] = SystemDeclaration(sid, name, desc, ch.chunk_id)
    # Non-S IDs (e.g. MER-01) are mapped to the next free S1..S7 slot, in order of appearance
    out, taken = [], {k for k in found if re.fullmatch(r"S[1-7]", k)}
    free = (f"S{i}" for i in range(1, 8) if f"S{i}" not in taken)
    for k, d in found.items():
        if not re.fullmatch(r"S[1-7]", k):
            nid = next(free, None)
            if nid is None:
                continue
            d.system_id = nid
        out.append(d)
    return sorted(out, key=lambda d: int(d.system_id[1:]))


def _finish(chunks: list[DocumentChunk], origin: str, pages: int) -> ConfluenceScan:
    return ConfluenceScan(chunks=chunks, assertions=extract_assertions(chunks),
                          systems=extract_system_declarations(chunks), origin=origin, pages=pages)


def scan_local_confluence(folder: Path | str, tenant_id: str) -> ConfluenceScan:
    root = Path(folder)
    if not root.is_dir():
        raise FileNotFoundError(f"Confluence folder not found: {root}")
    chunks, pages = [], 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in LOCAL_SUFFIXES:
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        is_md = True
        if _is_markup(raw, p.suffix.lower()):
            raw, is_md = xhtml_to_markdown(raw), True
        elif p.suffix.lower() == ".txt":
            is_md = False
        pages += 1
        chunks.extend(parse_text(raw, p.relative_to(root).as_posix(), tenant_id, is_md=is_md))
    return _finish(chunks, f"local:{root}", pages)


class ConfluenceCloudClient:
    """Minimal Atlassian Cloud REST v2 client (basic auth: email + API token)."""

    def __init__(self, base_url: str, email: str, token: str, client: httpx.Client | None = None):
        self.base = base_url.rstrip("/")
        if not self.base.endswith("/wiki"):
            self.base += "/wiki"
        self.http = client or httpx.Client(auth=(email, token), timeout=30, headers={"Accept": "application/json"})
        self.root = re.match(r"https?://[^/]+", self.base).group(0)

    def _get(self, url: str, params: dict | None = None) -> dict:
        r = self.http.get(url if url.startswith("http") else self.base + url, params=params)
        r.raise_for_status()
        return r.json()

    def space_id(self, space_key: str) -> str:
        data = self._get("/api/v2/spaces", {"keys": space_key})
        if not data.get("results"):
            raise LookupError(f"Confluence space '{space_key}' not found")
        return data["results"][0]["id"]

    def get_page(self, page_id: str) -> dict:
        """One page with its storage-format body (used to fetch bodies concurrently after a body-less listing)."""
        return self._get(f"/api/v2/pages/{page_id}", {"body-format": "storage"})

    def pages(self, space_id: str, limit: int = 100, with_body: bool = True):
        url, params = f"/api/v2/spaces/{space_id}/pages", {"limit": limit, "status": "current", **({"body-format": "storage"} if with_body else {})}
        while url:
            data = self._get(url, params)
            yield from data.get("results", [])
            nxt = data.get("_links", {}).get("next")
            url, params = (self.root + nxt if nxt and nxt.startswith("/") else nxt), None


def scan_confluence_cloud(tenant_id: str, space_key: str | None = None, base_url: str | None = None,
                          email: str | None = None, token: str | None = None,
                          client: ConfluenceCloudClient | None = None) -> ConfluenceScan:
    base_url = base_url or os.getenv("CONFLUENCE_URL")
    email = email or os.getenv("CONFLUENCE_EMAIL") or os.getenv("CONFLUENCE_USERNAME")
    token = token or os.getenv("CONFLUENCE_API_TOKEN")
    space_key = space_key or os.getenv("CONFLUENCE_SPACE_KEY")
    if client is None:
        if not (base_url and email and token and space_key):
            raise ValueError("CONFLUENCE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN and space_key are required")
        client = ConfluenceCloudClient(base_url, email, token)
    chunks, n = [], 0
    space_id = client.space_id(space_key)
    can_fetch = hasattr(client, "get_page")
    # list page metadata first (cursor pagination is inherently sequential), then fetch the bodies concurrently
    listing = list(client.pages(space_id, with_body=False)) if can_fetch else list(client.pages(space_id))
    body_of = lambda pg: ((pg.get("body") or {}).get("storage") or {}).get("value")
    missing = [pg for pg in listing if not body_of(pg)]
    if missing and can_fetch:
        workers = int(os.getenv("GRAPHITE_CONFLUENCE_WORKERS", "6"))
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(missing)))) as pool:
            fetched = list(pool.map(lambda pg: client.get_page(pg["id"]), missing))  # map preserves page order
        by_id = {f["id"]: f for f in fetched}
        listing = [by_id.get(pg["id"], pg) for pg in listing]
    for page in listing:
        body = body_of(page) or ""
        md = xhtml_to_markdown(body)
        title = page.get("title", f"page-{page.get('id')}")
        n += 1
        text = f"# {title}\n\n{md}" if not md.lstrip().startswith("#") else md
        chunks.extend(parse_text(text, f"confluence/{space_key}/{title}", tenant_id, is_md=True))
    return _finish(chunks, f"confluence-cloud:{space_key}", n)


def scan_confluence_source(source: str | Path | None, tenant_id: str, space_key: str | None = None) -> ConfluenceScan:
    """`source`: local folder path, or None/'cloud' with CONFLUENCE_* env to use the live REST API."""
    if source in (None, "", "cloud"):
        return scan_confluence_cloud(tenant_id, space_key)
    return scan_local_confluence(source, tenant_id)
