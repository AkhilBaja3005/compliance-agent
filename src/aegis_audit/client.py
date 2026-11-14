"""Aegis Client and AuditSession models."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aegis_audit.remediator import generate_remediation_patches
from aegis_audit.report_pdf import render_audit_pdf
from aegis_audit.sarif import render_audit_sarif


@dataclass
class AuditSession:
    """Represents a completed or ongoing Aegis compliance audit session."""

    report_id: str
    company_name: str
    assessed_at: str
    scope: str
    rule_library_version: str
    input_coverage_pct: int
    overall_readiness: str
    readiness_summary: str
    bundle_sha256: str
    stack_telemetry: Dict[str, Any] = field(default_factory=dict)
    system_inventory: List[Dict[str, Any]] = field(default_factory=list)
    compliance_matrix: List[Dict[str, Any]] = field(default_factory=list)
    confirmed_findings: List[Dict[str, Any]] = field(default_factory=list)
    suspected_gaps: List[Dict[str, Any]] = field(default_factory=list)
    quarantined_for_human_review: List[Dict[str, Any]] = field(default_factory=list)
    passed_checks: List[Dict[str, Any]] = field(default_factory=list)
    agent_execution_trace: List[Dict[str, Any]] = field(default_factory=list)
    eval_results: Dict[str, Any] = field(default_factory=dict)
    fairness_metrics: Dict[str, Any] = field(default_factory=dict)
    roadmap: List[Dict[str, Any]] = field(default_factory=list)
    input_coverage: Dict[str, Any] = field(default_factory=dict)
    frameworks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "company_name": self.company_name,
            "assessed_at": self.assessed_at,
            "scope": self.scope,
            "rule_library_version": self.rule_library_version,
            "input_coverage_pct": self.input_coverage_pct,
            "overall_readiness": self.overall_readiness,
            "readiness_summary": self.readiness_summary,
            "bundle_sha256": self.bundle_sha256,
            "stack_telemetry": self.stack_telemetry,
            "system_inventory": self.system_inventory,
            "compliance_matrix": self.compliance_matrix,
            "confirmed_findings": self.confirmed_findings,
            "suspected_gaps": self.suspected_gaps,
            "quarantined_for_human_review": self.quarantined_for_human_review,
            "passed_checks": self.passed_checks,
            "agent_execution_trace": self.agent_execution_trace,
            "eval_results": self.eval_results,
            "fairness_metrics": self.fairness_metrics,
            "roadmap": self.roadmap,
            "input_coverage": self.input_coverage,
            "frameworks": self.frameworks,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save_pdf(self, output_path: str = "aegis_compliance_report.pdf") -> str:
        """Renders the exact 6-section executive A4 PDF report using WeasyPrint."""
        return render_audit_pdf(self.to_dict(), output_path=output_path)

    def save_sarif(self, output_path: str = "aegis_compliance_report.sarif") -> Dict[str, Any]:
        """Renders the OASIS SARIF v2.1.0 code scanning JSON output."""
        return render_audit_sarif(self.to_dict(), output_path=output_path)

    def generate_patches(self, repo_paths: Optional[List[str | Path]] = None, apply: bool = False, patch_out: Optional[str] = None) -> List[Dict[str, Any]]:
        """Generates unified git patches to automatically remediate statutory violations."""
        paths = repo_paths or [Path.cwd()]
        return generate_remediation_patches(self.to_dict(), paths, apply=apply, patch_out=patch_out)

    def print_rich_summary(self) -> None:
        """Prints an executive terminal dashboard using Rich."""
        console = Console()

        # Title Banner
        console.print(
            Panel(
                f"[bold white]{self.company_name}[/bold white] — [bold red]{self.overall_readiness}[/bold red]\n"
                f"[dim]Scope: {self.scope} | Report ID: {self.report_id} | Coverage: {self.input_coverage_pct}%[/dim]\n"
                f"[yellow]{self.readiness_summary}[/yellow]",
                title="[bold #70C5FF]GRAPHITE AI SAFETY & REGULATORY COMPLIANCE AUDITOR[/bold #70C5FF]",
                border_style="red" if "NOT" in self.overall_readiness else "green",
            )
        )

        # Platform Telemetry Strip
        tel = self.stack_telemetry
        telem_text = (
            f"[bold cyan]Mosaic AI Serving:[/bold cyan] {tel.get('databricks_endpoint', 'N/A')}  |  "
            f"[bold magenta]Unity Catalog:[/bold magenta] {tel.get('unity_catalog_table', 'N/A')}\n"
            f"[bold green]MLflow Trace:[/bold green] {tel.get('mlflow_trace_id', 'N/A')}  |  "
            f"[bold blue]MongoDB Atlas CP:[/bold blue] {tel.get('mongodb_checkpoint_id', 'N/A')}  |  "
            f"[bold yellow]Linkup Verified URLs:[/bold yellow] {tel.get('linkup_sources_verified_count', 0)}"
        )
        console.print(Panel(telem_text, title="Platform Pillars & Telemetry", border_style="cyan"))

        # Summary Metric Table
        m_table = Table(title="Statutory Findings & Controls Summary", header_style="bold magenta")
        m_table.add_column("Category", style="cyan")
        m_table.add_column("Count", justify="right", style="bold")
        m_table.add_column("Status / Policy Interpretation", style="white")

        m_table.add_row(
            "[bold red]Confirmed Violations[/bold red]",
            str(len(self.confirmed_findings)),
            "[bold red]Breach of statutory mandates / Contractual DPA drift[/bold red]",
        )
        m_table.add_row(
            "[bold yellow]Suspected Gaps (Closed-World)[/bold yellow]",
            str(len(self.suspected_gaps)),
            "[yellow]Unproven statutory controls (Zero False Negatives enforced)[/yellow]",
        )
        m_table.add_row(
            "[bold blue]Quarantined Claims[/bold blue]",
            str(len(self.quarantined_for_human_review)),
            "[blue]Held in Guardrail Gate 4 (Quarantine-over-drop policy)[/blue]",
        )
        m_table.add_row(
            "[bold green]Passed Controls[/bold green]",
            str(len(self.passed_checks)),
            "[green]Verified technical & organizational safeguards[/green]",
        )
        console.print(m_table)

        # Detailed Findings Table
        f_table = Table(title="Top Confirmed Regulatory Violations", header_style="bold red")
        f_table.add_column("ID", style="dim", width=12)
        f_table.add_column("Severity", style="bold red", width=10)
        f_table.add_column("System", width=18)
        f_table.add_column("Primary Statutory Rule", width=26)
        f_table.add_column("Title & Summary", width=42)

        for f in self.confirmed_findings[:5]:
            f_table.add_row(
                f.get("finding_id", ""),
                f.get("severity", ""),
                f"{f.get('system_id', '')} ({f.get('system_name', '')})",
                f.get("primary_rule", ""),
                f"[bold]{f.get('title', '')}[/bold]\n[dim]{f.get('summary', '')[:120]}...[/dim]",
            )
        console.print(f_table)


class ComplianceAuditor:
    """Enterprise Compliance Auditor client coordinating Connectors, RAG, and LangGraph Agents."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        use_databricks: bool = False,
        linkup_api_key: Optional[str] = None,
        mongodb_uri: Optional[str] = None,
    ):
        self.base_url = base_url or os.getenv("BYOM_BASE_URL", "http://localhost:11434/v1")
        self.api_key = api_key or os.getenv("BYOM_API_KEY", "ollama")
        self.use_databricks = use_databricks or (os.getenv("USE_DATABRICKS", "false").lower() == "true")
        self.linkup_api_key = linkup_api_key or os.getenv("LINKUP_API_KEY")
        self.mongodb_uri = mongodb_uri or os.getenv("MONGODB_URI")

    def audit(
        self,
        company_name: str = "Northwind Labs Ltd",
        github_repos: Optional[List[str]] = None,
        confluence_space: Optional[str] = None,
        target_dir: Optional[str] = None,
        github_url: Optional[str] = None,
        confluence_path: Optional[str] = None,
        diff_base: Optional[str] = None,
    ) -> AuditSession:
        """Runs a complete multi-agent compliance audit across GitHub and Confluence assets."""
        from src.connectors.github_connector import is_github_url

        target_str = str(github_url or target_dir or "./sample_connectors")
        now_str = datetime.now(timezone.utc).strftime("%d %B %Y")

        if is_github_url(target_str) or (target_dir and is_github_url(target_dir)):
            from src.agents import run_audit
            url = target_str if is_github_url(target_str) else str(target_dir)
            repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
            tenant_id = f"gh_{repo_name}"
            real_report = run_audit(
                None,
                tenant_id,
                github_source=url,
                confluence_source=confluence_path,
                diff_base=diff_base,
            )
            return self._build_session(real_report, company_name or repo_name, now_str, self._scope_label(f"Live GitHub Repo ({url})", real_report))

        target_path = Path(target_dir or "./sample_connectors").resolve()

        # If pointing to an actual company directory, invoke the multi-agent pipeline
        # Any folder with files is a real company to audit; only the bundled sample root (which holds `enterprise/`) uses the demo data.
        is_company_dir = (
            target_path.is_dir()
            and not (target_path / "enterprise").is_dir()
            and any(p.is_file() for p in target_path.rglob("*"))
        )

        if is_company_dir:
            from src.agents import run_audit
            tenant_id = target_path.name
            real_report = run_audit(target_path, tenant_id, diff_base=diff_base)
            return self._build_session(real_report, company_name, now_str, self._scope_label(f"Scanned Repository ({target_path.name})", real_report))

        # 7 Systems modeled on Northwind Labs Ltd (sample_connectors default)
        systems = [
            {
                "system_id": "S1",
                "name": "Customer Support Assistant",
                "repo": "support-assistant",
                "purpose": "Omnichannel customer query resolution (Email, Web, Mobile, Widget)",
                "eu_tier": "Article 50(1) Generative AI",
                "uk_regime": "EU Consumer Rights (Directive 2011/83/EU)",
                "declared": True,
            },
            {
                "system_id": "S2",
                "name": "Candidate Ranking Engine",
                "repo": "talent-screener-vendor",
                "purpose": "Automated resume parsing and applicant shortlisting",
                "eu_tier": "Annex III §4(a) High-Risk (Employment)",
                "uk_regime": "EU Non-Discrimination Directives",
                "declared": False,  # Purple undeclared badge
            },
            {
                "system_id": "S3",
                "name": "Credit Decision Engine",
                "repo": "credit-decision-engine",
                "purpose": "Automated underwriting and dynamic credit limit reductions",
                "eu_tier": "Annex III §5(b) High-Risk (Creditworthiness)",
                "uk_regime": "EU GDPR Art 22 Automated Profiling",
                "declared": True,
            },
            {
                "system_id": "S4",
                "name": "Imagery Studio Diffusion API",
                "repo": "imagery-studio",
                "purpose": "Commercial diffusion image and portrait synthesis",
                "eu_tier": "Article 50(2) Generative AI & Prohibited Risk",
                "uk_regime": "EU DSM Directive Art 4 (TDM)",
                "declared": False,  # Purple undeclared badge
            },
            {
                "system_id": "S5",
                "name": "Voice Synthesis Engine",
                "repo": "voice-cloning-api",
                "purpose": "Audio generation and text-to-speech rendering",
                "eu_tier": "Article 50(2) Synthetic Audio",
                "uk_regime": "EU AI Act Art 50 Transparency",
                "declared": True,
            },
            {
                "system_id": "S6",
                "name": "Enterprise Search RAG",
                "repo": "internal-knowledge-rag",
                "purpose": "Internal policy document indexing and retrieval",
                "eu_tier": "Limited Risk (Internal)",
                "uk_regime": "EU GDPR & EU TDM",
                "declared": True,
            },
            {
                "system_id": "S7",
                "name": "Developer Code Copilot",
                "repo": "developer-copilot",
                "purpose": "Internal code autocomplete and docstring generator",
                "eu_tier": "Minimal / No Risk",
                "uk_regime": "EU General Software",
                "declared": True,
            },
        ]

        # Modeled findings directly reflecting Northwind Labs code & policy facts
        confirmed = [
            {
                "finding_id": "FINDING-NW-001",
                "severity": "CRITICAL",
                "status": "CONFIRMED_VIOLATION",
                "due_date": "Immediate",
                "days_remaining": 0,
                "confidence": 0.99,
                "title": "Facial Likeness Moderation Bypass on Pro Tier",
                "system_id": "S4",
                "system_name": "Imagery Studio",
                "primary_rule": "EU AI Act Article 5(1)(d) & Confluence AUP Policy Drift",
                "also_engages": "EU Digital Services Act (DSA) / GDPR Privacy",
                "summary": "Line 48 of moderation.yaml sets face_upload_filter: false for 'pro' subscribers, enabling unconsented facial uploads and intimate imagery generation, directly violating Confluence AUP Policy v2.1 guarantees.",
                "code_vs_doc_drift": {
                    "doc_claim": "AUP_Policy_v2_1.md §1.1: 'Intimate imagery is blocked unconditionally across all tiers, including Free, Creator, and Pro accounts. Zero bypass allowed.'",
                    "code_reality": "moderation.yaml:48: 'face_upload_filter: false' for tier 'pro', with allow_raw_prompts: true.",
                },
                "evidence": [
                    {
                        "source_type": "CODE_AST",
                        "item": "moderation.yaml",
                        "artifact_id": "github/imagery-studio/moderation.yaml",
                        "exact_locator": "moderation.yaml:48",
                        "sha256_hash": "c2094ba81f09230e",
                        "source_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689",
                        "source_date": "2026-11-14",
                        "snippet": "pro:\n  face_upload_filter: false # Line 48: High-tier bypass allows unverified faces\n  deepfake_detection_enforced: false",
                    },
                    {
                        "source_type": "CONFLUENCE_DOC",
                        "item": "AUP_Policy_v2_1.md",
                        "artifact_id": "confluence/AIGOV/AUP_Policy_v2_1.md",
                        "exact_locator": "Section 1.1: Universal Facial Likeness Policy",
                        "sha256_hash": "b83a00912f7188aa",
                        "source_url": "https://www.legislation.gov.uk/ukpga/2023/50/contents/enacted",
                        "source_date": "2026-11-14",
                        "snippet": "Intimate and non-consensual imagery generation is blocked unconditionally across all tiers, including Free, Creator, and Pro accounts.",
                    },
                ],
                "exposure_text": "Fines up to €35,000,000 or 7% of worldwide annual turnover for prohibited AI practices under EU AI Act Article 99(3).",
                "owner": "Director of Media AI",
                "effort_days": 2,
                "human_review_required": False,
                "remediation_steps": [
                    "Remove tier-based bypass in moderation.yaml line 48 and set face_upload_filter: true unconditionally.",
                    "Enforce cryptographic biometric identity verification across all commercial rendering endpoints.",
                    "Audit past 90 days of Pro tier image generations for unconsented intimate likeness.",
                ],
                "history_status": "NEW",
                "linkup_citation_urls": [
                    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689",
                    "https://www.legislation.gov.uk/ukpga/2023/50/contents/enacted",
                ],
            },
            {
                "finding_id": "FINDING-NW-002",
                "severity": "CRITICAL",
                "status": "CONFIRMED_VIOLATION",
                "due_date": "2 Dec 2026",
                "days_remaining": 18,
                "confidence": 0.98,
                "title": "Omission of Machine-Readable C2PA Watermark in Synthetic Media",
                "system_id": "S4",
                "system_name": "Imagery Studio",
                "primary_rule": "EU AI Act Article 50(2) (Synthetic Content Marking)",
                "also_engages": "CEN-CENELEC / ISO 5474 Synthetic Media Standards",
                "summary": "src/generate.py emits raw synthetic PNG images without C2PA cryptographic metadata or machine-readable watermarking, violating the Dec 2, 2026 statutory transparency deadline.",
                "code_vs_doc_drift": {
                    "doc_claim": "Model_Card.md §2: 'Target Distribution: Deployed as Enterprise SaaS adhering to emerging global transparency rules.'",
                    "code_reality": "src/generate.py L43-52: Return payload provides direct image URL with zero c2pa_provenance_manifest or steganographic watermark.",
                },
                "evidence": [
                    {
                        "source_type": "CODE_AST",
                        "item": "src/generate.py",
                        "artifact_id": "github/imagery-studio/src/generate.py",
                        "exact_locator": "generate_image():L43-L52",
                        "sha256_hash": "f0198aa71c99021a",
                        "source_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689#art_50",
                        "source_date": "2026-11-14",
                        "snippet": 'return {"status": "SUCCESS", "render_id": "rnd_981249", "media_url": generated_media_url, "format": request.output_format}',
                    }
                ],
                "exposure_text": "Fines up to €15,000,000 or 3% of worldwide annual turnover for Article 50 transparency breaches.",
                "owner": "Head of Platform Architecture",
                "effort_days": 4,
                "human_review_required": False,
                "remediation_steps": [
                    "Integrate c2pa-python SDK into the render output pipeline.",
                    "Embed signed cryptographic claim generator into all PNG/WebP headers.",
                    "Attach 'ai_generated: true' to all API JSON metadata responses.",
                ],
                "history_status": "RECURRING",
                "linkup_citation_urls": [
                    "https://c2pa.org/specifications/specifications/2.0/index.html",
                    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689",
                ],
            },
            {
                "finding_id": "FINDING-NW-003",
                "severity": "CRITICAL",
                "status": "CONFIRMED_VIOLATION",
                "due_date": "Immediate",
                "days_remaining": 0,
                "confidence": 0.97,
                "title": "Solely Automated Credit Limits & US PII Data Egress",
                "system_id": "S3",
                "system_name": "Credit Decision Engine",
                "primary_rule": "EU GDPR Article 22 & DPA Drift",
                "also_engages": "EU AI Act Annex III §5(b) High-Risk Credit Scoring",
                "summary": "src/credit_scorer.py transmits raw customer names, identifiers, and postcodes directly to a US-hosted OpenAI endpoint without Presidio redaction, and executes solely automated credit-limit cuts with appeal_route_available=False.",
                "code_vs_doc_drift": {
                    "doc_claim": "DPA_Customer_Data.md §1: 'All PII must be redacted via Presidio... Customer data is processed strictly within European enclaves (eu-central-1)... all automated decisions must provide accessible human contestation.'",
                    "code_reality": "src/credit_scorer.py L12 & L48: OpenAI(base_url='https://api.openai.com/v1') receiving raw prompt and returning appeal_route_available=False.",
                },
                "evidence": [
                    {
                        "source_type": "CODE_AST",
                        "item": "src/credit_scorer.py",
                        "artifact_id": "github/credit-decision-engine/src/credit_scorer.py",
                        "exact_locator": "evaluate_credit_limit():L38-L56",
                        "sha256_hash": "a4f89d31e8c04b12",
                        "source_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
                        "source_date": "2026-11-14",
                        "snippet": 'prompt = f"Analyze credit limit for customer: {request.applicant_name}, ID: {request.id}..."\nreturn {"decision": "AUTOMATED_LIMIT_REDUCTION", "appeal_route_available": False}',
                    }
                ],
                "exposure_text": "EU DPA enforcement notice, statutory damages under GDPR Art. 22 automated decision provisions, and fines up to €20M / 4% global turnover.",
                "owner": "Head of Credit Underwriting & FinTech Ops",
                "effort_days": 5,
                "human_review_required": False,
                "remediation_steps": [
                    "Wrap input payload with local Microsoft Presidio anonymizer before inference.",
                    "Migrate model target to sovereign EU regional inference enclave.",
                    "Build human-in-the-loop escalation workflow and customer appeal request portal.",
                ],
                "history_status": "NEW",
                "linkup_citation_urls": [
                    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
                    "https://artificialintelligenceact.eu/annex/3/",
                ],
            },
            {
                "finding_id": "FINDING-NW-004",
                "severity": "HIGH",
                "status": "CONFIRMED_VIOLATION",
                "due_date": "30 Days",
                "days_remaining": 30,
                "confidence": 0.96,
                "title": "Commercial SaaS Deployment of CC-BY-NC-4.0 & GPL-3.0 Weights",
                "system_id": "S4",
                "system_name": "Imagery Studio",
                "primary_rule": "Intellectual Property / Open Source License Breach",
                "also_engages": "EU AI Act General Purpose AI Governance",
                "summary": "Model_Card.md documents fine-tuning over CC-BY-NC-4.0 non-commercial weights and dynamic linking against GPL-3.0 audiocraft components inside a $149/seat closed commercial SaaS product.",
                "code_vs_doc_drift": {
                    "doc_claim": "Model_Card.md §1-2: 'Base Checkpoint License: CC-BY-NC-4.0. Dependencies: audiocraft-gpl==1.2.0 (GPL-3.0). Deployed in paid Enterprise SaaS.'",
                    "code_reality": "Direct commercial exploitation of non-commercial license without copyright holder variance.",
                },
                "evidence": [
                    {
                        "source_type": "CONFLUENCE_DOC",
                        "item": "Model_Card.md",
                        "artifact_id": "github/imagery-studio/Model_Card.md",
                        "exact_locator": "Section 1: Lineage & Checkpoints",
                        "sha256_hash": "887fa014299b9802",
                        "source_url": "https://creativecommons.org/licenses/by-nc/4.0/",
                        "source_date": "2026-11-14",
                        "snippet": "Released under CC-BY-NC-4.0 (Creative Commons Attribution-NonCommercial 4.0 International)... links against GPL-3.0.",
                    }
                ],
                "exposure_text": "Injunctive relief, mandatory copyright statutory damages, and potential forced open-sourcing of proprietary rendering code under GPL copyleft.",
                "owner": "VP Legal & Chief IP Counsel",
                "effort_days": 14,
                "human_review_required": True,
                "remediation_steps": [
                    "Substitute base diffusion weights with Apache-2.0 / MIT cleared foundation models.",
                    "Refactor audio pipeline into isolated sub-process or replace GPL-3.0 library.",
                ],
                "history_status": "RECURRING",
                "linkup_citation_urls": [
                    "https://creativecommons.org/licenses/by-nc/4.0/",
                    "https://www.gnu.org/licenses/gpl-3.0.en.html",
                ],
            },
            {
                "finding_id": "FINDING-NW-005",
                "severity": "HIGH",
                "status": "CONFIRMED_VIOLATION",
                "due_date": "14 Days",
                "days_remaining": 14,
                "confidence": 0.95,
                "title": "Customer Interaction AI Disclosure Omitted on Email and In-App Widget",
                "system_id": "S1",
                "system_name": "Customer Support Assistant",
                "primary_rule": "EU AI Act Article 50(1) (Interaction Disclosure)",
                "also_engages": "EU Unfair Commercial Practices Directive",
                "summary": "2 of 4 chat entry points in src/routes.py (/v1/email-support/auto-respond and /v1/in-app-widget/instant-reply) fail to inform customers that they are conversing with an automated artificial intelligence system.",
                "code_vs_doc_drift": {
                    "doc_claim": "AUP_Policy_v2_1.md: 'All customer-facing synthetic dialogs maintain clear transparency notices.'",
                    "code_reality": "src/routes.py L45: in-app widget masquerades as 'Sarah (Support Associate)' with zero AI disclosure.",
                },
                "evidence": [
                    {
                        "source_type": "CODE_AST",
                        "item": "src/routes.py",
                        "artifact_id": "github/support-assistant/src/routes.py",
                        "exact_locator": "in_app_instant_reply():L40-L48",
                        "sha256_hash": "33418ef0192a884b",
                        "source_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689#art_50",
                        "source_date": "2026-11-14",
                        "snippet": 'return {"reply_bubble": f"Hi! Regarding your query...", "rep_name": "Sarah (Support Associate)"}',
                    }
                ],
                "exposure_text": "Regulatory warnings and fines up to €15,000,000 for Article 50 transparency failures.",
                "owner": "Director of Customer Experience",
                "effort_days": 1,
                "human_review_required": False,
                "remediation_steps": [
                    "Add 'ai_disclosure: This message was generated by an AI assistant' to email templates.",
                    "Update in-app chat widget UI avatar and header to clearly designate bot identity.",
                ],
                "history_status": "NEW",
                "linkup_citation_urls": [
                    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689#art_50"
                ],
            },
        ]

        suspected = [
            {
                "finding_id": "GAP-NW-001",
                "severity": "HIGH",
                "status": "SUSPECTED_GAP",
                "due_date": "Immediate",
                "days_remaining": 0,
                "confidence": 0.92,
                "title": "Missing Fundamental Rights Impact Assessment (FRIA) for High-Risk HR Screening",
                "system_id": "S2",
                "system_name": "Candidate Ranking Engine",
                "primary_rule": "EU AI Act Article 27 & Annex III §4(a)",
                "also_engages": "EU AI Act Annex III Employment Guidelines",
                "summary": "[Closed-World Assumption]: Automated candidate screening deployed without formal Article 27 Fundamental Rights Impact Assessment on record in Confluence space.",
            }
        ]

        quarantined = [
            {
                "finding_id": "QUARANTINE-NW-001",
                "severity": "MEDIUM",
                "status": "QUARANTINED_FOR_HUMAN_REVIEW",
                "claim_text": "Speculative assertion that fine-tuned audio weights leak memorized copyright samples.",
                "gate_failed": "Gate 2 (Evidence Hash Matching)",
                "reason": "Draft finding from oss_license agent lacked verified code AST or Linkup source URL match. Quarantined for expert review per Zero False Negatives policy.",
                "confidence": 0.38,
            }
        ]

        passed = [
            {
                "check_id": "PASS-NW-001",
                "system_id": "S1",
                "primary_rule": "EU AI Act Art 50(1) Web & Mobile Chat Disclosure",
                "title": "Compliant Web & Mobile Chat AI Disclosures",
                "evidence": "src/routes.py properly emits ai_disclosure on /v1/web-support/chat and /v1/mobile-support/chat.",
            },
            {
                "check_id": "PASS-NW-002",
                "system_id": "S7",
                "primary_rule": "EU AI Act Article 9 / Minimal Risk",
                "title": "Internal Developer Copilot Governance",
                "evidence": "Sandboxed internal autocomplete operating within boundary without customer PII ingestion.",
            },
        ]

        session = AuditSession(
            report_id=f"GRAPHITE-NW-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
            company_name=company_name,
            assessed_at=now_str,
            scope=f"GitHub Repositories ({len(systems)} systems) & Confluence AIGOV Space",
            rule_library_version="EU-2026.11-Unified",
            input_coverage_pct=94,
            overall_readiness="NOT READY — 5 CRITICAL STATUTORY BREACHES",
            readiness_summary=(
                "Northwind Labs faces severe regulatory exposure across EU AI Act Article 5(1)(d) (facial likeness bypass), "
                "Article 50(2) (missing C2PA synthetic media watermark ahead of Dec 2, 2026 deadline), "
                "EU GDPR Article 22 solely automated decision profiling, and commercial CC-BY-NC-4.0 license infringement."
            ),
            bundle_sha256="7c992a019488f1c09892ba0174ef9921cba10291ba488219ba488109ba472910",
            stack_telemetry={
                "databricks_endpoint": os.getenv("DATABRICKS_SERVING_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct"),
                "unity_catalog_table": os.getenv("DATABRICKS_UNITY_CATALOG_TABLE", "compliance_catalog.audit_prod.triaged_audit_reports"),
                "mlflow_trace_id": "tr-nw-881940a1b2",
                "mongodb_database": os.getenv("MONGODB_DATABASE", "aegis_compliance"),
                "mongodb_checkpoint_id": "chk-atlas-9981240f",
                "linkup_sources_verified_count": 48,
            },
            system_inventory=systems,
            confirmed_findings=confirmed,
            suspected_gaps=suspected,
            quarantined_for_human_review=quarantined,
            passed_checks=passed,
        )
        return session

    @staticmethod
    def _scope_label(label: str, real_report) -> str:
        """Append the incremental-scan marker (`[diff vs <base>: N changed file(s)]`) so a PR-gate report says what it covered."""
        import re as _re

        m = _re.search(r"\[diff vs [^\]]+\]", getattr(real_report, "scope", "") or "")
        return f"{label} {m.group(0)}" if m else label

    def _build_session(self, real_report, company_name: str, assessed_at: str, scope: str) -> AuditSession:
        export_data = real_report.to_export_dict()
        return AuditSession(
            report_id=export_data["report_id"],
            company_name=company_name or export_data["company_name"],
            assessed_at=assessed_at or export_data["assessed_at"],
            scope=scope or export_data["scope"],
            rule_library_version=export_data["rule_library_version"],
            input_coverage_pct=export_data["input_coverage_pct"],
            overall_readiness=export_data["overall_readiness"],
            readiness_summary=export_data["readiness_summary"],
            bundle_sha256=export_data["bundle_sha256"],
            stack_telemetry=export_data["stack_telemetry"],
            system_inventory=export_data["system_inventory"],
            compliance_matrix=export_data["compliance_matrix"],
            confirmed_findings=export_data["confirmed_findings"],
            suspected_gaps=export_data["suspected_gaps"],
            quarantined_for_human_review=export_data["quarantined_for_human_review"],
            passed_checks=export_data["passed_checks"],
            agent_execution_trace=export_data["agent_execution_trace"],
            eval_results=export_data["eval_results"],
            fairness_metrics=export_data["fairness_metrics"],
            roadmap=export_data["roadmap"],
            input_coverage=export_data["input_coverage"],
            frameworks=export_data["frameworks"],
        )
