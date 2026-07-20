# ============================================================
# ATLAS OS - bio_updater.py
# Atualiza a pagina "link na bio" (docs/index.html) automaticamente
# sempre que um produto de afiliado e publicado, e envia para o GitHub
# Pages (git add/commit/push) em segundo plano, sem travar o painel.
# ============================================================

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Coalescing: se varios produtos forem publicados em sequencia, roda uma vez so.
_lock = threading.Lock()
_state = {"running": False, "dirty": False}


def _run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("DATABASE_URL", "sqlite:///./atlas_local.db")
    return subprocess.run(
        args,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _do_update() -> None:
    # 1) Regenera a pagina da bio a partir do banco.
    build = _run([sys.executable, "scripts/build_bio.py"])
    if build.returncode != 0:
        logger.error("Bio: falha ao gerar a pagina: %s", (build.stderr or "").strip())
        return

    # 2) Prepara o commit.
    _run(["git", "add", "docs/index.html"])

    # 3) Se nada mudou, nao commita (evita commit vazio).
    diff = _run(["git", "diff", "--cached", "--quiet", "--", "docs/index.html"])
    if diff.returncode == 0:
        logger.info("Bio: nada mudou, nada a publicar.")
        return

    # 4) Commit + push para o GitHub Pages.
    commit = _run(["git", "commit", "-m", "Bio: atualiza produtos (automatico)"])
    if commit.returncode != 0:
        logger.error("Bio: falha no commit: %s", (commit.stderr or "").strip())
        return

    push = _run(["git", "push"])
    if push.returncode != 0:
        logger.error("Bio: falha no push: %s", (push.stderr or "").strip())
        return

    logger.info("Bio: pagina atualizada e publicada no GitHub Pages.")


def _worker() -> None:
    while True:
        with _lock:
            if not _state["dirty"]:
                _state["running"] = False
                return
            _state["dirty"] = False
        try:
            _do_update()
        except Exception:  # nunca deixa quebrar o fluxo de publicacao
            logger.exception("Bio: erro inesperado ao atualizar automaticamente.")


def trigger_bio_update() -> None:
    """Agenda a atualizacao da bio em segundo plano (nao bloqueia o chamador)."""
    with _lock:
        _state["dirty"] = True
        if _state["running"]:
            return
        _state["running"] = True
    threading.Thread(target=_worker, name="bio-updater", daemon=True).start()
