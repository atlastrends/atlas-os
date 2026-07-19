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
                metrics = self._collect_video(pub.platform, pub.external_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{pub.platform}:{pub.external_id} -> {exc}")
                metrics = None

            if metrics:
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

    def _collect_video(self, platform: str, external_id: str) -> dict | None:
        if platform == "youtube":
            return self._youtube_video(external_id)
        if platform == "instagram":
            return self._instagram_video(external_id)
        if platform == "facebook":
            return self._facebook_video(external_id)
        if platform == "tiktok":
            return self._tiktok_video(external_id)
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
        resp = requests.get(
            f"{GRAPH_BASE}/{media_id}/insights",
            params={"metric": "plays,likes,comments,shares", "access_token": token},
            timeout=30,
        ).json()
        data = {d["name"]: (d.get("values", [{}])[0].get("value", 0)) for d in resp.get("data", [])}
        if not data:
            return None
        return {
            "views": data.get("plays", 0),
            "likes": data.get("likes", 0),
            "comments": data.get("comments", 0),
            "shares": data.get("shares", 0),
        }

    def _facebook_video(self, video_id: str) -> dict | None:
        token = os.getenv("META_ACCESS_TOKEN")
        if not token:
            return None
        resp = requests.get(
            f"{GRAPH_BASE}/{video_id}",
            params={
                "fields": "views,likes.summary(true),comments.summary(true)",
                "access_token": token,
            },
            timeout=30,
        ).json()
        if "error" in resp:
            return None
        likes = (resp.get("likes", {}) or {}).get("summary", {}).get("total_count", 0)
        comments = (resp.get("comments", {}) or {}).get("summary", {}).get("total_count", 0)
        return {
            "views": resp.get("views", 0),
            "likes": likes,
            "comments": comments,
        }

    def _tiktok_video(self, publish_id: str) -> dict | None:
        # A metrica por video no TikTok requer o video_id final (apos o
        # processamento) e o escopo video.list. Deixado como ponto de
        # extensao; retorna None ate o fluxo de status ser implementado.
        return None

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
        return None

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
