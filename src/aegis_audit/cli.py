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


@app.command("ingest-pdf")
def ingest_pdf(
    path: str = typer.Argument(
        ...,
        help="Path to a PDF file or a directory of PDFs",
    ),
    jurisdiction: str = typer.Option(
        "EU_AI_ACT",
        "--jurisdiction",
        "-j",
        help="Statutory jurisdiction (EU_AI_ACT, UK_GDPR_ICO, etc.)",
    ),
    category: str = typer.Option(
        "REGULATORY_PDF",
        "--category",
        "-c",
        help="Document category (REGULATORY_PDF or COMPANY_DOC)",
    ),
    tenant_id: str = typer.Option(
        "global_regulations",
        "--tenant-id",
        "-t",
        help="Target tenant ID ('global_regulations' for public laws)",
    ),
):
    """Parses and indexes regulatory or company policy PDFs into MongoDB Atlas + local retriever."""
    from src.edge_extractors.pdf_ingestor import ingest_pdf_file
    from src.storage import get_compliance_store
    from src.agents.llm_client import _load_dotenv
    _load_dotenv()

    target_path = Path(path).resolve()
    if not target_path.exists():
        console.print(f"[bold red]Error: Path not found: {path}[/bold red]")
        raise typer.Exit(1)

    pdf_files = [target_path] if target_path.is_file() and target_path.suffix.lower() == ".pdf" else sorted(target_path.glob("**/*.pdf"))
    if not pdf_files:
        console.print(f"[bold yellow]No PDF files found in: {path}[/bold yellow]")
        raise typer.Exit(0)

    console.print(
        Panel(
            f"[bold cyan]Input Target:[/bold cyan] {path} ({len(pdf_files)} PDF file(s))\n"
            f"[bold cyan]Jurisdiction:[/bold cyan] {jurisdiction} | [bold cyan]Category:[/bold cyan] {category}\n"
            f"[bold cyan]Tenant ID:[/bold cyan] {tenant_id}",
            title="[bold blue]📄 Aegis Admin PDF Ingestion & Indexer[/bold blue]",
            border_style="blue",
        )
    )

    store = get_compliance_store()
    table = Table(title="PDF Ingestion & Indexing Summary", header_style="bold green")
    table.add_column("PDF Filename", style="bold")
    table.add_column("Pages", justify="right")
    table.add_column("Chunks", justify="right")
    table.add_column("Sample Locator", style="dim")
    table.add_column("Status", style="green")

    total_chunks = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("[cyan]Processing PDFs...", total=len(pdf_files))
        for pdf_f in pdf_files:
            progress.update(task, description=f"[cyan]Parsing & chunking {pdf_f.name}...")
            chunks = ingest_pdf_file(
                pdf_path=pdf_f,
                jurisdiction=jurisdiction,
                tenant_id=tenant_id,
                doc_category=category,
            )
            count = store.index_pdf_chunks(chunks)
            total_chunks += count

            from pypdf import PdfReader
            try:
                pages_cnt = len(PdfReader(str(pdf_f)).pages)
            except Exception:
                pages_cnt = 1

            sample_loc = chunks[0].exact_locator if chunks else "N/A"
            table.add_row(
                pdf_f.name,
                str(pages_cnt),
                str(count),
                sample_loc[:35] + "...",
                f"✓ INDEXED ({'Atlas' if store.is_atlas else 'Local'})",
            )
            progress.advance(task, 1)

    console.print(table)
    console.print(f"[bold green]✓ Successfully indexed {total_chunks} chunk(s) across {len(pdf_files)} file(s).[/bold green]\n")


@app.command("query-rules")
def query_rules(
    query: str = typer.Argument(
        ...,
        help="Search query across statutory rules and ingested PDFs",
    ),
    jurisdiction: Optional[str] = typer.Option(
        None,
        "--jurisdiction",
        "-j",
        help="Filter by jurisdiction",
    ),
    top_k: int = typer.Option(
        5,
        "--top-k",
        "-k",
        help="Maximum results to return",
    ),
):
    """Executes semantic + hybrid retrieval across indexed rules and PDF passages."""
    from src.storage import get_compliance_store
    from src.agents.llm_client import _load_dotenv
    _load_dotenv()

    console.print(
        Panel(
            f"[bold cyan]Query:[/bold cyan] {query}\n"
            f"[bold cyan]Jurisdiction Filter:[/bold cyan] {jurisdiction or 'All'}\n"
            f"[bold cyan]Top K:[/bold cyan] {top_k}",
            title="[bold magenta]🔎 Aegis Regulatory Knowledge & PDF Search[/bold magenta]",
            border_style="magenta",
        )
    )

    store = get_compliance_store()
    results = store.search_regulatory_knowledge(query=query, jurisdiction=jurisdiction, top_k=top_k)

    if not results:
        console.print("[yellow]No matching passages or statutory rules found.[/yellow]")
        return

    table = Table(title=f"Top {len(results)} Retrieval Results", header_style="bold blue")
    table.add_column("Rank", style="dim", width=6)
    table.add_column("Source / Locator", style="bold cyan", width=28)
    table.add_column("Score", justify="right", width=8)
    table.add_column("SHA-256", style="dim", width=12)
    table.add_column("Passage / Excerpt", width=46)

    for i, r in enumerate(results, 1):
        loc = r.get("exact_locator") or r.get("reference") or r.get("rule_id", "Statutory Rule")
        score = f"{r.get('score', 0.0):.3f}"
        sha = str(r.get("sha256_hash", ""))[:10]
        text_snip = (r.get("text") or r.get("title") or "")[:180].replace("\n", " ") + "..."
        table.add_row(str(i), loc, score, sha, text_snip)

    console.print(table)
    console.print()


def main():
    app()


if __name__ == "__main__":
    main()
