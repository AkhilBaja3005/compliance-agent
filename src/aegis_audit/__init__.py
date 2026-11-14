"""Aegis AI Safety & Regulatory Compliance Auditor SDK."""

import sys
from pathlib import Path

# Ensure root directory is in sys.path when installed in editable or script mode
_root = str(Path(__file__).resolve().parents[2])
if _root not in sys.path:
    sys.path.insert(0, _root)

from aegis_audit.client import AuditSession, ComplianceAuditor
from aegis_audit.report_pdf import render_audit_pdf

__all__ = [
    "ComplianceAuditor",
    "AuditSession",
    "render_audit_pdf",
]

