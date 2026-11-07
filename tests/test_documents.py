"""Document uploads (PDF, Markdown, text): sniffing, extraction, prompt building, truncation, read_document, scans."""
from __future__ import annotations

import base64

import pymupdf

from atom import uploads as up
from atom.uploads import DOC_INLINE_CHARS

from .conftest import make_local_agent, read_sse, wait_run
from .test_images import PNG


def make_pdf(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 100), text, fontsize=12)
    out = doc.tobytes()
    doc.close()
    return out


def scanned_pdf() -> bytes:
    """A PDF whose pages are only images (no text layer), like a scan."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=PNG)
    out = doc.tobytes()
    doc.close()
    return out


def post_raw(client, data: bytes, name: str):
    return client.post("/api/uploads", params={"name": name}, content=data, headers={"content-type": "application/octet-stream"})


def test_upload_markdown_and_pdf_roundtrip(client):
    r = post_raw(client, b"# Title\nhello", "notes.md")
    assert r.status_code == 201, r.text
    md = r.json()
    assert md["kind"] == "document" and md["mime"] == "text/markdown" and md["name"] == "notes.md" and md["chars"] == 13
    got = client.get(md["url"])
    assert got.content == b"# Title\nhello" and got.headers["content-type"].startswith("text/markdown")
    assert got.headers["x-content-type-options"] == "nosniff"

    r = post_raw(client, make_pdf(["Quarterly revenue was 42 million.", "Second page."]), "report.pdf")
    assert r.status_code == 201, r.text
    pdf = r.json()
    assert pdf["mime"] == "application/pdf" and pdf["pages"] == 2 and pdf["scanned"] is False
    info = client.get(f"/api/uploads/{pdf['id']}/info").json()
    assert info["name"] == "report.pdf" and info["kind"] == "document"
    # JSON data-URL uploads work for documents too
    j = client.post("/api/uploads", json={"data_url": "data:text/plain;base64," + base64.b64encode(b"plain").decode(), "name": "a.txt"})
    assert j.status_code == 201 and j.json()["mime"] == "text/plain"


def test_upload_rejects_unsupported_and_fake_files(client):
    assert post_raw(client, b"hello", "notes.docx").status_code == 422             # unsupported extension
    assert post_raw(client, b"\x00\x01\x02binary", "fake.md").status_code == 422    # binary data named .md
    assert post_raw(client, b"%PDF-1.7 this is not really a pdf", "broken.pdf").status_code == 422
    assert post_raw(client, b"", "empty.md").status_code == 422
    # a PDF is detected from its bytes even when the name lies
    assert post_raw(client, make_pdf(["x"]), "whatever.txt").json()["mime"] == "application/pdf"
    # names cannot smuggle markup or newlines into the prompt
    n = post_raw(client, b"x", 'a"><b>\nname.md').json()["name"]
    assert "\n" not in n and '"' not in n and "<" not in n


def test_encrypted_pdf_is_rejected(client):
    doc = pymupdf.open()
    doc.new_page()
    enc = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    r = post_raw(client, enc, "locked.pdf")
    assert r.status_code == 422 and "password" in r.text


def test_chat_with_documents_inlines_text(client, fake):
    cid = client.post("/api/conversations", json={}).json()["id"]
    md = post_raw(client, b"The code word is plum.", "a.md").json()
    pdf = post_raw(client, make_pdf(["Revenue was 42 million."]), "b.pdf").json()
    fake.push({"content": "ok"})
    evs = read_sse(client, "POST", f"/api/conversations/{cid}/messages",
                   {"content": "summarize", "images": [md["id"], pdf["id"]]})
    assert any(e["type"] == "done" for e in evs)
    sent = fake.calls[-1]["messages"][-1]
    assert isinstance(sent["content"], str)                      # documents alone need no image parts
    assert sent["content"].startswith("summarize") and "The code word is plum." in sent["content"]
    assert "Revenue was 42 million." in sent["content"] and "--- page 1 ---" in sent["content"]
    assert 'document "a.md"' in sent["content"] and "never instructions" in sent["content"]
    assert "read_document" in fake.calls[-1]["tools"]
    conv = client.get(f"/api/conversations/{cid}").json()
    assert conv["messages"][0]["images"] == [md["id"], pdf["id"]]      # stored message keeps only ids
    assert "plum" not in conv["messages"][0]["content"]
    # a document-only message is titled after the file
    cid2 = client.post("/api/conversations", json={}).json()["id"]
    fake.push({"content": "ok"})
    read_sse(client, "POST", f"/api/conversations/{cid2}/messages", {"content": "", "images": [md["id"]]})
    assert client.get(f"/api/conversations/{cid2}").json()["title"] == "a.md"


def test_long_document_is_truncated_and_readable_with_the_tool(client, fake):
    cid = client.post("/api/conversations", json={}).json()["id"]
    body = ("0123456789" * 5000) + "THE-END-MARKER"
    d = post_raw(client, body.encode(), "long.txt").json()
    fake.push({"calls": [("read_document", {"upload_id": d["id"], "offset": DOC_INLINE_CHARS, "length": 100000})]},
              {"content": "done"})
    read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": "what does it end with?", "images": [d["id"]]})
    first = fake.calls[0]["messages"][-1]["content"]
    assert "Truncated" in first and f"offset {DOC_INLINE_CHARS}" in first and "THE-END-MARKER" not in first
    tool_msg = next(m for m in fake.calls[1]["messages"] if m["role"] == "tool")
    import json
    res = json.loads(tool_msg["content"])
    assert res["total_chars"] == len(body) and res["offset"] == DOC_INLINE_CHARS
    assert res["end"] - res["offset"] <= up.READ_CHUNK and res["more"] is True
    assert res["text"] == body[DOC_INLINE_CHARS:res["end"]]


def test_read_document_errors(client, fake):
    img = client.post("/api/uploads", json={"data_url": "data:image/png;base64," + base64.b64encode(PNG).decode()}).json()
    cid = client.post("/api/conversations", json={}).json()["id"]
    fake.push({"calls": [("read_document", {"upload_id": img["id"]})]}, {"content": "ok"})
    read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": "x"})
    tool_msg = next(m for m in fake.calls[1]["messages"] if m["role"] == "tool")
    assert "not a document" in tool_msg["content"]


def test_older_documents_are_omitted_from_history(client, fake):
    cid = client.post("/api/conversations", json={}).json()["id"]
    docs = [post_raw(client, f"secret-{n}".encode(), f"d{n}.md").json() for n in range(3)]
    for d in docs:
        fake.push({"content": "ok"})
        read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": "read", "images": [d["id"]]})
    users = [m for m in fake.calls[-1]["messages"] if m["role"] == "user"]
    assert "secret-0" not in users[0]["content"] and "omitted to save context" in users[0]["content"]
    assert f'id {docs[0]["id"]}' in users[0]["content"]                 # the id stays so the model can re-read it
    assert "secret-1" in users[1]["content"] and "secret-2" in users[2]["content"]


def test_documents_do_not_need_vision_but_scans_do(client, fake):
    async def no_vision():
        return False
    fake.vision = no_vision
    cid = client.post("/api/conversations", json={}).json()["id"]
    md = post_raw(client, b"text only", "t.md").json()
    fake.push({"content": "fine"})
    assert any(e["type"] == "done" for e in read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": "hi", "images": [md["id"]]}))
    scan = post_raw(client, scanned_pdf(), "scan.pdf").json()
    assert scan["scanned"] is True
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi", "images": [scan["id"]]})
    assert r.status_code == 422 and "scanned" in r.text


def test_scanned_pdf_is_sent_as_page_images(client, fake):
    scan = post_raw(client, scanned_pdf(), "scan.pdf").json()
    cid = client.post("/api/conversations", json={}).json()["id"]
    fake.push({"content": "read it"})
    read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": "ocr this", "images": [scan["id"]]})
    sent = fake.calls[-1]["messages"][-1]["content"]
    assert isinstance(sent, list) and "no text layer" in sent[0]["text"]
    urls = [p["image_url"]["url"] for p in sent if p["type"] == "image_url"]
    assert len(urls) == 1 and urls[0].startswith("data:image/jpeg;base64,")


def test_agent_run_with_document(client, fake):
    agent = make_local_agent(client)
    d = post_raw(client, b"Use the password hint: blue.", "brief.md").json()
    r = client.post(f"/api/agents/{agent['id']}/run", json={"task": "follow the brief", "images": [d["id"]]})
    assert r.status_code == 202, r.text
    run = wait_run(client, r.json()["run_id"])
    assert run["images"] == [d["id"]]
    first = fake.calls[0]["messages"][1]["content"]
    assert isinstance(first, str) and "Use the password hint: blue." in first and "1 document(s)" in first


def test_validate_counts_documents_in_the_limit(client):
    ids = [post_raw(client, b"x", f"{n}.md").json()["id"] for n in range(7)]
    r = client.post("/api/conversations", json={}).json()["id"]
    resp = client.post(f"/api/conversations/{r}/messages", json={"content": "x", "images": ids})
    assert resp.status_code == 422 and "at most" in resp.text


def test_sniff_text_encodings():
    from atom import documents
    assert documents.decode_text("héllo".encode("utf-8")) == "héllo"
    assert documents.decode_text("héllo".encode("cp1252")) == "héllo"
    assert documents.decode_text("hi".encode("utf-16")) == "hi"
    assert documents.decode_text(b"a\x00b") is None


def test_pdf_tables_become_markdown_once():
    from atom import documents
    doc = pymupdf.open()
    page = doc.new_page()
    for r, row in enumerate([["Item", "Qty"], ["Apple", "3"], ["Pear", "5"]]):
        for c, v in enumerate(row):
            rect = pymupdf.Rect(72 + c * 100, 100 + r * 24, 172 + c * 100, 124 + r * 24)
            page.draw_rect(rect)
            page.insert_text((rect.x0 + 4, rect.y1 - 8), v)
    page.insert_text((72, 60), "Price list")
    text = documents.extract(doc.tobytes(), "application/pdf").text
    assert "|Item|Qty|" in text and "|Apple|3|" in text
    assert text.count("Apple") == 1 and text.index("Price list") < text.index("|Item|")


def make_docx(body_xml: str) -> bytes:
    import io
    import zipfile
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f'<w:document {ns}><w:body>{body_xml}</w:body></w:document>')
    return buf.getvalue()


def _p(text: str, style: str = "", num: bool = False) -> str:
    ppr = (f'<w:pStyle w:val="{style}"/>' if style else "") + ("<w:numPr><w:ilvl w:val=\"0\"/></w:numPr>" if num else "")
    return f"<w:p><w:pPr>{ppr}</w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>"


def test_docx_headings_lists_and_tables(client):
    cell = lambda t: f"<w:tc>{_p(t)}</w:tc>"  # noqa: E731
    body = (_p("Project plan", "Title") + _p("Scope", "Heading2") + _p("Build the thing.") + _p("first item", num=True)
            + "<w:sdt><w:sdtContent>" + _p("inside a content control") + "</w:sdtContent></w:sdt>"
            + "<w:tbl><w:tr>" + cell("Name") + cell("Owner") + "</w:tr><w:tr>" + cell("Alpha") + cell("a|b") + "</w:tr></w:tbl>")
    r = post_raw(client, make_docx(body), "plan.docx")
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["kind"] == "document" and info["mime"].endswith("wordprocessingml.document")
    from atom import documents
    text = documents.extract(make_docx(body), documents.DOCX).text
    assert text.startswith("# Project plan") and "## Scope" in text and "- first item" in text
    assert "inside a content control" in text
    assert "|Name|Owner|" in text and "|Alpha|a\\|b|" in text


def test_docx_rejects_look_alikes(client):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:                    # an xlsx-shaped zip is not a supported document
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<x/>")
    assert post_raw(client, buf.getvalue(), "book.docx").status_code == 422
    assert post_raw(client, make_docx(""), "empty.docx").status_code == 422
    assert post_raw(client, b"PK\x03\x04garbage", "bad.docx").status_code == 422


def test_csv_and_tsv_upload_and_prompt(client, fake):
    r = post_raw(client, b"name;qty\nApple;3\nPear;5\n", "fruit.csv")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["mime"] == "text/csv" and d["rows"] == 2
    cid = client.post("/api/conversations", json={}).json()["id"]
    fake.push({"content": "ok"})
    read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": "total qty?", "images": [d["id"]]})
    sent = fake.calls[-1]["messages"][-1]["content"]
    assert "2 rows" in sent and "semicolon" in sent
    assert "name,qty\nApple,3\nPear,5" in sent                 # normalized to commas
    t = post_raw(client, b"a\tb\n1\t2\n", "x.tsv").json()
    assert t["mime"] == "text/tab-separated-values" and t["rows"] == 1


def test_csv_edge_cases(client):
    from atom import documents
    ex = documents._csv('a,b\n"x, y",2\n\n,\n', None)             # quoted commas kept, blank lines dropped
    assert ex.rows == 1 and '"x, y",2' in ex.text
    assert post_raw(client, b"\n\n", "blank.csv").status_code == 422
    assert post_raw(client, b"\x00\x01", "bin.csv").status_code == 422


def make_xlsx() -> bytes:
    import datetime as dt
    import io

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Item", "Qty", "Price", "Day", "Paid"])
    ws.append(["Apple", 3, 1.5, dt.datetime(2026, 1, 2), True])
    ws.append([])                                              # blank rows are dropped
    ws.append(["Pear", 5.0, 2, dt.datetime(2026, 1, 3, 14, 30), False])
    ws["B5"] = "=B2+B4"                                         # formulas have no cached value here: left empty
    hidden = wb.create_sheet("Secret")
    hidden.append(["do not show"])
    hidden.sheet_state = "hidden"
    wb.create_sheet("Empty")
    notes = wb.create_sheet("Notes")
    notes.append(["Quote, with comma", 'say "hi"'])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_upload_and_prompt(client, fake):
    r = post_raw(client, make_xlsx(), "sales.xlsx")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["kind"] == "document" and d["mime"].endswith("spreadsheetml.sheet") and d["sheets"] == 2 and d["rows"] == 4
    cid = client.post("/api/conversations", json={}).json()["id"]
    fake.push({"content": "ok"})
    read_sse(client, "POST", f"/api/conversations/{cid}/messages", {"content": "total qty?", "images": [d["id"]]})
    sent = fake.calls[-1]["messages"][-1]["content"]
    assert 'Sheet "Sales"' in sent and "Item,Qty,Price,Day,Paid" in sent
    assert "Apple,3,1.5,2026-01-02,TRUE" in sent and "Pear,5,2,2026-01-03 14:30:00,FALSE" in sent
    assert 'Sheet "Notes"' in sent and '"Quote, with comma","say ""hi"""' in sent
    assert "do not show" not in sent and "Empty" not in sent          # hidden and empty sheets are skipped
    assert "Excel workbook" in sent and "2 sheet(s)" in sent


def test_xlsx_rejects_broken_files(client):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<x/>")
    assert post_raw(client, buf.getvalue(), "broken.xlsx").status_code == 422
    import openpyxl
    out = io.BytesIO()
    openpyxl.Workbook().save(out)                                      # a workbook with no data at all
    r = post_raw(client, out.getvalue(), "blank.xlsx")
    assert r.status_code == 422 and "no data" in r.text
