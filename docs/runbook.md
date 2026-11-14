# Runbook

## First deploy
1. `cp .env.example .env`; generate keys: `python -c "import secrets;print(secrets.token_urlsafe(32))"`; set `AEGIS_API_KEYS` (one admin key, one auditor key per tenant group, viewer keys for readers).
2. Set `AEGIS_DATA_DIR` to a persistent volume (jobs, reports, sign-offs). Without it everything is in memory.
3. `aegis doctor --live` and fix every FAIL. WARN/SKIP are acceptable when the service is intentionally unused.
4. `aegis sync-laws` (indexes statutory rules and `regulatory_pdfs/` into Atlas). Atlas builds vector indexes in the background (about a minute): wait for them to be queryable (`aegis doctor --live` lists their state) before relying on semantic search; BM25 is the fallback meanwhile.
5. Start: `docker compose up -d` or `uvicorn src.api:app --workers 1`. Probe `GET /healthz` and `/readyz`.

## Keeping the knowledge base current
`aegis sync-laws` is the one command. It (1) refreshes statutory rules (feed, Linkup citations, review gate) and embeds them, (2) ingests every folder and URL in `sync_sources.yaml` (or `--folder` / `--url` flags), (3) optionally indexes env-configured remote document sources into one tenant (`--remote-docs-tenant`, never the shared global tenant). Each source is hashed: unchanged sources are skipped, a changed one replaces its old passages, a deleted file's passages are removed. A source that fails (blocked page, 403, bad host) is reported and the rest still sync; the exit code is 1 so a scheduler notices.

Scheduling, pick one:
- **Separate process (recommended):** `aegis sync-daemon --interval-hours 24` (the `sync` service in `docker-compose.yml`).
- **cron:** `15 3 * * * cd /opt/aegis && .venv/bin/aegis sync-laws --no-deep-linkup >> /var/log/aegis-sync.log 2>&1`
- **Inside the API:** `AUTO_SYNC=true` (interval `AEGIS_SYNC_INTERVAL_HOURS`). With several API workers each one would run it, so prefer the daemon.
- **On demand:** `POST /laws/ingest` (admin) runs the same sync for the configured sources; request bodies cannot add paths or URLs.

Web sources must be https on a public host (private, loopback and link-local addresses are refused, redirects are re-checked). EUR-Lex often answers bots with a browser-check page: that is reported as an error and never indexed.

## Daily operations
- Logs are JSON on stdout with `request_id`, `status`, `duration_ms`, `key_id` (a short hash, never the key). Correlate with the `X-Request-ID` response header.
- Metrics: `GET /metrics` (admin) in Prometheus text: `aegis_http_requests_total`, `aegis_audits_total`, `aegis_findings_total`.
- Rule updates: with `AEGIS_RULE_REVIEW_REQUIRED=true`, scheduled or manual syncs stage changes. Review `GET /laws/pending`, then approve or reject. Reports record the rule-library version they were judged against.
- Sign-off: each decision is appended to `signoffs.jsonl` with the reviewer key id and a hash chain. `GET /reports/{id}/signoff` returns `chain_valid`; `false` means the file was edited.

## Incidents
| Symptom | Check | Action |
|---|---|---|
| every request 503 | `/readyz` says auth NOT CONFIGURED | set `AEGIS_API_KEYS` |
| 429 on audits | `AEGIS_RATE_LIMIT_HEAVY_PER_MIN` (default 10) | wait for `Retry-After` or raise the limit |
| job `timed_out` / `interrupted` | `AEGIS_JOB_TIMEOUT_S`, restart history | resubmit (same `Idempotency-Key` returns the old record; use a new key to rerun) |
| no semantic search results | `aegis doctor --live` index state | wait for the Atlas index, or re-run `aegis sync-laws` |
| `$vectorSearch ... failed` in logs | Atlas index missing or not READY | recreate through `aegis sync-laws`; BM25 fallback is automatic |
| key leaked | rotate the entry in `AEGIS_API_KEYS`, restart | review logs by `key_id` |

## Backups
`AEGIS_DATA_DIR` (reports, jobs, sign-offs) and the Mongo `audit_history` collection. Sign-off logs must be backed up unmodified (the chain is the evidence).
