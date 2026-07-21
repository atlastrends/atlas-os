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

import requests
from sqlalchemy.orm import Session

from app.models.dashboard import (
    Publication,
    PublicationStatusEnum,
    PlatformStat,
    VideoMetric,
)
from app.publishing.base import list_publishing_accounts

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


class MetricsService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------------------------------------------------------
    # ENTRADA PRINCIPAL
    # ----------------------------------------------------------------

    def collect_all(self) -> dict:
        """Coleta metricas de todas as publicacoes e contas configuradas."""
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

        for pub in publications:
            try:
                metrics = self._collect_video(
                    pub.platform, pub.external_id, pub.video_asset_id
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{pub.platform}:{pub.external_id} -> {exc}")
                metrics = None

            if metrics:
                # Se o coletor descobriu o link publico do video (ex.: TikTok
                # depois que o rascunho vira post publico), grava/atualiza na
                # publicacao para aparecer o botao "Abrir" no Analytics.
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
                video_snapshots += 1

        # Estatisticas de conta por CONTA configurada (YouTube BR/US,
        # Instagram/Facebook Afiliados/Trends BR/US, etc.).
        platform_snapshots = 0
        for account in list_publishing_accounts():
            if not account.get("external_id"):
                continue
            try:
                stats = self._collect_account(account)
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
            return {} if "error" in resp else resp

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
