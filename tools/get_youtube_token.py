"""
Gera o login (refresh token) de um canal do YouTube.

Use isto para autorizar UM canal especifico. Ao abrir o navegador,
faca login e ESCOLHA O CANAL certo (ex.: "Atlas Trends US").

Como usar (no terminal, dentro da pasta atlas-os):

    .\.venv-dash\Scripts\python.exe tools\get_youtube_token.py BR
    .\.venv-dash\Scripts\python.exe tools\get_youtube_token.py US

(sem argumento ele pergunta 1=BR / 2=US). Ao final ele GRAVA o refresh
token direto no .env (YOUTUBE_REFRESH_TOKEN_BR ou _US) e NUNCA mostra o
valor na tela. Depois reinicie o painel para valer.

Requisitos ja instalados no ambiente:
    google-auth-oauthlib, google-api-python-client
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _active_env_path() -> Path:
    """O MESMO .env que o app le e escreve (espelha env_loader.active_env_path).

    Ordem: 1) ATLAS_ENV_FILE se existir; 2) %OneDrive%\\ATLAS-OS-SECRETS\\.env
    se existir; senao 3) o .env na raiz do projeto (pasta acima de tools/).
    Grava o refresh token no arquivo que o SERVIDOR realmente le - o
    compartilhado vence o do projeto (env_loader carrega com override=False).
    """
    explicit = (os.getenv("ATLAS_ENV_FILE") or "").strip()
    if explicit and Path(explicit).is_file():
        return Path(explicit).resolve()
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = (os.getenv(var) or "").strip()
        if root:
            candidate = Path(root) / "ATLAS-OS-SECRETS" / ".env"
            if candidate.is_file():
                return candidate.resolve()
    return Path(__file__).resolve().parent.parent / ".env"


# .env ATIVO (compartilhado quando existir) = onde gravamos o token novo.
ENV_PATH = _active_env_path()
_PROJECT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Carrega as variaveis como o app faz (o ativo manda, o do projeto completa)
# para reaproveitar CLIENT_ID / CLIENT_SECRET onde quer que estejam.
try:
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH, override=True)
    if _PROJECT_ENV_PATH != ENV_PATH:
        load_dotenv(_PROJECT_ENV_PATH, override=False)
except Exception:  # noqa: BLE001
    pass

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

UPLOAD_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Porta FIXA para o retorno do login. Precisa estar cadastrada no Google Cloud
# em "URIs de redirecionamento autorizados" (para clientes do tipo Web):
#     http://localhost:8090/
# Se preferir outra porta, mude aqui e cadastre a mesma no Google.
REDIRECT_PORT = int((os.getenv("YOUTUBE_OAUTH_PORT") or "8090").strip() or "8090")
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/"


def _upsert_env_var(key: str, value: str) -> bool:
    """Cria/atualiza `key=value` no .env preservando o resto do arquivo.

    Retorna True se gravou com sucesso. Nunca imprime o valor secreto.
    """
    env_path = str(ENV_PATH)
    line = f"{key}={value}"
    try:
        try:
            with open(env_path, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except FileNotFoundError:
            lines = []

        replaced = False
        for i, existing in enumerate(lines):
            stripped = existing.lstrip()
            if stripped.startswith(f"{key}=") and not stripped.startswith("#"):
                lines[i] = line
                replaced = True
                break
        if not replaced:
            lines.append(line)

        with open(env_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"AVISO: falha ao gravar no .env: {exc}")
        return False


def main() -> int:
    client_id = (os.getenv("YOUTUBE_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("YOUTUBE_CLIENT_SECRET") or "").strip()

    if not client_id or not client_secret:
        print("ERRO: defina YOUTUBE_CLIENT_ID e YOUTUBE_CLIENT_SECRET no .env antes.")
        return 1

    # O painel resolve o canal do YouTube por MERCADO (BR/US): trends e
    # afiliados do mesmo pais usam o MESMO canal e o MESMO refresh token.
    # Por isso so existem duas variaveis, EXATAMENTE as que o app le em
    # resolve_youtube_channel(): YOUTUBE_REFRESH_TOKEN_BR e YOUTUBE_REFRESH_TOKEN_US.
    by_market = {
        "BR": ("YOUTUBE_REFRESH_TOKEN_BR", "Brasil (BR)"),
        "US": ("YOUTUBE_REFRESH_TOKEN_US", "EUA (US)"),
    }
    by_number = {"1": "BR", "2": "US"}

    # O mercado pode vir por argumento (modo nao-interativo), ex.: ... py BR
    arg = sys.argv[1].strip().upper() if len(sys.argv) > 1 else ""
    market = arg if arg in by_market else by_number.get(arg, "")
    if not market:
        print("Qual canal voce vai autorizar agora?")
        print("  1) Brasil (BR)")
        print("  2) EUA (US)")
        picked = ""
        try:
            picked = input("Digite 1 ou 2 e ENTER: ").strip()
        except EOFError:
            picked = ""
        market = by_number.get(picked, "BR")
    env_var, channel_label = by_market[market]

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }

    print("=" * 60)
    print(f" Gerar login do canal: {channel_label}")
    print("=" * 60)
    print("IMPORTANTE: no Google Cloud Console, o cliente OAuth precisa ter")
    print("este endereco em 'URIs de redirecionamento autorizados':")
    print(f"    {REDIRECT_URI}")
    print("-" * 60)
    print(f"Vai abrir o navegador. Faca login e ESCOLHA O CANAL '{channel_label}'.")
    print("Se aparecer aviso 'app nao verificado', clique em 'Avancado' ->")
    print("'Ir para ... (nao seguro)' para continuar (e o seu proprio app).")
    print("-" * 60)

    flow = InstalledAppFlow.from_client_config(
        client_config,
        scopes=UPLOAD_SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    creds = flow.run_local_server(port=REDIRECT_PORT, prompt="consent")

    refresh_token = getattr(creds, "refresh_token", None)
    if not refresh_token:
        print("ERRO: o Google nao retornou refresh_token. Tente de novo com prompt=consent.")
        return 1

    # Grava o token DIRETO no .env (nunca imprime o valor secreto na tela).
    written = _upsert_env_var(env_var, refresh_token)

    print()
    print("=" * 60)
    print(" LOGIN GERADO COM SUCESSO")
    print("=" * 60)
    print(f"Canal autorizado: {channel_label}")
    if written:
        print(f"Gravado no .env: {env_var} (len={len(refresh_token)})")
        print("Agora reinicie o painel para valer.")
    else:
        print("NAO consegui gravar no .env automaticamente.")
        print(f"Defina manualmente a variavel {env_var} no .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
