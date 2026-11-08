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
