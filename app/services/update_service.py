# ============================================================
# ATLAS OS - update_service.py
# Verifica e aplica atualizacoes a partir de um repositorio
# PUBLICO no GitHub, SEM precisar de git instalado no PC.
#
# Como funciona:
#  - "check": pergunta ao GitHub qual e o ultimo commit do repositorio
#    e compara com o arquivo VERSION (o commit instalado agora).
#  - "apply": abre uma nova janela e roda o script atualizar.ps1, que
#    baixa o ZIP mais novo, substitui o codigo (preservando seus dados
#    e segredos), reinstala dependencias, recompila o painel e reinicia.
#
# Config (no .env):
#   ATLAS_UPDATE_REPO=usuario/atlas-os   (ex.: cpenteri/atlas-os)
#   ATLAS_UPDATE_BRANCH=main             (opcional, padrao "main")
# ============================================================

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _project_root() -> Path:
    root = os.getenv("ATLAS_ROOT")
    if root:
        return Path(root)
    # app/services/update_service.py -> raiz do projeto
    return Path(__file__).resolve().parents[2]


def _repo() -> str:
    return (os.getenv("ATLAS_UPDATE_REPO") or "").strip().strip("/")


def _branch() -> str:
    return (os.getenv("ATLAS_UPDATE_BRANCH") or "main").strip()


def _version_file() -> Path:
    return _project_root() / "VERSION"


def current_version() -> str:
    try:
        txt = _version_file().read_text(encoding="utf-8").strip()
        return txt or "dev"
    except Exception:
        return "dev"


def _http_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "atlas-os-updater",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (url fixo do github)
        return json.loads(resp.read().decode("utf-8"))


def check() -> dict:
    """Consulta o GitHub e diz se ha versao nova disponivel."""
    repo = _repo()
    current = current_version()
    if not repo:
        return {
            "configured": False,
            "current": current,
            "update_available": False,
            "error": (
                "Ainda nao configurado. Defina ATLAS_UPDATE_REPO=usuario/atlas-os "
                "no arquivo .env para ligar as atualizacoes."
            ),
        }

    branch = _branch()
    url = f"https://api.github.com/repos/{repo}/commits/{branch}"
    try:
        data = _http_json(url)
    except urllib.error.HTTPError as exc:
        msg = "Repositorio nao encontrado." if exc.code == 404 else f"Erro do GitHub ({exc.code})."
        return {
            "configured": True,
            "current": current,
            "update_available": False,
            "error": msg,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "configured": True,
            "current": current,
            "update_available": False,
            "error": f"Nao consegui falar com o GitHub: {exc}",
        }

    latest = str(data.get("sha") or "")
    commit = data.get("commit") or {}
    author = commit.get("author") or {}
    message = (commit.get("message") or "").split("\n")[0].strip()
    date = author.get("date") or ""

    # Regra: se estamos em "dev", oferecemos a instalacao da versao publicada;
    # caso contrario, so quando o commit mais novo for diferente do instalado.
    if current == "dev":
        update_available = bool(latest)
    else:
        update_available = bool(latest) and latest[:12] != current[:12]

    return {
        "configured": True,
        "repo": repo,
        "branch": branch,
        "current": current[:12] if current != "dev" else "dev",
        "latest": latest[:12],
        "latest_full": latest,
        "latest_message": message,
        "latest_date": date,
        "update_available": update_available,
        "error": None,
    }


def apply() -> dict:
    """Abre uma janela nova e roda o atualizar.ps1 (baixa ZIP + reinicia)."""
    repo = _repo()
    if not repo:
        return {
            "started": False,
            "error": "Configure ATLAS_UPDATE_REPO no .env antes de atualizar.",
        }

    root = _project_root()
    script = root / "atualizar.ps1"
    if not script.exists():
        return {"started": False, "error": "Script atualizar.ps1 nao encontrado."}

    CREATE_NEW_CONSOLE = 0x00000010
    try:
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Repo",
                repo,
                "-Branch",
                _branch(),
            ],
            cwd=str(root),
            creationflags=CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"started": False, "error": f"Nao consegui iniciar a atualizacao: {exc}"}

    return {
        "started": True,
        "message": (
            "Atualizacao iniciada em uma nova janela. O painel vai fechar e voltar "
            "sozinho em instantes. Aguarde a janela terminar e recarregue a pagina."
        ),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
