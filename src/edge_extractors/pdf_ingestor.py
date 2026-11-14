"""PDF Parser & Article/Section Chunker for Regulatory & Company Documentation.

Extracts text page-by-page using pypdf (with pdfplumber fallback for tables/multi-column layouts),
splits into structured chunks preserving statutory headings (Article, Section, Annex, Chapter, etc.)
with overlapping sliding windows (~800 chars, 120 overlap) for long text.
Stamps exact_locator ("{filename}#page={page_num}:{section_title}"), page_number, sha256_hash,
and source_type.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.schemas.artifacts import ComplianceAssertion, DocumentChunk, sha256_text

# Regex for statutory / legal / executive headings
_STATUTORY_HEADING = re.compile(
    r"^(Article\s+\d+[a-z]?|Section\s+\d+[a-z]?|Annex\s+[IVXLCDM\d]+|Chapter\s+[IVXLCDM\d]+|Recital\s+\d+|Part\s+\d+|Schedule\s+\d+)"
    r"(?:\s*[-–—:]\s*(.+))?",
    re.IGNORECASE
)
_MD_OR_TITLE_HEADING = re.compile(r"^(#{1,6}\s+|[A-Z0-9\.\s]{3,80}$)")


class PDFChunk:
    """Represents an ingested chunk from a PDF."""

    def __init__(
        self,
        chunk_id: str,
        filename: str,
        page_number: int,
        section_title: str,
        text: str,
        exact_locator: str,
        sha256_hash: str,
        tenant_id: str = "global_regulations",
        jurisdiction: str = "EU_AI_ACT",
        source_type: str = "REGULATORY_PDF",
    ):
        self.chunk_id = chunk_id
        self.filename = filename
        self.page_number = page_number
        self.section_title = section_title
        self.text = text
        self.exact_locator = exact_locator
        self.sha256_hash = sha256_hash
        self.tenant_id = tenant_id
        self.jurisdiction = jurisdiction
        self.source_type = source_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "filename": self.filename,
            "page_number": self.page_number,
            "section_title": self.section_title,
            "text": self.text,
            "exact_locator": self.exact_locator,
            "sha256_hash": self.sha256_hash,
            "tenant_id": self.tenant_id,
            "jurisdiction": self.jurisdiction,
            "source_type": self.source_type,
        }

    def to_document_chunk(self) -> DocumentChunk:
        return DocumentChunk(
            chunk_id=self.chunk_id,
            tenant_id=self.tenant_id,
            doc_name=self.filename,
            section_header=f"Page {self.page_number}: {self.section_title}",
            line_range=(self.page_number, self.page_number),
            text=self.text,
            sha256_hash=self.sha256_hash,
        )


def _extract_page_text(page_idx: int, pypdf_page: Any, pdfplumber_pdf: Any = None) -> str:
    """Extracts text using pypdf, falling back to pdfplumber if extracted text is sparse."""
    text = ""
    try:
        text = pypdf_page.extract_text() or ""
    except Exception:
        text = ""

    # If pypdf yielded sparse text (e.g. multi-column or table), try pdfplumber
    if len(text.strip()) < 50 and pdfplumber_pdf is not None:
        try:
            if page_idx < len(pdfplumber_pdf.pages):
                plumber_page = pdfplumber_pdf.pages[page_idx]
                plumber_text = plumber_page.extract_text(layout=True) or ""
                if len(plumber_text.strip()) > len(text.strip()):
                    text = plumber_text
        except Exception:
            pass

    return text.strip()


def _chunk_text_with_sliding_window(
    text: str, window_size: int = 800, overlap: int = 120
) -> List[str]:
    """Splits a long paragraph or section into overlapping sliding window chunks."""
    if len(text) <= window_size:
        return [text]

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + window_size, text_len)
        # Try to break on a sentence boundary or newline if possible
        if end < text_len:
            last_period = text.rfind(".", start + window_size // 2, end)
            last_newline = text.rfind("\n", start + window_size // 2, end)
            break_point = max(last_period, last_newline)
            if break_point > start:
                end = break_point + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break
        start = max(start + 1, end - overlap)

    return chunks


def ingest_pdf_file(
    pdf_path: str | Path,
    jurisdiction: str = "EU_AI_ACT",
    tenant_id: str = "global_regulations",
    doc_category: str = "REGULATORY_PDF",
) -> List[PDFChunk]:
    """
    Parses a PDF into structured chunks with statutory headings and sliding windows.
    Returns list of PDFChunk objects stamped with exact_locator and sha256_hash.
    """
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PDF file not found: {path}")

    filename = path.name

    # Initialize readers
    from pypdf import PdfReader
    pypdf_reader = PdfReader(str(path))

    pdfplumber_pdf = None
    try:
        import pdfplumber
        pdfplumber_pdf = pdfplumber.open(str(path))
    except Exception:
        pdfplumber_pdf = None

    chunks: List[PDFChunk] = []
    current_section = "General"

    try:
        for page_idx, page in enumerate(pypdf_reader.pages):
            page_num = page_idx + 1
            page_text = _extract_page_text(page_idx, page, pdfplumber_pdf)
            if not page_text:
                continue

            lines = page_text.splitlines()
            current_section_lines = []

            for line in lines:
                s_line = line.strip()
                if not s_line:
                    continue

                # Check if this line is a statutory heading (Article, Section, Annex, etc.)
                m_stat = _STATUTORY_HEADING.match(s_line)
                if m_stat:
                    # Flush previous section lines
                    if current_section_lines:
                        sec_body = "\n".join(current_section_lines).strip()
                        if sec_body:
                            for window in _chunk_text_with_sliding_window(sec_body):
                                sha = sha256_text(window)
                                locator = f"{filename}#page={page_num}:{current_section}"
                                c_id = f"pdf-{sha256_text(f'{filename}:{page_num}:{sha}')[:12]}"
                                chunks.append(
                                    PDFChunk(
                                        chunk_id=c_id,
                                        filename=filename,
                                        page_number=page_num,
                                        section_title=current_section,
                                        text=window,
                                        exact_locator=locator,
                                        sha256_hash=sha,
                                        tenant_id=tenant_id,
                                        jurisdiction=jurisdiction,
                                        source_type=doc_category,
                                    )
                                )
                        current_section_lines = []

                    heading_prefix = m_stat.group(1).strip()
                    heading_title = m_stat.group(2).strip() if m_stat.group(2) else ""
                    current_section = f"{heading_prefix} - {heading_title}" if heading_title else heading_prefix
                    current_section_lines.append(s_line)
                    continue

                current_section_lines.append(s_line)

            # Flush remaining lines on this page
            if current_section_lines:
                sec_body = "\n".join(current_section_lines).strip()
                if sec_body:
                    for window in _chunk_text_with_sliding_window(sec_body):
                        sha = sha256_text(window)
                        locator = f"{filename}#page={page_num}:{current_section}"
                        c_id = f"pdf-{sha256_text(f'{filename}:{page_num}:{sha}')[:12]}"
                        chunks.append(
                            PDFChunk(
                                chunk_id=c_id,
                                filename=filename,
                                page_number=page_num,
                                section_title=current_section,
                                text=window,
                                exact_locator=locator,
                                sha256_hash=sha,
                                tenant_id=tenant_id,
                                jurisdiction=jurisdiction,
                                source_type=doc_category,
                            )
                        )

    finally:
        if pdfplumber_pdf is not None:
            try:
                pdfplumber_pdf.close()
            except Exception:
                pass

    return chunks
