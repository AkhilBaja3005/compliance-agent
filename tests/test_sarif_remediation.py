"""Unit tests for SARIF 2.1.0 exporter, patch remediator, and CLI CI/CD flags."""
from __future__ import annotations

import json
from pathlib import Path
from typer.testing import CliRunner

from graphite_audit.cli import app
from graphite_audit.client import ComplianceAuditor
from graphite_audit.remediator import generate_remediation_patches
from graphite_audit.sarif import render_audit_sarif

runner = CliRunner()


def test_sarif_export_schema_and_scoring(fixtures_dir):
    auditor = ComplianceAuditor()
    session = auditor.audit(company_name="Northwind Labs Ltd", target_dir=None)

    sarif = session.save_sarif()
    assert sarif["version"] == "2.1.0"
    assert sarif["$schema"].startswith("https://docs.oasis-open.org/sarif/sarif/v2.1.0")

    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "Graphite Compliance Auditor"
    assert len(run["results"]) >= 5

    # Check rule scoring
    rule = run["tool"]["driver"]["rules"][0]
    assert "security-severity" in rule["properties"]
    assert float(rule["properties"]["security-severity"]) >= 7.0

    # Check finding result mapping and physical location
    result = next(r for r in run["results"] if "moderation.yaml" in str(r.get("locations", [])))
    assert result["level"] == "error"
    loc = result["locations"][0]["physicalLocation"]
    assert "moderation.yaml" in loc["artifactLocation"]["uri"]
    assert loc["region"]["startLine"] == 48


def test_remediation_patch_generation(tmp_path):
    # Setup sample non-compliant moderation file
    mod_yaml = tmp_path / "moderation.yaml"
    mod_yaml.write_text(
        "pro:\n  face_upload_filter: false\n  deepfake_detection_enforced: false\n",
        encoding="utf-8",
    )

    finding = {
        "finding_id": "F-001",
        "title": "Facial Likeness Moderation Bypass on Pro Tier",
        "primary_rule": "EU AI Act Article 5(1)(d)",
        "summary": "Line 48 of moderation.yaml sets face_upload_filter: false",
        "evidence": [{"exact_locator": "moderation.yaml:48"}],
    }
    report = {"confirmed_findings": [finding]}

    # Dry-run patch generation
    patches = generate_remediation_patches(report, [tmp_path], apply=False)
    assert len(patches) == 1
    assert "face_upload_filter: true" in patches[0]["diff"]
    assert patches[0]["applied"] is False

    # Apply patch in-place
    patches_applied = generate_remediation_patches(report, [tmp_path], apply=True)
    assert patches_applied[0]["applied"] is True
    updated = mod_yaml.read_text(encoding="utf-8")
    assert "face_upload_filter: true" in updated
    assert "deepfake_detection_enforced: true" in updated


def test_cli_sarif_and_fail_on_gate(tmp_path):
    # 1. Test SARIF export via CLI
    sarif_file = tmp_path / "audit.sarif"
    res = runner.invoke(app, ["scan", "--format", "all", "--sarif-out", str(sarif_file)])
    assert res.exit_code == 0
    assert sarif_file.is_file()
    sarif_data = json.loads(sarif_file.read_text(encoding="utf-8"))
    assert sarif_data["version"] == "2.1.0"

    # 2. Test CI/CD fail-on critical gate
    res_gate = runner.invoke(app, ["scan", "--fail-on", "critical"])
    assert res_gate.exit_code == 1
    assert "CI/CD Gate Failed" in res_gate.output

    # 3. Test CI/CD gate pass when threshold is none
    res_pass = runner.invoke(app, ["scan", "--fail-on", "none"])
    assert res_pass.exit_code == 0


def test_cli_fix_command(tmp_path):
    report_file = tmp_path / "report.json"
    mod_yaml = tmp_path / "moderation.yaml"
    mod_yaml.write_text("pro:\n  face_upload_filter: false\n", encoding="utf-8")

    report_data = {
        "confirmed_findings": [{
            "finding_id": "F-MOD-01",
            "title": "Facial Likeness Moderation Bypass on Pro Tier",
            "primary_rule": "EU AI Act Article 5(1)(d)",
            "summary": "face_upload_filter: false on line 48",
            "evidence": [{"exact_locator": f"{mod_yaml.name}:2"}],
        }]
    }
    report_file.write_text(json.dumps(report_data), encoding="utf-8")

    # Run graphite fix with --apply
    patch_file = tmp_path / "fixes.patch"
    res = runner.invoke(app, [
        "fix",
        "--report", str(report_file),
        "--repos", str(tmp_path),
        "--apply",
        "--patch-out", str(patch_file),
    ])
    assert res.exit_code == 0
    assert "Successfully applied" in res.output
    assert patch_file.is_file()
    assert "face_upload_filter: true" in mod_yaml.read_text(encoding="utf-8")
