"""Data-driven HTML builders for the Aegis PDF (sections 2-6). Same template for every company; rows and columns
come from the audit report (systems, findings, checks, roadmap, coverage), never from hardcoded sample text."""
from __future__ import annotations

import html
import re
from typing import Any

_E = html.escape
SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
RISK_LABEL = {
    "PROHIBITED": ("Art. 5 · Prohibited practice", "badge-critical"),
    "HIGH_RISK": ("High-risk · Annex III", "badge-high"),
    "LIMITED_RISK": ("Limited risk · Art. 50", "badge-medium"),
    "MINIMAL_RISK": ("Minimal risk", "badge-low"),
    "UNKNOWN": ("Not classified", "badge-na"),
}
STATUS_CELL = {  # finding status -> (label, badge class)
    "CONFIRMED_VIOLATION": ("Gap", "badge-gap"),
    "SUSPECTED_GAP": ("Suspected", "badge-partial"),
    "QUARANTINED_FOR_HUMAN_REVIEW": ("Review", "badge-partial"),
    "PASS": ("Pass", "badge-pass"),
}
STATUS_RANK = {"CONFIRMED_VIOLATION": 0, "SUSPECTED_GAP": 1, "QUARANTINED_FOR_HUMAN_REVIEW": 2, "PASS": 3}


def _sev(f: dict) -> str:
    return str(f.get("severity") or "").upper()


def normalize_system(s: dict) -> dict:
    """Accept both the sample-mock keys (name/declared/eu_tier) and backend AISystemRecord keys."""
    s = dict(s)
    s.setdefault("name", s.get("system_name"))
    if "declared" not in s:
        s["declared"] = s.get("declared_in_docs", False)
    loc = (s.get("locators") or [""])[0]
    s.setdefault("repo", loc.split("/")[0] if "/" in loc else (loc.split(":")[0] if loc else "docs only"))
    s.setdefault("purpose", s.get("description", ""))
    if "eu_tier" not in s:
        s["eu_tier"] = RISK_LABEL.get(s.get("risk_category", "UNKNOWN"), RISK_LABEL["UNKNOWN"])[0]
    return s


def _file_of(locator: str) -> str:
    m = re.search(r"\(?([^\s()]+?\.[A-Za-z0-9]+)(?::\d+(?:-\d+)?)?\)?$", locator.strip())
    return (m.group(1) if m else locator).split(":")[0]


def finding_systems(f: dict, systems: list[dict]) -> set[str]:
    """Systems a finding touches: its own system_id plus any system whose code locators match its evidence files."""
    out = {f["system_id"]} if f.get("system_id") else set()
    files = {_file_of(str(e.get("exact_locator", ""))) for e in f.get("evidence", []) if e.get("source_type") == "code"}
    for s in systems:
        if files & {_file_of(l) for l in s.get("locators", [])}:
            out.add(s["system_id"])
    return out


def _badge(label: str, cls: str) -> str:
    return f'<span class="badge {cls}">{_E(label)}</span>'


# ------------------------------------------------------------------ section 2
def sec2_callout(systems: list[dict], findings: list[dict]) -> str:
    focus = [s for s in systems if s.get("risk_category") in ("PROHIBITED", "HIGH_RISK") or s.get("detected_in_code")]
    if not focus:
        return ""
    def path_items(s):
        caps = ", ".join(s.get("capabilities") or []) or "none detected"
        regs = ", ".join(r for r in s.get("hosting_regions", []) if r) or "unresolved"
        fnd = [f for f in findings if s["system_id"] in finding_systems(f, systems)]
        top = ", ".join(sorted({f.get("primary_rule", "") for f in fnd if f.get("status") != "PASS"})) or "no open findings"
        reg = "declared in the AI register" if s.get("declared") else "<strong>not in the AI register (shadow AI)</strong>"
        return (f"<li><strong>{_E(s['system_id'])} · {_E(str(s['name']))}:</strong> {_E(s['eu_tier'])}. "
                f"Capabilities: {_E(caps)}. Hosting regions: {_E(regs)}. {reg}. Open rules: {_E(top)}.</li>")
    left = "".join(path_items(s) for s in focus[:5])
    ev_rows = []
    for s in focus[:5]:
        n = len(s.get("locators", []))
        ev_rows.append(f"<li><strong>{_E(s['system_id'])}</strong>: {n} code locator(s)"
                       f"{' · ' + _E(s['locators'][0]) if n else ' · no code found (documents only)'}; "
                       f"declared in docs: {'yes' if s.get('declared') else 'no'}, detected in code: "
                       f"{'yes' if s.get('detected_in_code') else 'no'}.</li>")
    return f"""
<div class="callout-card">
    <div style="font-size:8pt; font-weight:700; color:#0D1322; margin-bottom:6px; text-transform:uppercase;">Classification Record</div>
    <div class="callout-grid">
        <div class="callout-col">
            <strong style="color:#161F34;">Decision path &amp; trigger rules:</strong>
            <ul style="margin:4px 0 0 14px; padding:0; color:#2F4B68; font-size:7.2pt; line-height:1.4;">{left}</ul>
        </div>
        <div class="callout-col">
            <strong style="color:#161F34;">Evidence &amp; provenance:</strong>
            <ul style="margin:4px 0 0 14px; padding:0; color:#2F4B68; font-size:7.2pt; line-height:1.4;">{''.join(ev_rows)}</ul>
        </div>
    </div>
</div>
"""


# ------------------------------------------------------------------ section 3
def sec3(report: dict, systems: list[dict], findings: list[dict]) -> str:
    cols = systems[:7]
    ref = {r.get("rule_id"): r.get("reference") for r in report.get("compliance_matrix", [])}
    rules: dict[str, list[dict]] = {}
    for f in findings:
        rules.setdefault(f.get("primary_rule") or "UNMAPPED", []).append(f)
    head = "".join(f'<th style="background:#006DDD;">{_E(s["system_id"])}<br><span style="font-weight:normal;">{_E(str(s["name"])[:18])}</span></th>' for s in cols)
    body, n_pass_rules = "", 0
    for rule, fs in sorted(rules.items()):
        cells, any_cell = "", False
        for s in cols:
            mine = [f for f in fs if s["system_id"] in finding_systems(f, systems)]
            if mine:
                worst = min(mine, key=lambda f: STATUS_RANK.get(f.get("status"), 9))
                lab, cls = STATUS_CELL.get(worst.get("status"), ("?", "badge-na"))
                cells += f'<td>{_badge(lab, cls)}<br><span style="font-size:6pt;color:#40668D;">{_E(str(worst.get("check_id") or ""))}</span></td>'
                any_cell = True
            else:
                cells += f'<td>{_badge("N/A", "badge-na")}</td>'
        co = [f for f in fs if not finding_systems(f, systems)]
        co_lab = ""
        if co:
            worst = min(co, key=lambda f: STATUS_RANK.get(f.get("status"), 9))
            lab, cls = STATUS_CELL.get(worst.get("status"), ("?", "badge-na"))
            co_lab = f'<td>{_badge(lab, cls)}<br><span style="font-size:6pt;color:#40668D;">{_E(str(worst.get("check_id") or ""))}</span></td>'
        elif any_cell or fs:
            co_lab = f'<td>{_badge("—", "badge-na")}</td>'
        if all(f.get("status") == "PASS" for f in fs):
            n_pass_rules += 1
        label = ref.get(rule) or rule
        body += f'<tr><td style="text-align:left;"><strong>{_E(str(label))}</strong></td>{cells}{co_lab}</tr>'
    legend = " ".join(_badge(l, c) for l, c in (("Pass", "badge-pass"), ("Suspected", "badge-partial"), ("Gap", "badge-gap"), ("N/A", "badge-na")))
    # company-level controls: findings that map to no system
    ctrl = ""
    for f in sorted([f for f in findings if not finding_systems(f, systems)], key=lambda f: STATUS_RANK.get(f.get("status"), 9)):
        lab, cls = STATUS_CELL.get(f.get("status"), ("?", "badge-na"))
        h = next((str(e.get("sha256_hash", ""))[:12] for e in f.get("evidence", []) if e.get("sha256_hash")), "—")
        ctrl += (f'<tr><td><strong>{_E(str(f.get("title"))[:70])}</strong></td><td>{_E(str(f.get("primary_rule")))}</td>'
                 f'<td>{_badge(lab, cls)}</td><td><code>{"sha256:" + h if h != "—" else "—"}</code></td></tr>')
    ctrl_html = (f"""
<h4 style="font-size:8pt; margin-top:10px; margin-bottom:4px; text-transform:uppercase;">Company-Level Governance Controls</h4>
<table class="data-table"><thead><tr><th style="width:38%;">Control</th><th style="width:24%;">Rule</th><th style="width:14%;">Status</th><th style="width:24%;">Evidence hash</th></tr></thead>
<tbody>{ctrl}</tbody></table>""" if ctrl else "")
    return f"""
<h2>Section 3: Statutory Compliance Matrix</h2>
<p style="color:#2F4B68; font-size:7.5pt; margin-bottom:8px;">
Requirement areas by system for {_E(str(report.get('company_name', '')))}. A system cell shows the worst verdict among checks whose evidence touches that system.
The last column holds company-level verdicts with no single system. {n_pass_rules} of {len(rules)} assessed requirement areas pass. {legend}
</p>
<table class="data-table" style="text-align:center;">
<thead><tr><th style="width:24%; text-align:left; background:#2F4B68;">Requirement area</th>{head}<th style="background:#2F4B68;">Company-level</th></tr></thead>
<tbody>{body}</tbody></table>
{ctrl_html}
"""


# ------------------------------------------------------------------ section 4 extras
def sec4_extra(report: dict) -> str:
    def rows(items):
        out = ""
        for f in items:
            sev = _sev(f) or "INFO"
            reason = f.get("quarantine_reason") or f.get("human_review_reason") or ""
            out += (f'<tr><td><strong>{_E(str(f.get("finding_id")))}</strong></td><td>{_badge(sev, "badge-" + sev.lower())}</td>'
                    f'<td><strong>{_E(str(f.get("title")))}</strong><br><span style="color:#40668D;font-size:6.6pt;">{_E(str(f.get("summary", ""))[:170])}</span></td>'
                    f'<td>{_E(str(f.get("primary_rule")))}</td><td>{_E(str(f.get("owner") or ""))}</td></tr>')
        return out
    parts = ""
    gaps = report.get("suspected_gaps", [])
    quar = report.get("quarantined_for_human_review", [])
    hdr = '<thead><tr><th style="width:18%;">ID</th><th style="width:10%;">Severity</th><th style="width:44%;">Finding</th><th style="width:16%;">Rule</th><th style="width:12%;">Owner</th></tr></thead>'
    if gaps:
        parts += f"""<h4 style="font-size:8pt; margin-top:10px; margin-bottom:4px; text-transform:uppercase;">Suspected gaps (closed-world: no explicit evidence of compliance)</h4>
<table class="data-table">{hdr}<tbody>{rows(gaps)}</tbody></table>"""
    if quar:
        parts += f"""<h4 style="font-size:8pt; margin-top:10px; margin-bottom:4px; text-transform:uppercase;">Quarantined for human review (kept, never dropped)</h4>
<table class="data-table">{hdr}<tbody>{rows(quar)}</tbody></table>"""
    return parts


# ------------------------------------------------------------------ section 5
def _checks():
    try:
        from src.regulatory_rag.tier_a_rules import CHECKS
        return {c.check_id: c for c in CHECKS}
    except Exception:
        return {}


def sec5(report: dict, findings: list[dict]) -> str:
    chk = _checks()
    rows = ""
    for f in sorted(findings, key=lambda f: (STATUS_RANK.get(f.get("status"), 9), str(f.get("check_id")))):
        cid = f.get("check_id") or next((k for k in chk if str(f.get("finding_id", "")).endswith(k)), "")
        c = chk.get(cid)
        agent = getattr(c, "agent", "") if c else ""
        q = getattr(c, "question", "") if c else str(f.get("title", ""))
        lab, cls = STATUS_CELL.get(f.get("status"), ("?", "badge-na"))
        conf = f.get("confidence", f.get("confidence_score"))
        rows += (f'<tr><td><code>{_E(cid)}</code></td><td>{_E(agent)}</td><td>{_E(q[:95])}</td>'
                 f'<td>{_E(str(f.get("primary_rule")))}</td><td>{int(float(conf) * 100) if conf is not None else "—"}%</td><td>{_badge(lab, cls)}</td></tr>')
    ev = report.get("eval_results", {}) or {}
    fair = report.get("fairness_metrics", {}) or {}
    hist = ev.get("history", {}) or {}
    guards = "".join(f"<li>{_E(g)}</li>" for g in ev.get("guardrails", []))
    fstatus = fair.get("status", "UNKNOWN")
    fcls = {"DOCUMENTED": "badge-pass", "COMPUTED": "badge-pass", "FLAGGED": "badge-gap", "SUSPECTED_GAP": "badge-gap", "NOT_APPLICABLE": "badge-na"}.get(fstatus, "badge-partial")
    prot = ", ".join(fair.get("protected_attributes_in_code", [])) or "none found in code"
    metrics = fair.get("metrics") or []
    fair_bars = ""
    if metrics:
        for m in metrics:
            if m.get("ratio_vs_top") is None:
                fair_bars += f'<tr><td>{_E(m["attribute"])}: {_E(str(m["group"]))}</td><td>n={m["n"]}</td><td colspan="2">not testable: {_E(str(m.get("note", "")))}</td></tr>'
                continue
            r = m["ratio_vs_top"]
            col = "#EF4444" if m.get("flag") else "#10B981"
            fair_bars += (f'<tr><td>{_E(m["attribute"])}: {_E(str(m["group"]))}</td><td>n={m["n"]}</td>'
                          f'<td style="width:40%;"><div style="background:#CCE9FF;height:8px;position:relative;"><div style="background:{col};height:8px;width:{min(100, int(r * 100))}%;"></div>'
                          f'<div style="position:absolute;left:80%;top:-2px;height:12px;border-left:1px solid #0D1322;"></div></div></td>'
                          f'<td>{r:.2f}× {"BELOW 0.80" if m.get("flag") else "ok"}</td></tr>')
        fair_bars = (f'<h4 style="font-size:8pt; margin-top:10px; margin-bottom:4px; text-transform:uppercase;">Selection-rate ratios (source: {_E(str(fair.get("metrics_source", "")))})</h4>'
                     f'<table class="data-table"><thead><tr><th>Group</th><th>Sample</th><th>Ratio vs highest-rate group (tick = 0.80)</th><th>Result</th></tr></thead><tbody>{fair_bars}</tbody></table>')
    return f"""
<h2>Section 5: Automated Control Verification &amp; Fairness Screen</h2>
<p style="color:#2F4B68; font-size:7.5pt; margin-bottom:8px;">
Checks run by the micro-agents against code, documents and dependency manifests. {ev.get('checks_resolved', len(findings))} of {ev.get('checks_total', len(findings))}
mandatory checks resolved ({ev.get('resolution_pct', 100)}%); mean confidence {ev.get('mean_confidence', 0)}. No live endpoint or adversarial (red-team) testing was performed in this run.
</p>
<table class="data-table">
<thead><tr><th style="width:12%;">Check</th><th style="width:14%;">Agent</th><th style="width:38%;">Question</th><th style="width:16%;">Rule</th><th style="width:8%;">Conf.</th><th style="width:12%;">Result</th></tr></thead>
<tbody>{rows}</tbody></table>
<h4 style="font-size:8pt; margin-top:10px; margin-bottom:4px; text-transform:uppercase;">Fairness screen (deterministic)</h4>
<table class="data-table"><tbody>
<tr><td style="width:30%;"><strong>Status</strong></td><td>{_badge(fstatus.replace('_', ' '), fcls)}</td></tr>
<tr><td><strong>Protected attributes referenced in code</strong></td><td>{_E(prot)}</td></tr>
<tr><td><strong>Bias testing documented</strong></td><td>{'yes' if fair.get('bias_testing_documented') else 'no'}</td></tr>
<tr><td><strong>Automated decisions present</strong></td><td>{'yes' if fair.get('automated_decisions') else 'no'}</td></tr>
<tr><td><strong>Note</strong></td><td>{_E(str(fair.get('note', '')))}</td></tr>
</tbody></table>
{fair_bars}
<h4 style="font-size:8pt; margin-top:10px; margin-bottom:4px; text-transform:uppercase;">Guardrail gates &amp; history</h4>
<ul style="margin:0 0 0 14px; padding:0; font-size:6.8pt; color:#2F4B68; line-height:1.4;">{guards}
<li>Longitudinal history: {hist.get('NEW', 0)} new, {hist.get('RECURRING', 0)} recurring, {hist.get('RESOLVED', 0)} resolved since last run.</li></ul>
"""


# ------------------------------------------------------------------ section 6
PHASES = (("Immediate", "Phase 1: Immediate", "#DC2626"), ("Next quarter", "Phase 2: Next quarter", None), ("Backlog", "Phase 3: Backlog", None))


def sec6(report: dict) -> str:
    road = report.get("roadmap", []) or []
    cols = ""
    for key, title, color in PHASES:
        items = [r for r in road if r.get("phase") == key]
        lis = "".join(
            f'<li><strong>{_E(str(r.get("finding_id", "")).split("-", 1)[-1])}</strong> · {_E(str(r.get("action", ""))[:110])}'
            f' <span style="color:#40668D;">({_E(str(r.get("owner") or ""))}, due {_E(str(r.get("due_date") or "n/a"))}, ~{_E(str(r.get("effort_days") or "?"))}d)</span></li>'
            for r in items[:6]) or "<li>No open items in this phase.</li>"
        more = f'<li style="color:#40668D;">+{len(items) - 6} more</li>' if len(items) > 6 else ""
        style = f' style="color:{color};"' if color else ""
        cols += (f'<div class="roadmap-col" style="width:33%;"><div class="roadmap-header"{style}>{title}<br>'
                 f'<span style="font-size:6pt; font-weight:normal;">{len(items)} item(s)</span></div>'
                 f'<ul style="margin:0 0 0 12px; padding:0; font-size:6.8pt; color:#2F4B68; line-height:1.4;">{lis}{more}</ul></div>')
    cov = report.get("input_coverage", {}) or {}
    code, docs = cov.get("code", {}), cov.get("documents", {})
    deps, sysc = cov.get("dependencies", {}), cov.get("systems", {})
    kinds = cov.get("kinds_present", {})

    def st(ok, yes="CONNECTED", no="MISSING"):
        return _badge(yes if ok else no, "badge-pass" if ok else "badge-gap")
    rows = [
        ("Code (GitHub)", code.get("origin", "n/a"), st(kinds.get("code")),
         f"{code.get('python_files', 0)} code file(s), {code.get('ast_slices', 0)} AST slice(s), {code.get('capability_cards', 0)} capability card(s); commit {str(code.get('commit_sha') or 'n/a')[:18]}"),
        ("Languages parsed", ", ".join(f"{k} ({v})" for k, v in sorted((cov.get("languages", {}).get("parsed") or {}).items())) or "python", _badge("PARSED", "badge-pass"), "tree-sitter parsing; code is never executed."),
        ("Policies &amp; DPAs (Confluence)", docs.get("origin", "n/a"), st(kinds.get("policy_documents")),
         f"{docs.get('documents', 0)} document(s), {docs.get('sections', 0)} section(s), {docs.get('assertions', 0)} compliance assertion(s)"),
        ("Dependency manifests", "requirements / model manifests", st(kinds.get("dependency_manifest")),
         f"{deps.get('packages', 0)} package(s), {deps.get('model_licences', 0)} model licence record(s)"),
        *([("Languages NOT scanned", ", ".join(f"{k} ({v})" for k, v in sorted(cov["languages"]["unscanned"].items())), _badge("GAP", "badge-gap"),
            "Behaviour in these files is unverified (closed-world).")] if (cov.get("languages", {}).get("unscanned")) else []),
        *[(f"Remote docs: {d.get('source')}", "remote API", _badge("ERROR" if d.get("errors") else "CONNECTED", "badge-gap" if d.get("errors") else "badge-pass"),
           (d.get("errors") or [f"{d.get('documents', 0)} document(s)"])[0]) for d in (cov.get("doc_sources") or [])],
        ("Data assets", f"{(cov.get('data') or {}).get('assets', 0)} schema(s)/card(s)", st(bool((cov.get('data') or {}).get('assets')), "SCANNED", "NOT CONNECTED"),
         (f"{(cov.get('data') or {}).get('personal_columns', 0)} classified column(s); values never stored" if (cov.get('data') or {}).get('assets') else "No datasets, schemas or manifests supplied: data governance checks were not run.")),
        ("DPA / DPIA documents", "documents", st(kinds.get("dpa_dpia_documents")), "Zero-data-retention, DPIA and Annex IV evidence is searched here."),
        ("AI system inventory", "code + register", _badge(f"{sysc.get('detected_in_code', 0)}/{sysc.get('inventory', 0)} in code", "badge-partial"),
         f"{sysc.get('declared_in_docs', 0)} of {sysc.get('inventory', 0)} systems declared in documents."),
        ("Live system access / red-team", "not connected", _badge("MISSING", "badge-gap"), "No endpoint testing, incident tickets or inference logs were supplied."),
    ]
    body = "".join(f"<tr><td><strong>{a}</strong></td><td><code>{_E(str(b))}</code></td><td>{c}</td><td>{_E(d) if not d.startswith('Zero') else d}</td></tr>" for a, b, c, d in rows)
    return f"""
<h2>Section 6: Remediation Roadmap, Coverage &amp; Sign-Off</h2>
<p style="color:#2F4B68; font-size:7.5pt; margin-bottom:8px;">
Open items for {_E(str(report.get('company_name', '')))} ordered by severity and statutory deadline. Scope: {_E(str(report.get('scope', '')))}.
</p>
<div class="roadmap-grid">{cols}</div>
<h4 style="font-size:8pt; margin-top:8px; margin-bottom:4px; text-transform:uppercase;">Input Coverage &amp; Method Limitations ({report.get('input_coverage_pct', 0)}%)</h4>
<table class="data-table">
<thead><tr><th style="width:20%;">Input</th><th style="width:30%;">Source</th><th style="width:14%;">Status</th><th style="width:36%;">Notes</th></tr></thead>
<tbody>{body}</tbody></table>
<p style="font-size:6.8pt; color:#2F4B68; margin-top:4px;">Rules judged against: {_E(str(report.get('rule_library_version', '')))}. Evidence hierarchy: code and config &gt; documents (claims).
Where a claim and the code disagree it is flagged as drift. Findings are technical observations, not legal advice; classification of borderline systems needs counsel.</p>
"""
