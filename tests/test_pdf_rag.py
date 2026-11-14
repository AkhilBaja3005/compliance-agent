"""Tests for Admin PDF Ingestion, Indexing, and Retrieval."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from weasyprint import HTML

from src.edge_extractors.pdf_ingestor import ingest_pdf_file
from src.storage import MongoComplianceStore
from src.schemas.findings import ComplianceFinding, EvidencePointer
from src.guardrails import gate1_citations
from src.guardrails.common import GateContext
from src.edge_extractors import TriModalIndex
from src.law_sync import get_store


@pytest.fixture
def sample_eu_ai_act_pdf(tmp_path: Path) -> Path:
    """Generates a realistic multi-page EU AI Act regulatory PDF fixture."""
    pdf_path = tmp_path / "EU_AI_Act_Regulation_2024_1689.pdf"
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            @page { size: A4; margin: 20mm; }
            h1 { color: #1E3A8A; font-size: 18pt; }
            h2 { color: #1F2937; font-size: 14pt; margin-top: 15pt; }
            p { font-size: 10pt; line-height: 1.5; color: #374151; }
            .page-break { page-break-before: always; }
        </style>
    </head>
    <body>
        <h1>REGULATION (EU) 2024/1689 OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL</h1>
        <p>Laying down harmonised rules on artificial intelligence (Artificial Intelligence Act).</p>
        
        <h2>Article 5 - Prohibited Artificial Intelligence Practices</h2>
        <p>1. The following artificial intelligence practices shall be prohibited:
        (a) the placing on the market, the putting into service or the use of an AI system that deploys subliminal techniques beyond a person's consciousness;
        (b) the placing on the market, the putting into service or the use of an AI system that exploits any of the vulnerabilities of a natural person;
        (c) the placing on the market, the putting into service or the use of AI systems for the evaluation or classification of natural persons over a certain period of time based on their social behaviour;
        (d) the use of AI systems for non-consensual biometric identification or intimate image synthesis without strict verification.</p>

        <div class="page-break"></div>

        <h2>Article 14 - Human Oversight</h2>
        <p>1. High-risk AI systems shall be designed and developed in such a way, including with appropriate human-machine interface tools, that they can be effectively overseen by natural persons during the period in which they are in use.
        2. Human oversight shall aim to prevent or minimise the risks to health, safety or fundamental rights that may emerge when a high-risk AI system is used in accordance with its intended purpose.</p>

        <h2>Article 50 - Transparency Obligations for Providers and Deployers</h2>
        <p>1. Providers shall ensure that AI systems intended to interact directly with natural persons are designed and developed in such a way that the natural persons concerned are informed that they are interacting with an AI system.
        2. Providers of AI systems, including general-purpose AI systems, generating synthetic audio, image, video or text content, shall ensure that the outputs of the AI system are marked in a machine-readable format and detectable as artificially generated or manipulated.
        3. Compliance with watermarking and machine-readable metadata standards such as C2PA shall be enforced across member states no later than 2 December 2026.</p>

        <div class="page-break"></div>

        <h2>Annex III - High-Risk AI Systems</h2>
        <p>High-risk AI systems pursuant to Article 6(2) are the AI systems listed in any of the following areas:
        1. Biometrics, in so far as their use is permitted under relevant Union or national law;
        2. Critical infrastructure;
        3. Educational and vocational training;
        4. Employment, workers management and access to self-employment (including candidate ranking and automated resume screening);
        5. Access to and enjoyment of essential private services and public services and benefits (including creditworthiness evaluation).</p>
    </body>
    </html>
    """
    HTML(string=html_content).write_pdf(str(pdf_path))
    return pdf_path


def test_pdf_parsing_and_chunking(sample_eu_ai_act_pdf: Path):
    """Verifies that ingest_pdf_file parses statutory headings, locators, and SHA-256 hashes."""
    chunks = ingest_pdf_file(
        pdf_path=sample_eu_ai_act_pdf,
        jurisdiction="EU_AI_ACT",
        tenant_id="global_regulations",
        doc_category="REGULATORY_PDF",
    )

    assert len(chunks) >= 4, f"Expected at least 4 chunks, got {len(chunks)}"

    # Check statutory headings
    titles = [c.section_title for c in chunks]
    assert any("Article 5" in t for t in titles), f"Missing Article 5 in {titles}"
    assert any("Article 14" in t for t in titles), f"Missing Article 14 in {titles}"
    assert any("Article 50" in t for t in titles), f"Missing Article 50 in {titles}"
    assert any("Annex III" in t for t in titles), f"Missing Annex III in {titles}"

    # Check locator formatting
    for c in chunks:
        assert "#page=" in c.exact_locator
        assert len(c.sha256_hash) == 64
        assert c.source_type == "REGULATORY_PDF"


def test_pdf_indexing_and_search(sample_eu_ai_act_pdf: Path):
    """Verifies indexing into MongoComplianceStore and hybrid retrieval."""
    chunks = ingest_pdf_file(
        pdf_path=sample_eu_ai_act_pdf,
        jurisdiction="EU_AI_ACT",
        tenant_id="global_regulations",
        doc_category="REGULATORY_PDF",
    )

    store = MongoComplianceStore()
    indexed_count = store.index_pdf_chunks(chunks)
    assert indexed_count == len(chunks)

    # Search for Article 50 watermarking
    results = store.search_regulatory_knowledge("Article 50 watermarking machine-readable C2PA", top_k=3)
    assert len(results) > 0

    top_hit = results[0]
    assert "50" in top_hit.get("text", "") or "watermark" in top_hit.get("text", "").lower()
    assert "#page=" in top_hit.get("exact_locator", "")
    assert top_hit.get("sha256_hash") is not None


def test_gate1_citations_accepts_pdf_evidence(sample_eu_ai_act_pdf: Path):
    """Verifies that Guardrail Gate 1 accepts Regulatory PDF evidence pointers without quarantine."""
    chunks = ingest_pdf_file(
        pdf_path=sample_eu_ai_act_pdf,
        jurisdiction="EU_AI_ACT",
        tenant_id="global_regulations",
        doc_category="REGULATORY_PDF",
    )
    art50_chunk = next(c for c in chunks if "Article 50" in c.section_title)

    law_store = get_store()
    rule_id = "EU_AI_ACT:Art.50"
    assert law_store.has_rule(rule_id)

    # Construct finding citing both code and the ingested regulatory PDF
    pdf_ev = EvidencePointer(
        source_type="Regulatory PDF",
        artifact_id=art50_chunk.chunk_id,
        exact_locator=art50_chunk.exact_locator,
        sha256_hash=art50_chunk.sha256_hash,
        snippet=art50_chunk.text[:100],
    )

    finding = ComplianceFinding(
        finding_id="TEST-FINDING-001",
        tenant_id="test_tenant",
        jurisdiction="EU_AI_ACT",
        regulatory_reference=rule_id,
        risk_tier="LIMITED_RISK",
        status="CONFIRMED_VIOLATION",
        confidence_score=0.95,
        title="Missing Machine-Readable Watermarking",
        summary="Synthetic media output omits C2PA machine-readable markings per Article 50(2).",
        evidence=[pdf_ev],
    )

    empty_index = TriModalIndex(tenant_id="test_tenant", company_name="Test Corp", sector="tech")
    ctx = GateContext(index=empty_index, store=law_store, trace=[])

    filtered = gate1_citations.apply([finding], ctx)
    assert len(filtered) == 1
    assert filtered[0].status == "CONFIRMED_VIOLATION", f"Finding was quarantined: {filtered[0].quarantine_reason}"
