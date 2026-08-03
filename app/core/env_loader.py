# ============================================================
# ATLAS OS - env_loader.py
# Carrega o .env de forma robusta.
#
# Os segredos (chaves de API + login do TikTok/Meta) ficam no .env na
# RAIZ DO PROJETO (local, fora do OneDrive). Os tokens renovados sao
# gravados nesse mesmo arquivo. Nada e lido/escrito no OneDrive -- isso
# evitava que o OneDrive revertesse o refresh_token e derrubasse a conexao
# do TikTok toda semana.
#
# Opcional: defina ATLAS_ENV_FILE com o caminho completo de outro .env
# para usa-lo no lugar. Sem isso, usa o .env da raiz do projeto.
# ============================================================

from __future__ import annotations

import os

from dotenv import load_dotenv


def _project_env_path() -> str:
    """Caminho do .env na raiz do projeto (comportamento padrao)."""
    explicit = (os.getenv("ATLAS_ROOT") or "").strip()
    if explicit:
        root = os.path.abspath(explicit)
    else:
        # Fallback robusto: raiz derivada da localizacao deste arquivo,
        # independente do diretorio de onde o processo foi iniciado.
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, ".env")


def shared_env_path() -> str | None:
    """Caminho de um .env externo, se ATLAS_ENV_FILE estiver definido.

    So usamos um arquivo externo quando ATLAS_ENV_FILE aponta para ele
    (caminho completo). NAO procuramos mais no OneDrive: os segredos e os
    tokens renovados ficam no .env LOCAL do projeto, para o OneDrive nunca
    reverter o refresh_token do TikTok e derrubar a conexao.
    """
    explicit = (os.getenv("ATLAS_ENV_FILE") or "").strip()
    if explicit and os.path.isfile(explicit):
        return os.path.abspath(explicit)
    return None


def active_env_path() -> str:
    """O .env que o app deve LER e ESCREVER (tokens renovados).

    Usa o compartilhado quando ativo; senao, o .env do projeto.
    """
    return shared_env_path() or _project_env_path()


def load_env() -> None:
    """Carrega as variaveis de ambiente para o processo atual.

    Regras:
      - NUNCA sobrescreve variaveis ja definidas no ambiente (ex.: o
        start script define DATABASE_URL=sqlite; isso deve vencer sempre).
      - O .env COMPARTILHADO e a fonte da verdade dos segredos, entao e
        carregado ANTES do .env do projeto (com override=False, o primeiro
        a definir a chave vence).
    """
    shared = shared_env_path()
    if shared:
        load_dotenv(shared, override=False)
    load_dotenv(_project_env_path(), override=False)
