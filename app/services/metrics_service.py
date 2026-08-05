# ============================================================
# ATLAS OS - metrics_service.py
# Coleta metricas das publicacoes (views, likes, comments, shares)
# e estatisticas de conta (seguidores) por plataforma, gravando
# snapshots em video_metrics e platform_stats.
#
# YouTube usa a API Key (estatisticas publicas). Instagram/Facebook
# usam a Graph API (insights). TikTok usa a Display/Content API.
# Cada coletor e protegido: se faltar credencial ou a API falhar,
# aquela plataforma e apenas ignorada, sem quebrar o restante.
# ============================================================

from __future__ import annotations

import os
import time

import requests
from sqlalchemy.orm import Session

from app.models.dashboard import (
    Publication,
    PublicationStatusEnum,
    PlatformStat,
    VideoMetric,
)
from app.publishing.base import (
    MetaGraphTransientError,
    is_meta_app_limit,
    list_publishing_accounts,
    meta_app_cooldown_remaining,
    project_root,
    trip_meta_app_cooldown,
)

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Plataformas que compartilham a MESMA cota do app da Meta ((#4)).
_META_PLATFORMS = {"instagram", "facebook"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _meta_offset_file() -> str:
    """Cursor rotativo (em disco) de qual fatia de posts IG/FB foi coletada por
    ultimo, para as rodadas cobrirem todos os videos ao longo do tempo."""
    return os.path.join(project_root(), "storage", "state", "metrics_meta_offset")


def _read_meta_offset() -> int:
    try:
        with open(_meta_offset_file(), "r", encoding="utf-8") as fh:
            return max(0, int((fh.read() or "0").strip() or "0"))
    except (OSError, ValueError):
        return 0


def _write_meta_offset(value: int) -> None:
    path = _meta_offset_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(max(0, int(value))))
    except OSError:
        pass


class MetricsService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------------------------------------------------------
    # ENTRADA PRINCIPAL
    # ----------------------------------------------------------------

    def collect_all(self, force_meta: bool = False) -> dict:
        """Coleta metricas de todas as publicacoes e contas configuradas.

        As chamadas ao Instagram/Facebook (Graph API) compartilham a MESMA cota
        do app da Meta. Para NAO estourar o (#4) 'Application request limit', a
        coleta IG/FB aqui: (1) e PULADA enquanto houver cooldown ativo do app;
        (2) e LIMITADA a um numero de posts por rodada (rotativo, para todos os
        videos serem cobertos ao longo das rodadas); (3) ESPACA as chamadas; e
        (4) ao detectar um (#4), abre o cooldown e PARA de bater no Graph nesta
        rodada. YouTube/TikTok nao entram nesse limite.

        force_meta=True (clique MANUAL em "Coletar metricas") ignora o flag
        ATLAS_METRICS_META_ENABLED e coleta TODOS os posts IG/FB desta vez
        (sem teto rotativo), respeitando ainda o cooldown do (#4).
        """
        video_snapshots = 0
        errors: list[str] = []

        publications = (
            self.db.query(Publication)
            .filter(
                Publication.status == PublicationStatusEnum.PUBLISHED,
                Publication.external_id.isnot(None),
            )
            .all()
        )

        meta_pubs = [p for p in publications if p.platform in _META_PLATFORMS]
        other_pubs = [p for p in publications if p.platform not in _META_PLATFORMS]

        # 1) YouTube / TikTok: fora do limite de app da Meta, coleta tudo.
        for pub in other_pubs:
            video_snapshots += self._snapshot_one(pub, errors)

        # Salva o lote YouTube/TikTok de imediato: os numeros ja comecam a
        # mudar no painel sem esperar a coleta (mais lenta) de IG/FB terminar.
        self.db.commit()

        # 2) Instagram / Facebook: so coleta se HABILITADO e sem cooldown do
        # (#4); limita e espaca. A coleta de metricas IG/FB pode ser DESLIGADA
        # por completo (ATLAS_METRICS_META_ENABLED=false) para NAO gastar a cota
        # do app da Meta com varredura horaria - as PUBLICACOES continuam
        # funcionando normalmente (o link do produto fica na BIO).
        meta_enabled = force_meta or _env_bool("ATLAS_METRICS_META_ENABLED", True)
        meta_blocked = (not meta_enabled) or (meta_app_cooldown_remaining() > 0)
        if not meta_enabled and meta_pubs:
            errors.append(
                "meta: coleta de metricas IG/FB DESATIVADA "
                "(ATLAS_METRICS_META_ENABLED=false) - nenhuma chamada ao Graph."
            )
        elif meta_app_cooldown_remaining() > 0 and meta_pubs:
            errors.append(
                "meta: cooldown do (#4) ativo (~"
                f"{int(meta_app_cooldown_remaining())}s) - pulei metricas IG/FB "
                "nesta rodada."
            )
        elif meta_pubs:
            spacing = max(0, _env_int("ATLAS_METRICS_META_SPACING_MS", 400)) / 1000.0
            meta_pubs.sort(key=lambda p: p.id or 0)
            total = len(meta_pubs)
            # No clique MANUAL coletamos TODOS os posts IG/FB de uma vez; na
            # varredura automatica respeitamos o teto rotativo por rodada.
            cap = total if force_meta else max(1, _env_int("ATLAS_METRICS_META_MAX_POSTS", 50))
            start = 0 if force_meta else (_read_meta_offset() % total)
            attempted = 0
            for i in range(min(cap, total)):
                pub = meta_pubs[(start + i) % total]
                attempted += 1
                try:
                    video_snapshots += self._snapshot_one(
                        pub, errors, raise_app_limit=True
                    )
                except MetaGraphTransientError:
                    trip_meta_app_cooldown()
                    meta_blocked = True
                    errors.append(
                        "meta: (#4) detectado -> abri cooldown e parei a coleta "
                        "IG/FB nesta rodada (retoma sozinho na proxima)."
                    )
                    break
                # Salva em lotes: os numeros de IG/FB vao aparecendo no painel
                # aos poucos e o progresso nao se perde se algo falhar no meio.
                if attempted % 15 == 0:
                    self.db.commit()
                if spacing:
                    time.sleep(spacing)
            self.db.commit()
            # Avanca o cursor rotativo pelos que TENTAMOS, para a proxima rodada
            # continuar de onde parou e cobrir todos os videos ao longo do tempo.
            _write_meta_offset((start + attempted) % total)

        # 3) Estatisticas de conta por CONTA configurada (YouTube BR/US,
        # Instagram/Facebook Afiliados/Trends BR/US, etc.). Pula IG/FB se o
        # cooldown da Meta estiver ativo.
        platform_snapshots = 0
        for account in list_publishing_accounts():
            if not account.get("external_id"):
                continue
            if account.get("platform") in _META_PLATFORMS and meta_blocked:
                continue
            try:
                stats = self._collect_account(account)
            except MetaGraphTransientError:
                trip_meta_app_cooldown()
                meta_blocked = True
                errors.append("meta: (#4) em estatisticas de conta -> cooldown.")
                stats = None
            except Exception as exc:  # noqa: BLE001
                errors.append(f"account:{account['key']} -> {exc}")
                stats = None

            if stats:
                self.db.add(
                    PlatformStat(
                        platform=account["platform"],
                        account=account["key"],
                        followers=int(stats.get("followers", 0) or 0),
                        following=int(stats.get("following", 0) or 0),
                        total_views=int(stats.get("total_views", 0) or 0),
                        total_likes=int(stats.get("total_likes", 0) or 0),
                    )
                )
                platform_snapshots += 1

        self.db.commit()

        return {
            "video_snapshots": video_snapshots,
            "platform_snapshots": platform_snapshots,
            "publications_checked": len(publications),
            "errors": errors,
        }

    def _snapshot_one(
        self,
        pub: Publication,
        errors: list[str],
        raise_app_limit: bool = False,
    ) -> int:
        """Coleta e grava UM snapshot de metricas de uma publicacao.

        Retorna 1 se gravou, 0 caso contrario. Se raise_app_limit=True e o Graph
        devolver o (#4) do app da Meta, propaga MetaGraphTransientError para o
        chamador abrir o cooldown e parar a coleta IG/FB da rodada.
        """
        try:
            metrics = self._collect_video(
                pub.platform, pub.external_id, pub.video_asset_id
            )
        except MetaGraphTransientError:
            if raise_app_limit:
                raise
            errors.append(f"{pub.platform}:{pub.external_id} -> (#4) app limit")
            return 0
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{pub.platform}:{pub.external_id} -> {exc}")
            return 0

        if not metrics:
            return 0

        # Se o coletor descobriu o link publico do video (ex.: TikTok depois que
        # o rascunho vira post publico), grava/atualiza na publicacao para
        # aparecer o botao "Abrir" no Analytics.
        new_url = (metrics.get("external_url") or "").strip()
        if new_url and pub.external_url != new_url:
            pub.external_url = new_url

        self.db.add(
            VideoMetric(
                video_asset_id=pub.video_asset_id,
                platform=pub.platform,
                views=int(metrics.get("views", 0) or 0),
                likes=int(metrics.get("likes", 0) or 0),
                comments=int(metrics.get("comments", 0) or 0),
                shares=int(metrics.get("shares", 0) or 0),
                clicks=int(metrics.get("clicks", 0) or 0),
            )
        )
        return 1

    # ----------------------------------------------------------------
    # COLETORES POR VIDEO
    # ----------------------------------------------------------------

    def _collect_video(
        self, platform: str, external_id: str, video_asset_id: int | None = None
    ) -> dict | None:
        if platform == "youtube":
            return self._youtube_video(external_id)
        if platform == "instagram":
            return self._instagram_video(external_id)
        if platform == "facebook":
            return self._facebook_video(external_id)
        if platform == "tiktok":
            return self._tiktok_video(external_id, video_asset_id)
        return None

    def _youtube_video(self, video_id: str) -> dict | None:
        api_key = os.getenv("YOUTUBE_API_KEY")
        if not api_key:
            return None
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics", "id": video_id, "key": api_key},
            timeout=30,
        ).json()
        items = resp.get("items") or []
        if not items:
            return None
        stats = items[0].get("statistics", {})
        return {
            "views": stats.get("viewCount", 0),
            "likes": stats.get("likeCount", 0),
            "comments": stats.get("commentCount", 0),
        }

    def _instagram_video(self, media_id: str) -> dict | None:
        token = os.getenv("META_ACCESS_TOKEN")
        if not token:
            return None
        # OBS.: para Reels o Instagram nao aceita mais a metrica "plays";
        # o nome atual e "views". As demais (likes/comments/shares) seguem
        # iguais. Exige a permissao instagram_manage_insights no token.
        resp = requests.get(
            f"{GRAPH_BASE}/{media_id}/insights",
            params={"metric": "views,likes,comments,shares", "access_token": token},
            timeout=30,
        ).json()
        if isinstance(resp, dict) and "error" in resp:
            if is_meta_app_limit(resp.get("error")):
                raise MetaGraphTransientError(str(resp.get("error")))
            return None
        data = {d["name"]: (d.get("values", [{}])[0].get("value", 0)) for d in resp.get("data", [])}
        if not data:
            return None
        out = {
            "views": data.get("views", 0),
            "likes": data.get("likes", 0),
            "comments": data.get("comments", 0),
            "shares": data.get("shares", 0),
        }
        # Tambem confere o link real (permalink) e corrige se estiver errado.
        try:
            info = requests.get(
                f"{GRAPH_BASE}/{media_id}",
                params={"fields": "permalink", "access_token": token},
                timeout=30,
            ).json()
            real = (info or {}).get("permalink")
            if real:
                out["external_url"] = real
        except Exception:  # noqa: BLE001
            pass
        return out

    def _facebook_video(self, video_id: str) -> dict | None:
        # Cada campo e buscado numa chamada separada porque o Facebook
        # bloqueia a resposta INTEIRA se qualquer campo pedido faltar
        # permissao (ex.: "comments" pode exigir uma permissao que o
        # token ainda nao tem). Assim, se "comments" falhar, "views" e
        # "likes" continuam aparecendo normalmente.
        token = os.getenv("META_ACCESS_TOKEN")
        if not token:
            return None

        def _safe_get(fields: str) -> dict:
            try:
                resp = requests.get(
                    f"{GRAPH_BASE}/{video_id}",
                    params={"fields": fields, "access_token": token},
                    timeout=30,
                ).json()
            except Exception:  # noqa: BLE001
                return {}
            if isinstance(resp, dict) and "error" in resp:
                if is_meta_app_limit(resp.get("error")):
                    raise MetaGraphTransientError(str(resp.get("error")))
                return {}
            return resp

        base_resp = _safe_get("views,permalink_url")
        if not base_resp:
            return None
        likes_resp = _safe_get("likes.summary(true)")
        comments_resp = _safe_get("comments.summary(true)")

        likes = (likes_resp.get("likes", {}) or {}).get("summary", {}).get("total_count", 0)
        comments = (comments_resp.get("comments", {}) or {}).get("summary", {}).get("total_count", 0)
        resp = base_resp
        out = {
            "views": resp.get("views", 0),
            "likes": likes,
            "comments": comments,
        }
        real = (resp.get("permalink_url") or "").strip()
        if real:
            out["external_url"] = real if real.startswith("http") else f"https://www.facebook.com{real}"
        return out

    def _tiktok_video(
        self, publish_id: str, video_asset_id: int | None = None
    ) -> dict | None:
        # Metrica por video no TikTok:
        #   1) publish_id -> post_id via /post/publish/status/fetch/
        #      (so retorna post_id depois que o video vira publico no perfil).
        #   2) post_id -> estatisticas via /video/query/ (escopo video.list).
        # Videos ainda em rascunho/inbox nao tem post_id -> retornam None.
        if not publish_id:
            return None
        from app.services import tiktok_oauth_service

        market = self._tiktok_market_for_asset(video_asset_id)
        token = tiktok_oauth_service.get_access_token(market)
        if not token:
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        status = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
            headers=headers,
            json={"publish_id": publish_id},
            timeout=30,
        ).json()
        data = status.get("data") or {}
        post_ids = data.get("publicaly_available_post_id") or []
        if not post_ids:
            return None

        query = requests.post(
            "https://open.tiktokapis.com/v2/video/query/",
            headers=headers,
            params={
                "fields": "id,view_count,like_count,comment_count,share_count,share_url"
            },
            json={"filters": {"video_ids": [str(x) for x in post_ids]}},
            timeout=30,
        ).json()
        videos = (query.get("data") or {}).get("videos") or []
        if not videos:
            return None

        views = likes = comments = shares = 0
        share_url = None
        for v in videos:
            views += int(v.get("view_count", 0) or 0)
            likes += int(v.get("like_count", 0) or 0)
            comments += int(v.get("comment_count", 0) or 0)
            shares += int(v.get("share_count", 0) or 0)
            if not share_url and v.get("share_url"):
                share_url = v.get("share_url")
        return {
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "external_url": share_url,
        }

    def _tiktok_market_for_asset(self, video_asset_id: int | None) -> str:
        """Descobre o mercado (BR/US) do video para escolher a conta/token."""
        if not video_asset_id:
            return "BR"
        from app.models.dashboard import VideoAsset
        from app.publishing.base import market_code

        asset = (
            self.db.query(VideoAsset)
            .filter(VideoAsset.id == video_asset_id)
            .first()
        )
        if not asset:
            return "BR"
        return market_code(asset.country_code or "", asset.language or "")

    # ----------------------------------------------------------------
    # COLETORES POR CONTA
    # ----------------------------------------------------------------

    def _collect_account(self, account: dict) -> dict | None:
        platform = account["platform"]
        ext = (account.get("external_id") or "").strip()
        if platform == "youtube":
            return self._youtube_channel(ext)
        if platform == "instagram":
            return self._instagram_account(ext)
        if platform == "facebook":
            return self._facebook_page(ext)
        if platform == "tiktok":
            return self._tiktok_account(account)
        return None

    def _tiktok_account(self, account: dict) -> dict | None:
        # Estatisticas da conta do TikTok (seguidores, curtidas totais)
        # via /v2/user/info/. Requer o escopo user.info.stats.
        from app.services import tiktok_oauth_service

        market = (account.get("market") or "BR").strip().upper()
        token = tiktok_oauth_service.get_access_token(market)
        if not token:
            return None
        resp = requests.get(
            "https://open.tiktokapis.com/v2/user/info/",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "fields": "follower_count,following_count,likes_count,video_count"
            },
            timeout=30,
        ).json()
        if (resp.get("error") or {}).get("code") not in (None, "ok"):
            return None
        user = (resp.get("data") or {}).get("user") or {}
        if not user:
            return None
        return {
            "account": account.get("external_id") or market,
            "followers": user.get("follower_count", 0),
            "following": user.get("following_count", 0),
            "total_likes": user.get("likes_count", 0),
        }

    def _youtube_channel(self, channel_id: str | None = None) -> dict | None:
        api_key = os.getenv("YOUTUBE_API_KEY")
        channel_id = channel_id or os.getenv("YOUTUBE_CHANNEL_ID")
        if not api_key or not channel_id:
            return None
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "statistics", "id": channel_id, "key": api_key},
            timeout=30,
        ).json()
        items = resp.get("items") or []
        if not items:
            return None
        stats = items[0].get("statistics", {})
        return {
            "account": channel_id,
            "followers": stats.get("subscriberCount", 0),
            "total_views": stats.get("viewCount", 0),
        }

    def _instagram_account(self, ig_id: str | None = None) -> dict | None:
        token = os.getenv("META_ACCESS_TOKEN")
        ig_id = ig_id or os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
        if not token or not ig_id:
            return None
        resp = requests.get(
            f"{GRAPH_BASE}/{ig_id}",
            params={"fields": "followers_count,follows_count,media_count", "access_token": token},
            timeout=30,
        ).json()
        if "error" in resp:
            return None
        return {
            "account": ig_id,
            "followers": resp.get("followers_count", 0),
            "following": resp.get("follows_count", 0),
        }

    def _facebook_page(self, page_id: str | None = None) -> dict | None:
        token = os.getenv("META_ACCESS_TOKEN")
        page_id = page_id or os.getenv("FACEBOOK_PAGE_ID")
        if not token or not page_id:
            return None
        resp = requests.get(
            f"{GRAPH_BASE}/{page_id}",
            params={"fields": "followers_count,fan_count", "access_token": token},
            timeout=30,
        ).json()
        if "error" in resp:
            return None
        return {
            "account": page_id,
            "followers": resp.get("followers_count", resp.get("fan_count", 0)),
        }
