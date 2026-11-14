"""Office/web/text document readers: .docx .xlsx .pptx .html .rtf .odt .csv .tsv .txt -> Markdown-like text.

Output keeps headings as `#` lines, slide/sheet/page markers as `##` headings and tables as `|` rows so the shared chunker
produces locators like `deck.pptx` + section header "Slide 3: Title" / "Sheet Policies" with stable line ranges.
Parsing only: macros and embedded scripts are never executed.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

OFFICE_SUFFIXES = {".docx", ".xlsx", ".pptx", ".html", ".htm", ".rtf", ".odt", ".csv", ".tsv"}


def _docx(path: Path) -> str:
    import docx  # python-docx

    d = docx.Document(str(path))
    out: list[str] = []
    body = d.element.body
    paras = {p._p: p for p in d.paragraphs}
    tables = {t._tbl: t for t in d.tables}
    for el in body.iterchildren():
        if el in paras:
            p = paras[el]
            txt = p.text.strip()
            if not txt:
                continue
            style = (p.style.name or "") if p.style is not None else ""
            m = re.match(r"Heading (\d)", style)
            if m:
                out.append("#" * min(6, int(m.group(1))) + " " + txt)
            elif style == "Title":
                out.append("# " + txt)
            elif "List" in style:
                out.append("- " + txt)
            else:
                out.append(txt)
        elif el in tables:
            for row in tables[el].rows:
                out.append("| " + " | ".join(c.text.strip().replace("\n", " ") for c in row.cells) + " |")
            out.append("")
    for sec in d.sections:  # headers/footers often carry classification and version claims
        for p in list(sec.header.paragraphs) + list(sec.footer.paragraphs):
            if p.text.strip():
                out.append(f"(header/footer) {p.text.strip()}")
    return "\n".join(out)


def _xlsx(path: Path) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)  # formulas are never evaluated
    out: list[str] = []
    for ws in wb.worksheets:
        out.append(f"## Sheet {ws.title}")
        for r_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
            cells = [(c, v) for c, v in enumerate(row, 1) if v not in (None, "")]
            if not cells:
                continue
            first, last = cells[0][0], cells[-1][0]
            def col(n: int) -> str:
                s = ""
                while n:
                    n, rem = divmod(n - 1, 26)
                    s = chr(65 + rem) + s
                return s
            out.append(f"[{ws.title}!{col(first)}{r_idx}:{col(last)}{r_idx}] " + " | ".join(str(v).strip() for _, v in cells))
    return "\n".join(out)


def _pptx(path: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    out: list[str] = []
    for i, slide in enumerate(prs.slides, 1):
        title = slide.shapes.title.text.strip() if slide.shapes.title is not None and slide.shapes.title.has_text_frame else ""
        out.append(f"## Slide {i}: {title}".rstrip(": "))
        for sh in slide.shapes:
            if sh.has_text_frame and sh is not slide.shapes.title:
                for p in sh.text_frame.paragraphs:
                    t = "".join(r.text for r in p.runs).strip()
                    if t:
                        out.append("- " + t)
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    out.append("| " + " | ".join(c.text.strip() for c in row.cells) + " |")
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            n = slide.notes_slide.notes_text_frame.text.strip()
            if n:
                out.append(f"Speaker notes (slide {i}): {n}")
    return "\n".join(out)


def _html(path: Path) -> str:
    return html_to_text(path.read_text(encoding="utf-8", errors="replace"))


def html_to_text(markup: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(markup, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    out: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "pre"]):
        txt = " | ".join(c.get_text(" ", strip=True) for c in el.find_all(["td", "th"])) if el.name == "tr" else el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name.startswith("h"):
            out.append("#" * int(el.name[1]) + " " + txt)
        elif el.name == "li":
            out.append("- " + txt)
        elif el.name == "tr":
            out.append("| " + txt + " |")
        else:
            out.append(txt)
    return "\n".join(out)


def _rtf(path: Path) -> str:
    raw = path.read_text(encoding="latin-1", errors="replace")
    raw = re.sub(r"\\par[d]?\b", "\n", raw)
    raw = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("latin-1"), raw)
    raw = re.sub(r"\{\\\*[^{}]*\}|\\[a-zA-Z]+-?\d* ?|[{}]", "", raw)
    return re.sub(r"\n{3,}", "\n\n", raw).strip()


def _odt(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("content.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"<text:h[^>]*outline-level=\"(\d)\"[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", xml)
    xml = re.sub(r"</text:(p|h)>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    import html as _h

    return _h.unescape(xml).strip()


def _csv(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    out = []
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if rows:  # a data file (personal / special-category / protected columns) is a DATA asset: never read its values as a document
        from .data_scanner import classify_column

        if any(classify_column(h).classes for h in rows[0]):
            return "[data file] columns: " + ", ".join(rows[0]) + f"; {max(0, len(rows) - 1)} row(s); values withheld"
    for r_idx, row in enumerate(rows, 1):
        if any(c.strip() for c in row):
            out.append(f"[row {r_idx}] " + " | ".join(c.strip() for c in row))
    return "\n".join(out)


_READERS = {".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx, ".html": _html, ".htm": _html, ".rtf": _rtf, ".odt": _odt,
            ".csv": _csv, ".tsv": _csv}


def read_document(path: Path) -> str | None:
    """Return Markdown-like text, or None when the format is unsupported or the file cannot be parsed."""
    fn = _READERS.get(path.suffix.lower())
    if fn is None:
        return None
    try:
        return fn(path)
    except Exception:
        return None
