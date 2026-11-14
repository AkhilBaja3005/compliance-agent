"""Gate 2: DLP (secrets / PII redaction) and tenant-isolation verification."""
from __future__ import annotations

import re

from src.schemas.findings import ComplianceFinding, EvidencePointer

from .common import GateContext, quarantine

GATE = "gate2_dlp_tenant"
PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(ghp|gho|xox[bp])[_-][A-Za-z0-9\-]{16,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b(\s*[:=]\s*)([\"']?)[^\s\"',;]{6,}\3"), r"\1\2[REDACTED_SECRET]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b"), "[REDACTED_NI_NUMBER]"),
]
TENANT_RE = re.compile(r"\bcompany_[a-z0-9]+_[a-z0-9_]+\b")


def redact(text: str | None, own_tenant: str, other_tenants: set[str]) -> tuple[str | None, bool, bool]:
    """Return (clean_text, redacted_something, leaked_other_tenant)."""
    if not text:
        return text, False, False
    new, changed, leaked = text, False, False
    for rx, repl in PATTERNS:
        new2 = rx.sub(repl, new)
        changed |= new2 != new
        new = new2

    def _tenant(m):
        nonlocal leaked
        if m.group(0) != own_tenant:
            leaked = True
            return "[REDACTED_TENANT]"
        return m.group(0)

    new2 = TENANT_RE.sub(_tenant, new)
    for t in other_tenants:
        if t != own_tenant and t in new2:
            new2 = new2.replace(t, "[REDACTED_TENANT]")
            leaked = True
    return new2, changed or new2 != text, leaked


def apply(findings: list[ComplianceFinding], ctx: GateContext) -> list[ComplianceFinding]:
    own = ctx.index.tenant_id
    out, red, quar = [], 0, 0
    for f in findings:
        upd, did, leak = {}, False, False
        for field in ("title", "summary", "code_vs_doc_drift", "quarantine_reason", "human_review_reason"):
            val = getattr(f, field)
            new, c, l = redact(val, own, ctx.known_tenants)
            if c:
                upd[field] = new
            did |= c
            leak |= l
        evs = []
        for e in f.evidence:
            snip, c, l = redact(e.snippet, own, ctx.known_tenants)
            did |= c
            leak |= l
            evs.append(e.model_copy(update={"snippet": snip}) if c else e)
        if did:
            red += 1
            upd["evidence"] = evs
        f2 = f.model_copy(update=upd) if upd else f
        if f.tenant_id != own:
            f2 = quarantine(f2, f"cross-tenant finding: tenant_id '{f.tenant_id}' != '{own}'", GATE)
            quar += 1
        elif leak:
            f2 = quarantine(f2, "reference to another tenant detected and redacted", GATE)
            quar += 1
        out.append(f2)
    ctx.trace.append(f"guardrail gate2_dlp_tenant: {red} finding(s) redacted, {quar} quarantined for tenant leakage")
    return out
