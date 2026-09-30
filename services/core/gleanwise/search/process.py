# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Managed SearXNG child process (pip-installed, no Docker required)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import sys
from pathlib import Path

import httpx

from gleanwise.config import Settings

log = logging.getLogger(__name__)


def bundled_settings_path() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "deploy" / "searxng" / "settings.yml"
        if candidate.exists():
            return candidate
    return None


def render_settings(bundled: str, proxy_url: str | None) -> str:
    """Bundled SearXNG settings plus (optionally) an outgoing proxy so upstream engines go via the gateway."""
    if not proxy_url:
        return bundled
    tail = "" if bundled.endswith("\n") else "\n"
    return f"{bundled}{tail}outgoing:\n  proxies:\n    all://:\n      - {proxy_url}\n"


class SearXNGProcess:
    """Starts a private SearXNG when ``searxng_managed`` and a local install is present."""

    def __init__(self, settings: Settings, proxy_url: str | None = None) -> None:
        self.settings = settings
        self.proxy_url = proxy_url
        self._proc: asyncio.subprocess.Process | None = None
        self.status = "external"

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def _command(self) -> list[str] | None:
        if self.settings.searxng_bin:
            return [self.settings.searxng_bin]
        venv = Path(self.settings.resolved_data_dir()) / "searxng" / "venv"
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if py.exists():
            return [str(py), "-m", "searx.webapp"]
        found = shutil.which("searxng-run")
        return [found] if found else None

    async def _healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0, trust_env=False) as c:
                r = await c.get(self.settings.searxng_url.rstrip("/") + "/healthz")
                return r.status_code < 500
        except httpx.HTTPError:
            return False

    async def start(self) -> None:
        if not self.settings.searxng_managed or self.running:
            return
        if await self._healthy():
            self.status = "external"
            return
        cmd = self._command()
        if not cmd:
            self.status = "missing"
            log.info("No managed SearXNG installed; expecting one at %s", self.settings.searxng_url)
            return
        env = os.environ.copy()
        cfg = bundled_settings_path()
        data = self.settings.resolved_data_dir() / "searxng"
        data.mkdir(exist_ok=True)
        if cfg:
            runtime = data / "settings.yml"
            runtime.write_text(render_settings(cfg.read_text(), self.proxy_url))
            runtime.chmod(0o600)
            env["SEARXNG_SETTINGS_PATH"] = str(runtime)
        secret_file = data / "secret_key"
        if not secret_file.exists():
            import secrets

            secret_file.write_text(secrets.token_hex(32))
            secret_file.chmod(0o600)
        env["SEARXNG_SECRET"] = secret_file.read_text().strip()
        from urllib.parse import urlsplit

        parts = urlsplit(self.settings.searxng_url)
        env["SEARXNG_BIND_ADDRESS"] = parts.hostname or "127.0.0.1"
        env["SEARXNG_PORT"] = str(parts.port or 8888)
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            start_new_session=True,
            cwd=str(data),
        )
        self.status = "starting"
        log.info("Started SearXNG pid=%s", self._proc.pid)
        for _ in range(40):  # up to ~10 s
            if self._proc.returncode is not None:
                self.status = "crashed"
                return
            if await self._healthy():
                self.status = "managed"
                return
            await asyncio.sleep(0.25)

    async def stop(self) -> None:
        proc = self._proc
        if not proc or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=8)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        self._proc = None
        self.status = "stopped"


def python_executable() -> str:
    return sys.executable
