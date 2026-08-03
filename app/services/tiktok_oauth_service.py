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
USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"

# Permissoes necessarias para postar video pelo Content Posting API.
# Por padrao pedimos apenas os scopes disponiveis no Sandbox
# (user.info.basic + video.upload). Se voce habilitar o "Direct Post"
# no portal do TikTok, pode adicionar "video.publish" definindo a
# variavel TIKTOK_SCOPES no .env.
_DEFAULT_SCOPES = "user.info.basic,video.upload"


def _scopes() -> str:
    return (os.getenv("TIKTOK_SCOPES") or _DEFAULT_SCOPES).strip()


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
        "scope": _scopes(),
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
# Perfil da conta (user.info.basic) — nome + avatar para o painel
# ---------------------------------------------------------------
def fetch_user_info(access_token: str) -> dict:
    """Le o perfil basico (open_id, display_name, avatar_url).

    Usa o scope user.info.basic, apenas para o usuario confirmar em qual
    conta o video sera publicado. Nao guardamos mais nada do perfil.
    """
    try:
        resp = requests.get(
            USER_INFO_URL,
            params={"fields": "open_id,display_name,avatar_url"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        data = resp.json() or {}
        return (data.get("data") or {}).get("user") or {}
    except Exception:
        return {}


def _expires_at(data: dict) -> int:
    expires_in = int(data.get("expires_in") or 0)
    return int(time.time()) + expires_in if expires_in else 0


# ---------------------------------------------------------------
# Contas conectadas no BANCO (multiusuario)
# ---------------------------------------------------------------
def upsert_account(db, market: str, token_data: dict):
    """Cria/atualiza a conta do TikTok no banco a partir da resposta de token.

    Cada criador conecta a PROPRIA conta; guardamos os tokens dela (renovaveis)
    e o perfil basico. Chave estavel = open_id (uma linha por conta).
    """
    from app.models.dashboard import TikTokAccount

    access = (token_data.get("access_token") or "").strip()
    refresh = (token_data.get("refresh_token") or "").strip()
    open_id = (token_data.get("open_id") or "").strip()
    scope = (token_data.get("scope") or _scopes()).strip()

    info = fetch_user_info(access) if access else {}
    if not open_id:
        open_id = (info.get("open_id") or "").strip()
    if not open_id:
        raise ValueError("O TikTok nao retornou o open_id da conta.")

    account = (
        db.query(TikTokAccount)
        .filter(TikTokAccount.open_id == open_id)
        .first()
    )
    if account is None:
        account = TikTokAccount(open_id=open_id)
        db.add(account)

    account.market = _norm_market(market)
    if access:
        account.access_token = access
    if refresh:
        account.refresh_token = refresh
    account.token_expires_at = _expires_at(token_data)
    account.scopes = scope
    if info.get("display_name"):
        account.display_name = info.get("display_name")
    if info.get("avatar_url"):
        account.avatar_url = info.get("avatar_url")

    db.commit()
    db.refresh(account)
    return account


def list_accounts(db) -> list[dict]:
    """Lista as contas conectadas (para o painel)."""
    from app.models.dashboard import TikTokAccount

    rows = (
        db.query(TikTokAccount)
        .order_by(TikTokAccount.market, TikTokAccount.id)
        .all()
    )
    return [
        {
            "id": a.id,
            "open_id": a.open_id,
            "display_name": a.display_name or "(sem nome)",
            "avatar_url": a.avatar_url or "",
            "market": a.market or "",
            "connected": bool(a.refresh_token or a.access_token),
        }
        for a in rows
    ]


def delete_account(db, account_id: int) -> bool:
    """Desconecta (apaga) uma conta do TikTok."""
    from app.models.dashboard import TikTokAccount

    account = (
        db.query(TikTokAccount)
        .filter(TikTokAccount.id == account_id)
        .first()
    )
    if account is None:
        return False
    db.delete(account)
    db.commit()
    return True


def _valid_token_for_account(db, account) -> str:
    """Access_token valido da conta, renovando pelo refresh se preciso."""
    now = int(time.time())
    access = (account.access_token or "").strip()
    refresh = (account.refresh_token or "").strip()
    expires_at = int(account.token_expires_at or 0)
    if refresh and (not access or expires_at == 0 or now >= expires_at - 300):
        data = refresh_access_token(refresh)
        new_access = (data.get("access_token") or "").strip()
        if new_access:
            account.access_token = new_access
            new_refresh = (data.get("refresh_token") or "").strip()
            if new_refresh:
                account.refresh_token = new_refresh
            account.token_expires_at = _expires_at(data)
            db.commit()
            return new_access
    return access


def get_access_token_from_db(market: str) -> str:
    """Token valido de uma conta conectada (banco) para o mercado.

    Roteamento ESTRITO: usa SOMENTE a conta marcada para aquele mercado
    (BR/US). Se nao houver conta daquele mercado, devolve '' (o publisher
    pede para conectar a conta certa). NUNCA usa a conta de outro mercado
    como fallback -- era isso que fazia BR e US publicarem na mesma conta.
    """
    from app.core.database import SessionLocal
    from app.models.dashboard import TikTokAccount

    market = _norm_market(market)
    db = SessionLocal()
    try:
        account = (
            db.query(TikTokAccount)
            .filter(TikTokAccount.market == market)
            .order_by(TikTokAccount.updated_at.desc())
            .first()
        )
        if account is None:
            return ""
        return _valid_token_for_account(db, account)
    except Exception:
        return ""
    finally:
        db.close()


# ---------------------------------------------------------------
# Obter um access_token valido para publicar (renova se preciso)
# ---------------------------------------------------------------
def get_access_token(market: str) -> str:
    """Devolve um access_token valido para o mercado.

    Primeiro tenta as contas conectadas pelo painel (banco, multiusuario);
    se nao houver, cai nos tokens antigos do .env (compatibilidade).
    """
    market = _norm_market(market)

    db_token = get_access_token_from_db(market)
    if db_token:
        return db_token

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

    # Sem conta/token para ESTE mercado: retorna '' para NAO publicar na conta
    # de outro mercado. (Removido o fallback do token unico TIKTOK_ACCESS_TOKEN,
    # que fazia BR e US caírem na mesma conta.)
    return ""


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
