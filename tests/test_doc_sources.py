"""Remote document sources against httpx.MockTransport: pagination, 429 retry, ACL limits, incremental sync, failure isolation."""
from __future__ import annotations

import httpx

from src.connectors.doc_sources import (GitHubIssuesSource, GoogleDriveSource, JiraSource, NotionSource, SharePointSource,
                                        SlackSource, collect)

NOSLEEP = {"sleep": lambda s: None}


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_notion_pages_blocks_and_incremental():
    def h(req):
        p = req.url.path
        if p == "/v1/search":
            return httpx.Response(200, json={"results": [{"id": "p1"}]})
        if p == "/v1/pages/p1":
            return httpx.Response(200, json={"last_edited_time": "2026-11-01T00:00:00Z", "url": "u", "properties": {"Name": {"type": "title", "title": [{"plain_text": "AI Policy"}]}}})
        if p == "/v1/blocks/p1/children":
            return httpx.Response(200, json={"results": [{"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Oversight"}]}},
                                                         {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "A human reviews every decision."}]}}], "has_more": False})
    src = NotionSource("t", client=client(h), **NOSLEEP)
    docs = src.fetch()
    assert docs[0].title == "AI Policy" and "# Oversight" in docs[0].text
    assert src.fetch(since="2026-12-01T00:00:00Z") == []  # unchanged since last sync


def test_jira_paginates_and_reads_adf_comments():
    calls = []

    def h(req):
        calls.append(int(req.url.params["startAt"]))
        issue = lambda k: {"key": k, "self": "s", "fields": {"summary": f"Incident {k}", "updated": "2026-11-02T00:00:00Z", "issuetype": {"name": "Bug"}, "status": {"name": "Open"},
                           "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Model leaked PII"}]}]},
                           "comment": {"comments": [{"body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Patched"}]}]}}]}}}
        start = int(req.url.params["startAt"])
        return httpx.Response(200, json={"total": 2, "issues": [issue("AI-1")] if start == 0 else [issue("AI-2")]})
    docs = JiraSource("https://x.atlassian.net", "a@b.c", "tok", client=client(h), **NOSLEEP).fetch()
    assert [d.doc_id for d in docs] == ["AI-1", "AI-2"] and "Model leaked PII" in docs[0].text and "Comment: Patched" in docs[0].text
    assert calls == [0, 1]


def test_slack_skips_private_channels_by_default():
    def h(req):
        ch = req.url.params["channel"]
        if req.url.path == "/api/conversations.info":
            return httpx.Response(200, json={"channel": {"name": "pub" if ch == "C1" else "secret", "is_private": ch == "C2"}})
        return httpx.Response(200, json={"messages": [{"ts": "1767225600.0", "text": f"msg in {ch}"}], "response_metadata": {"next_cursor": ""}})
    docs = SlackSource("t", ["C1", "C2"], include_private=False, client=client(h), **NOSLEEP).fetch()
    assert [d.doc_id for d in docs] == ["C1"]
    assert [d.doc_id for d in SlackSource("t", ["C1", "C2"], include_private=True, client=client(h), **NOSLEEP).fetch()] == ["C1", "C2"]


def test_drive_exports_google_docs_and_retries_429():
    state = {"n": 0}

    def h(req):
        if req.url.path == "/drive/v3/files":
            return httpx.Response(200, json={"files": [{"id": "d1", "name": "DPA", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "2026-11-03T00:00:00Z"}]})
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, text="We do not retain customer prompts (ZDR).")
    docs = GoogleDriveSource("tok", client=client(h), **NOSLEEP).fetch()
    assert state["n"] == 2 and "ZDR" in docs[0].text


def test_sharepoint_reads_office_files(tmp_path):
    import docx
    d = docx.Document()
    d.add_heading("Register", 1)
    d.add_paragraph("Credit Engine is high risk.")
    p = tmp_path / "r.docx"
    d.save(p)
    raw = p.read_bytes()

    def h(req):
        if req.url.path.endswith("/children"):
            return httpx.Response(200, json={"value": [{"id": "i1", "name": "register.docx", "file": {}, "lastModifiedDateTime": "2026-11-04T00:00:00Z", "webUrl": "w"}]})
        return httpx.Response(200, content=raw)
    docs = SharePointSource("tok", "drv", client=client(h), **NOSLEEP).fetch()
    assert "Credit Engine is high risk." in docs[0].text


def test_github_issues_and_failing_source_is_isolated():
    def ok(req):
        return httpx.Response(200, json=[{"number": 7, "title": "Add watermark", "body": "TODO C2PA", "updated_at": "2026-11-05T00:00:00Z", "html_url": "h"}]
                              if req.url.params["page"] == "1" else [])

    def boom(req):
        return httpx.Response(403, json={"message": "forbidden"})
    chunks, statuses = collect([GitHubIssuesSource("o/r", client=client(ok), **NOSLEEP), JiraSource("https://x", "a", "b", client=client(boom), **NOSLEEP)], "t")
    assert any("Add watermark" in c.text for c in chunks)
    assert statuses[0].documents == 1 and statuses[1].errors and "403" in statuses[1].errors[0]
    assert all("last modified" in c.text or c.text for c in chunks)
