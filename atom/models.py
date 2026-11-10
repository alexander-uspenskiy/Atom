"""Model registry: which model profiles exist, whether they are downloaded / running, and start/stop/download.

Each profile is its own llama-server (ops/llama-server.sh <profile>) on its own port, so several can be loaded
at once and an agent can pick one. Servers Atom started are tracked directly; one started from a terminal
(ops/start.sh) is adopted by looking up the llama-server listening on the profile's port, so it can be stopped
from the dashboard too. Quitting Atom only stops the servers it started itself.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any

import httpx

from .config import LLM_PROFILES, Settings

ROOT = Path(__file__).resolve().parent.parent


def _repo_dir(repo: str) -> Path:
    return Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + repo.replace("/", "--"))


class ModelManager:
    def __init__(self, settings_fn):
        self._settings = settings_fn          # callable -> effective Settings
        self._servers: dict[str, subprocess.Popen] = {}
        self._downloads: dict[str, subprocess.Popen] = {}

    # ---------- disk ----------
    def installed(self, profile: str) -> bool:
        p = LLM_PROFILES[profile]
        snaps = _repo_dir(p["repo"]) / "snapshots"
        return all(any(snaps.glob(f"*/{f}")) for f in p["files"])

    def _downloaded_bytes(self, profile: str) -> int:
        blobs = _repo_dir(LLM_PROFILES[profile]["repo"]) / "blobs"
        return sum(f.stat().st_size for f in blobs.glob("*")) if blobs.is_dir() else 0

    def download_state(self, profile: str) -> dict | None:
        proc = self._downloads.get(profile)
        if proc is not None and proc.poll() is not None:
            self._downloads.pop(profile)
            proc = None
        if proc is None and not _has_partial(_repo_dir(LLM_PROFILES[profile]["repo"])):
            return None
        total = LLM_PROFILES[profile]["size_gb"] * 1e9
        got = self._downloaded_bytes(profile)
        return {"bytes": got, "total": int(total), "percent": min(99.0, round(100 * got / total, 1)),
                "active": proc is not None}

    def download(self, profile: str) -> None:
        if self.installed(profile) or self.download_state(profile) and self.download_state(profile)["active"]:
            return
        cli = shutil.which("huggingface-cli") or shutil.which("hf")
        if not cli:
            raise RuntimeError("huggingface-cli not found (pip install -U huggingface_hub)")
        p = LLM_PROFILES[profile]
        log = open(ROOT / "logs" / f"download-{profile}.log", "ab") if (ROOT / "logs").is_dir() else subprocess.DEVNULL
        self._downloads[profile] = subprocess.Popen([cli, "download", p["repo"], *p["files"]], stdout=log, stderr=log,
                                                    start_new_session=True)

    # ---------- servers ----------
    async def running(self, profile: str) -> bool:
        port = LLM_PROFILES[profile]["port"]
        try:
            async with httpx.AsyncClient(timeout=1.0) as c:
                return (await c.get(f"http://127.0.0.1:{port}/health")).status_code == 200
        except httpx.HTTPError:
            return False

    def managed(self, profile: str) -> bool:
        proc = self._servers.get(profile)
        return proc is not None and proc.poll() is None

    def start(self, profile: str) -> None:
        if not self.installed(profile):
            raise RuntimeError(f"{LLM_PROFILES[profile]['label']} is not downloaded yet")
        if self.managed(profile):
            return
        (ROOT / "logs").mkdir(exist_ok=True)
        log = open(ROOT / "logs" / f"llama-server-{profile}.log", "ab")
        self._servers[profile] = subprocess.Popen([str(ROOT / "ops" / "llama-server.sh"), profile], stdout=log,
                                                  stderr=log, cwd=ROOT, start_new_session=True)

    def external_pid(self, profile: str) -> int | None:
        """PID of a llama-server listening on the profile's port that Atom did not start (e.g. ops/start.sh)."""
        port = LLM_PROFILES[profile]["port"]
        try:
            pids = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True,
                                  text=True, timeout=3).stdout.split()
            for pid in pids:
                cmd = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True, text=True,
                                     timeout=3).stdout
                if "llama-server" in cmd:
                    return int(pid)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return None

    def stop(self, profile: str) -> None:
        proc = self._servers.pop(profile, None)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            return
        pid = self.external_pid(profile)       # adopt a server started from a terminal
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    async def list(self) -> list[dict[str, Any]]:
        active = self._settings().llm_profile
        health = await asyncio.gather(*(self.running(k) for k in LLM_PROFILES))
        out = []
        for (k, p), up in zip(LLM_PROFILES.items(), health):
            starting = self.managed(k) and not up
            # A server started outside the dashboard is still controllable (stop works via its port).
            controllable = self.managed(k) or (up and await asyncio.to_thread(self.external_pid, k) is not None)
            out.append({"id": k, "label": p["label"], "detail": p["detail"], "model": p["alias"],
                        "base_url": f"http://127.0.0.1:{p['port']}/v1", "size_gb": p["size_gb"],
                        "installed": self.installed(k), "running": up, "starting": starting,
                        "managed": controllable, "active": k == active, "download": self.download_state(k)})
        return out

    def shutdown(self) -> None:
        for k in list(self._servers):
            self.stop(k)


def _has_partial(repo_dir: Path) -> bool:
    blobs = repo_dir / "blobs"
    return blobs.is_dir() and any(blobs.glob("*.incomplete"))
