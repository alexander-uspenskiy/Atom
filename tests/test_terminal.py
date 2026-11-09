import asyncio

import pytest

from atom.config import Settings
from atom.terminal import TerminalError, run_command


def _s(tmp_path, **kw):
    return Settings(data_dir=tmp_path, terminal_enabled=True, **kw)


def test_disabled_by_default(tmp_path):
    with pytest.raises(TerminalError):
        asyncio.run(run_command(Settings(data_dir=tmp_path), "echo hi"))


def test_runs_and_reports_exit(tmp_path):
    text, ok = asyncio.run(run_command(_s(tmp_path), "echo hi; exit 3"))
    assert "hi" in text and "exit code 3" in text and not ok
    assert (tmp_path / "workspace").is_dir()


def test_timeout_kills(tmp_path):
    text, ok = asyncio.run(run_command(_s(tmp_path), "sleep 20", timeout=1))
    assert "Timed out" in text and not ok


def test_base_folder_override(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    text, ok = asyncio.run(run_command(_s(tmp_path), "pwd", base=str(d)))
    assert ok and str(d.resolve()) in text or str(d) in text


def test_restrict_blocks_outside_paths(tmp_path):
    s = _s(tmp_path)
    for cmd in ("cat /etc/hosts", "ls ~", "ls ..", "echo x > /tmp/x", "cat ../secret"):
        with pytest.raises(TerminalError, match="restriction"):
            asyncio.run(run_command(s, cmd))
    with pytest.raises(TerminalError, match="restriction"):
        asyncio.run(run_command(s, "ls", cwd="/"))


def test_restrict_allows_inside_and_system_bins(tmp_path):
    s = _s(tmp_path)
    text, ok = asyncio.run(run_command(s, "mkdir -p a && echo hi > a/f.txt && /bin/cat a/f.txt 2>/dev/null"))
    assert ok and "hi" in text
    inside = tmp_path / "workspace" / "a"
    text, ok = asyncio.run(run_command(s, f"ls {inside}"))
    assert ok


def test_restrict_ignores_markup_and_quoted_heredocs(tmp_path):
    s = _s(tmp_path)
    html = "<div><a href=x>hi</a></div>"
    text, ok = asyncio.run(run_command(s, f"echo '{html}' > page.html && cat page.html"))
    assert ok and "</div>" in text
    text, ok = asyncio.run(run_command(s, "cat > p.html <<'EOF'\n<html>\n<script>x</script>\n/etc/hosts\n</html>\nEOF\ncat p.html"))
    assert ok and "</script>" in text


def test_restrict_ignores_tag_attributes_in_quotes(tmp_path):
    s = _s(tmp_path)
    for cmd in ("""echo '<a href="/x">hi</a>' > p.html && cat p.html""",
                'echo "<a href=\\"/x\\">hi</a>" > p.html && cat p.html',
                """echo '<link rel=stylesheet href=/css/a.css><img src="/img/a.png" />' > p.html && cat p.html"""):
        text, ok = asyncio.run(run_command(s, cmd))
        assert ok and "<" in text, cmd


def test_restrict_tag_exemption_does_not_hide_real_paths(tmp_path):
    s = _s(tmp_path)
    for cmd in ("""dd <a if="/etc/passwd">x""",
                """cat '/etc/hosts'""",
                """cat "/etc/hosts" """,
                """echo '<a' "href=/etc/x" '>'""",
                """echo "<b>$(cat /etc/hosts)</b>" """):
        with pytest.raises(TerminalError, match="restriction"):
            asyncio.run(run_command(s, cmd))


def test_restrict_still_checks_unquoted_heredoc_substitutions(tmp_path):
    s = _s(tmp_path)
    with pytest.raises(TerminalError, match="restriction"):
        asyncio.run(run_command(s, "cat <<EOF\n$(cat /etc/hosts)\nEOF"))
    text, ok = asyncio.run(run_command(s, "cat <<EOF\n<b>x</b>\nEOF"))
    assert ok and "</b>" in text


def test_restrict_blocks_redirect_from_outside_path(tmp_path):
    s = _s(tmp_path)
    for cmd in ("cat </etc/hosts", "cat < /etc/hosts"):
        with pytest.raises(TerminalError, match="restriction"):
            asyncio.run(run_command(s, cmd))


def test_restrict_off_allows_outside(tmp_path):
    text, ok = asyncio.run(run_command(_s(tmp_path, terminal_restrict=False), "ls /"))
    assert ok
