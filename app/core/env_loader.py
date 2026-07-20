# ============================================================
# ATLAS OS - env_loader.py
# Carrega o .env de forma robusta e permite CENTRALIZAR os segredos
# (chaves de API + login do TikTok/Meta) num arquivo unico que
# SINCRONIZA sozinho entre computadores (ex.: OneDrive).
#
# Objetivo: funcionar em varias maquinas SEM copiar o .env toda vez e
# SEM colocar segredos no Git (o repositorio e publico).
#
# Como ATIVAR o modo compartilhado (opcional, feito UMA vez):
#   - Coloque o seu .env em:  %OneDrive%\ATLAS-OS-SECRETS\.env
#     (o OneDrive sincroniza esse arquivo para os seus outros PCs)
#   - OU defina a variavel de ambiente ATLAS_ENV_FILE apontando para
#     um arquivo .env (caminho completo).
#
# Sem nenhuma dessas opcoes, o comportamento e o de sempre: usa o
# .env que fica na raiz do projeto. Ou seja, nada muda por padrao.
# ============================================================

from __future__ import annotations

import os

from dotenv import load_dotenv


def _project_env_path() -> str:
    """Caminho do .env na raiz do projeto (comportamento padrao)."""
    root = os.path.abspath(os.getenv("ATLAS_ROOT", os.getcwd()))
    return os.path.join(root, ".env")


def _onedrive_roots() -> list[str]:
    """Pastas raiz do OneDrive detectadas pelas variaveis do Windows."""
    roots: list[str] = []
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        val = (os.getenv(var) or "").strip()
        if val and val not in roots:
            roots.append(val)
    return roots


def shared_env_path() -> str | None:
    """Caminho do .env COMPARTILHADO (sincronizado), se estiver ativo.

    Ordem de prioridade:
      1) ATLAS_ENV_FILE (caminho explicito) — se o arquivo existir.
      2) %OneDrive%\\ATLAS-OS-SECRETS\\.env — se o arquivo existir.
    Retorna None quando nenhum existe (ai o app usa o .env do projeto).
    """
    explicit = (os.getenv("ATLAS_ENV_FILE") or "").strip()
    if explicit and os.path.isfile(explicit):
        return os.path.abspath(explicit)

    for root in _onedrive_roots():
        candidate = os.path.join(root, "ATLAS-OS-SECRETS", ".env")
        if os.path.isfile(candidate):
            return candidate

    return None


def active_env_path() -> str:
    """O .env que o app deve LER e ESCREVER (tokens renovados).

    Usa o compartilhado quando ativo; senao, o .env do projeto.
    """
    return shared_env_path() or _project_env_path()


def load_env() -> None:
    """Carrega as variaveis de ambiente para o processo atual.

    Primeiro o .env do projeto (base) e depois o compartilhado (que
    vence), para que os segredos sincronizados sejam a fonte da verdade.
    """
    load_dotenv(_project_env_path(), override=False)
    shared = shared_env_path()
    if shared:
        load_dotenv(shared, override=True)
