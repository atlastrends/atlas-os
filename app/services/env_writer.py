# ============================================================
# ATLAS OS - env_writer.py
# Grava/atualiza valores no arquivo .env de forma segura.
#
# Usado para guardar tokens gerados na hora (ex.: login do TikTok),
# sem o usuario precisar copiar nada na mao.
#
# - Atualiza a linha existente (KEY=...) ou adiciona uma nova.
# - Preserva os comentarios e a ordem do arquivo.
# - Tambem atualiza os.environ para o processo atual enxergar na hora.
# ============================================================

from __future__ import annotations

import os
import threading

_LOCK = threading.Lock()


def _env_path() -> str:
    """Caminho do .env (na raiz do projeto)."""
    root = os.path.abspath(os.getenv("ATLAS_ROOT", os.getcwd()))
    return os.path.join(root, ".env")


def set_env_vars(values: dict[str, str]) -> None:
    """Atualiza/insere varias chaves no .env e no ambiente atual.

    Exemplo:
        set_env_vars({"TIKTOK_REFRESH_TOKEN_BR": "abc123"})
    """
    if not values:
        return

    # Normaliza tudo para string.
    clean: dict[str, str] = {str(k): ("" if v is None else str(v)) for k, v in values.items()}

    with _LOCK:
        path = _env_path()
        lines: list[str] = []
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()

        remaining = dict(clean)

        # Atualiza linhas existentes.
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                lines[i] = f"{key}={remaining.pop(key)}"

        # Adiciona as que faltaram (no fim do arquivo).
        if remaining:
            if lines and lines[-1].strip() != "":
                lines.append("")
            for key, value in remaining.items():
                lines.append(f"{key}={value}")

        content = "\n".join(lines).rstrip("\n") + "\n"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    # Reflete no processo atual (o painel ja rodando enxerga sem reiniciar).
    for key, value in clean.items():
        os.environ[key] = value
