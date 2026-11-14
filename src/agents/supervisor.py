"""Cyclic Supervisor (LangGraph) dispatching atomic single-question tasks to 6 micro-agents."""
from __future__ import annotations

import uuid
from typing import TypedDict

from langgraph.graph import END, StateGraph

from src.regulatory_rag import MandatoryCheck
from src.schemas.findings import ComplianceFinding


from .base import AuditContext, MicroAgent
from .tracing import current_trace_id, traced
from .code_doc_drift_agent import CodeDocDriftAgent
from .dpa_provenance_agent import DPAProvenanceAgent
from .hitl_oversight_agent import HITLOversightAgent
from .oss_license_agent import OSSLicenseAgent
from .pii_flow_agent import PIIFlowAgent
from .safety_watermark_agent import SafetyWatermarkAgent

AGENTS: dict[str, MicroAgent] = {a.name: a for a in (
    PIIFlowAgent(), HITLOversightAgent(), SafetyWatermarkAgent(), OSSLicenseAgent(), DPAProvenanceAgent(), CodeDocDriftAgent())}
MAX_ATTEMPTS = 2


class AuditState(TypedDict):
    pending: list[str]
    findings: dict[str, dict]  # JSON-serialisable so any LangGraph checkpointer (Mongo/Memory) can persist it
    trace: list[str]
    current: str | None
    attempts: dict[str, int]
    iteration: int


class SupervisorAgent:
    def __init__(self, ctx: AuditContext, checklist: list[MandatoryCheck], checkpointer=None):
        self.ctx = ctx
        self.checkpointer = checkpointer
        self.checkpoint_id: str | None = None
        self.trace_id: str | None = None
        self.checks = {c.check_id: c for c in checklist}
        self.order = [c.check_id for c in checklist]

    # ---- graph nodes
    def supervisor_node(self, state: AuditState) -> dict:
        trace = list(state["trace"])
        pending = list(state["pending"])
        findings = state["findings"]
        # loop until 100% of mandatory checks are resolved
        missing = [cid for cid in self.order if cid not in findings and cid not in pending]
        pending += missing
        if not pending:
            resolved = sum(1 for c in self.order if c in findings)
            trace.append(f"supervisor: {resolved}/{len(self.order)} mandatory checks resolved -> finish")
            return {"pending": [], "current": None, "trace": trace, "iteration": state["iteration"] + 1}
        cid = pending.pop(0)
        chk = self.checks[cid]
        trace.append(f"supervisor: dispatch {cid} ({chk.regulatory_reference}) -> {chk.agent}_agent | Q: {chk.question}")
        return {"pending": pending, "current": cid, "trace": trace, "iteration": state["iteration"] + 1}

    def route(self, state: AuditState) -> str:
        cid = state["current"]
        return END if cid is None else self.checks[cid].agent

    def agent_node(self, agent_name: str):
        agent = AGENTS[agent_name]

        def node(state: AuditState) -> dict:
            cid = state["current"]
            chk = self.checks[cid]
            trace, findings = list(state["trace"]), dict(state["findings"])
            attempts, pending = dict(state["attempts"]), list(state["pending"])
            try:
                f = agent.run(chk, self.ctx)
                findings[cid] = f.model_dump(mode="json")
                trace.append(f"{agent_name}_agent: {cid} -> {f.status} (confidence {f.confidence_score:.2f}, {len(f.evidence)} evidence)")
            except Exception as exc:
                attempts[cid] = attempts.get(cid, 0) + 1
                if attempts[cid] < MAX_ATTEMPTS:
                    pending.insert(0, cid)
                    trace.append(f"{agent_name}_agent: {cid} errored ({exc!r}); supervisor will retry")
                else:
                    findings[cid] = ComplianceFinding(
                        finding_id=f"{self.ctx.index.tenant_id}-{cid}", tenant_id=self.ctx.index.tenant_id,
                        jurisdiction=chk.jurisdiction, regulatory_reference=chk.regulatory_reference,
                        risk_tier=chk.risk_tier, status="SUSPECTED_GAP", confidence_score=0.3,
                        title=f"{cid}: check could not be completed",
                        summary=f"Agent error ({exc!r}); closed-world rule marks the check SUSPECTED_GAP.", check_id=cid).model_dump(mode="json")
                    trace.append(f"{agent_name}_agent: {cid} failed twice -> SUSPECTED_GAP (closed-world)")
            return {"findings": findings, "trace": trace, "attempts": attempts, "pending": pending}

        return node

    def build(self):
        g = StateGraph(AuditState)
        g.add_node("supervisor", self.supervisor_node)
        for name in AGENTS:
            g.add_node(name, self.agent_node(name))
            g.add_edge(name, "supervisor")  # cycle back to the supervisor
        g.add_conditional_edges("supervisor", self.route, {**{n: n for n in AGENTS}, END: END})
        g.set_entry_point("supervisor")
        return g.compile(checkpointer=self.checkpointer)

    @traced("SupervisorAgent.run", span_type="CHAIN")
    def run(self, thread_id: str | None = None) -> tuple[list[ComplianceFinding], list[str]]:
        graph = self.build()
        init: AuditState = {"pending": list(self.order), "findings": {}, "trace": [], "current": None, "attempts": {}, "iteration": 0}
        config = {"recursion_limit": 6 * len(self.order) + 50,
                  "configurable": {"thread_id": thread_id or f"{self.ctx.index.tenant_id}-{uuid.uuid4().hex[:12]}"}}
        out = graph.invoke(init, config)
        self.trace_id = current_trace_id()
        if self.checkpointer is not None:
            try:  # id of the final LangGraph checkpoint persisted for this run
                self.checkpoint_id = graph.get_state(config).config["configurable"]["checkpoint_id"]
            except Exception:
                self.checkpoint_id = None
        findings = [ComplianceFinding.model_validate(out["findings"][c]) for c in self.order]
        return findings, out["trace"]
