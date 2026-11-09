import asyncio

import pytest

from atom.config import Settings
from atom.files import FILE_TOOLS, FileError, dispatch
from atom.tools import ToolContext, build_tools


def _s(tmp_path, **kw):
    return Settings(data_dir=tmp_path, terminal_enabled=True, **kw)


def _run(s, name, **a):
    return dispatch(s, name, a)


def test_disabled_by_default(tmp_path):
    with pytest.raises(FileError, match="disabled"):
        _run(Settings(data_dir=tmp_path), "write_file", path="a.txt", content="x")


def test_write_verbatim_html_with_quotes_and_tags(tmp_path):
    s = _s(tmp_path)
    html = '<!DOCTYPE html>\n<html><head><title>Calc</title></head>\n<body onclick="go(\'/x\')">$HOME `x`</body></html>\n'
    out = _run(s, "write_file", path="css/../index.html", content=html)
    assert "Created index.html" in out
    assert (tmp_path / "workspace" / "index.html").read_text() == html


def test_write_creates_parents_overwrite_append(tmp_path):
    s = _s(tmp_path)
    assert "Created" in _run(s, "write_file", path="js/app.js", content="a")
    assert "Overwrote" in _run(s, "write_file", path="js/app.js", content="b")
    assert "Appended" in _run(s, "write_file", path="js/app.js", content="c", append=True)
    assert _run(s, "read_file", path="js/app.js") == "bc"


def test_restrict_blocks_outside_and_symlink_escape(tmp_path):
    s = _s(tmp_path)
    for p in ("../x.txt", "/etc/hosts", "~/x.txt", "a/../../x"):
        with pytest.raises(FileError, match="restriction"):
            _run(s, "write_file", path=p, content="x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "workspace").mkdir(exist_ok=True)
    (tmp_path / "workspace" / "link").symlink_to(outside)
    with pytest.raises(FileError, match="restriction"):
        _run(s, "write_file", path="link/x.txt", content="x")
    # unrestricted lets it through
    out = _run(_s(tmp_path, terminal_restrict=False), "write_file", path=str(outside / "ok.txt"), content="x")
    assert "Created" in out and (outside / "ok.txt").exists()


def test_edit(tmp_path):
    s = _s(tmp_path)
    _run(s, "write_file", path="f.txt", content="one two two")
    with pytest.raises(FileError, match="2 places"):
        _run(s, "edit_file", path="f.txt", old="two", new="3")
    with pytest.raises(FileError, match="not found"):
        _run(s, "edit_file", path="f.txt", old="zzz", new="3")
    _run(s, "edit_file", path="f.txt", old="one", new="1")
    _run(s, "edit_file", path="f.txt", old="two", new="2", replace_all=True)
    assert _run(s, "read_file", path="f.txt") == "1 2 2"


def test_read_pagination_and_binary(tmp_path):
    s = _s(tmp_path)
    _run(s, "write_file", path="big.txt", content="x" * 30000)
    out = _run(s, "read_file", path="big.txt")
    assert "offset=12000" in out
    assert _run(s, "read_file", path="big.txt", offset=29990) == "x" * 10
    (tmp_path / "workspace" / "b.bin").write_bytes(b"\0\1\2")
    with pytest.raises(FileError, match="binary"):
        _run(s, "read_file", path="b.bin")
    with pytest.raises(FileError, match="does not exist"):
        _run(s, "read_file", path="nope")


def test_list_mkdir_move_delete(tmp_path):
    s = _s(tmp_path)
    _run(s, "make_dir", path="src/deep")
    _run(s, "write_file", path="src/a.txt", content="hi")
    listing = _run(s, "list_files")
    assert "src/" in listing and "src/a.txt  (2 B)" in listing
    _run(s, "move_file", src="src/a.txt", dest="src/deep")
    assert (tmp_path / "workspace/src/deep/a.txt").exists()
    _run(s, "write_file", path="b.txt", content="B")
    with pytest.raises(FileError, match="exists"):
        _run(s, "move_file", src="b.txt", dest="src/deep/a.txt")
    _run(s, "move_file", src="b.txt", dest="src/deep/a.txt", overwrite=True)
    assert _run(s, "read_file", path="src/deep/a.txt") == "B"
    with pytest.raises(FileError, match="recursive"):
        _run(s, "delete_file", path="src")
    assert "Deleted folder" in _run(s, "delete_file", path="src", recursive=True)
    with pytest.raises(FileError, match="project folder itself"):
        _run(s, "delete_file", path=".")
    assert _run(s, "list_files") == "(empty)"


def test_registered_for_agents_and_marked_side_effect():
    tools = build_tools()
    for n in FILE_TOOLS:
        assert n in tools
    assert tools["write_file"].side_effect and not tools["read_file"].side_effect


def test_agent_handler_raises_actionerror_when_blocked(tmp_path):
    from atom.browser.session import ActionError
    ctx = ToolContext(session=None, llm=None, settings=_s(tmp_path))
    h = build_tools()["write_file"].handler
    out = asyncio.run(h(ctx, {"path": "a.txt", "content": "ok"}))
    assert "Created a.txt" in out.text
    with pytest.raises(ActionError):
        asyncio.run(h(ctx, {"path": "../a.txt", "content": "no"}))
