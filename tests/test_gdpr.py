"""EU GDPR framework: rules seeded, scope switch, conservative transfer logic, Art. 22 and Art. 28 checks."""
from __future__ import annotations

from pathlib import Path

from src.agents import run_audit
from src.law_sync import get_store
from src.regulatory_rag.tier_a_rules import CHECKS, active_frameworks

FIX = Path(__file__).parent / "fixtures"


def test_gdpr_rules_seeded_and_checks_registered():
    ids = {r for r in get_store().snapshot()}
    assert {"EU_GDPR:Art.9", "EU_GDPR:Art.22", "EU_GDPR:Art.28", "EU_GDPR:Art.32", "EU_GDPR:Art.35", "EU_GDPR:Art.44"} <= ids
    assert {c.check_id for c in CHECKS if c.jurisdiction == "EU_GDPR"} == {f"GDPR-0{i}" for i in range(1, 7)}


def test_default_scope_is_ai_act_plus_gdpr(monkeypatch):
    monkeypatch.delenv("AEGIS_FRAMEWORKS", raising=False)
    assert active_frameworks() == {"EU_AI_ACT", "EU_GDPR"}


def _gdpr(path, monkeypatch, fw="EU_AI_ACT,EU_GDPR"):
    monkeypatch.setenv("AEGIS_FRAMEWORKS", fw)
    rep = run_audit(path, "g")
    return {f.check_id: f for f in rep.all_findings() if (f.check_id or "").startswith("GDPR-")}, rep


def test_us_transfer_is_a_gap_not_a_confirmed_violation(monkeypatch):
    f, rep = _gdpr(FIX / "companies" / "company_a_finscore", monkeypatch)
    assert f["GDPR-01"].status == "SUSPECTED_GAP"  # SCCs/DPF may exist: ask for the mechanism, do not accuse
    assert f["GDPR-02"].status == "CONFIRMED_VIOLATION" and f["GDPR-02"].primary_rule == "EU_GDPR:Art.22"
    assert "EUR 20m" in f["GDPR-02"].exposure_text and "GBP" not in f["GDPR-02"].exposure_text
    assert rep.frameworks == ["EU_AI_ACT", "EU_GDPR"] and "EU AI Act + EU GDPR" in rep.scope


def test_transfer_mechanism_in_docs_turns_gap_into_pass(monkeypatch, tmp_path):
    import shutil
    dst = tmp_path / "co"
    shutil.copytree(FIX / "companies" / "company_a_finscore", dst)
    (dst / "transfers.md").write_text("# Transfers\nData sent to the US provider is covered by Standard Contractual Clauses and a transfer impact assessment.\n")
    f, _ = _gdpr(dst, monkeypatch)
    assert f["GDPR-01"].status == "PASS"


def test_hardcoded_secret_is_art32_gap_without_leaking_value(monkeypatch, tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\nENV OPENAI_API_KEY=sk-live-0123456789abcdef0123\n")
    (tmp_path / "app.py").write_text("print('x')\n")
    f, rep = _gdpr(tmp_path, monkeypatch)
    assert f["GDPR-06"].status == "SUSPECTED_GAP"
    assert "sk-live" not in rep.model_dump_json()


def test_ai_act_only_scope_excludes_gdpr(monkeypatch):
    f, _ = _gdpr(FIX / "companies" / "company_a_finscore", monkeypatch, fw="EU_AI_ACT")
    assert f == {}
