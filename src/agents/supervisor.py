"""Cyclic Supervisor (LangGraph) dispatching atomic single-question tasks to 6 micro-agents."""
from __future__ import annotations

import contextvars
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
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
    batch: list[str]  # checks dispatched in parallel in the current round
    attempts: dict[str, int]
    iteration: int


class SupervisorAgent:
    """Cyclic supervisor: each round dispatches every unresolved check to its micro-agent in parallel, gathers the results, and loops
    until 100% of the mandatory checks are resolved (a failed check is retried once, then becomes SUSPECTED_GAP)."""

    def __init__(self, ctx: AuditContext, checklist: list[MandatoryCheck], checkpointer=None, max_workers: int | None = None):
        self.ctx = ctx
        self.checkpointer = checkpointer
        self.checkpoint_id: str | None = None
        self.trace_id: str | None = None
        self.checks = {c.check_id: c for c in checklist}
        self.order = [c.check_id for c in checklist]
        self.max_workers = max_workers or int(os.getenv("GRAPHITE_AGENT_WORKERS", "6"))

    # ---- graph nodes
    def supervisor_node(self, state: AuditState) -> dict:
        trace = list(state["trace"])
        findings = state["findings"]
        pending = sorted({*state["pending"], *(cid for cid in self.order if cid not in findings)})  # deterministic, independent of agent timing
        pending = [c for c in pending if c not in findings]
        if not pending:
            resolved = sum(1 for c in self.order if c in findings)
            trace.append(f"supervisor: {resolved}/{len(self.order)} mandatory checks resolved -> finish")
            return {"pending": [], "batch": [], "trace": trace, "iteration": state["iteration"] + 1}
        for cid in pending:
            chk = self.checks[cid]
            trace.append(f"supervisor: dispatch {cid} ({chk.regulatory_reference}) -> {chk.agent}_agent | Q: {chk.question}")
        return {"pending": [], "batch": pending, "trace": trace, "iteration": state["iteration"] + 1}

    def route(self, state: AuditState) -> str:
        return END if not state["batch"] else "run_checks"

    def _run_one(self, cid: str) -> tuple[str, dict | None, str | None]:
        chk = self.checks[cid]
        try:
            f = AGENTS[chk.agent].run(chk, self.ctx)
            return cid, f.model_dump(mode="json"), None
        except Exception as exc:  # isolated per check: one failing agent never aborts its siblings
            return cid, None, repr(exc)

    def run_checks_node(self, state: AuditState) -> dict:
        batch = list(state["batch"])
        workers = max(1, min(self.max_workers, len(batch)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="aegis-agent") as pool:
            futures = [pool.submit(contextvars.copy_context().run, self._run_one, cid) for cid in batch]  # keep trace/MLflow context in each thread
            results = [f.result() for f in futures]
        results.sort(key=lambda r: r[0])  # deterministic: by check_id, never by completion order
        trace, findings = list(state["trace"]), dict(state["findings"])
        attempts, pending = dict(state["attempts"]), []
        for cid, data, err in results:
            chk = self.checks[cid]
            if data is not None:
                findings[cid] = data
                trace.append(f"{chk.agent}_agent: {cid} -> {data['status']} (confidence {data['confidence_score']:.2f}, {len(data['evidence'])} evidence)")
                continue
            attempts[cid] = attempts.get(cid, 0) + 1
            if attempts[cid] < MAX_ATTEMPTS:
                pending.append(cid)
                trace.append(f"{chk.agent}_agent: {cid} errored ({err}); supervisor will retry")
            else:
                findings[cid] = ComplianceFinding(
                    finding_id=f"{self.ctx.index.tenant_id}-{cid}", tenant_id=self.ctx.index.tenant_id,
                    jurisdiction=chk.jurisdiction, regulatory_reference=chk.regulatory_reference,
                    risk_tier=chk.risk_tier, status="SUSPECTED_GAP", confidence_score=0.3,
                    title=f"{cid}: check could not be completed",
                    summary=f"Agent error ({err}); closed-world rule marks the check SUSPECTED_GAP.", check_id=cid).model_dump(mode="json")
                trace.append(f"{chk.agent}_agent: {cid} failed twice -> SUSPECTED_GAP (closed-world)")
        return {"findings": findings, "trace": trace, "attempts": attempts, "pending": pending, "batch": []}

    def build(self):
        g = StateGraph(AuditState)
        g.add_node("supervisor", self.supervisor_node)
        g.add_node("run_checks", self.run_checks_node)
        g.add_edge("run_checks", "supervisor")  # cycle back to the supervisor
        g.add_conditional_edges("supervisor", self.route, {"run_checks": "run_checks", END: END})
        g.set_entry_point("supervisor")
        return g.compile(checkpointer=self.checkpointer)

    @traced("SupervisorAgent.run", span_type="CHAIN")
    def run(self, thread_id: str | None = None) -> tuple[list[ComplianceFinding], list[str]]:
        graph = self.build()
        init: AuditState = {"pending": list(self.order), "findings": {}, "trace": [], "batch": [], "attempts": {}, "iteration": 0}
        config = {"recursion_limit": 10 * MAX_ATTEMPTS + 40,
                  "configurable": {"thread_id": thread_id or f"{self.ctx.index.tenant_id}-{uuid.uuid4().hex[:12]}"}}
        out = graph.invoke(init, config)
        self.trace_id = current_trace_id()
        if self.checkpointer is not None:
            try:  # id of the final LangGraph checkpoint persisted for this run
                self.checkpoint_id = graph.get_state(config).config["configurable"]["checkpoint_id"]
            except Exception:
                self.checkpoint_id = None
        findings = [ComplianceFinding.model_validate(out["findings"][c]) for c in sorted(self.order)]  # deterministic order: by check_id
        return findings, out["trace"]
