"""Deterministic document parser: .md / .txt / .pdf -> DocumentChunk + ComplianceAssertion."""
from __future__ import annotations

import re
from pathlib import Path

from src.schemas.artifacts import ComplianceAssertion, DocumentChunk, sha256_text

from .code_scanner import SKIP_DIRS

from .doc_formats import OFFICE_SUFFIXES, read_document

DOC_SUFFIXES = {".md", ".txt", ".pdf"} | OFFICE_SUFFIXES
_MD_HEADER = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_NUM_HEADER = re.compile(r"^\d+(\.\d+)*[.)]?\s+[A-Z][^.!?]{2,80}$")
_UNDERLINE = re.compile(r"^\s*(=|-){3,}\s*$")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def _is_plain_header(line: str, nxt: str | None) -> bool:
    s = line.strip()
    if not s or len(s) > 80:
        return False
    if nxt is not None and _UNDERLINE.match(nxt):
        return True
    if _NUM_HEADER.match(s):
        return True
    return s.isupper() and len(s) > 3 and not s.endswith(".")


def _marker_chunk(rel: str, tenant_id: str, header: str, text: str) -> list[DocumentChunk]:
    """A visible placeholder chunk for a document that could not be read, so the audit never silently ignores it."""
    sha = sha256_text(text + rel)
    return [DocumentChunk(chunk_id=f"chunk-{sha256_text(f'{tenant_id}:{rel}:marker')[:12]}", tenant_id=tenant_id, doc_name=rel,
                          section_header=header, line_range=(1, 1), text=text, sha256_hash=sha)]


def parse_document(path: Path, rel: str, tenant_id: str) -> list[DocumentChunk]:
    if path.suffix.lower() in OFFICE_SUFFIXES:
        text = read_document(path)
        if text is None or not text.strip():
            return _marker_chunk(rel, tenant_id, "UNPARSED_DOCUMENT",
                                 f"Document {rel} could not be parsed or is empty; its content is unverified (closed-world).")
        return parse_text(text, rel, tenant_id, is_md=True)
    if path.suffix.lower() == ".pdf":
        try:
            from .pdf_ingestor import ingest_pdf_file
            pdf_chunks = ingest_pdf_file(
                pdf_path=path,
                jurisdiction="EU_AI_ACT",
                tenant_id=tenant_id,
                doc_category="COMPANY_DOC",
            )
            if not pdf_chunks or sum(len(c.text) for c in pdf_chunks) < 40:
                return _ocr_or_marker(path, rel, tenant_id)
            return [c.to_document_chunk() for c in pdf_chunks]
        except Exception:
            text = _read_pdf(path)
            return parse_text(text, rel, tenant_id, is_md=False)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        return parse_text(text, rel, tenant_id, is_md=path.suffix.lower() == ".md")


def _ocr_or_marker(path: Path, rel: str, tenant_id: str) -> list[DocumentChunk]:
    """Scanned PDF: OCR when pytesseract + pypdfium2 are present (low confidence -> human review), else a marker chunk."""
    try:
        import pypdfium2 as pdfium
        import pytesseract

        pdf = pdfium.PdfDocument(str(path))
        pages, confs = [], []
        for i in range(len(pdf)):
            img = pdf[i].render(scale=2).to_pil()
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            words = [(w, float(c)) for w, c in zip(data["text"], data["conf"]) if w.strip() and float(c) >= 0]
            pages.append(f"## Page {i + 1}\n" + " ".join(w for w, _ in words))
            confs += [c for _, c in words]
        mean = sum(confs) / len(confs) if confs else 0.0
        chunks = parse_text("\n".join(pages), rel, tenant_id, is_md=True)
        if mean < 70:
            chunks += _marker_chunk(rel, tenant_id, "LOW_OCR_CONFIDENCE",
                                    f"OCR of {rel} had mean confidence {mean:.0f}/100; extracted text needs human review.")
        return chunks
    except Exception:
        return _marker_chunk(rel, tenant_id, "OCR_REQUIRED",
                             f"{rel} is a scanned or image-only PDF and OCR is unavailable; its content is unverified (closed-world).")


def parse_text(text: str, rel: str, tenant_id: str, is_md: bool = False) -> list[DocumentChunk]:
    lines = text.splitlines()

    chunks: list[DocumentChunk] = []
    header, start, buf = "(preamble)", 1, []

    def flush(end: int):
        body = "\n".join(buf).strip()
        if body:
            sha = sha256_text(body)
            chunks.append(DocumentChunk(
                chunk_id=f"chunk-{sha256_text(f'{tenant_id}:{rel}:{start}')[:12]}", tenant_id=tenant_id,
                doc_name=rel, section_header=header, line_range=(start, max(start, end)), text=body, sha256_hash=sha,
            ))

    for i, line in enumerate(lines, 1):
        nxt = lines[i] if i < len(lines) else None
        m = _MD_HEADER.match(line) if is_md or line.lstrip().startswith("#") else None
        if m or (not is_md and _is_plain_header(line, nxt)):
            flush(i - 1)
            header = (m.group(2) if m else line.strip()).strip()
            start, buf = i, [line]
            continue
        if _UNDERLINE.match(line) and buf and len(buf) == 1:
            buf.append(line)
            continue
        buf.append(line)
    flush(len(lines))
    return chunks


def parse_documents(company_dir: Path | str, tenant_id: str, skip_top_dirs: set[str] | None = None) -> list[DocumentChunk]:
    root = Path(company_dir)
    skip_top_dirs = skip_top_dirs or set()
    chunks: list[DocumentChunk] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in DOC_SUFFIXES:
            continue
        if set(p.relative_to(root).parts[:-1]) & SKIP_DIRS:
            continue
        if p.relative_to(root).parts[0] in skip_top_dirs and len(p.relative_to(root).parts) > 1:
            continue
        if p.name.lower().startswith("requirements"):
            continue
        chunks.extend(parse_document(p, p.relative_to(root).as_posix(), tenant_id))
    return chunks


# ----------------------------------------------------------------------------- assertions
_CLAIMS: list[tuple[str, str, re.Pattern, re.Pattern | None]] = [
    ("PRIVACY", "pii_redaction_before_external_call",
     re.compile(r"\b(pii|personal(ly)?[- ]?(identifiable)?\s*(data|information)|names?|emails?|identifiers?|customer data|patient data)\b", re.I),
     re.compile(r"\b(mask\w*|redact\w*|anonymi[sz]\w*|pseudonymi[sz]\w*|scrub\w*|strip\w*|remov\w*|de-?identif\w*)\b", re.I)),
    ("HOSTING", "eu_uk_hosting_only",
     re.compile(r"\b(host\w*|stored|processed|process\w*|reside\w*|residen\w+|servers?|regions?|infrastructure|data centres?|data centers?|inference)\b", re.I),
     re.compile(r"\b(EU|E\.U\.|European|Europe|UK|U\.K\.|United Kingdom|Britain|London|Frankfurt|Dublin|Ireland)\b")),
    ("HITL", "human_approval_gate",
     re.compile(r"\b(human|analyst|clinician|reviewer|manual|underwriter|officer|person|doctor|physician)\b", re.I),
     re.compile(r"\b(review\w*|approv\w*|oversight|in[- ]the[- ]loop|sign[- ]?off|overrid\w*|verif\w*|confirm\w*)\b", re.I)),
    ("SAFETY_MODERATION", "moderation_hook",
     re.compile(r"\b(hate|toxic\w*|harm\w*|abusive|offensive|unsafe|prohibited content|illegal content)\b", re.I),
     re.compile(r"\b(filter\w*|moderat\w*|block\w*|refus\w*|prevent\w*|screen\w*|classif\w*|detect\w*)\b", re.I)),
    ("WATERMARK", "ai_generated_watermark",
     re.compile(r"\b(watermark\w*|c2pa|content credentials|machine[- ]readable|ai[- ]generated|synthetic (content|media|audio|text|voice))\b", re.I),
     re.compile(r"\b(mark\w*|label\w*|embed\w*|disclos\w*|tag\w*|header|metadata|signal\w*|watermark\w*|c2pa|content credentials)\b", re.I)),
    ("IP_LICENSE", "commercial_license_rights",
     re.compile(r"\b(commercial\w*)\b", re.I),
     re.compile(r"\b(licen[cs]\w*|rights|permitted|permissive|open[- ]source)\b", re.I)),
]
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n\s*[-*•]\s+|\n+")
_NEGATED_RE = re.compile(r"\b(we do not|we don't|does not|do not|not currently|no longer|isn't|is not|are not|never)\s+(mask|redact|anonymi|filter|moderat|watermark|label|review|host)", re.I)


def extract_assertions(chunks: list[DocumentChunk]) -> list[ComplianceAssertion]:
    out: list[ComplianceAssertion] = []
    for ch in chunks:
        if ch.doc_name.lower().startswith(("requirements",)):
            continue
        for sent in _SENT_SPLIT.split(ch.text):
            s = sent.strip(" \t#*-•")
            if len(s) < 20 or _NEGATED_RE.search(s):
                continue
            for claim_type, control, subj, act in _CLAIMS:
                if subj.search(s) and (act is None or act.search(s)):
                    if claim_type == "IP_LICENSE" and not re.search(r"\b(model|weights|dependenc\w*|librar\w*|open[- ]source|training|licen[cs]\w*)\b", s, re.I):
                        continue
                    if claim_type == "HITL" and not re.search(r"\b(decision|review|approv\w*|oversight|loop|sign[- ]?off|overrid\w*)\b", s, re.I):
                        continue
                    out.append(ComplianceAssertion(
                        assertion_id=f"asrt-{sha256_text(f'{ch.chunk_id}:{claim_type}:{s}')[:12]}",
                        tenant_id=ch.tenant_id, source_chunk_id=ch.chunk_id, claim_type=claim_type,
                        claim_text=s[:400], expected_control=control,
                    ))
    return out


# ----------------------------------------------------------------------------- LLM claim extraction (additive to the regex floor)
def extract_assertions_llm(chunks: list[DocumentChunk], llm, max_chunks: int = 60) -> list[ComplianceAssertion]:
    """Paraphrase-tolerant claim extraction via the model; a claim is kept only if its quote appears verbatim in the chunk.

    Negated statements ("we do not redact") describe the absence of a control, not a promise, and are dropped.
    Returns [] when no model is reachable, so the regex extractor stays the deterministic floor.
    """
    import json as _json
    from typing import Literal

    from pydantic import BaseModel, Field

    if llm is None or not getattr(llm, "available", lambda: False)():
        return []

    class _Claim(BaseModel):
        claim_type: Literal["PRIVACY", "HOSTING", "HITL", "SAFETY_MODERATION", "WATERMARK", "IP_LICENSE"]
        quote: str
        negated: bool = False

    class _Claims(BaseModel):
        claims: list[_Claim] = Field(default_factory=list)

    system = ("You extract compliance PROMISES made by a company document. Types: PRIVACY (personal data is masked/redacted before external "
              "calls), HOSTING (data stays in EU regions), HITL (a human reviews/approves decisions), SAFETY_MODERATION (harmful content is "
              "filtered), WATERMARK (AI outputs are marked/labelled), IP_LICENSE (commercial rights to models/dependencies). Copy `quote` "
              "EXACTLY from the text. Set negated=true if the sentence says the control is NOT done.")
    norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()
    out: list[ComplianceAssertion] = []
    failures = {"n": 0}

    def _fallback():
        failures["n"] += 1
        return _Claims()

    for ch in chunks[:max_chunks]:
        if failures["n"] >= 2:  # model unreachable/misconfigured: stop early, the regex floor already ran
            break
        if len(ch.text) < 30 or ch.section_header in {"UNPARSED_DOCUMENT", "OCR_REQUIRED", "LOW_OCR_CONFIDENCE"}:
            continue
        res = llm.structured(system, ch.text[:6000], _Claims, _fallback)
        for c in res.claims:
            if c.negated or not c.quote or norm(c.quote) not in norm(ch.text):
                continue  # hallucinated or negated: never becomes an assertion
            out.append(ComplianceAssertion(
                assertion_id=f"asrt-{sha256_text(f'{ch.chunk_id}:{c.claim_type}:{c.quote}')[:12]}", tenant_id=ch.tenant_id,
                source_chunk_id=ch.chunk_id, claim_type=c.claim_type, claim_text=c.quote[:400],
                expected_control=next(ctl for t, ctl, _, _ in _CLAIMS if t == c.claim_type)))
    return out
