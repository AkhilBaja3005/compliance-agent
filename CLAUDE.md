# Project Contract: Graphite AI Safety & Regulatory Compliance Auditor (`graphite_audit`)

## Tech Stack
- Python 3.11+, Pydantic v2, LangGraph, FastAPI, Typer, Rich, WeasyPrint, PyGithub, BeautifulSoup4, html2text, `linkup-sdk`, `pymongo`, `langgraph-checkpoint-mongodb`, `databricks-sdk`, `mlflow`, `rank-bm25`.

## Strict Directory Ownership (Zero Merge Conflicts)
- **Antigravity Owns (Python Library SDK, Rich CLI, WeasyPrint 6-Section PDF Renderer & Sample GitHub/Confluence Fixtures):**
  `pyproject.toml`, `.env.example`, `src/graphite_audit/`, `src/sample_connectors/`
- **Claude Code Owns (GitHub/Confluence Connectors, Linkup Scout, MongoDB Atlas & Databricks Storage, 7 Core Auditing Agents, 4-Gate Guardrails, FastAPI & Tests):**
  `src/schemas/`, `src/connectors/`, `src/edge_extractors/`, `src/law_sync/`, `src/regulatory_rag/`, `src/storage/`, `src/agents/`, `src/guardrails/`, `src/api.py`, `tests/`

## Core Agent & Stack Architecture
1. **7 Core Auditing Agents (LangGraph Cyclic Loop) + 1 Background Scout:**
   - `SupervisorAgent`: Holds mandatory EU checklist, routes single-question tasks to 6 micro-agents, loops until 100% resolved.
   - `MicroAgent 1 (pii_flow)`: PII leakage & EU vs. US server residency.
   - `MicroAgent 2 (hitl_oversight)`: Human-in-the-loop approval gates & contest routes (EU AI Act Art. 14 / EU GDPR Art. 22).
   - `MicroAgent 3 (safety_watermark)`: Unmoderated harmful/hate-speech generation (Art. 5) & Art. 50 AI disclosures/C2PA watermarks.
   - `MicroAgent 4 (oss_license)`: `GPL-3.0` & `CC-BY-NC-4.0` commercial license violations verified via Linkup.
   - `MicroAgent 5 (dpa_provenance)`: ZDR clauses, EU DSM TDM copyright, Annex IV & FRIA completeness.
   - `MicroAgent 6 (code_doc_drift)`: Cross-verifies Confluence/policy promises against GitHub AST & behavioral code facts.
   - `LinkupRegulatoryScout`: Fetches & cites live EU AI Act and EU DPA/EDPB updates into MongoDB Atlas.
2. **Three Core Platform Pillars:**
   - **Databricks:** Mosaic AI Model Serving (`DATABRICKS_SERVING_ENDPOINT`, supporting Claude or Llama without `response_format` schema failures), `@mlflow.trace` on all 7 auditing agents, and Unity Catalog Delta tables (`compliance_catalog.audit_prod.*`).
   - **Linkup:** `LinkupClient().search(..., depth="deep", output_type="sourcedAnswer")` providing verified `source_url` citations on regulatory rules and license checks.
   - **MongoDB Atlas:** `$vectorSearch` over regulatory rules & company artifacts, LangGraph `MongoDBSaver` checkpointer, and `audit_history` longitudinal drift tracking (`NEW` | `RECURRING` | `RESOLVED`).
3. **Zero False Negatives:**
   - **Closed-World Assumption:** Missing explicit evidence -> `SUSPECTED_GAP` (never `PASS`).
   - **Quarantine-Over-Drop:** Findings failing Guardrail Gates 1–3 -> `QUARANTINED_FOR_HUMAN_REVIEW` (never deleted).

## Shared `TriagedAuditReport` Schema Fields
- `report_id`, `company_name`, `assessed_at`, `scope`, `rule_library_version`, `input_coverage_pct`, `overall_readiness`, `readiness_summary`, `bundle_sha256`
- `stack_telemetry`: `{databricks_endpoint, unity_catalog_table, mlflow_trace_id, mongodb_database, mongodb_checkpoint_id, linkup_sources_verified_count}`
- `system_inventory` (list of `AISystemRecord` `S1..S7`), `compliance_matrix`, `confirmed_findings`, `suspected_gaps`, `quarantined_for_human_review`, `passed_checks`, `eval_results`, `fairness_metrics`, `roadmap`, `input_coverage`, `agent_execution_trace`
- Each `ComplianceFinding` includes: `finding_id`, `severity`, `status`, `due_date`, `days_remaining`, `confidence`, `title`, `system_id`, `system_name`, `primary_rule`, `also_engages`, `summary`, `code_vs_doc_drift`, `evidence` (list of `{type, item, exact_locator, sha256_hash, source_url, source_date}`), `exposure_text`, `owner`, `effort_days`, `human_review_required`, `remediation_steps`, `related_ids`, `history_status` (`NEW` | `RECURRING` | `RESOLVED`), `first_seen_at`, `linkup_citation_urls`.
