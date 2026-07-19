# ============================================================
# ATLAS OS - tiktok_oauth_service.py
# Login (OAuth) do TikTok direto pelo painel, sem copiar tokens na mao.
#
# Fluxo:
#   1) Usuario clica "Conectar TikTok (BR/US)" no painel.
#   2) /api/tiktok/connect monta o link de autorizacao e redireciona.
#   3) TikTok volta em /api/tiktok/callback com um "code".
#   4) Trocamos o code por access_token + refresh_token e salvamos no .env.
#
# Depois, na hora de publicar, usamos o refresh_token para gerar um
# access_token novo automaticamente (o access_token do TikTok expira rapido).
# ============================================================

from __future__ import annotations

import os
import secrets
import time

import requests

from app.services.env_writer import set_env_vars

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

# Permissoes necessarias para postar video pelo Content Posting API.
SCOPES = "user.info.basic,video.publish,video.upload"

MARKETS = ("BR", "US")

# Guarda temporaria dos "state" gerados (protecao CSRF). Como e um app local
# de um usuario so, uma memoria simples ja resolve.
_pending_state: dict[str, str] = {}


# ---------------------------------------------------------------
# Credenciais do app (mesmo Client key/secret para BR e US)
# ---------------------------------------------------------------
def _client_key() -> str:
    return (os.getenv("TIKTOK_CLIENT_KEY") or "").strip()


def _client_secret() -> str:
    return (os.getenv("TIKTOK_CLIENT_SECRET") or "").strip()


def public_base() -> str:
    return (os.getenv("ATLAS_PUBLIC_BASE_URL") or "").strip().rstrip("/")


def redirect_uri() -> str:
    """Endereco de retorno que o TikTok chama depois do login.

    Precisa ser HTTPS e cadastrado no painel do TikTok
    (Login Kit -> Configure for Web -> Redirect URI).

    Preferimos um endereco FIXO (ATLAS_TIKTOK_REDIRECT_URI): uma pagininha
    hospedada no GitHub Pages que apenas reenvia o "code" para o ATLAS local
    (http://localhost:8000/api/tiktok/callback). Assim NAO precisamos de tunel
    publico, e o endereco nunca muda. Se essa variavel estiver vazia, caimos
    no modo antigo (link publico/tunel), se existir.
    """
    fixed = (os.getenv("ATLAS_TIKTOK_REDIRECT_URI") or "").strip()
    if fixed:
        return fixed
    base = public_base()
    return f"{base}/api/tiktok/callback" if base else ""


def _norm_market(market: str) -> str:
    m = (market or "").strip().upper()
    return m if m in MARKETS else "BR"


# ---------------------------------------------------------------
# Passo 1: montar o link de autorizacao
# ---------------------------------------------------------------
def build_authorize_url(market: str) -> str:
    from urllib.parse import urlencode

    market = _norm_market(market)
    csrf = secrets.token_urlsafe(16)
    state = f"{market}.{csrf}"
    _pending_state[state] = market

    params = {
        "client_key": _client_key(),
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def market_from_state(state: str) -> str:
    """Recupera o mercado a partir do state retornado pelo TikTok."""
    if state and state in _pending_state:
        return _pending_state.pop(state)
    # Fallback: o mercado esta no prefixo (BR.xxxx / US.xxxx).
    prefix = (state or "").split(".", 1)[0].upper()
    return prefix if prefix in MARKETS else "BR"


# ---------------------------------------------------------------
# Passo 2: trocar o code por tokens
# ---------------------------------------------------------------
def exchange_code(code: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": _client_key(),
            "client_secret": _client_secret(),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri(),
        },
        timeout=60,
    )
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": _client_key(),
            "client_secret": _client_secret(),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=60,
    )
    return resp.json()


# ---------------------------------------------------------------
# Salvar tokens no .env (por mercado)
# ---------------------------------------------------------------
def save_tokens(market: str, data: dict) -> None:
    market = _norm_market(market)
    access = (data.get("access_token") or "").strip()
    refresh = (data.get("refresh_token") or "").strip()
    open_id = (data.get("open_id") or "").strip()
    expires_in = int(data.get("expires_in") or 0)
    expires_at = int(time.time()) + expires_in if expires_in else 0

    values: dict[str, str] = {}
    if access:
        values[f"TIKTOK_ACCESS_TOKEN_{market}"] = access
    if refresh:
        values[f"TIKTOK_REFRESH_TOKEN_{market}"] = refresh
    if open_id:
        values[f"TIKTOK_OPEN_ID_{market}"] = open_id
    values[f"TIKTOK_TOKEN_EXPIRES_{market}"] = str(expires_at)

    if values:
        set_env_vars(values)


# ---------------------------------------------------------------
# Obter um access_token valido para publicar (renova se preciso)
# ---------------------------------------------------------------
def get_access_token(market: str) -> str:
    """Devolve um access_token valido para o mercado.

    Se houver refresh_token e o access_token estiver perto de expirar,
    renova automaticamente e salva o novo no .env.
    """
    market = _norm_market(market)
    refresh = (os.getenv(f"TIKTOK_REFRESH_TOKEN_{market}") or "").strip()
    access = (os.getenv(f"TIKTOK_ACCESS_TOKEN_{market}") or "").strip()
    expires_at = int((os.getenv(f"TIKTOK_TOKEN_EXPIRES_{market}") or "0").strip() or "0")

    now = int(time.time())
    # Renova se: tem refresh e (sem access, ou faltam menos de 5 min p/ expirar).
    if refresh and (not access or expires_at == 0 or now >= expires_at - 300):
        data = refresh_access_token(refresh)
        new_access = (data.get("access_token") or "").strip()
        if new_access:
            save_tokens(market, data)
            return new_access

    if access:
        return access

    # Ultimo recurso: token unico manual.
    return (os.getenv("TIKTOK_ACCESS_TOKEN") or "").strip()


# ---------------------------------------------------------------
# Status para o painel
# ---------------------------------------------------------------
def status() -> dict:
    has_client = bool(_client_key() and _client_secret())
    base = public_base()
    redirect = redirect_uri()
    # O que importa para conectar e o redirect_uri ser https (pagina fixa no
    # GitHub Pages OU link publico). Nao exigimos mais o tunel.
    is_https = redirect.lower().startswith("https://")

    markets = {}
    for m in MARKETS:
        refresh = (os.getenv(f"TIKTOK_REFRESH_TOKEN_{m}") or "").strip()
        access = (os.getenv(f"TIKTOK_ACCESS_TOKEN_{m}") or "").strip()
        open_id = (os.getenv(f"TIKTOK_OPEN_ID_{m}") or "").strip()
        markets[m] = {
            "connected": bool(refresh or access),
            "has_refresh": bool(refresh),
            "open_id": open_id,
        }

    return {
        "has_client": has_client,
        "public_base": base,
        "is_public_https": is_https,
        "redirect_uri": redirect_uri(),
        "markets": markets,
    }
