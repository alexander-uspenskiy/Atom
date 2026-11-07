"""Document extraction for uploads: PDF and plain text / Markdown -> text the model can read.

Everything here is synchronous and CPU-bound; callers run it in a thread. Extraction happens once, at upload time,
and the result is cached next to the file (see uploads.py), so building a prompt never parses a document again.
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .stores import Invalid

MAX_DOC_BYTES = 25 * 1024 * 1024
MAX_EXTRACT_CHARS = 2_000_000       # hard cap on stored text (a zip-bomb / giant-file guard)
MAX_PDF_PAGES = 300                 # pages read from one PDF
SCAN_CHARS_PER_PAGE = 10           # below this average a PDF is treated as scanned (no text layer)
MAX_XLSX_UNZIPPED = 300 * 1024 * 1024   # total uncompressed size accepted for a workbook (zip-bomb guard)
MAX_SHEET_ROWS = 200_000            # rows counted per sheet
MAX_XML_BYTES = 60 * 1024 * 1024    # uncompressed size accepted for a DOCX's document.xml (zip-bomb guard)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_EXTS = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain",
             ".csv": "text/csv", ".tsv": "text/tab-separated-values"}


@dataclass
class Extracted:
    text: str
    pages: int | None = None        # PDFs
    scanned: bool = False           # PDF without a usable text layer; read the rendered pages with vision instead
    truncated: bool = False         # text was cut at MAX_EXTRACT_CHARS
    rows: int | None = None         # CSV / TSV data rows (header excluded); XLSX non-empty rows over all sheets
    sheets: int | None = None       # XLSX sheets read


def sniff_document(data: bytes, name: str = "") -> str | None:
    """Detect a supported document type: PDF by magic bytes, text/Markdown by extension plus decodable content."""
    if data[:1024].lstrip(b"\x00 \t\r\n").startswith(b"%PDF-"):
        return "application/pdf"
    if data[:4] == b"PK\x03\x04":
        kind = _zip_kind(data)
        if kind:
            return kind
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext in TEXT_EXTS and decode_text(data) is not None:
        return TEXT_EXTS[ext]
    return None


def decode_text(data: bytes) -> str | None:
    """UTF-8 (with or without BOM) or UTF-16 with BOM, else Windows-1252. None for binary data."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252")
        except UnicodeDecodeError:
            return None


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()


def extract(data: bytes, mime: str) -> Extracted:
    if mime == "application/pdf":
        return _pdf(data)
    if mime == DOCX:
        return _docx(data)
    if mime == XLSX:
        return _xlsx(data)
    text = decode_text(data)
    if text is None:
        raise Invalid("could not read that file as text")
    if mime in ("text/csv", "text/tab-separated-values"):
        return _csv(text, "\t" if mime == "text/tab-separated-values" else None)
    text = _clean(text)
    cut = len(text) > MAX_EXTRACT_CHARS
    return Extracted(text[:MAX_EXTRACT_CHARS], truncated=cut)


# ---------------------------------------------------------------------------- DOCX
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _zip_kind(data: bytes) -> str | None:
    """DOCX or XLSX, told apart by their package contents (never by file name)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
    except zipfile.BadZipFile:
        return None
    if "[Content_Types].xml" not in names:
        return None
    if "word/document.xml" in names:
        return DOCX
    if "xl/workbook.xml" in names:
        return XLSX
    return None


def _blocks(parent):
    """Paragraphs and tables of a body or table cell, looking through content controls (w:sdt)."""
    for el in parent:
        if el.tag in (_W + "p", _W + "tbl"):
            yield el
        elif el.tag == _W + "sdt":
            content = el.find(_W + "sdtContent")
            if content is not None:
                yield from _blocks(content)


def _para_text(p) -> str:
    out: list[str] = []
    for el in p.iter():
        if el.tag == _W + "t" and el.text:
            out.append(el.text)
        elif el.tag == _W + "tab":
            out.append("\t")
        elif el.tag in (_W + "br", _W + "cr"):
            out.append("\n")
    return "".join(out)


def _para(p) -> str:
    text = _para_text(p).strip()
    if not text:
        return ""
    ppr = p.find(_W + "pPr")
    style = ""
    if ppr is not None:
        st = ppr.find(_W + "pStyle")
        style = (st.get(_W + "val") or "") if st is not None else ""
        if ppr.find(_W + "numPr") is not None:                      # list item
            lvl = ppr.find(_W + "numPr").find(_W + "ilvl")
            depth = int(lvl.get(_W + "val") or 0) if lvl is not None and (lvl.get(_W + "val") or "").isdigit() else 0
            return f"{'  ' * depth}- {text}"
    low = style.lower().replace(" ", "")
    if low == "title":
        return f"# {text}"
    if low.startswith("heading") and low[7:].isdigit():
        return f"{'#' * min(max(int(low[7:]), 1), 6)} {text}"
    return text


def _table(tbl) -> str:
    rows = []
    for tr in tbl.findall(_W + "tr"):
        cells = []
        for tc in tr.findall(_W + "tc"):
            txt = " ".join(t for t in (_para_text(p).strip().replace("\n", " ") for p in tc.iter(_W + "p")) if t)
            cells.append(txt.replace("|", "\\|"))
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["|" + "|".join(rows[0]) + "|", "|" + "|".join("---" for _ in range(width)) + "|"]
    lines += ["|" + "|".join(r) + "|" for r in rows[1:]]
    return "\n".join(lines)


def _docx(data: bytes) -> Extracted:
    """Word document -> Markdown-ish text: headings, list items, paragraphs and tables (no images, headers or footnotes)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        info = z.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as e:
        raise Invalid("could not read that file as a Word document (.docx)") from e
    if info.file_size > MAX_XML_BYTES:
        raise Invalid("this Word document is too large to read")
    try:
        root = ET.fromstring(z.read(info))
    except ET.ParseError as e:
        raise Invalid("the Word document is damaged") from e
    body = root.find(_W + "body")
    parts = [t for t in ((_table(b) if b.tag == _W + "tbl" else _para(b)) for b in _blocks(body if body is not None else root)) if t]
    text = _clean("\n\n".join(parts))
    if not text:
        raise Invalid("this Word document has no readable text")
    return Extracted(text[:MAX_EXTRACT_CHARS], truncated=len(text) > MAX_EXTRACT_CHARS)


# ---------------------------------------------------------------------------- XLSX
def _cell(v) -> str:
    import datetime as dt
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time(0) else v.isoformat(sep=" ")
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    return str(v).replace("\r\n", "\n").replace("\r", "\n")


def _xlsx(data: bytes) -> Extracted:
    """Workbook -> one comma-separated block per visible sheet, using cached formula results (nothing is evaluated)."""
    import openpyxl
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_XLSX_UNZIPPED:
                raise Invalid("this workbook is too large to read")
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Invalid:
        raise
    except Exception as e:  # noqa: BLE001
        raise Invalid(f"could not read that file as an Excel workbook ({type(e).__name__})") from e
    parts: list[str] = []
    size = rows_total = sheets = 0
    truncated = False
    try:
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                continue
            out = io.StringIO()
            writer = csv.writer(out, lineterminator="\n")
            n = width = 0
            for row in ws.iter_rows(values_only=True):
                cells = [_cell(v) for v in row]
                while cells and not cells[-1]:
                    cells.pop()
                if not cells:
                    continue
                n += 1
                width = max(width, len(cells))
                if size + out.tell() <= MAX_EXTRACT_CHARS:
                    writer.writerow(cells)
                else:
                    truncated = True
                if n >= MAX_SHEET_ROWS:
                    truncated = True
                    break
            if not n:
                continue
            sheets += 1
            rows_total += n
            title = ws.title.replace('"', "'")
            body = f'## Sheet "{title}": {n:,}{"+" if n >= MAX_SHEET_ROWS else ""} rows, {width} columns\n{out.getvalue().strip()}'
            parts.append(body)
            size += len(body)
    finally:
        wb.close()
    if not parts:
        raise Invalid("this workbook has no data")
    text = "\n\n".join(parts)
    return Extracted(text[:MAX_EXTRACT_CHARS], truncated=truncated or len(text) > MAX_EXTRACT_CHARS, rows=rows_total, sheets=sheets)


# ---------------------------------------------------------------------------- CSV / TSV
def _csv(text: str, delimiter: str | None) -> Extracted:
    """CSV/TSV -> normalized comma-separated text with a one-line summary on top (the first row is the header)."""
    text = text.lstrip("\ufeff")
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:16384], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    n = width = 0
    truncated = False
    try:
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            if not any(c.strip() for c in row):
                continue
            n += 1
            width = max(width, len(row))
            if out.tell() <= MAX_EXTRACT_CHARS:
                writer.writerow(row)
            else:
                truncated = True
    except csv.Error as e:
        raise Invalid(f"could not parse the table: {e}") from e
    if not n:
        raise Invalid("this table has no rows")
    data_rows = n - 1
    delim = {"\t": "tab", ",": "comma", ";": "semicolon", "|": "pipe"}.get(delimiter, delimiter)
    head = f"[Table: {data_rows:,} data rows, {width} columns, first row is the header; originally {delim}-separated]\n"
    return Extracted((head + out.getvalue().strip())[:MAX_EXTRACT_CHARS + len(head)], truncated=truncated, rows=data_rows)


def _open_pdf(data: bytes):
    import pymupdf
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise Invalid(f"could not open the PDF ({type(e).__name__}); it may be corrupt") from e
    if doc.needs_pass:
        doc.close()
        raise Invalid("this PDF is password-protected; remove the password and try again")
    return doc


def _page_text(page) -> str:
    """Page text in reading order; tables found on the page are emitted once, as Markdown tables, in place."""
    try:
        tables = [(t.bbox, t.to_markdown().strip()) for t in page.find_tables().tables]
    except Exception:  # noqa: BLE001
        tables = []
    tables = [t for t in tables if t[1]]
    if not tables:
        return _clean(page.get_text("text", sort=True))

    def inside(b) -> bool:
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        return any(t[0][0] <= cx <= t[0][2] and t[0][1] <= cy <= t[0][3] for t in tables)

    items = [(b[1], b[4]) for b in page.get_text("blocks", sort=True) if b[6] == 0 and not inside(b)]
    items += [(bbox[1], md) for bbox, md in tables]
    items.sort(key=lambda it: it[0])
    return _clean("\n\n".join(_clean(t) for _, t in items if t.strip()))


def _pdf(data: bytes) -> Extracted:
    doc = _open_pdf(data)
    try:
        total = doc.page_count
        if total == 0:
            raise Invalid("this PDF has no pages")
        read = min(total, MAX_PDF_PAGES)
        parts: list[str] = []
        size = 0
        for i in range(read):
            page = doc[i]
            txt = _page_text(page)
            parts.append(f"--- page {i + 1} ---\n{txt}" if txt else f"--- page {i + 1} ---\n(no text)")
            size += len(parts[-1])
            if size > MAX_EXTRACT_CHARS:
                break
        body = "\n\n".join(parts)
        chars = sum(len(p.split("\n", 1)[1]) for p in parts if not p.endswith("(no text)"))
        scanned = chars < SCAN_CHARS_PER_PAGE * len(parts)
        cut = len(body) > MAX_EXTRACT_CHARS or read < total
        return Extracted(body[:MAX_EXTRACT_CHARS], pages=total, scanned=scanned, truncated=cut)
    finally:
        doc.close()


def render_pdf_pages(data: bytes, max_pages: int, dpi: int = 110) -> list[bytes]:
    """First pages of a PDF as JPEG bytes (for scanned PDFs: the vision model does the OCR)."""
    import pymupdf
    doc = _open_pdf(data)
    try:
        return [doc[i].get_pixmap(dpi=dpi).tobytes("jpeg", jpg_quality=80) for i in range(min(max_pages, doc.page_count))]
    finally:
        doc.close()
