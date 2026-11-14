# Input coverage: what each scanner and connector reads

Every reader emits the same evidence model: `exact_locator`, `sha256_hash`, source type and `tenant_id`. Findings built on it obey
Closed-World (no evidence is `SUSPECTED_GAP`, never `PASS`) and Quarantine-Over-Drop. Nothing scanned is ever executed.
The report's Section 6 "Input Coverage" table lists, per input, CONNECTED / PARTIAL / MISSING and what could not be concluded.

## Code (`src/edge_extractors/`)

| Reader | Reads | Cannot see | Known false positives / negatives |
|---|---|---|---|
| `code_scanner.py` (Python) | tree-sitter AST: routes, AI SDK calls, outbound HTTP + region, redaction, human gates, moderation, watermark, system prompts | dynamic dispatch, calls through wrappers in other files | cross-file call graphs are not followed (FN); keyword-named gates count even if not enforced (FP) |
| `lang_scanner.py` (TS/JS, Java, Kotlin, Go, C#, Rust, Ruby, PHP, Swift, Bash) | tree-sitter functions/handlers, same-file call graph, same facts as Python | cross-file flows, framework magic (DI-wired routes), reflection | `fetch`/`axios` only count as outbound when an absolute URL is present in the function (relative browser calls are ignored); controls must be named conventionally (`redact`, `humanReviewQueue`, ...) |
| notebooks (`.ipynb`) | each code cell as Python, locator `file.ipynb#cellN:a-b` | magics (`%`, `!`) are dropped | output cells ignored |
| unsupported languages (`.scala`, `.c`, `.cpp`, `.dart`, ...) | extension and count only | everything inside | reported as `COV-01` SUSPECTED_GAP, never silently skipped |
| `manifest_scanner.py` (dependencies) | requirements, pyproject, poetry, package.json, package-lock (declared licences), go.mod, Cargo.toml, Gemfile, composer.json, pom.xml, Gradle, `.csproj`, `Package.swift` | transitive dependencies except lockfiles that list them; licences not in the built-in table are `UNKNOWN` | unknown licence is not flagged as copyleft (FN) |
| `manifest_scanner.py` (infra/config) | Dockerfile, compose, Terraform/OpenTofu, CloudFormation, Kubernetes, serverless.yml, GitHub Actions, `.env.example`: cloud region, model-provider hosts, hard-coded secrets (name only, value withheld) | runtime configuration, secrets managers | region in variables resolved elsewhere is missed (FN) |

Parsers: `tree-sitter` + `tree-sitter-language-pack`. If a grammar is unavailable the file still counts as code and the signal scan runs.

## Documents (`doc_parser.py`, `doc_formats.py`, `src/connectors/`)

Local formats: Markdown, text, PDF (OCR via `pytesseract` + `pypdfium2` when installed; low confidence becomes a visible `LOW_OCR_CONFIDENCE` chunk, no OCR becomes `OCR_REQUIRED`), `.docx` (headings, tables, headers/footers), `.xlsx` (sheet + cell addresses, formulas never evaluated), `.pptx` (slides + speaker notes), HTML, RTF, ODT, CSV/TSV. An unreadable file becomes an `UNPARSED_DOCUMENT` chunk so it is never ignored silently. A CSV whose header contains personal/special-category columns is treated as data: its values are withheld.

Remote sources (`doc_sources.py`): Notion, Jira (issues + comments), Slack (explicitly listed channels, public only unless `SLACK_INCLUDE_PRIVATE=true`), Google Drive, SharePoint/OneDrive (Microsoft Graph), GitHub issues/PRs. Each paginates, retries 429/502/503 with `Retry-After`, stamps `last modified`, supports incremental sync (`since`), reads only what the credential can read, and isolates failures (a failing source is reported in coverage, the audit continues). Enable with `GRAPHITE_REMOTE_DOC_SOURCES=true` plus:

| Source | Variables / scopes |
|---|---|
| Notion | `NOTION_TOKEN`, optional `NOTION_PAGE_IDS` (integration must be shared with the pages) |
| Jira | `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, optional `JIRA_JQL` (read-only Browse Projects) |
| Slack | `SLACK_BOT_TOKEN`, `SLACK_CHANNELS` (`channels:history`, `channels:read`) |
| Google Drive | `GOOGLE_ACCESS_TOKEN`, optional `GOOGLE_DRIVE_FOLDER_ID` (`drive.readonly`) |
| SharePoint | `MS_GRAPH_TOKEN`, `SHAREPOINT_DRIVE_ID`, optional `SHAREPOINT_FOLDER` (`Files.Read.All`) |
| GitHub issues | `GITHUB_ISSUES_REPO`, optional `GITHUB_TOKEN` |

Claim extraction: regex rules are the deterministic floor. When a model is reachable (`DATABRICKS_SERVING_ENDPOINT` / BYOM), `extract_assertions_llm` adds paraphrased claims; a claim is kept only if its quote appears verbatim in the chunk, and negated statements ("we never redact") are dropped. Extraction stops after two model failures. Recall on paraphrased and negated claims has **not** been measured on a labelled doc set.

Not implemented: Confluence Cloud live testing, Google Docs comments/suggestions, Slack threads and private channels by default, ACL mirroring beyond what the credential can read.

## Data (`data_scanner.py`, `src/agents/data_governance.py`)

Reads schemas, manifests and cards: CSV/TSV, Parquet, JSON Lines, SQL DDL, dbt `schema.yml`, JSON Schema, Avro, Protobuf, DVC, data cards / datasheets / Hugging Face dataset cards. Live read-only metadata through injected clients: SQL `information_schema` (Postgres/Snowflake/BigQuery-style), Unity Catalog (`databricks-sdk`), MongoDB (bounded sample).

Privacy: only column names, types, row counts, null rates, distinct-count buckets, classification and schema hashes are kept. Values are inspected in memory on at most 200 rows to classify a column, then discarded; tests assert they never appear in the asset or in the report. Checks DATA-01..05 run only when data assets exist; otherwise the coverage table shows "NOT CONNECTED".

| Check | Rule | Meaning |
|---|---|---|
| DATA-01 | Art. 10 | governance / bias examination documented for personal or protected-attribute data |
| DATA-02 | Art. 10 | safeguards documented for special-category columns |
| DATA-03 | Art. 53 / CDSM | datasets declare source, licence, lineage; non-commercial licence is a confirmed violation |
| DATA-04 | Art. 10 | retention / deletion documented for personal data |
| DATA-05 | Art. 5(1)(e) | biometric data not acquired by untargeted scraping; no lawful basis is a suspected gap |

Fairness: `compute_fairness` reads a labelled outcomes CSV (an outcome column plus sex/age/ethnicity/disability) and reports selection-rate ratios against the highest-rate group, flagging < 0.80 as a screening indicator (not a legal test). Groups with n < 30 are not rated. With no outcomes file it reports "not testable" and never invents numbers.

Not implemented: Snowflake/BigQuery/Postgres connectors beyond the generic `information_schema` reader, residency from catalog tags other than `region`/`location`, value-level lineage, differential privacy.

## Evaluation (`src/evaluation.py`, `tests/eval/gold.json`, `aegis eval`)

Scores confirmed findings against gold labels (precision/recall per check and overall); `known_missed` lists planted defects with no check yet and counts as false negatives. CI gate: `tests/test_eval_gate.py`. The gold set is small and synthetic: its numbers describe that set only.
