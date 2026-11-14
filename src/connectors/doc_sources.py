"""Remote document sources: Notion, Jira, Slack, Google Drive, SharePoint/OneDrive (Microsoft Graph), GitHub issues/PRs/wiki.

All sources share one contract (`DocumentSource.fetch`) and one evidence model: every document becomes Markdown-like text with a
`last_modified` stamp and a stable `doc_name` (`<source>:<id> <title>`), chunked by the same parser as local files, so findings
cite an exact locator and sha256. Sources read only what the configured credential can already read (the remote API enforces the
ACL); Slack is limited to explicitly listed public channels unless SLACK_INCLUDE_PRIVATE=true. Nothing is written back.
Rate limits: HTTP 429/503 are retried with Retry-After. Incremental sync: pass `since` (ISO timestamp) to skip unchanged documents.
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Protocol

import httpx

from src.edge_extractors.doc_formats import OFFICE_SUFFIXES, read_document
from src.edge_extractors.doc_parser import parse_text
from src.schemas.artifacts import DocumentChunk


@dataclass
class SourceDoc:
    source: str
    doc_id: str
    title: str
    text: str
    last_modified: str | None = None
    url: str | None = None

    @property
    def doc_name(self) -> str:
        return f"{self.source}:{self.doc_id} {self.title}".strip()[:160]


@dataclass
class SourceStatus:
    source: str
    configured: bool
    documents: int = 0
    skipped_unchanged: int = 0
    errors: list[str] = field(default_factory=list)


class DocumentSource(Protocol):
    name: str

    def fetch(self, since: str | None = None) -> list[SourceDoc]: ...


class _Http:
    """Thin httpx wrapper: auth headers, pagination helpers, retry on 429/5xx honouring Retry-After."""

    def __init__(self, base_url: str, headers: dict, client: httpx.Client | None = None, max_retries: int = 4, sleep: Callable[[float], None] = time.sleep):
        self.client = client or httpx.Client(base_url=base_url, headers=headers, timeout=30)
        if client is not None:
            self.client.headers.update(headers)
            self.base = base_url.rstrip("/")
        else:
            self.base = ""
        self.max_retries, self.sleep = max_retries, sleep

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        full = url if url.startswith("http") else f"{self.base}{url}"
        for attempt in range(self.max_retries + 1):
            r = self.client.request(method, full, **kw)
            if r.status_code in {429, 502, 503} and attempt < self.max_retries:
                self.sleep(min(float(r.headers.get("Retry-After", 2 ** attempt)), 30))
                continue
            r.raise_for_status()
            return r
        raise RuntimeError("unreachable")

    def get_json(self, url: str, **kw) -> dict:
        return self.request("GET", url, **kw).json()


def _changed(last_modified: str | None, since: str | None) -> bool:
    return not (since and last_modified and last_modified <= since)


# ----------------------------------------------------------------------------- Notion
class NotionSource:
    name = "notion"

    def __init__(self, token: str, page_ids: list[str] | None = None, client: httpx.Client | None = None, **kw):
        self.page_ids = page_ids or []
        self.http = _Http("https://api.notion.com", {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"}, client, **kw)

    def _blocks(self, block_id: str) -> Iterator[dict]:
        cursor = None
        while True:
            j = self.http.get_json(f"/v1/blocks/{block_id}/children", params={"page_size": 100, **({"start_cursor": cursor} if cursor else {})})
            yield from j.get("results", [])
            if not j.get("has_more"):
                return
            cursor = j.get("next_cursor")

    def fetch(self, since=None) -> list[SourceDoc]:
        docs = []
        ids = self.page_ids
        if not ids:  # every page the integration was shared with
            j = self.http.request("POST", "/v1/search", json={"filter": {"property": "object", "value": "page"}, "page_size": 100}).json()
            ids = [p["id"] for p in j.get("results", [])]
        for pid in ids:
            page = self.http.get_json(f"/v1/pages/{pid}")
            lm = page.get("last_edited_time")
            if not _changed(lm, since):
                continue
            title = next((("".join(t.get("plain_text", "") for t in v.get("title", []))) for v in page.get("properties", {}).values() if v.get("type") == "title"), pid)
            lines = [f"# {title}"]
            for b in self._blocks(pid):
                t = b.get("type", "")
                txt = "".join(r.get("plain_text", "") for r in b.get(t, {}).get("rich_text", []))
                if not txt:
                    continue
                lines.append({"heading_1": "# ", "heading_2": "## ", "heading_3": "### ", "bulleted_list_item": "- ", "numbered_list_item": "- "}.get(t, "") + txt)
            docs.append(SourceDoc("notion", pid, title, "\n".join(lines), lm, page.get("url")))
        return docs


# ----------------------------------------------------------------------------- Jira
def _adf_text(node) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    sep = "\n" if node.get("type") in {"paragraph", "heading", "listItem", "bulletList", "orderedList"} else ""
    return _adf_text(node.get("content", [])) + sep


class JiraSource:
    name = "jira"

    def __init__(self, base_url: str, email: str, token: str, jql: str = "ORDER BY updated DESC", client: httpx.Client | None = None, max_issues: int = 200, **kw):
        auth = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.http = _Http(base_url.rstrip("/"), {"Authorization": f"Basic {auth}", "Accept": "application/json"}, client, **kw)
        self.jql, self.max_issues = jql, max_issues

    def fetch(self, since=None) -> list[SourceDoc]:
        docs, start = [], 0
        while len(docs) < self.max_issues:
            j = self.http.get_json("/rest/api/3/search", params={"jql": self.jql, "startAt": start, "maxResults": 50,
                                                                 "fields": "summary,description,comment,updated,issuetype,status"})
            issues = j.get("issues", [])
            for it in issues:
                f = it.get("fields", {})
                lm = f.get("updated")
                if not _changed(lm, since):
                    continue
                lines = [f"# {it['key']}: {f.get('summary', '')}", f"Type: {(f.get('issuetype') or {}).get('name', '')}; Status: {(f.get('status') or {}).get('name', '')}",
                         _adf_text(f.get("description") or "")]
                for c in ((f.get("comment") or {}).get("comments", [])):
                    lines.append(f"Comment: {_adf_text(c.get('body'))}")
                docs.append(SourceDoc("jira", it["key"], f.get("summary", ""), "\n".join(l for l in lines if l.strip()), lm, f"{it.get('self', '')}"))
            start += len(issues)
            if not issues or start >= j.get("total", 0):
                break
        return docs


# ----------------------------------------------------------------------------- Slack
class SlackSource:
    name = "slack"

    def __init__(self, token: str, channels: list[str], include_private: bool | None = None, client: httpx.Client | None = None, max_messages: int = 500, **kw):
        self.http = _Http("https://slack.com/api", {"Authorization": f"Bearer {token}"}, client, **kw)
        self.channels, self.max_messages = channels, max_messages
        self.include_private = include_private if include_private is not None else os.getenv("SLACK_INCLUDE_PRIVATE", "").lower() == "true"

    def fetch(self, since=None) -> list[SourceDoc]:
        docs = []
        for ch in self.channels:  # explicitly listed channels only
            info = self.http.get_json("/conversations.info", params={"channel": ch}).get("channel", {})
            if (info.get("is_private") or info.get("is_im") or info.get("is_mpim")) and not self.include_private:
                continue
            msgs, cursor = [], None
            while len(msgs) < self.max_messages:
                j = self.http.get_json("/conversations.history", params={"channel": ch, "limit": 200, **({"cursor": cursor} if cursor else {})})
                msgs += j.get("messages", [])
                cursor = (j.get("response_metadata") or {}).get("next_cursor")
                if not cursor:
                    break
            name = info.get("name", ch)
            lm = max((m.get("ts", "0") for m in msgs), default=None)
            lm_iso = datetime.fromtimestamp(float(lm), tz=timezone.utc).isoformat() if lm else None
            if not msgs or not _changed(lm_iso, since):
                continue
            lines = [f"# Slack #{name}"] + [f"- [{datetime.fromtimestamp(float(m.get('ts', 0)), tz=timezone.utc):%Y-%m-%d}] {m.get('text', '')}"
                                           for m in sorted(msgs, key=lambda m: m.get("ts", "0")) if m.get("text")]
            docs.append(SourceDoc("slack", ch, f"#{name}", "\n".join(lines), lm_iso, None))
        return docs


# ----------------------------------------------------------------------------- Google Drive
class GoogleDriveSource:
    name = "gdrive"
    _EXPORT = {"application/vnd.google-apps.document": "text/plain", "application/vnd.google-apps.presentation": "text/plain",
               "application/vnd.google-apps.spreadsheet": "text/csv"}

    def __init__(self, access_token: str, folder_id: str | None = None, client: httpx.Client | None = None, **kw):
        self.http = _Http("https://www.googleapis.com", {"Authorization": f"Bearer {access_token}"}, client, **kw)
        self.folder_id = folder_id

    def fetch(self, since=None) -> list[SourceDoc]:
        q = "trashed=false" + (f" and '{self.folder_id}' in parents" if self.folder_id else "")
        docs, token = [], None
        while True:
            j = self.http.get_json("/drive/v3/files", params={"q": q, "pageSize": 100, "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink)",
                                                              **({"pageToken": token} if token else {})})
            for f in j.get("files", []):
                lm = f.get("modifiedTime")
                if not _changed(lm, since):
                    continue
                mime = f.get("mimeType", "")
                text = None
                if mime in self._EXPORT:
                    text = self.http.request("GET", f"/drive/v3/files/{f['id']}/export", params={"mimeType": self._EXPORT[mime]}).text
                elif Path(f["name"]).suffix.lower() in OFFICE_SUFFIXES | {".txt", ".md"}:
                    raw = self.http.request("GET", f"/drive/v3/files/{f['id']}", params={"alt": "media"}).content
                    text = _read_bytes(raw, Path(f["name"]).suffix)
                if text:
                    docs.append(SourceDoc("gdrive", f["id"], f["name"], f"# {f['name']}\n{text}", lm, f.get("webViewLink")))
            token = j.get("nextPageToken")
            if not token:
                return docs


def _read_bytes(raw: bytes, suffix: str) -> str | None:
    if suffix.lower() in {".txt", ".md"}:
        return raw.decode("utf-8", errors="replace")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"doc{suffix}"
        p.write_bytes(raw)
        return read_document(p)


# ----------------------------------------------------------------------------- SharePoint / OneDrive (Microsoft Graph)
class SharePointSource:
    name = "sharepoint"

    def __init__(self, access_token: str, drive_id: str, folder_path: str = "", client: httpx.Client | None = None, **kw):
        self.http = _Http("https://graph.microsoft.com/v1.0", {"Authorization": f"Bearer {access_token}"}, client, **kw)
        self.drive_id, self.folder = drive_id, folder_path.strip("/")

    def fetch(self, since=None) -> list[SourceDoc]:
        base = f"/drives/{self.drive_id}/root" + (f":/{self.folder}:" if self.folder else "")
        url, docs = f"{base}/children", []
        while url:
            j = self.http.get_json(url)
            for it in j.get("value", []):
                if "file" not in it:
                    continue
                suffix = Path(it["name"]).suffix.lower()
                lm = it.get("lastModifiedDateTime")
                if suffix not in OFFICE_SUFFIXES | {".txt", ".md"} or not _changed(lm, since):
                    continue
                raw = self.http.request("GET", f"/drives/{self.drive_id}/items/{it['id']}/content", follow_redirects=True).content
                text = _read_bytes(raw, suffix)
                if text:
                    docs.append(SourceDoc("sharepoint", it["id"], it["name"], f"# {it['name']}\n{text}", lm, it.get("webUrl")))
            url = j.get("@odata.nextLink")
        return docs


# ----------------------------------------------------------------------------- GitHub issues / PRs / wiki
class GitHubIssuesSource:
    name = "github-issues"

    def __init__(self, repo: str, token: str | None = None, client: httpx.Client | None = None, max_items: int = 200, **kw):
        h = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
        self.http = _Http("https://api.github.com", h, client, **kw)
        self.repo, self.max_items = repo, max_items

    def fetch(self, since=None) -> list[SourceDoc]:
        docs, page = [], 1
        while len(docs) < self.max_items:
            items = self.http.get_json(f"/repos/{self.repo}/issues", params={"state": "all", "per_page": 100, "page": page, **({"since": since} if since else {})})
            if not isinstance(items, list) or not items:
                break
            for it in items:
                kind = "PR" if "pull_request" in it else "Issue"
                docs.append(SourceDoc("github-issues", str(it["number"]), it.get("title", ""),
                                      f"# {kind} #{it['number']}: {it.get('title', '')}\n{it.get('body') or ''}", it.get("updated_at"), it.get("html_url")))
            page += 1
        return docs


# ----------------------------------------------------------------------------- orchestration
def sources_from_env() -> list[DocumentSource]:
    """Build the sources whose credentials are present in the environment; nothing is contacted until fetch()."""
    e, out = os.environ.get, []
    if e("NOTION_TOKEN"):
        out.append(NotionSource(e("NOTION_TOKEN"), [p for p in e("NOTION_PAGE_IDS", "").split(",") if p]))
    if e("JIRA_BASE_URL") and e("JIRA_EMAIL") and e("JIRA_API_TOKEN"):
        out.append(JiraSource(e("JIRA_BASE_URL"), e("JIRA_EMAIL"), e("JIRA_API_TOKEN"), e("JIRA_JQL", "ORDER BY updated DESC")))
    if e("SLACK_BOT_TOKEN") and e("SLACK_CHANNELS"):
        out.append(SlackSource(e("SLACK_BOT_TOKEN"), [c for c in e("SLACK_CHANNELS").split(",") if c]))
    if e("GOOGLE_ACCESS_TOKEN"):
        out.append(GoogleDriveSource(e("GOOGLE_ACCESS_TOKEN"), e("GOOGLE_DRIVE_FOLDER_ID")))
    if e("MS_GRAPH_TOKEN") and e("SHAREPOINT_DRIVE_ID"):
        out.append(SharePointSource(e("MS_GRAPH_TOKEN"), e("SHAREPOINT_DRIVE_ID"), e("SHAREPOINT_FOLDER", "")))
    if e("GITHUB_ISSUES_REPO"):
        out.append(GitHubIssuesSource(e("GITHUB_ISSUES_REPO"), e("GITHUB_TOKEN")))
    return out


def collect(sources: list[DocumentSource], tenant_id: str, since: str | None = None) -> tuple[list[DocumentChunk], list[SourceStatus]]:
    """Fetch every source (a failing source is reported, never fatal) and chunk the documents with last-modified stamps."""
    chunks: list[DocumentChunk] = []
    statuses: list[SourceStatus] = []
    for src in sources:
        st = SourceStatus(src.name, True)
        try:
            for d in src.fetch(since):
                stamp = f"\n(last modified: {d.last_modified})" if d.last_modified else ""
                chunks += parse_text(d.text + stamp, d.doc_name, tenant_id, is_md=True)
                st.documents += 1
        except Exception as exc:  # network/ACL/rate-limit failure: coverage shows it, audit continues
            st.errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
        statuses.append(st)
    return chunks, statuses
