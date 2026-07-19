"""
Gera o login (refresh token) de um canal do YouTube.

Use isto para autorizar UM canal especifico. Ao abrir o navegador,
faca login e ESCOLHA O CANAL certo (ex.: "Atlas Trends US").

Como usar (no terminal, dentro da pasta atlas-os):

    .\.venv-dash\Scripts\python.exe tools\get_youtube_token.py

No fim ele imprime a linha pronta para colar no .env, por exemplo:

    YOUTUBE_REFRESH_TOKEN_US=1//0abc...

Requisitos ja instalados no ambiente:
    google-auth-oauthlib, google-api-python-client
"""

from __future__ import annotations

import os
import sys

# Carrega o .env para reaproveitar CLIENT_ID / CLIENT_SECRET ja configurados.
try:
    from dotenv import load_dotenv

    load_dotenv()
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


def main() -> int:
    client_id = (os.getenv("YOUTUBE_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("YOUTUBE_CLIENT_SECRET") or "").strip()

    if not client_id or not client_secret:
        print("ERRO: defina YOUTUBE_CLIENT_ID e YOUTUBE_CLIENT_SECRET no .env antes.")
        return 1

    # Pergunta qual canal esta sendo autorizado, para imprimir a linha certa.
    choices = {
        "1": ("YOUTUBE_REFRESH_TOKEN_TREND_BR", "Trends Brasil"),
        "2": ("YOUTUBE_REFRESH_TOKEN_TREND_US", "Trends US"),
        "3": ("YOUTUBE_REFRESH_TOKEN_AFFILIATE_BR", "Afiliados Brasil"),
        "4": ("YOUTUBE_REFRESH_TOKEN_AFFILIATE_US", "Afiliados US"),
    }
    print("Qual canal voce vai autorizar agora?")
    print("  1) Trends Brasil")
    print("  2) Trends US")
    print("  3) Afiliados Brasil")
    print("  4) Afiliados US")
    picked = ""
    try:
        picked = input("Digite 1, 2, 3 ou 4 e ENTER: ").strip()
    except EOFError:
        picked = ""
    env_var, channel_label = choices.get(picked, ("YOUTUBE_REFRESH_TOKEN_AFFILIATE_US", "Afiliados US"))

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

    print()
    print("=" * 60)
    print(" LOGIN GERADO COM SUCESSO")
    print("=" * 60)
    print(f"Canal autorizado: {channel_label}")
    print("Cole a linha abaixo no .env:")
    print()
    print(f"{env_var}={refresh_token}")
    print()
    print("Depois reinicie o painel para valer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
