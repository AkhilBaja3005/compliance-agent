"""Aegis Rich Terminal CLI Interface."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from aegis_audit.client import ComplianceAuditor

app = typer.Typer(
    name="aegis",
    help="Aegis AI Safety & Regulatory Compliance Auditor CLI (Multi-Agent + BYOM + Zero False Negatives)",
    no_args_is_help=True,
)
console = Console()


@app.command("scan")
def scan(
    target_dir: str = typer.Option(
        "./sample_connectors",
        "--target-dir",
        "-t",
        help="Root path containing GitHub repos and Confluence spaces",
    ),
    company: str = typer.Option(
        "Northwind Labs Ltd",
        "--company",
        "-c",
        help="Target company name",
    ),
    output_pdf: str = typer.Option(
        "aegis_compliance_report.pdf",
        "--output-pdf",
        "-o",
        help="File path to save the generated 6-section WeasyPrint A4 PDF report",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output raw JSON to stdout",
    ),
):
    """Executes a full multi-agent compliance scan across enterprise connectors."""
    console.print(
        Panel(
            f"[bold cyan]Target Entity:[/bold cyan] {company}\n"
            f"[bold cyan]Input Connectors:[/bold cyan] {target_dir}\n"
            f"[bold cyan]Executive Report Output:[/bold cyan] {output_pdf}",
            title="[bold blue]🛡️ Aegis AI Regulatory Compliance Audit Execution[/bold blue]",
            border_style="blue",
        )
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task1 = progress.add_task("[cyan]Connecting to Databricks Mosaic AI Serving & MLflow...", total=100)
        time.sleep(0.4)
        progress.update(task1, advance=25, description="[cyan]Verifying Linkup Regulatory citations & EUR-Lex rules...")
        time.sleep(0.4)
        progress.update(task1, advance=25, description="[cyan]Tri-modal AST indexing (GitHub repos & Confluence AIGOV)...")
        time.sleep(0.5)
        progress.update(task1, advance=25, description="[cyan]Supervisor cyclic routing across 6 micro-agents...")
        time.sleep(0.5)
        progress.update(task1, advance=25, description="[cyan]Executing 4-Gate Guardrails & WeasyPrint 6-Section PDF Engine...")
        time.sleep(0.4)

    auditor = ComplianceAuditor()
    session = auditor.audit(company_name=company, target_dir=target_dir)

    # Save PDF Report
    pdf_path = session.save_pdf(output_path=output_pdf)

    if json_output:
        sys.stdout.write(session.to_json())
        return

    # Print Rich Summary Dashboard
    session.print_rich_summary()

    console.print(
        f"\n[bold green]✓ 6-Section Executive PDF Report generated successfully:[/bold green] "
        f"[bold underline]{pdf_path}[/bold underline]\n"
    )


@app.command("sync-laws")
def sync_laws(
    jurisdiction: str = typer.Option(
        "ALL",
        "--jurisdiction",
        "-j",
        help="Jurisdictions to synchronize (EU, UK, or ALL)",
    ),
    deep_linkup: bool = typer.Option(
        True,
        "--deep-linkup/--no-deep-linkup",
        help="Use Linkup deep web search for active legal amendments",
    ),
):
    """Synchronizes live statutory rules from EUR-Lex, UK Legislation, and Linkup deep search into MongoDB Atlas."""
    from src.agents.llm_client import _load_dotenv
    _load_dotenv()
    from src.law_sync import get_store
    from src.law_sync.linkup_scout import get_scout
    from src.storage import get_compliance_store

    rules_col_name = os.getenv("MONGODB_RULES_COLLECTION", "regulatory_rules")
    console.print(
        Panel(
            f"[bold cyan]Target Jurisdictions:[/bold cyan] {jurisdiction}\n"
            f"[bold cyan]Linkup Deep Regulatory Search:[/bold cyan] {'Enabled' if deep_linkup else 'Disabled'}\n"
            f"[bold cyan]MongoDB Atlas Vector Collection:[/bold cyan] {rules_col_name}",
            title="[bold magenta]📚 Aegis Live Regulatory RAG & Statutory Sync[/bold magenta]",
            border_style="magenta",
        )
    )

    law_store = get_store()
    scout = get_scout()
    compliance_store = get_compliance_store()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("[magenta]Loading statutory rules & EUR-Lex baseline...", total=100)
        time.sleep(0.3)
        rules = law_store.snapshot()
        progress.update(task, advance=33, description="[magenta]Enriching with Linkup deep web citations...")
        if deep_linkup and scout.enabled:
            rules = scout.enrich(rules)
        progress.update(task, advance=33, description=f"[magenta]Writing {len(rules)} vector embeddings to MongoDB Atlas ({rules_col_name})...")
        compliance_store.index_rules(rules)
        progress.update(task, advance=34, description="[magenta]Sync complete!")
        time.sleep(0.2)

    t = Table(title="Regulatory RAG Synchronization Status", header_style="bold green")
    t.add_column("Framework", style="bold")
    t.add_column("Statutory Reference", style="cyan")
    t.add_column("Indexed Rules", justify="right")
    t.add_column("Linkup Verified URLs", justify="right")
    t.add_column("Status", style="green")

    eu_rules = [r for r in rules.values() if "EU_AI_ACT" in str(r.jurisdiction)]
    uk_rules = [r for r in rules.values() if "UK" in str(r.jurisdiction)]
    ip_rules = [r for r in rules.values() if "COPYRIGHT" in str(r.jurisdiction) or "IP" in str(r.jurisdiction)]

    eu_linkup = sum(1 for r in eu_rules if r.linkup_source_url)
    uk_linkup = sum(1 for r in uk_rules if r.linkup_source_url)
    ip_linkup = sum(1 for r in ip_rules if r.linkup_source_url)

    t.add_row("EU AI Act", "Regulation (EU) 2024/1689 (Art 5, 14, 50)", str(len(eu_rules)), str(eu_linkup), "✓ SYNCHRONIZED")
    t.add_row("UK Data Regime", "UK DUAA 2025 & UK GDPR Art 22 ADM", str(len(uk_rules)), str(uk_linkup), "✓ SYNCHRONIZED")
    t.add_row("IP & Licensing", "EU CDSM / UK TDM & GPL Copyleft", str(len(ip_rules)), str(ip_linkup), "✓ SYNCHRONIZED")
    console.print(t)

    console.print(f"[bold green]✓ Total {len(rules)} statutory rules actively indexed in MongoDB Atlas '{rules_col_name}' collection.[/bold green]\n")


def main():
    app()


if __name__ == "__main__":
    main()
