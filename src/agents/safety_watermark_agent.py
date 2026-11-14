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
