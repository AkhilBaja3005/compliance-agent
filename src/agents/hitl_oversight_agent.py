from __future__ import annotations

from .tracing import traced
from .base import MicroAgent, Verdict, decision_candidates, ev_card, ev_slice, no_code_verdict


def oversight_verdict(s, explicit: bool) -> Verdict:
    """Per-decision-path result shared with regression enforcement."""
    if s.has_hitl_gate:
        return Verdict("PASS", 0.9, "Human approval gate present on decision path",
                       "The decision entry point has a human review/approval control.", [ev_slice(s)])
    if explicit:
        return Verdict("CONFIRMED_VIOLATION", 0.9, "Automated decision released without human approval gate",
                       "The decision entry point has no detected human approval/queue in its call path.", [ev_slice(s)])
    return Verdict("SUSPECTED_GAP", 0.6, "No human oversight evidence in high-risk sector",
                   "Human oversight could not be verified on this entry point.", [ev_slice(s)])


class HITLOversightAgent(MicroAgent):
    name = "hitl_oversight"

    @traced("hitl_oversight_agent.evaluate")
    def evaluate(self, check, ctx) -> Verdict:
        ix = ctx.index
        if not ix.has_code:
            return no_code_verdict(f"{check.check_id}: no code to inspect")
        cands, explicit = decision_candidates(ix)
        if not cands:
            return Verdict("SUSPECTED_GAP", 0.6, "Human-oversight gate could not be located",
                           "No decision entry point was identified, so the presence of a human approval gate is unproven.")
        bad = [s for s in cands if oversight_verdict(s, explicit).status != "PASS"]
        if not bad:
            return Verdict("PASS", 0.9, "Human approval gate present on decision path",
                           "Decision entry point(s) route output through a human review/approval step.", [ev_slice(s) for s in cands[:4]])
        ev = [ev_slice(s) for s in bad[:3]]
        ev += [ev_card(c) for c in ix.cards if "no_human_gate" in c.capability_tags][:1]
        if explicit:
            return Verdict("CONFIRMED_VIOLATION", 0.9, "Automated decision released without human approval gate",
                           f"{len(bad)} decision entry point(s) have no human-in-the-loop approval/queue in their call path.", ev)
        return Verdict("SUSPECTED_GAP", 0.6, "No human oversight evidence in high-risk sector",
                       "Entry points in a high-risk sector show no human approval step.", ev)
