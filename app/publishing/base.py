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

import os
from dataclasses import dataclass, field
from typing import Optional


def project_root() -> str:
    """Raiz do projeto (usada para resolver caminhos de video)."""
    return os.path.abspath(os.getenv("ATLAS_ROOT", os.getcwd()))


def resolve_video_path(video_path: str) -> str:
    """Converte um caminho relativo do video para caminho absoluto."""
    if not video_path:
        return ""
    if os.path.isabs(video_path):
        return video_path
    return os.path.abspath(os.path.join(project_root(), video_path))


def public_media_url(video_path: str) -> str:
    """URL publica do video, servida pela rota /media/{path}.

    Necessaria para plataformas que baixam o video por URL
    (Instagram, Facebook, TikTok PULL_FROM_URL).
    """
    if not video_path:
        return ""
    base = (os.getenv("ATLAS_PUBLIC_BASE_URL") or "http://localhost:8000").rstrip("/")
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
        accounts.append(
            {
                "key": account_key("tiktok", None, market),
                "platform": "tiktok",
                "role": None,
                "market": market,
                "label": _account_label("tiktok", None, market),
                "external_id": "",
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
