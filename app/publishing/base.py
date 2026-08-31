# ============================================================
# ATLAS OS - publishing/base.py
# Interface comum para todos os conectores de publicacao.
#
# Cada conector sabe:
#  - verificar se as credenciais necessarias existem (is_configured)
#  - publicar um video (publish)
#
# Enquanto as credenciais oficiais nao forem preenchidas no .env,
# o conector responde CREDENTIALS_MISSING, sem quebrar o fluxo.
# ============================================================

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import requests


def project_root() -> str:
    """Raiz do projeto (usada para resolver caminhos de video)."""
    explicit = (os.getenv("ATLAS_ROOT") or "").strip()
    if explicit:
        return os.path.abspath(explicit)
    # Fallback robusto: raiz derivada da localizacao deste arquivo
    # (independe do diretorio de onde o servidor foi iniciado).
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve_video_path(video_path: str) -> str:
    """Converte um caminho relativo do video para caminho absoluto."""
    if not video_path:
        return ""
    if os.path.isabs(video_path):
        return video_path
    return os.path.abspath(os.path.join(project_root(), video_path))


def local_media_file(video_path: str) -> str:
    """Caminho absoluto do arquivo LOCAL do video, se ele existir no disco.

    Usado para enviar os BYTES direto para a Meta (rupload.facebook.com), sem
    depender de uma URL publica. Isso elimina de vez o erro recorrente
    "403 Restricted by robots.txt": a Meta so bate em robots.txt quando PRECISA
    BAIXAR o video de uma URL (Supabase esgotado -> fallback para o tunel
    trycloudflare, que bloqueia bots). Enviando os bytes, nao ha URL para a Meta
    buscar e o robots.txt deixa de importar."""
    full = resolve_video_path(video_path)
    return full if full and os.path.isfile(full) else ""


def public_media_url(video_path: str) -> str:
    """URL publica do video, servida pela rota /media/{path}.

    Necessaria para plataformas que baixam o video por URL
    (Instagram, Facebook, TikTok PULL_FROM_URL).

    Se o armazenamento na nuvem (Supabase) estiver configurado, SOBE o video
    para la e devolve a URL publica de la (funciona atras de firewall que
    bloqueia o tunel). Senao, cai para ATLAS_PUBLIC_BASE_URL (tunel/localhost).
    """
    if not video_path:
        return ""
    try:
        from app.services.media_storage import get_or_upload_public_url, is_enabled

        if is_enabled():
            remote = get_or_upload_public_url(video_path)
            if remote:
                return remote
    except Exception:
        # Nunca quebra a publicacao por causa do armazenamento; cai no fallback.
        pass
    base = (os.getenv("ATLAS_PUBLIC_BASE_URL") or "http://localhost:8000").rstrip("/")
    from app.services.public_tunnel_service import (
        ensure_public_base_url,
        is_public_https_url,
    )

    if not is_public_https_url(base):
        base = ensure_public_base_url() or base
    rel = str(video_path).replace("\\", "/").lstrip("/")
    return f"{base}/media/{rel}"


def market_code(country_code: str = "", language: str = "") -> str:
    """Deduz o mercado ('BR' ou 'US') a partir do pais/idioma do video."""
    code = (country_code or "").strip().upper()
    lang = (language or "").strip().lower()
    if code.startswith("BR") or code == "PT" or lang.startswith("pt"):
        return "BR"
    if code.startswith("US") or code == "EN" or lang.startswith("en"):
        return "US"
    return "US"


def role_code(kind: str = "") -> str:
    """Papel da conta: 'AFFILIATE' (Achados/Finds) ou 'TREND' (reels)."""
    return "AFFILIATE" if (kind or "").strip().lower() == "affiliate" else "TREND"


# ----------------------------------------------------------------
# REGISTRO DE CONTAS (todas as contas de todas as plataformas)
# ----------------------------------------------------------------

MARKET_LABELS = {"BR": "Brasil", "US": "US"}
ROLE_LABELS = {"AFFILIATE": "Afiliados", "TREND": "Trends"}
PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook": "Facebook",
}
_MARKETS = ("BR", "US")


def _account_label(platform: str, role: str | None, market: str) -> str:
    plat = PLATFORM_LABELS.get((platform or "").lower(), platform.capitalize())
    mkt = MARKET_LABELS.get(market, market)
    if role:
        return f"{plat} {ROLE_LABELS.get(role, role)} {mkt}"
    return f"{plat} {mkt}"


def account_key(platform: str, role: str | None, market: str) -> str:
    """Chave URL-safe de uma conta: ex. 'instagram.AFFILIATE.BR',
    'youtube.all.US'."""
    return f"{(platform or '').lower()}.{role or 'all'}.{market}"


def account_for_video(
    platform: str,
    kind: str = "",
    country_code: str = "",
    language: str = "",
) -> dict:
    """Deduz a conta usada para publicar um video numa plataforma,
    a partir do tipo (afiliado/trend) e do mercado (BR/US)."""
    platform = (platform or "").lower()
    market = market_code(country_code, language)
    # Instagram/Facebook tem contas por PAPEL (Afiliados x Trends).
    # YouTube e TikTok agrupam so por mercado: afiliados e trends do mesmo
    # pais vao para o MESMO canal (BR->Brasil, US->EUA).
    role = role_code(kind) if platform in ("instagram", "facebook") else None
    return {
        "key": account_key(platform, role, market),
        "platform": platform,
        "role": role,
        "market": market,
        "label": _account_label(platform, role, market),
    }


def list_publishing_accounts() -> list[dict]:
    """Enumera todas as contas configuradas no .env, por plataforma.

    Cada conta: key, platform, role, market, label, external_id, connected.
    Sao incluidas apenas as contas que possuem um identificador definido
    (canal/pagina/perfil) ou um login valido.
    """
    accounts: list[dict] = []
    default_market = (os.getenv("YOUTUBE_DEFAULT_MARKET") or "BR").strip().upper()

    # YouTube: UM canal por mercado (BR/US). Afiliados e trends do mesmo
    # pais publicam no MESMO canal (sem separacao por papel).
    for market in _MARKETS:
        lang_suffix = "PT" if market == "BR" else "EN"
        token = (os.getenv(f"YOUTUBE_REFRESH_TOKEN_{market}") or "").strip()
        if not token and market == default_market:
            token = (os.getenv("YOUTUBE_REFRESH_TOKEN") or "").strip()
        ext = (
            os.getenv(f"YOUTUBE_CHANNEL_ID_{lang_suffix}")
            or os.getenv("YOUTUBE_CHANNEL_ID")
            or ""
        ).strip()
        if ext or token:
            accounts.append(
                {
                    "key": account_key("youtube", None, market),
                    "platform": "youtube",
                    "role": None,
                    "market": market,
                    "label": _account_label("youtube", None, market),
                    "external_id": ext,
                    "connected": bool(token),
                }
            )

    # Instagram e Facebook: por papel (Afiliados/Trends) x mercado.
    for role in ("AFFILIATE", "TREND"):
        for market in _MARKETS:
            ig = (os.getenv(f"IG_{role}_{market}") or "").strip()
            if ig:
                accounts.append(
                    {
                        "key": account_key("instagram", role, market),
                        "platform": "instagram",
                        "role": role,
                        "market": market,
                        "label": _account_label("instagram", role, market),
                        "external_id": ig,
                        "connected": bool(os.getenv("META_ACCESS_TOKEN")),
                    }
                )
            fb = (os.getenv(f"FB_PAGE_{role}_{market}") or "").strip()
            if fb:
                accounts.append(
                    {
                        "key": account_key("facebook", role, market),
                        "platform": "facebook",
                        "role": role,
                        "market": market,
                        "label": _account_label("facebook", role, market),
                        "external_id": fb,
                        "connected": bool(os.getenv("META_ACCESS_TOKEN")),
                    }
                )

    # TikTok: por mercado (BR/US).
    for market in _MARKETS:
        tok = (
            os.getenv(f"TIKTOK_ACCESS_TOKEN_{market}")
            or os.getenv("TIKTOK_ACCESS_TOKEN")
            or ""
        ).strip()
        open_id = (os.getenv(f"TIKTOK_OPEN_ID_{market}") or "").strip()
        accounts.append(
            {
                "key": account_key("tiktok", None, market),
                "platform": "tiktok",
                "role": None,
                "market": market,
                "label": _account_label("tiktok", None, market),
                # open_id identifica a conta; a coleta usa o token do mercado.
                "external_id": open_id,
                "connected": bool(tok),
            }
        )

    return accounts


def resolve_meta_targets(
    kind: str = "",
    country_code: str = "",
    language: str = "",
) -> tuple[str, str, str, str]:
    """Escolhe a Pagina do Facebook e a conta do Instagram corretas
    conforme o tipo de video (afiliado/trend) e o mercado (BR/US).

    Ordem de resolucao:
      1) variavel especifica  FB_PAGE_{ROLE}_{MERCADO} / IG_{ROLE}_{MERCADO}
      2) fallback antigo       FACEBOOK_PAGE_ID / INSTAGRAM_BUSINESS_ACCOUNT_ID

    Retorna (page_id, ig_id, role, market).
    """
    role = role_code(kind)
    market = market_code(country_code, language)

    page_id = (
        os.getenv(f"FB_PAGE_{role}_{market}")
        or os.getenv("FACEBOOK_PAGE_ID")
        or ""
    ).strip()
    ig_id = (
        os.getenv(f"IG_{role}_{market}")
        or os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
        or ""
    ).strip()

    return page_id, ig_id, role, market


# Cache simples em memoria: {page_id: (page_access_token, obtido_em)}.
# Uma unica chamada /me/accounts ja devolve TODAS as Paginas, entao
# cacheamos todas de uma vez. O token da Pagina e LONGEVO (nao muda com
# frequencia), por isso o TTL e alto: menos chamadas ao Graph API = menor
# risco de estourar o limite de requisicoes do app ("(#4) Application
# request limit reached"), sobretudo com o app em modo "Nao publicado".
_PAGE_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_PAGE_TOKEN_TTL_SECONDS = 6 * 60 * 60  # 6 horas

# Cooldown apos um rate-limit do app (#4) em /me/accounts: enquanto durar,
# reaproveitamos o token em cache em vez de chamar o Graph de novo (evita
# piorar o bloqueio quando um lote inteiro publica em sequencia).
_ME_ACCOUNTS_COOLDOWN_SECONDS = 120
_ME_ACCOUNTS_STATE: dict[str, float] = {"blocked_until": 0.0}

# Persistencia do cache de tokens de Pagina EM DISCO, para SOBREVIVER a
# reinicios do servidor. Sem isso, o 1o publish depois de um restart precisa
# chamar /me/accounts - e e exatamente ai que o (#4) costuma estourar (quando a
# cota do app ja foi esgotada por outro consumidor, ex.: a coleta de metricas).
# Com o token em disco, o publish reaproveita o token da Pagina e nem toca no
# /me/accounts.
_PAGE_TOKEN_CACHE_FILE = os.path.join(
    project_root(), "storage", "state", "meta_page_tokens.json"
)
_PAGE_TOKEN_LOCK = threading.Lock()


def _load_page_token_cache() -> None:
    """Carrega o cache de tokens de Pagina do disco para a memoria (no import)."""
    try:
        with open(_PAGE_TOKEN_CACHE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    for pid, entry in data.items():
        try:
            token, ts = entry
        except (TypeError, ValueError):
            continue
        if pid and token:
            _PAGE_TOKEN_CACHE[str(pid)] = (str(token), float(ts))


def _save_page_token_cache() -> None:
    """Grava o cache de tokens de Pagina no disco (apos atualizar pela API)."""
    path = _PAGE_TOKEN_CACHE_FILE
    try:
        with _PAGE_TOKEN_LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            snapshot = {
                pid: [tok, ts] for pid, (tok, ts) in _PAGE_TOKEN_CACHE.items()
            }
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh)
            os.replace(tmp, path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# COOLDOWN COMPARTILHADO do limite do APP da Meta ((#4) Application request
# limit reached). E um limite do APP INTEIRO (IG + FB + metricas + comentarios
# somados) e some sozinho apos alguns minutos. Fica CENTRALIZADO aqui para que
# TODOS os consumidores do Graph (publicacao, coleta de metricas, robo de
# comentarios e a propria resolucao de token) respeitem a MESMA janela e parem
# de chamar o Graph enquanto ela durar - assim a cota se recupera em vez de ser
# martelada sem parar. Mesmo arquivo/formato usado pelo publishing_service (o
# estado e cross-processo: servidor + scripts interoperam).
# ---------------------------------------------------------------------------
_META_APP_LIMIT_HINTS = (
    "application request limit",
    "request limit reached",
    "(#4)",
)


def is_meta_app_limit(error_text: object) -> bool:
    """True se o texto for o rate-limit do APP da Meta (#4) (temporario)."""
    if not error_text:
        return False
    text = str(error_text).lower()
    return any(h in text for h in _META_APP_LIMIT_HINTS)


def _meta_cooldown_file() -> str:
    return os.path.join(project_root(), "storage", "state", "meta_app_cooldown")


def meta_app_cooldown_remaining() -> float:
    """Segundos restantes do cooldown do app da Meta (0.0 se nao ha)."""
    try:
        with open(_meta_cooldown_file(), "r", encoding="utf-8") as fh:
            expiry = float((fh.read() or "0").strip() or "0")
    except (OSError, ValueError):
        return 0.0
    remaining = expiry - time.time()
    return remaining if remaining > 0 else 0.0


def trip_meta_app_cooldown() -> None:
    """Abre a janela de cooldown do app da Meta apos um (#4). Duracao em
    ATLAS_META_COOLDOWN_MINUTES (padrao 20 min)."""
    try:
        minutes = int(os.getenv("ATLAS_META_COOLDOWN_MINUTES", "20") or "20")
    except ValueError:
        minutes = 20
    minutes = max(1, minutes)
    path = _meta_cooldown_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(time.time() + minutes * 60))
    except OSError:
        pass


_load_page_token_cache()


class MetaGraphTransientError(RuntimeError):
    """Erro TEMPORARIO do Graph API (ex.: rate limit do app) ao resolver o
    token da Pagina. Deve ser tratado como 'aguardar reenvio', nao como
    permissao negada - o proprio texto do erro e propagado para que
    publishing_service consiga classifica-lo via _is_rate_limited()."""


def get_page_access_token(page_id: str) -> str:
    """Troca o token MESTRE do usuario (META_ACCESS_TOKEN) pelo token
    ESPECIFICO da Pagina do Facebook (necessario para publicar Reels/posts
    e para publicar no Instagram conectado aquela Pagina).

    O Graph API exige o token da propria Pagina para acoes de escrita
    (video_reels, media, media_publish) - o token de usuario sozinho,
    mesmo com 'pages_manage_posts', recebe 403/#200 nessas chamadas.

    Se /me/accounts responder com um ERRO do Graph (ex.: "(#4) Application
    request limit reached", rate limit do app), NAO caimos silenciosamente
    para o token de usuario (isso so trocaria um erro claro de rate-limit
    por um #200 confuso e ainda gastaria mais uma chamada de API tentando
    publicar com um token que ja sabemos que vai falhar). Em vez disso,
    levantamos MetaGraphTransientError com a mensagem original do Graph.

    Se a Pagina simplesmente nao aparecer em /me/accounts (sem erro - ex.:
    token sem acesso aquela Pagina), ai sim caimos para o token de usuario,
    para nao travar o fluxo (pode funcionar ou nao, dependendo das permissoes).
    """
    user_token = (os.getenv("META_ACCESS_TOKEN") or "").strip()
    if not page_id or not user_token:
        return user_token

    now = time.time()
    cached = _PAGE_TOKEN_CACHE.get(page_id)
    if cached and (now - cached[1]) < _PAGE_TOKEN_TTL_SECONDS:
        return cached[0]

    # Se levamos rate-limit do app (#4) ha pouco, nao martelamos /me/accounts
    # de novo dentro da janela de cooldown (isso so pioraria o bloqueio quando
    # um lote publica em sequencia). Reaproveita o token da Pagina em cache
    # (mesmo vencido - ele e longevo e quase sempre continua valido) ou, se
    # nao houver cache, sinaliza erro TEMPORARIO para reenviar depois. Alem do
    # guarda local de 120s, respeita o cooldown COMPARTILHADO do app da Meta
    # (mesmo (#4) visto por metricas/comentarios) para nao reabrir o buraco.
    if now < _ME_ACCOUNTS_STATE["blocked_until"] or meta_app_cooldown_remaining() > 0:
        if cached:
            return cached[0]
        raise MetaGraphTransientError(
            "Limite de requisicoes do app (Meta) atingido ha pouco - "
            "aguardando a janela de reenvio antes de consultar /me/accounts."
        )

    graph_version = os.getenv("META_GRAPH_VERSION", "v21.0")
    resp_json: dict = {}
    try:
        resp = requests.get(
            f"https://graph.facebook.com/{graph_version}/me/accounts",
            params={"access_token": user_token, "fields": "id,access_token"},
            timeout=30,
        )
        resp_json = resp.json()
    except Exception as exc:  # noqa: BLE001
        # Falha de rede: reaproveita o token em cache (mesmo vencido) se houver.
        if cached:
            return cached[0]
        raise MetaGraphTransientError(
            f"Falha de rede ao consultar /me/accounts no Graph API: {exc}"
        ) from exc

    if "error" in resp_json:
        # Erro explicito do Graph (rate limit do app, token invalido, etc.).
        # Abre uma janela de cooldown para nao repetir a chamada no lote e,
        # se ja temos o token da Pagina em cache (mesmo vencido), usa-o em vez
        # de falhar por um bloqueio TEMPORARIO - o token da Pagina segue valido.
        _ME_ACCOUNTS_STATE["blocked_until"] = now + _ME_ACCOUNTS_COOLDOWN_SECONDS
        # Se for o (#4) do app inteiro, abre tambem o cooldown COMPARTILHADO
        # para que metricas/comentarios/publicacao parem de bater no Graph e a
        # cota se recupere de verdade (a causa mais comum deste (#4) e uma
        # rajada de chamadas de OUTRO consumidor esgotando o app).
        if is_meta_app_limit(resp_json.get("error")):
            trip_meta_app_cooldown()
        if cached:
            return cached[0]
        raise MetaGraphTransientError(
            f"Erro do Graph API (Meta) ao obter token da Pagina {page_id}: "
            f"{resp_json['error']}"
        )

    # Sucesso: cacheia TODAS as Paginas retornadas de uma vez. A mesma resposta
    # ja traz o token das outras Paginas, entao os proximos page_id viram
    # cache-hit e nao geram novas chamadas ao /me/accounts.
    found_token = ""
    for item in resp_json.get("data", []):
        pid = item.get("id")
        ptok = item.get("access_token")
        if pid and ptok:
            _PAGE_TOKEN_CACHE[pid] = (ptok, now)
            if pid == page_id:
                found_token = ptok
    # Persiste o cache atualizado em disco para sobreviver a reinicios.
    _save_page_token_cache()
    if found_token:
        return found_token

    # Pagina nao encontrada (sem erro do Graph) - fallback para o token de
    # usuario, para nao travar o fluxo.
    return user_token


def resolve_tiktok_token(
    country_code: str = "",
    language: str = "",
) -> tuple[str, str]:
    """Escolhe o token (conta) do TikTok conforme o mercado (BR/US).

    Afiliados e trends do mesmo pais publicam na MESMA conta do TikTok
    (o TikTok separa so por mercado, igual ao YouTube).

    Roteamento ESTRITO: usa SOMENTE o token da conta daquele mercado
    (TIKTOK_ACCESS_TOKEN_{MERCADO}). Sem esse token -> '' (nao cai no token
    unico TIKTOK_ACCESS_TOKEN, que misturaria as contas BR e US).

    Retorna (access_token, market).
    """
    market = market_code(country_code, language)
    token = (os.getenv(f"TIKTOK_ACCESS_TOKEN_{market}") or "").strip()
    return token, market



def resolve_youtube_channel(
    country_code: str = "",
    language: str = "",
    kind: str = "",
) -> tuple[str, str, str, str, str]:
    """Escolhe o canal correto do YouTube conforme o mercado (BR/US).

    Afiliados e trends do mesmo pais publicam no MESMO canal:
      - BR -> canal Brasil
      - US -> canal EUA

    IMPORTANTE: no YouTube, cada canal exige o SEU proprio refresh token
    (gerado autorizando aquele canal especifico).

    Ordem de resolucao do refresh token:
      - YOUTUBE_REFRESH_TOKEN_{MERCADO}
      - YOUTUBE_REFRESH_TOKEN            (so no mercado padrao)

    Retorna (refresh_token, client_id, client_secret, market, channel_id).
    """
    market = market_code(country_code, language)
    default_market = (os.getenv("YOUTUBE_DEFAULT_MARKET") or "BR").strip().upper()
    lang_suffix = "PT" if market == "BR" else "EN"

    refresh = (os.getenv(f"YOUTUBE_REFRESH_TOKEN_{market}") or "").strip()
    if not refresh and market == default_market:
        refresh = (os.getenv("YOUTUBE_REFRESH_TOKEN") or "").strip()

    client_id = (
        os.getenv(f"YOUTUBE_CLIENT_ID_{market}")
        or os.getenv("YOUTUBE_CLIENT_ID")
        or ""
    ).strip()
    client_secret = (
        os.getenv(f"YOUTUBE_CLIENT_SECRET_{market}")
        or os.getenv("YOUTUBE_CLIENT_SECRET")
        or ""
    ).strip()

    channel_id = (
        os.getenv(f"YOUTUBE_CHANNEL_ID_{lang_suffix}")
        or os.getenv("YOUTUBE_CHANNEL_ID")
        or ""
    ).strip()

    return refresh, client_id, client_secret, market, channel_id


@dataclass
class PublishResult:
    status: str  # published | failed | credentials_missing
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    error: Optional[str] = None
    detail: dict = field(default_factory=dict)


@dataclass
class PublishRequest:
    video_path: str
    title: str
    description: str
    caption: str
    hashtags: list
    kind: str = ""
    language: str = ""
    country_code: str = ""
    affiliate_url: Optional[str] = None
    extra: dict = field(default_factory=dict)


class BasePublisher:
    """Classe base de um conector de plataforma."""

    platform: str = "base"
    #: Variaveis de ambiente obrigatorias para o conector funcionar.
    required_env: tuple[str, ...] = ()

    def missing_credentials(self) -> list[str]:
        return [
            name
            for name in self.required_env
            if not (os.getenv(name) or "").strip()
        ]

    def is_configured(self) -> bool:
        return len(self.missing_credentials()) == 0

    def publish(self, request: PublishRequest) -> PublishResult:
        missing = self.missing_credentials()

        if missing:
            return PublishResult(
                status="credentials_missing",
                error=(
                    "Credenciais ausentes: "
                    + ", ".join(missing)
                ),
                detail={"missing_env": missing},
            )

        return self._do_publish(request)

    def _do_publish(self, request: PublishRequest) -> PublishResult:
        raise NotImplementedError
