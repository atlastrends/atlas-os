from __future__ import annotations

import atexit
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse


log = logging.getLogger("atlas.public_tunnel")

_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)
_lock = threading.Lock()
_process: subprocess.Popen | None = None
_log_handle = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def is_public_https_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and bool(host)
        and host not in {"localhost", "127.0.0.1", "::1"}
        and not host.endswith(".local")
    )


def _cloudflared_executable() -> Path | None:
    root = _project_root()
    candidates = (
        root / "cloudflared.exe",
        root / "bin" / "cloudflared.exe",
        root / "cloudflared",
        root / "bin" / "cloudflared",
    )
    return next((path for path in candidates if path.is_file()), None)


def _read_tunnel_url(log_path: Path) -> str:
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    matches = _URL_PATTERN.findall(text)
    return next(
        (url for url in reversed(matches) if "api.trycloudflare.com" not in url),
        "",
    )


def _stop_managed_tunnel() -> None:
    global _process, _log_handle
    process = _process
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    _process = None
    if _log_handle is not None:
        _log_handle.close()
        _log_handle = None


def shutdown_public_tunnel() -> None:
    with _lock:
        _stop_managed_tunnel()


atexit.register(_stop_managed_tunnel)


def ensure_public_base_url(timeout_seconds: float = 35.0) -> str:
    global _process, _log_handle

    configured = (os.getenv("ATLAS_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if is_public_https_url(configured):
        return configured

    with _lock:
        configured = (os.getenv("ATLAS_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        if is_public_https_url(configured):
            return configured

        executable = _cloudflared_executable()
        if executable is None:
            log.error("cloudflared nao encontrado; URL publica indisponivel.")
            return ""

        log_path = Path(tempfile.gettempdir()) / "atlas_cloudflared_runtime.log"
        existing_url = _read_tunnel_url(log_path)
        if (
            _process is not None
            and _process.poll() is None
            and is_public_https_url(existing_url)
        ):
            os.environ["ATLAS_PUBLIC_BASE_URL"] = existing_url
            return existing_url

        _stop_managed_tunnel()
        try:
            _log_handle = log_path.open("w", encoding="utf-8")
            creation_flags = (
                subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            _process = subprocess.Popen(
                [
                    str(executable),
                    "tunnel",
                    "--url",
                    "http://127.0.0.1:8000",
                    "--no-autoupdate",
                ],
                stdout=_log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
        except OSError as error:
            log.error("Falha ao iniciar cloudflared: %s", error)
            _stop_managed_tunnel()
            return ""

        deadline = time.monotonic() + max(5.0, timeout_seconds)
        while time.monotonic() < deadline:
            url = _read_tunnel_url(log_path)
            if is_public_https_url(url):
                os.environ["ATLAS_PUBLIC_BASE_URL"] = url
                state_path = _project_root() / "storage" / "public_tunnel.json"
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps(
                        {
                            "url": url,
                            "pid": _process.pid if _process else None,
                            "created_at": time.time(),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                log.info("Tunel publico automatico ativo: %s", url)
                return url
            if _process is not None and _process.poll() is not None:
                break
            time.sleep(0.5)

        log.error("cloudflared nao forneceu uma URL publica dentro do prazo.")
        _stop_managed_tunnel()
        return ""
