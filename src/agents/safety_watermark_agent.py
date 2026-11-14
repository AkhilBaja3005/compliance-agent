from __future__ import annotations

from datetime import date

from .tracing import traced
from .base import (ART50_APPLIES, ART50_LEGACY_DEADLINE, MicroAgent, Verdict, ev_card, ev_slice, generation_entries,
                   no_code_verdict)


class SafetyWatermarkAgent(MicroAgent):
    name = "safety_watermark"

    @traced("safety_watermark_agent.evaluate")
    def evaluate(self, check, ctx) -> Verdict:
        ix = ctx.index
        if check.check_id == "BIO-01":
            return self._bio01(ix)
        if check.check_id == "SAFE-04":
            return self._safe04(ix)
        if check.check_id == "SAFE-03":
            return self._safe03(ix)
        if not ix.has_code:
            return no_code_verdict(f"{check.check_id}: no code to inspect")
        gens = generation_entries(ix)
        if not gens:
            return Verdict("SUSPECTED_GAP", 0.6, "Generation endpoints could not be located",
                           "No generation entry point was identified; output controls are unproven.")
        if check.check_id == "SAFE-01":
            risky_cards = [c for c in ix.cards if "unmoderated_hate_speech_risk" in c.capability_tags]
            bad = [s for s in gens if not s.has_moderation_hook]
            if risky_cards or bad:
                unfiltered = any("unfiltered_prompt" in c.capability_tags for c in risky_cards)
                ev = [ev_card(c) for c in risky_cards[:2]] + [ev_slice(s) for s in bad[:2]]
                return Verdict(
                    "CONFIRMED_VIOLATION", 0.93 if unfiltered else 0.86,
                    "Unmoderated hate-speech / harmful generation risk",
                    ("A system prompt instructs the model to be unfiltered / never refuse, " if unfiltered else
                     "A generation endpoint has no moderation or safety-filter hook ")
                    + "and no moderation control exists on the generation path.",
                    ev, risk_tier="PROHIBITED" if unfiltered else None)
            return Verdict("PASS", 0.9, "Moderation control present on generation endpoints",
                           "All generation entry points invoke a moderation / safety filter.", [ev_slice(s) for s in gens[:4]])
        # SAFE-02 Art. 50 watermark
        bad = [s for s in gens if not s.has_watermark_hook]
        if bad:
            today = date.today()
            if today < ART50_APPLIES:
                timing = f"Art. 50 applies from {ART50_APPLIES:%d %b %Y}."
            elif today <= ART50_LEGACY_DEADLINE:
                timing = f"Art. 50 applies; legacy systems have until {ART50_LEGACY_DEADLINE:%d %b %Y} (transition period)."
            else:
                timing = f"Art. 50 applies; the {ART50_LEGACY_DEADLINE:%d %b %Y} legacy deadline has passed."
            return Verdict("CONFIRMED_VIOLATION", 0.87, "No machine-readable AI-generated marking on outputs",
                           f"{len(bad)} generation entry point(s) emit content with no watermark / C2PA / ai_generated marking. {timing}",
                           [ev_slice(s) for s in bad[:4]])
        return Verdict("PASS", 0.9, "Machine-readable AI-generated marking present",
                       "All generation entry points apply a watermark / C2PA / AI-generated disclosure.", [ev_slice(s) for s in gens[:4]])

    @staticmethod
    def _bio01(ix) -> Verdict:
        import re
        from src.edge_extractors.code_scanner import BIOMETRIC_RE
        bio = [c for c in ix.cards if "biometric_identification" in c.capability_tags]
        untargeted = [c for c in ix.cards if "untargeted_acquisition" in c.capability_tags]
        doc_bio = [d for d in ix.chunks if BIOMETRIC_RE.search(d.text)]
        if bio and untargeted:
            order = ("source-service", "config", "catalog", "ingestion", "identity-index", "search", "features")
            rank = lambda c: next((i for i, k in enumerate(order) if k in c.exact_locator), 99)
            cs = {c.exact_locator: c for c in sorted(untargeted, key=rank)[:3] + sorted(bio, key=rank)[:3]}
            ev = [ev_card(c) for c in cs.values()]
            return Verdict(
                "CONFIRMED_VIOLATION", 0.95, "Untargeted internet/CCTV acquisition builds a facial-recognition database",
                f"{len(untargeted)} source file(s) configure untargeted bulk acquisition (public-web / CCTV discovery, public accessibility "
                f"treated as sufficient, recurring expansion) and {len(bio)} file(s) implement facial/biometric identification or indexing. "
                "Taken together (source admission on public accessibility alone, ingestion that does not filter to enrolled subjects, features added to the searchable index, recurring expansion), "
                "this models the Art. 5(1)(e) prohibition on creating or expanding facial-recognition databases through untargeted scraping of facial images from the internet or CCTV. "
                "Safeguards such as logging, accuracy or human approval of searches do not cure it. Modeled practice: confirm actual acquisition methods and deployment facts before a real-world legal finding.",
                ev, risk_tier="PROHIBITED")
        if doc_bio and not bio and not ix.has_code:
            return Verdict("SUSPECTED_GAP", 0.6, "Facial-recognition functionality described but acquisition method is unproven",
                           "Documents describe facial/biometric identification and no code was available to prove the acquisition scope is limited to enrolled subjects.")
        if bio:
            return Verdict("SUSPECTED_GAP", 0.65, "Facial/biometric identification present; no evidence limiting acquisition to enrolled subjects",
                           "Facial/biometric identification is implemented but no explicit restriction to specifically enrolled subjects was found (closed-world).",
                           [ev_card(c) for c in bio[:3]])
        return Verdict("PASS", 0.8, "No facial-recognition database acquisition detected",
                       "No facial/biometric identification functionality or untargeted bulk image acquisition was found in code or documents.",
                       scan_basis=True)

    @staticmethod
    def _safe04(ix) -> Verdict:
        cards = [c for c in ix.cards if "safety_control_bypass" in c.capability_tags]
        if not cards:
            return Verdict("PASS", 0.8, "No safety-control bypass found",
                           "No disabled face/likeness/moderation filter or explicit bypass was found in code or configuration.", scan_basis=True)
        deep = [c for c in cards if "deepfake_risk" in c.capability_tags]
        intimate = any("intimate_imagery_risk" in c.capability_tags for c in cards)
        pick = (deep or cards)[:4]
        return Verdict(
            "CONFIRMED_VIOLATION", 0.9 if deep else 0.8, "Safety filter disabled or bypassed on some tier",
            f"{len(cards)} location(s) disable or bypass a face/likeness/content/safety filter"
            + (" on a path that handles faces, likeness or voice cloning, which can enable non-consensual deepfakes (Art. 5 / Art. 50(4))" if deep else "")
            + ". A control that is off on any tier is not enforced.",
            [ev_card(c) for c in pick], risk_tier="PROHIBITED" if intimate else "HIGH_RISK")

    @staticmethod
    def _safe03(ix) -> Verdict:
        import re
        chat_re = re.compile(r"\b(chat|conversation\w*|assistant|concierge|copilot|support|ideation|bot|message)\b", re.I)
        chats = [s for s in generation_entries(ix) if s.is_route and chat_re.search(re.sub(r"[_/\-]+", " ", s.function_name + " " + (s.code_snippet.splitlines() or [""])[0]))]
        if not ix.has_code:
            return no_code_verdict("SAFE-03: no code to inspect")
        if not chats:
            return Verdict("PASS", 0.75, "No conversational AI endpoints found", "No generation route looks like a chat / assistant interaction.", scan_basis=True)
        bad = [s for s in chats if s.disclosure_denied or not s.has_ai_disclosure]
        if bad:
            return Verdict("CONFIRMED_VIOLATION", 0.88, "Conversational endpoint does not disclose that users are talking to an AI",
                           f"{len(bad)} of {len(chats)} conversational endpoint(s) give no AI-interaction notice (no disclosure header/text, or `ai_disclosed` is false). "
                           "Art. 50(1) requires people to be informed they interact with an AI system.", [ev_slice(s) for s in bad[:4]])
        return Verdict("PASS", 0.85, "All conversational endpoints disclose AI interaction", f"{len(chats)} conversational endpoint(s) disclose they are AI.", [ev_slice(s) for s in chats[:3]])
