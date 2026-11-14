"""Multi-language scanning parity, notebooks, and the closed-world 'language not scanned' gap."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.edge_extractors import build_index
from src.edge_extractors.code_scanner import scan_code

LANGS = Path(__file__).parent / "fixtures" / "langs"
CODE_LANGS = ["typescript", "java", "go", "csharp", "kotlin", "ruby", "php", "rust", "swift", "bash"]


@pytest.mark.parametrize("lang", CODE_LANGS)
def test_planted_defects_found_in_every_language(lang):
    bad = scan_code(LANGS / lang / "bad", "t").slices
    assert bad, f"{lang}: no slice produced"
    s = bad[0]
    assert s.calls_ai_sdk and s.is_decision
    assert not s.has_pii_redaction and not s.has_hitl_gate
    assert "US" in s.endpoint_regions.values()


@pytest.mark.parametrize("lang", CODE_LANGS)
def test_clean_twin_shows_controls_and_eu_endpoint(lang):
    s = scan_code(LANGS / lang / "clean", "t").slices[0]
    assert s.has_pii_redaction and s.has_hitl_gate
    assert "US" not in s.endpoint_regions.values()


def test_notebook_cells_are_scanned_with_cell_locator():
    r = scan_code(LANGS / "notebook" / "bad", "t")
    assert r.slices and "#cell0" in r.slices[0].file_path
    assert r.slices[0].calls_http and "US" in r.slices[0].endpoint_regions.values()
    assert r.lang_files.get("notebook") == 1


def test_unsupported_language_becomes_suspected_gap_not_pass(monkeypatch):
    from src.agents import run_audit
    monkeypatch.setenv("GRAPHITE_FRAMEWORKS", "ALL")
    ix = build_index(LANGS / "unscanned" / "bad", "u")
    assert ix.unscanned == {".scala": 1} and ix.has_code
    rep = run_audit(LANGS / "unscanned" / "bad", "u")
    cov = next(f for f in rep.all_findings() if f.check_id == "COV-01")
    assert cov.status == "SUSPECTED_GAP"


def test_fully_parsed_repo_passes_coverage_check(monkeypatch):
    from src.agents import run_audit
    monkeypatch.setenv("GRAPHITE_FRAMEWORKS", "ALL")
    rep = run_audit(LANGS / "go" / "clean", "g")
    assert next(f for f in rep.all_findings() if f.check_id == "COV-01").status == "PASS"


INFRA = Path(__file__).parent / "fixtures" / "infra"


def test_infra_regions_and_secrets_extracted():
    bad = scan_code(INFRA / "bad", "t")
    assert {f["region"] for f in bad.infra_facts if f["kind"] == "region"} == {"US"}
    tags = {t for c in bad.cards for t in c.capability_tags}
    assert "infra_region_us" in tags and "infra_hardcoded_secret" in tags
    assert all("sk-live" not in c.system_prompt for c in bad.cards)  # secret value withheld
    clean = scan_code(INFRA / "clean", "t")
    assert "infra_region_us" not in {t for c in clean.cards for t in c.capability_tags}


def test_manifest_licences_across_ecosystems():
    deps = {d.name: d for d in scan_code(INFRA / "bad", "t").dependencies}
    assert deps["itext"].license_class == "STRONG_COPYLEFT" and deps["express"].license_class == "PERMISSIVE"
    assert "gin-gonic/gin" in {d.name for d in scan_code(INFRA / "clean", "t").dependencies} or scan_code(INFRA / "clean", "t").dependencies


def test_safety_bypass_in_yaml_and_python_and_disclosure_flags(tmp_path):
    (tmp_path / "moderation.yaml").write_text("tiers:\n  pro:\n    face_upload_filter: false  # intimate likeness allowed\n  free:\n    face_upload_filter: true\n")
    (tmp_path / "gen.py").write_text('from fastapi import FastAPI\napp = FastAPI()\n@app.post("/v1/chat/help")\nasync def chat_help(req):\n    return {"reply": "hi", "ai_disclosed": False}\n')
    r = scan_code(tmp_path, "t")
    byp = [c for c in r.cards if "safety_control_bypass" in c.capability_tags]
    assert len(byp) == 1 and byp[0].exact_locator == "moderation.yaml:3-3" and "deepfake_risk" in byp[0].capability_tags
    chat = next(s for s in r.slices if s.function_name == "chat_help")
    assert chat.disclosure_denied and not chat.has_ai_disclosure
