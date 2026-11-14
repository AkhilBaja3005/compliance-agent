"""Databricks Unity Catalog governance sink: persists reports + AI system inventory to Delta tables."""
from __future__ import annotations

import logging
import os

from src.schemas.findings import TriagedAuditReport

log = logging.getLogger(__name__)
CATALOG = os.getenv("DATABRICKS_CATALOG", "compliance_catalog")
SCHEMA = os.getenv("DATABRICKS_SCHEMA", "audit_prod")
AUDIT_REPORTS_TABLE = f"{CATALOG}.{SCHEMA}.audit_reports"
INVENTORY_TABLE = f"{CATALOG}.{SCHEMA}.ai_system_inventory"

_DDL_REPORTS = f"""CREATE TABLE IF NOT EXISTS {AUDIT_REPORTS_TABLE} (
  report_id STRING, tenant_id STRING, company_name STRING, assessed_at TIMESTAMP, overall_readiness STRING,
  rule_library_version STRING, bundle_sha256 STRING, confirmed_count INT, suspected_count INT, quarantined_count INT,
  passed_count INT, mlflow_trace_id STRING, report_json STRING) USING DELTA"""
_DDL_INVENTORY = f"""CREATE TABLE IF NOT EXISTS {INVENTORY_TABLE} (
  report_id STRING, tenant_id STRING, company_name STRING, system_id STRING, system_name STRING, sector STRING,
  risk_category STRING, hosting_regions STRING, declared_in_docs BOOLEAN, detected_in_code BOOLEAN,
  record_json STRING, recorded_at TIMESTAMP) USING DELTA"""


class DatabricksGovernanceSink:
    """Writes via WorkspaceClient().statement_execution.execute_statement when DATABRICKS_WAREHOUSE_ID is set."""

    def __init__(self, host: str | None = None, token: str | None = None, warehouse_id: str | None = None, client=None):
        self.host = host if host is not None else os.getenv("DATABRICKS_HOST")
        self.token = token if token is not None else os.getenv("DATABRICKS_TOKEN")
        self.warehouse_id = warehouse_id if warehouse_id is not None else os.getenv("DATABRICKS_WAREHOUSE_ID")
        self._client = client
        self._ready = False
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.warehouse_id and (self._client is not None or (self.host and self.token)))

    def _ws(self):
        if self._client is None:
            from databricks.sdk import WorkspaceClient

            self._client = WorkspaceClient(host=self.host, token=self.token)
        return self._client

    def _exec(self, statement: str, params: dict[str, object] | None = None) -> None:
        from databricks.sdk.service.sql import StatementParameterListItem

        plist = [StatementParameterListItem(name=k, value=None if v is None else str(v), type="STRING")
                 for k, v in (params or {}).items()]
        resp = self._ws().statement_execution.execute_statement(
            warehouse_id=self.warehouse_id, statement=statement, parameters=plist or None, wait_timeout="30s")
        state = getattr(getattr(resp, "status", None), "state", None)
        if state is not None and str(getattr(state, "value", state)).upper() not in {"SUCCEEDED", "STATEMENTSTATE.SUCCEEDED"}:
            err = getattr(getattr(resp.status, "error", None), "message", "")
            raise RuntimeError(f"statement {state}: {err}")

    def ensure_tables(self) -> None:
        if self._ready:
            return
        try:
            self._exec(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
        except Exception as exc:  # may lack CREATE SCHEMA privilege when the schema already exists
            log.debug("create schema skipped: %s", exc)
        self._exec(_DDL_REPORTS)
        self._exec(_DDL_INVENTORY)
        self._ready = True

    def persist(self, report: TriagedAuditReport) -> str | None:
        """Insert the report and its system inventory; returns the Unity Catalog table name, or None when disabled/failed."""
        if not self.enabled:
            return None
        try:
            self.ensure_tables()
            self._exec(
                f"INSERT INTO {AUDIT_REPORTS_TABLE} VALUES (:report_id, :tenant_id, :company_name, CAST(:assessed_at AS TIMESTAMP), "
                ":overall_readiness, :rule_library_version, :bundle_sha256, CAST(:confirmed AS INT), CAST(:suspected AS INT), "
                "CAST(:quarantined AS INT), CAST(:passed AS INT), :mlflow_trace_id, :report_json)",
                {"report_id": report.report_id, "tenant_id": report.tenant_id, "company_name": report.company_name,
                 "assessed_at": report.assessed_at.isoformat() if report.assessed_at else None,
                 "overall_readiness": report.overall_readiness, "rule_library_version": report.rule_library_version,
                 "bundle_sha256": report.bundle_sha256, "confirmed": len(report.confirmed_findings),
                 "suspected": len(report.suspected_gaps), "quarantined": len(report.quarantined_for_human_review),
                 "passed": len(report.passed_checks), "mlflow_trace_id": report.stack_telemetry.get("mlflow_trace_id"),
                 "report_json": report.model_dump_json()})
            for s in report.system_inventory:
                self._exec(
                    f"INSERT INTO {INVENTORY_TABLE} VALUES (:report_id, :tenant_id, :company_name, :system_id, :system_name, :sector, "
                    ":risk_category, :hosting_regions, CAST(:declared AS BOOLEAN), CAST(:detected AS BOOLEAN), :record_json, "
                    "CAST(:recorded_at AS TIMESTAMP))",
                    {"report_id": report.report_id, "tenant_id": report.tenant_id, "company_name": report.company_name,
                     "system_id": s.system_id, "system_name": s.system_name, "sector": s.sector,
                     "risk_category": s.risk_category, "hosting_regions": ",".join(s.hosting_regions),
                     "declared": str(s.declared_in_docs).lower(), "detected": str(s.detected_in_code).lower(),
                     "record_json": s.model_dump_json(),
                     "recorded_at": report.assessed_at.isoformat() if report.assessed_at else None})
            self.last_error = None
            return AUDIT_REPORTS_TABLE
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("Databricks governance sink failed: %s", self.last_error)
            return None
