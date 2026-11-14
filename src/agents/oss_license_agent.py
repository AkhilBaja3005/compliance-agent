from __future__ import annotations

from src.law_sync.linkup_scout import LinkupBase, LinkupCitation

from .base import MicroAgent, Verdict, ev_dep
from .tracing import traced


class LinkupLicenseVerifier(LinkupBase):
    """Live Linkup check of commercial-use terms for restrictive packages / weights (GPL-3.0, CC-BY-NC-4.0 ...)."""

    def verify(self, dep) -> LinkupCitation | None:
        what = "model weights" if dep.kind == "model_weights" else "software package"
        return self.ask(f"Does the {dep.license} licence permit commercial use of the {what} '{dep.name}'? "
                        f"Cite the licence terms on commercial use, distribution and copyleft or non-commercial restrictions.")


def _cite(ctx, deps) -> tuple[list, list[str]]:
    """Evidence pointers for `deps`, each annotated with its Linkup source when the verifier is live."""
    evs, urls = [], []
    verifier = getattr(ctx, "linkup", None)
    for d in deps:
        ev = ev_dep(d)
        cit = verifier.verify(d) if verifier is not None and verifier.enabled else None
        if cit and cit.first_url:
            ev = ev.model_copy(update={"source_url": cit.first_url, "linkup_snippet": cit.best_snippet})
            urls += [u for u in cit.urls[:3] if u not in urls]
        evs.append(ev)
    return evs, urls


class OSSLicenseAgent(MicroAgent):
    name = "oss_license"

    @traced("oss_license_agent.evaluate")
    def evaluate(self, check, ctx) -> Verdict:
        ix = ctx.index
        if check.check_id == "OSS-01":
            pk = [d for d in ix.dependencies if d.kind == "package"]
            if not pk:
                return Verdict("SUSPECTED_GAP", 0.6, "No dependency manifest found",
                               "No requirements file was found; dependency licences are unverified.")
            strong = [d for d in pk if d.license_class in {"STRONG_COPYLEFT", "NON_COMMERCIAL"}]
            weak = [d for d in pk if d.license_class == "WEAK_COPYLEFT"]
            unknown = [d for d in pk if d.license_class == "UNKNOWN"]
            if strong and ix.commercial:
                evs, urls = _cite(ctx, strong[:4])
                return Verdict("CONFIRMED_VIOLATION", 0.92, "Copyleft dependency in commercial product",
                               "Dependencies under strong-copyleft terms: " + ", ".join(f"{d.name} ({d.license})" for d in strong) + ".",
                               evs, citation_urls=urls)
            if weak or unknown:
                ev = [ev_dep(d) for d in (weak + unknown)[:4]]
                if weak:
                    return Verdict("SUSPECTED_GAP", 0.7, "Weak-copyleft dependency needs review",
                                   "Weak-copyleft dependencies: " + ", ".join(d.name for d in weak) + ".", ev)
                return Verdict("PASS", 0.8, "No copyleft dependencies found",
                               f"No GPL/AGPL licences detected; {len(unknown)} package(s) have unrecorded licences.", ev)
            return Verdict("PASS", 0.9, "All dependencies permissively licensed",
                           "All parsed dependencies carry permissive licences.", [ev_dep(d) for d in pk[:3]])
        # OSS-02 model weights
        mw = [d for d in ix.dependencies if d.kind == "model_weights"]
        nc = [d for d in mw if d.license_class in {"NON_COMMERCIAL", "STRONG_COPYLEFT"}]
        if nc and ix.commercial:
            evs, urls = _cite(ctx, nc[:3])
            return Verdict("CONFIRMED_VIOLATION", 0.92, "Non-commercial model licence used commercially",
                           "Model/weights licence restricts commercial use: " + ", ".join(d.license for d in nc) + ".",
                           evs, citation_urls=urls)
        if mw:
            return Verdict("PASS", 0.88, "Model licence permits commercial use", "Declared model licences: "
                           + ", ".join(d.license for d in mw) + ".", [ev_dep(d) for d in mw[:3]])
        if ix.uses_local_model:
            return Verdict("SUSPECTED_GAP", 0.6, "Local model weights without declared licence",
                           "Code loads local model weights but no licence declaration was found.")
        return Verdict("PASS", 0.85, "No local model weights in use",
                       "No local model weights are loaded; only hosted APIs are used.", scan_basis=True)
