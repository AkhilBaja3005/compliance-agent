# Threat model

Assets: client source code and documents, audit findings, API keys, the sign-off log, rule library integrity.

| Threat | Mitigation | Residual risk |
|---|---|---|
| Unauthenticated API use | closed by default; API keys, constant-time compare; 401/403 | key distribution is manual; no key expiry or per-key revocation list beyond editing the env |
| Cross-tenant data access | tenant scope on every key; jobs and reports return 404 (not 403) to other tenants; guardrail gate 2 quarantines findings that cite another tenant's artifacts | logical isolation only; a shared datastore bug would cross tenants |
| SSRF via repo URL | https only, host allow-list, no embedded credentials; ssh/file/git@ refused | a repository on an allow-listed host can still be large or hostile (clones are shallow and deleted) |
| Path traversal / local file read | local paths are admin-only and must resolve inside the companies or PDF root | admin is trusted |
| Hostile scanned code | files are parsed, never executed or installed; size caps; parser failures degrade to the signal scan | parser bugs (tree-sitter, python-docx, openpyxl) are a supply-chain exposure: keep pinned and run `pip-audit` |
| Resource exhaustion | rate limits, body-size limit, worker pool size, job timeout | a running thread cannot be killed; large repos can still use memory |
| Secret leakage | hard-coded credentials are reported by name and file only, values withheld; keys never logged; Linkup/Databricks/GitHub tokens go in headers only | secrets in scanned documents may appear in a cited snippet (280 chars); gate 2 redacts known patterns |
| Personal data in scanned data | only schemas, counts and classifications are stored; values are classified in memory and discarded | free-text columns could carry personal data in names or comments |
| Prompt injection from scanned docs | model output is validated against a schema; extracted claims must quote the document verbatim; findings are re-checked by deterministic gates; the model never executes tools | a hostile document can still influence narrative text, which is why findings require human sign-off |
| Rule library tampering | each rule has a sha256; changes produce a diff; `GRAPHITE_RULE_REVIEW_REQUIRED` stages changes for approval | seed text is not counsel-reviewed |
| Sign-off tampering | append-only, hash-chained log with verification | an attacker with disk access can rewrite the whole chain; keep an off-box copy |
