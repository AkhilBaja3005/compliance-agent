"""Office/web document readers, unparsable-file markers, and LLM claim extraction guards."""
from __future__ import annotations

import docx
import openpyxl
import pytest
from pptx import Presentation

from src.edge_extractors.doc_parser import extract_assertions, extract_assertions_llm, parse_document
from src.edge_extractors.doc_formats import read_document

CLAIM = "Customer data is hosted only in EU regions and personal data is masked before any external call."


def _chunks(path, name):
    return parse_document(path, name, "t")


def test_docx_headings_tables_and_claims(tmp_path):
    d = docx.Document()
    d.add_heading("Data Handling Policy", level=1)
    d.add_paragraph(CLAIM)
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Control", "Owner"
    p = tmp_path / "policy.docx"
    d.save(p)
    text = read_document(p)
    assert text.startswith("# Data Handling Policy") and "| Control | Owner |" in text
    chunks = _chunks(p, "policy.docx")
    assert any(c.section_header == "Data Handling Policy" for c in chunks)
    assert {a.claim_type for a in extract_assertions(chunks)} >= {"HOSTING", "PRIVACY"}


def test_xlsx_cell_addresses_and_formulas_not_evaluated(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Register"
    ws.append(["System", "Owner"])
    ws.append(["Credit Engine", "Risk"])
    ws["C2"] = "=1+1"
    p = tmp_path / "register.xlsx"
    wb.save(p)
    text = read_document(p)
    assert "## Sheet Register" in text and "[Register!A2:B2] Credit Engine | Risk" in text


def test_pptx_slides_and_speaker_notes(tmp_path):
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Oversight"
    s.placeholders[1].text = "A human reviews every credit decision."
    s.notes_slide.notes_text_frame.text = "We do not use customer data for training."
    p = tmp_path / "deck.pptx"
    prs.save(p)
    text = read_document(p)
    assert "## Slide 1: Oversight" in text and "Speaker notes (slide 1)" in text


@pytest.mark.parametrize("name,body,needle", [
    ("page.html", "<h1>Policy</h1><script>evil()</script><p>Outputs are watermarked.</p><table><tr><td>a</td><td>b</td></tr></table>", "# Policy"),
    ("note.rtf", r"{\rtf1\ansi Outputs are \b watermarked\b0 .\par Next.}", "watermarked"),
    ("reg.csv", "system,owner\ncredit,risk\n", "[row 2] credit | risk"),
])
def test_html_rtf_csv(tmp_path, name, body, needle):
    p = tmp_path / name
    p.write_text(body)
    text = read_document(p)
    assert needle in text and "evil()" not in text


def test_corrupt_office_file_yields_visible_unparsed_marker(tmp_path):
    p = tmp_path / "broken.docx"
    p.write_bytes(b"not a zip")
    chunks = _chunks(p, "broken.docx")
    assert [c.section_header for c in chunks] == ["UNPARSED_DOCUMENT"]


class FakeLLM:
    def __init__(self, claims):
        self._claims = claims

    def available(self):
        return True

    def structured(self, system, user, schema, fallback):
        return schema.model_validate({"claims": self._claims})


def test_llm_claims_require_verbatim_quote_and_drop_negations(tmp_path):
    p = tmp_path / "p.md"
    p.write_text("# Oversight\nEvery loan outcome is double-checked by an underwriter before release.\nWe never redact emails.\n")
    chunks = _chunks(p, "p.md")
    llm = FakeLLM([
        {"claim_type": "HITL", "quote": "Every loan outcome is double-checked by an underwriter before release."},
        {"claim_type": "HITL", "quote": "A quote the model invented that is not in the document."},
        {"claim_type": "PRIVACY", "quote": "We never redact emails.", "negated": True},
    ])
    got = extract_assertions_llm(chunks, llm)
    assert [(a.claim_type, a.claim_text) for a in got] == [("HITL", "Every loan outcome is double-checked by an underwriter before release.")]
    assert extract_assertions_llm(chunks, None) == []  # offline: regex floor only
