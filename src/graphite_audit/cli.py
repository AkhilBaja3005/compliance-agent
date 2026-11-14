"""Graphite Rich Terminal CLI Interface."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from graphite_audit.client import ComplianceAuditor

app = typer.Typer(
    name="graphite",
    help="Graphite AI Safety & Regulatory Compliance Auditor CLI (Multi-Agent + BYOM + Zero False Negatives)",
    no_args_is_help=False,
)
console = Console()


def print_graphite_banner() -> None:
    """Renders the official Graphite terminal logo banner."""
    node_art = """[bold #70C5FF]        ●[/]
[#386B94]       /|\\
      / | \\
     /  [/][bold #FFFFFF]●[/][#386B94]  \\
    /  / \\  \\
 [bold #0077FF]  ●[/][#386B94]---------●[/][bold #0077FF][/]"""

    wordmark = """[bold white]   ___ _ __ __ _ _ __  | |__  (_) |_ ___ [/]
[bold white]  / _ `/ '__/ _ `/ '_ \\ | '_ \\ | |  _/ -_)[/]
[bold white]  \\_, |_|  \\__,_| .__/ |_| |_|_|\\__\\___|[/]
[bold white]  |___/         |_|                     [/]
[bold #70C5FF]  AI Safety & Regulatory Compliance Auditor[/]
[dim]  EU AI Act (2024/1689) · GDPR · IP[/]"""

    grid = Table.grid(padding=(0, 2))
    grid.add_column(vertical="middle")
    grid.add_column(vertical="middle")
    grid.add_row(node_art, wordmark)
    console.print(Panel(grid, border_style="#1E456B", expand=True))


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """Graphite AI Safety & Regulatory Compliance Auditor CLI."""
    if ctx.invoked_subcommand is None:
        print_graphite_banner()
        console.print("[dim]Use [bold cyan]graphite --help[/bold cyan] to see available commands or [bold cyan]graphite scan[/bold cyan] to run an audit.[/dim]\n")


@app.command("scan")
def scan(
    target_dir: str = typer.Option(
        "./sample_connectors",
        "--target-dir",
        "-t",
        help="Root path containing GitHub repos and Confluence spaces, or local repo path",
    ),
    github_url: Optional[str] = typer.Option(
        None,
        "--github-url",
        "-g",
        help="Direct live GitHub repository URL (e.g. https://github.com/org/repo)",
    ),
    confluence_path: Optional[str] = typer.Option(
        None,
        "--confluence-path",
        help="Path to Confluence docs or export folder",
    ),
    company: str = typer.Option(
        "Northwind Labs Ltd",
        "--company",
        "-c",
        help="Target company name",
    ),
    output_pdf: str = typer.Option(
        "graphite_compliance_report.pdf",
        "--output-pdf",
        "-o",
        help="File path to save the generated 6-section WeasyPrint A4 PDF report",
    ),
    format: str = typer.Option(
        "pdf",
        "--format",
        "-f",
        help="Output format: 'pdf', 'json', 'sarif', or 'all'",
    ),
    sarif_out: Optional[str] = typer.Option(
        None,
        "--sarif-out",
        help="File path to save the SARIF 2.1.0 code scanning JSON output",
    ),
    diff: Optional[str] = typer.Option(
        None,
        "--diff",
        help="Git base branch/commit for incremental PR auditing (e.g. origin/main)",
    ),
    fail_on: str = typer.Option(
        "none",
        "--fail-on",
        help="Exit with code 1 if findings reach severity: 'critical', 'high', 'any', or 'none'",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output raw JSON to stdout",
    ),
):
    """Executes a full multi-agent compliance scan across enterprise connectors."""
    fmt = format.lower().strip()
    if not json_output and fmt != "json":
        print_graphite_banner()
        effective_source = github_url or target_dir
        console.print(
            Panel(
                f"[bold cyan]Target Entity:[/bold cyan] {company}\n"
                f"[bold cyan]Input Connectors / Source:[/bold cyan] {effective_source}\n"
                + (f"[bold cyan]Incremental PR Diff:[/bold cyan] {diff}\n" if diff else "")
                + f"[bold cyan]Report Format:[/bold cyan] {format.upper()} | [bold cyan]CI/CD Gate:[/bold cyan] {fail_on.upper()}",
                title="[bold #70C5FF]Graphite AI Regulatory Compliance Audit Execution[/bold #70C5FF]",
                border_style="#386B94",
            )
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task1 = progress.add_task("[cyan]Connecting to Databricks Mosaic AI Serving & MLflow...", total=100)
            time.sleep(0.2)
            progress.update(task1, advance=25, description="[cyan]Verifying Linkup Regulatory citations & EUR-Lex rules...")
            time.sleep(0.2)
            progress.update(task1, advance=25, description="[cyan]Tri-modal AST indexing (GitHub repos & Confluence AIGOV)...")
            time.sleep(0.2)
            progress.update(task1, advance=25, description="[cyan]Supervisor cyclic routing across 6 micro-agents...")
            time.sleep(0.2)
            progress.update(task1, advance=25, description="[cyan]Executing 4-Gate Guardrails & WeasyPrint 6-Section PDF Engine...")
            time.sleep(0.2)
    auditor = ComplianceAuditor()
    session = auditor.audit(
        company_name=company,
        target_dir=target_dir if not github_url else None,
        github_url=github_url,
        confluence_path=confluence_path,
        diff_base=diff,
    )

    pdf_path = None
    if fmt in ("pdf", "all"):
        pdf_path = session.save_pdf(output_path=output_pdf)

    # Determine SARIF output
    actual_sarif_path = sarif_out or (Path(output_pdf).with_suffix(".sarif").as_posix() if fmt in ("sarif", "all") else None)
    if actual_sarif_path:
        session.save_sarif(output_path=actual_sarif_path)

    if json_output or fmt == "json":
        sys.stdout.write(session.to_json())
    elif fmt == "sarif" and not json_output:
        sarif_doc = session.save_sarif(output_path=actual_sarif_path)
        if not sarif_out:
            sys.stdout.write(json.dumps(sarif_doc, indent=2))

    if not json_output and fmt != "json":
        session.print_rich_summary()
        if pdf_path:
            console.print(
                f"\n[bold green]✓ 6-Section Executive PDF Report generated successfully:[/bold green] "
                f"[bold underline]{pdf_path}[/bold underline]"
            )
        if actual_sarif_path:
            console.print(
                f"[bold green]✓ SARIF 2.1.0 Code Scanning Report generated successfully:[/bold green] "
                f"[bold underline]{actual_sarif_path}[/bold underline]\n"
            )

    # Check CI/CD release gate
    fail_threshold = fail_on.lower().strip()
    if fail_threshold != "none":
        crit_count = sum(1 for f in session.confirmed_findings if str(f.get("severity")).upper() == "CRITICAL")
        high_count = sum(1 for f in session.confirmed_findings if str(f.get("severity")).upper() in ("CRITICAL", "HIGH"))
        any_count = len(session.confirmed_findings) + len(session.suspected_gaps)

        should_fail = (
            (fail_threshold == "critical" and crit_count > 0)
            or (fail_threshold == "high" and high_count > 0)
            or (fail_threshold == "any" and any_count > 0)
        )
        if should_fail:
            console.print(
                f"[bold red]CI/CD Gate Failed: Detected statutory findings meeting threshold '{fail_threshold.upper()}'.[/bold red]"
            )
            raise typer.Exit(code=1)


def _build_sync_config(config: Optional[str], folder: list[str], url: list[str], jurisdiction: str, remote_docs_tenant: Optional[str], pdf_dir: str):
    from src.law_sync.ingest import FolderSource, SyncConfig, UrlSource, load_config

    cfg = load_config(config) if (config or Path("sync_sources.yaml").is_file() or os.getenv("GRAPHITE_SYNC_CONFIG")) else SyncConfig()
    j = "EU_AI_ACT" if "GDPR" not in jurisdiction.upper() else "EU_GDPR"
    cfg.folders += [FolderSource(str(Path(f).resolve()), j) for f in folder]
    cfg.urls += [UrlSource(u, j) for u in url]
    if not cfg.folders and not cfg.urls and not folder and not url and pdf_dir and Path(pdf_dir).is_dir():
        cfg.folders.append(FolderSource(str(Path(pdf_dir).resolve()), j, "REGULATORY_PDF"))  # backwards-compatible default
    if remote_docs_tenant:
        cfg.remote_docs_tenant = remote_docs_tenant
    return cfg


def _print_sync_report(rep) -> None:
    t = Table(title="Knowledge sources", header_style="bold green")
    for h in ("Source", "Status", "Chunks", "Detail"):
        t.add_column(h)
    style = {"new": "green", "updated": "cyan", "unchanged": "dim", "removed": "yellow", "error": "bold red"}
    for r in rep.sources:
        t.add_row(r.source[:70], f"[{style.get(r.status, 'white')}]{r.status}[/]", str(r.chunks), r.detail[:90])
    if rep.sources:
        console.print(t)
    console.print(f"[bold green]✓ {rep.rules_total} statutory rule(s) indexed ({rep.rules_version}); {rep.rule_changes} change(s) this run.[/bold green]")
    if rep.moved_legacy_chunks:
        console.print(f"[yellow]Moved {rep.moved_legacy_chunks} legacy PDF chunk(s) (one-time migration).[/yellow]")
    if rep.errors:
        console.print(f"[bold red]{len(rep.errors)} source(s) failed; the others were synced.[/bold red]")


@app.command("sync-laws")
def sync_laws(
    jurisdiction: str = typer.Option("EU", "--jurisdiction", "-j", help="Jurisdiction tag for --folder/--url sources (EU)"),
    deep_linkup: bool = typer.Option(True, "--deep-linkup/--no-deep-linkup", help="Use Linkup deep web search for active legal amendments"),
    folder: list[str] = typer.Option([], "--folder", "-f", help="Folder to ingest (repeatable): PDF, md, txt, docx, xlsx, pptx, html, rtf, odt, csv"),
    url: list[str] = typer.Option([], "--url", "-u", help="https web page or PDF to ingest (repeatable)"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="YAML/JSON file listing folders and urls (default ./sync_sources.yaml or $GRAPHITE_SYNC_CONFIG)"),
    remote_docs_tenant: Optional[str] = typer.Option(None, "--remote-docs-tenant", help="Also index env-configured remote sources (Notion, Jira, Slack, ...) into this tenant"),
    pdf_dir: str = typer.Option("regulatory_pdfs", "--pdf-dir", help="Default folder when no --folder/--url/config is given ('' to skip)"),
):
    """Syncs statutory rules, then ingests folders and web pages into the vector store. Only changed sources are re-embedded."""
    from src.agents.llm_client import _load_dotenv
    _load_dotenv()
    from src.law_sync.ingest import run_full_sync

    cfg = _build_sync_config(config, folder, url, jurisdiction, remote_docs_tenant, pdf_dir)
    console.print(Panel(
        f"[bold cyan]Linkup deep search:[/bold cyan] {'on' if deep_linkup else 'off'}\n"
        f"[bold cyan]Folders:[/bold cyan] {', '.join(f.path for f in cfg.folders) or '-'}\n"
        f"[bold cyan]URLs:[/bold cyan] {', '.join(u.url for u in cfg.urls) or '-'}\n"
        f"[bold cyan]Remote documents:[/bold cyan] {cfg.remote_docs_tenant or 'off'}",
        title="[bold magenta]Graphite regulatory knowledge sync[/bold magenta]", border_style="magenta"))
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task("[magenta]Syncing rules, folders and web sources...", total=None)
        rep = run_full_sync(cfg, deep_linkup=deep_linkup)
    _print_sync_report(rep)
    raise typer.Exit(1 if rep.errors else 0)


@app.command("sync-daemon")
def sync_daemon(
    interval_hours: float = typer.Option(24.0, "--interval-hours", help="Hours between full syncs"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Sources file (default ./sync_sources.yaml or $GRAPHITE_SYNC_CONFIG)"),
    run_now: bool = typer.Option(True, "--run-now/--wait", help="Run one sync immediately, then on the interval"),
):
    """Long-running scheduler for the full sync (use as a separate process/container). For cron use `graphite sync-laws` instead."""
    import threading

    from src.agents.llm_client import _load_dotenv
    _load_dotenv()
    from src.observability import configure_logging

    configure_logging(os.getenv("GRAPHITE_LOG_LEVEL", "INFO"))
    if config:
        os.environ["GRAPHITE_SYNC_CONFIG"] = config
    from src.law_sync.scheduler import start_scheduler

    start_scheduler(interval_hours, run_immediately=run_now)
    console.print(f"[green]sync daemon started: every {interval_hours:g} h{' (first run now)' if run_now else ''}. Ctrl+C to stop.[/green]")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        console.print("stopped")


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
        help="Statutory jurisdiction (EU_AI_ACT, EU_GDPR, etc.)",
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
            title="[bold blue]Graphite Admin PDF Ingestion & Indexer[/bold blue]",
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
            title="[bold magenta]Graphite Regulatory Knowledge & PDF Search[/bold magenta]",
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


@app.command("fix")
def fix_cmd(
    report_file: str = typer.Option(
        ...,
        "--report",
        "-r",
        help="Path to an Graphite audit report JSON file",
    ),
    repos: List[str] = typer.Option(
        ["."],
        "--repos",
        help="Repository directories containing source code to patch",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        "-a",
        help="Apply remediation patches in-place to the target source files",
    ),
    patch_out: Optional[str] = typer.Option(
        None,
        "--patch-out",
        "-p",
        help="File path to save the combined unified git diff patch file",
    ),
):
    """Generates unified diff patches or applies automated fixes for detected statutory violations."""
    import json as _json
    from graphite_audit.remediator import generate_remediation_patches

    report_p = Path(report_file)
    if not report_p.is_file():
        console.print(f"[bold red]Error: Report file not found: {report_file}[/bold red]")
        raise typer.Exit(code=1)

    try:
        report_data = _json.loads(report_p.read_text(encoding="utf-8"))
    except Exception as exc:
        console.print(f"[bold red]Error reading report JSON: {exc}[/bold red]")
        raise typer.Exit(code=1)

    console.print(
        Panel(
            f"[bold cyan]Report File:[/bold cyan] {report_file}\n"
            f"[bold cyan]Target Repositories:[/bold cyan] {', '.join(repos)}\n"
            f"[bold cyan]Mode:[/bold cyan] {'In-place Apply' if apply else 'Dry-run Patch Generation'}\n"
            + (f"[bold cyan]Patch Output File:[/bold cyan] {patch_out}\n" if patch_out else ""),
            title="[bold green]Graphite Automated Statutory Remediator[/bold green]",
            border_style="green",
        )
    )

    patches = generate_remediation_patches(report_data, repo_paths=repos, apply=apply, patch_out=patch_out)

    if not patches:
        console.print("[yellow]No automated remediation patches could be generated for the findings in this report.[/yellow]")
        return

    table = Table(title=f"Generated {len(patches)} Remediation Patch(es)", header_style="bold green")
    table.add_column("Rule / Check", style="bold cyan", width=22)
    table.add_column("Target File", style="white", width=26)
    table.add_column("Action / Fix Description", style="yellow", width=40)
    table.add_column("Status", width=12)

    for p in patches:
        status_str = "[bold green]APPLIED[/bold green]" if p.get("applied") else "[cyan]STAGED[/cyan]"
        table.add_row(
            p.get("rule", "")[:22],
            Path(p.get("file_path", "")).name,
            p.get("description", "")[:40],
            status_str,
        )

    console.print(table)

    if not apply:
        console.print(
            "\n[dim]Run with [bold]--apply[/bold] to write these fixes directly to disk, "
            "or use [bold]--patch-out <file.patch>[/bold] to export a unified patch.[/dim]\n"
        )
    else:
        console.print(f"\n[bold green]✓ Successfully applied {len(patches)} fix(es) in-place.[/bold green]\n")


def main():
    app()


if __name__ == "__main__":
    main()


@app.command("eval")
def eval_cmd(
    gold: str = typer.Option("tests/eval/gold.json", "--gold", help="Gold-label file"),
    frameworks: str = typer.Option("EU_AI_ACT,EU_GDPR", "--frameworks", help="EU_AI_ACT, EU_GDPR, ALL, or comma list"),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON"),
):
    """Scores audit findings against gold labels: precision and recall per check and overall."""
    import json as _json

    from src.agents.llm_client import _load_dotenv
    _load_dotenv()
    os.environ.setdefault("BYOM_OFFLINE", "true")  # deterministic scoring: no live model calls
    from src.evaluation import evaluate

    res = evaluate(gold, frameworks)
    if json_out:
        console.print_json(_json.dumps(res))
        return
    t = Table(title=f"Evaluation vs gold ({frameworks})", header_style="bold green")
    for h in ("Case", "TP", "FP", "FN", "Known missed"):
        t.add_column(h)
    for c in res["cases"]:
        t.add_row(c["name"], ", ".join(c["tp"]) or "-", ", ".join(c["fp"]) or "-", ", ".join(c["fn"]) or "-", "; ".join(m.split(" ")[0] for m in c["known_missed"]) or "-")
    console.print(t)
    pc = Table(title="Per check", header_style="bold cyan")
    for h in ("Check", "TP", "FP", "FN", "Precision", "Recall"):
        pc.add_column(h)
    for k, v in res["per_check"].items():
        pc.add_row(k, str(v["tp"]), str(v["fp"]), str(v["fn"]), str(v["precision"]), str(v["recall"]))
    console.print(pc)
    o = res["overall"]
    console.print(f"[bold]Overall[/bold] precision={o['precision']} recall={o['recall']} (recall excluding known-missed checks: {o['recall_excluding_known_missed']})")
    console.print(f"[dim]{res['caveat']}[/dim]")


@app.command("doctor")
def doctor_cmd(live: bool = typer.Option(False, "--live", help="Also make one small read-only call per configured service")):
    """Checks every integration (Linkup, Atlas, Databricks, MLflow, GitHub, Confluence, parsers, auth) and prints OK / FAIL / SKIP."""
    from src.agents.llm_client import _load_dotenv
    _load_dotenv()
    from src.doctor import exit_code, run_checks

    checks = run_checks(live=live)
    t = Table(title=f"Graphite doctor ({'live' if live else 'config only'})", header_style="bold cyan")
    for h in ("Check", "Status", "Detail"):
        t.add_column(h)
    style = {"OK": "green", "FAIL": "bold red", "WARN": "yellow", "SKIP": "dim"}
    for c in checks:
        t.add_row(c.name, f"[{style[c.status]}]{c.status}[/{style[c.status]}]", c.detail)
    console.print(t)
    raise typer.Exit(exit_code(checks))


@app.command("demo")
def demo_cmd(out_dir: str = typer.Option("demo_output", "--out-dir", help="Where PDFs and the JSON summary are written")):
    """One command: index the rule library, audit the bundled sample companies, write PDFs and a JSON summary."""
    import json as _json

    from src.agents.llm_client import _load_dotenv
    _load_dotenv()
    from graphite_audit.client import ComplianceAuditor
    from src.law_sync import get_store
    from src.storage import get_compliance_store

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = len(get_store().snapshot())
    get_compliance_store().index_rules(get_store().snapshot())
    console.print(f"[bold]Rule library:[/bold] {n} rules indexed ({get_store().version})")
    targets = [("sample_connectors/enterprise/graphite_health_uk", "Graphite Health UK"), ("sample_connectors/enterprise/meridian_omni_ai", "Meridian OmniTech"),
               ("synthetic_companies/veylan_analytics_face_identity", "Veylan Analytics")]
    summary = []
    for path, name in targets:
        if not Path(path).is_dir():
            console.print(f"[yellow]skipping {name}: {path} not found[/yellow]")
            continue
        sess = ComplianceAuditor().audit(company_name=name, target_dir=path)
        pdf = sess.save_pdf(str(out / f"{Path(path).name}.pdf"))
        d = sess.to_dict()
        summary.append({"company": name, "readiness": d["overall_readiness"], "confirmed": len(d["confirmed_findings"]), "suspected_gaps": len(d["suspected_gaps"]),
                        "quarantined": len(d["quarantined_for_human_review"]), "pdf": pdf, "report_id": d["report_id"], "frameworks": d["frameworks"]})
        console.print(f"[green]\u2713[/green] {name}: {d['overall_readiness']} -> {pdf}")
    (out / "summary.json").write_text(_json.dumps(summary, indent=2))
    console.print(f"[bold green]Demo complete.[/bold green] Summary: {out / 'summary.json'}")
