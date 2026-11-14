"""SARIF 2.1.0 Exporter for Graphite AI Compliance Auditor.

Conforms to the OASIS Static Analysis Results Interchange Format (SARIF) v2.1.0:
https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos02/schemas/sarif-schema-2.1.0.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

SEVERITY_MAP = {
    "CRITICAL": {"level": "error", "security_severity": "9.5"},
    "HIGH": {"level": "error", "security_severity": "7.5"},
    "MEDIUM": {"level": "warning", "security_severity": "5.0"},
    "LOW": {"level": "note", "security_severity": "2.5"},
    "INFO": {"level": "note", "security_severity": "1.0"},
}


def _parse_locator(locator: str) -> tuple[str, int, int]:
    """Extract (uri, start_line, end_line) from exact_locator strings.

    Examples:
      - 'moderation.yaml:48' -> ('moderation.yaml', 48, 48)
      - 'src/generate.py:L43-L52' -> ('src/generate.py', 43, 52)
      - 'generate_image():L43-L52' -> ('generate_image()', 43, 52)
      - 'github/imagery-studio/src/generate.py' -> ('src/generate.py', 1, 1)
    """
    loc = str(locator or "").strip()
    if not loc:
        return "unknown", 1, 1

    # Check for file:line or file:Lstart-Lend
    m = re.search(r"^(?:github/[^/]+/)?(.+?):(?:L?(\d+))(?:-L?(\d+))?$", loc)
    if m:
        uri = m.group(1).strip()
        start = int(m.group(2))
        end = int(m.group(3)) if m.group(3) else start
        return uri, max(1, start), max(1, end)

    # Check for locator ending with :digits
    m_simple = re.search(r"^(?:github/[^/]+/)?(.+?):(\d+)$", loc)
    if m_simple:
        return m_simple.group(1).strip(), max(1, int(m_simple.group(2))), max(1, int(m_simple.group(2)))

    # Fallback: clean uri prefix
    clean_uri = re.sub(r"^(?:github|local)/[^/]+/", "", loc)
    clean_uri = clean_uri.split(":")[0]
    return clean_uri or "repository", 1, 1


def render_audit_sarif(report: Any, output_path: Optional[str] = None) -> Dict[str, Any]:
    """Converts a TriagedAuditReport, AuditSession, or dict into a SARIF 2.1.0 document."""
    if hasattr(report, "to_dict"):
        data = report.to_dict()
    elif hasattr(report, "model_dump"):
        data = report.model_dump()
    elif isinstance(report, dict):
        data = report
    else:
        data = {k: getattr(report, k) for k in dir(report) if not k.startswith("_")}

    rules_dict: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []

    # Gather in-scope findings
    all_findings: List[Dict[str, Any]] = []
    for cat in ("confirmed_findings", "suspected_gaps", "quarantined_for_human_review"):
        for f in data.get(cat, []):
            f_dict = f if isinstance(f, dict) else (f.model_dump() if hasattr(f, "model_dump") else dict(f))
            all_findings.append(f_dict)

    for finding in all_findings:
        rule_id = finding.get("primary_rule") or finding.get("regulatory_reference") or finding.get("check_id") or "STATUTORY-RULE"
        sev_str = str(finding.get("severity") or "HIGH").upper()
        sev_meta = SEVERITY_MAP.get(sev_str, SEVERITY_MAP["HIGH"])

        # Populate rules metadata if not already present
        if rule_id not in rules_dict:
            title = finding.get("title") or rule_id
            rules_dict[rule_id] = {
                "id": rule_id,
                "name": re.sub(r"[^\w\-.]", "_", rule_id),
                "shortDescription": {"text": title[:100]},
                "fullDescription": {"text": finding.get("summary") or title},
                "defaultConfiguration": {"level": sev_meta["level"]},
                "properties": {
                    "security-severity": sev_meta["security_severity"],
                    "tags": ["compliance", "regulatory", finding.get("status", "CONFIRMED_VIOLATION")],
                    "precision": "very-high" if finding.get("status") == "CONFIRMED_VIOLATION" else "medium",
                },
                "help": {
                    "text": (
                        f"Statutory Mandate: {rule_id}\n"
                        f"Severity: {sev_str}\n"
                        f"Exposure: {finding.get('exposure_text', 'Regulatory enforcement / statutory fines')}\n\n"
                        f"Remediation Steps:\n" + "\n".join(f"- {s}" for s in finding.get("remediation_steps", []))
                    )
                },
            }

        # Build message
        msg_parts = [
            f"[{sev_str}] {finding.get('title', 'Statutory Finding')}",
            f"Rule: {rule_id}",
            finding.get("summary", ""),
        ]
        if finding.get("remediation_steps"):
            msg_parts.append("Remediation: " + "; ".join(finding["remediation_steps"][:2]))
        message_text = "\n\n".join(p for p in msg_parts if p)

        # Build physical locations from evidence
        locations: List[Dict[str, Any]] = []
        evidence_list = finding.get("evidence", [])
        if evidence_list:
            for ev in evidence_list:
                ev_dict = ev if isinstance(ev, dict) else (ev.model_dump() if hasattr(ev, "model_dump") else dict(ev))
                loc_str = ev_dict.get("exact_locator") or ev_dict.get("artifact_id") or ev_dict.get("item") or ""
                uri, s_line, e_line = _parse_locator(loc_str)
                locations.append({
                    "physicalLocation": {
                        "artifactLocation": {"uri": uri, "uriBaseId": "%SRCROOT%"},
                        "region": {
                            "startLine": s_line,
                            "endLine": e_line,
                            "snippet": {"text": ev_dict.get("snippet", "")[:300]} if ev_dict.get("snippet") else None,
                        },
                    }
                })
        else:
            locations.append({
                "physicalLocation": {
                    "artifactLocation": {"uri": "repository", "uriBaseId": "%SRCROOT%"},
                    "region": {"startLine": 1, "endLine": 1},
                }
            })

        # Remove None values from location regions
        for loc in locations:
            reg = loc["physicalLocation"]["region"]
            if reg.get("snippet") is None:
                reg.pop("snippet", None)

        result_item: Dict[str, Any] = {
            "ruleId": rule_id,
            "level": sev_meta["level"],
            "message": {"text": message_text},
            "locations": locations,
            "properties": {
                "findingId": finding.get("finding_id", ""),
                "status": finding.get("status", "CONFIRMED_VIOLATION"),
                "confidence": finding.get("confidence", 1.0),
                "humanReviewRequired": finding.get("human_review_required", False),
            },
        }
        results.append(result_item)

    sarif_doc: Dict[str, Any] = {
        "$schema": "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos02/schemas/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Graphite Compliance Auditor",
                        "organization": "Graphite AI Safety",
                        "semanticVersion": "1.0.0",
                        "informationUri": "https://github.com/graphite-ai/graphite",
                        "rules": list(rules_dict.values()),
                    }
                },
                "results": results,
            }
        ],
    }

    if output_path:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(sarif_doc, indent=2), encoding="utf-8")

    return sarif_doc
