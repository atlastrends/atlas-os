# ============================================================
# ATLAS OS - analytics_service.py
# Agrega metricas para o painel:
#  - totais (videos, publicados, curtidas, cliques, seguidores)
#  - metricas por plataforma
#  - metricas por video (ultimo snapshot)
#  - cliques dos links de afiliado
#
# As metricas reais sao populadas pelos coletores das APIs oficiais
# (quando as credenciais existem). Sem credenciais, retorna o que
# houver armazenado (ou zeros), sem quebrar o painel.
# ============================================================

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.dashboard import (
    PlatformStat,
    Publication,
    PublicationStatusEnum,
    ShortLink,
    VideoAsset,
    VideoKindEnum,
    VideoMetric,
    VideoStatusEnum,
)
from app.publishing.registry import PLATFORMS
from app.publishing.base import (
    _account_label,
    account_for_video,
    list_publishing_accounts,
)


class AnalyticsService:
    def __init__(self, db: Session):
        self.db = db

    def overview(self) -> dict:
        db = self.db

        total_videos = db.query(func.count(VideoAsset.id)).scalar() or 0
        total_reels = (
            db.query(func.count(VideoAsset.id))
            .filter(VideoAsset.kind == VideoKindEnum.REEL)
            .scalar()
            or 0
        )
        total_affiliate = (
            db.query(func.count(VideoAsset.id))
            .filter(VideoAsset.kind == VideoKindEnum.AFFILIATE)
            .scalar()
            or 0
        )
        published = (
            db.query(func.count(VideoAsset.id))
            .filter(VideoAsset.status == VideoStatusEnum.PUBLISHED)
            .scalar()
            or 0
        )
        pending = (
            db.query(func.count(VideoAsset.id))
            .filter(VideoAsset.status == VideoStatusEnum.CREATED)
            .scalar()
            or 0
        )

        def _count_status(value) -> int:
            return (
                db.query(func.count(VideoAsset.id))
                .filter(VideoAsset.status == value)
                .scalar()
                or 0
            )

        approved = _count_status(VideoStatusEnum.APPROVED)
        rejected = _count_status(VideoStatusEnum.REJECTED)
        publishing = _count_status(VideoStatusEnum.PUBLISHING)
        failed = _count_status(VideoStatusEnum.FAILED)

        totals = self._metric_totals()
        total_clicks = db.query(func.coalesce(func.sum(ShortLink.clicks), 0)).scalar() or 0
        # Soma apenas a ULTIMA coleta de cada CONTA (evita contar o
        # historico varias vezes e bater com a tabela por conta).
        total_followers = sum(
            int(stat.followers or 0)
            for stat in self._latest_account_stats().values()
        )

        views = int(totals["views"])
        likes = int(totals["likes"])
        comments = int(totals["comments"])
        shares = int(totals["shares"])

        engagement = likes + comments + shares
        engagement_rate = round((engagement / views) * 100, 2) if views else 0.0
        click_through_rate = round((int(total_clicks) / views) * 100, 2) if views else 0.0

        last_metric_at = (
            db.query(func.max(VideoMetric.captured_at)).scalar()
        )

        return {
            "total_videos": int(total_videos),
            "total_reels": int(total_reels),
            "total_affiliate": int(total_affiliate),
            "published": int(published),
            "pending_review": int(pending),
            "approved": int(approved),
            "rejected": int(rejected),
            "publishing": int(publishing),
            "failed": int(failed),
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "engagement": int(engagement),
            "engagement_rate": engagement_rate,
            "click_through_rate": click_through_rate,
            "affiliate_clicks": int(total_clicks),
            "followers": int(total_followers),
            "last_metrics_at": (
                last_metric_at.isoformat() if last_metric_at else None
            ),
        }

    def _latest_video_metrics(self):
        """Ultimo snapshot de cada (video, plataforma)."""
        db = self.db
        subq = (
            db.query(
                VideoMetric.video_asset_id.label("vid"),
                VideoMetric.platform.label("plat"),
                func.max(VideoMetric.captured_at).label("last_at"),
            )
            .group_by(VideoMetric.video_asset_id, VideoMetric.platform)
            .subquery()
        )
        return (
            db.query(VideoMetric)
            .join(
                subq,
                (VideoMetric.video_asset_id == subq.c.vid)
                & (VideoMetric.platform == subq.c.plat)
                & (VideoMetric.captured_at == subq.c.last_at),
            )
            .all()
        )

    def _latest_platform_stats(self) -> dict:
        """Ultima coleta somada por plataforma (soma das contas)."""
        acc_stats = self._latest_account_stats()
        out: dict = {}
        for key, stat in acc_stats.items():
            platform = key.split(".", 1)[0]
            cur = out.get(platform)
            if cur is None:
                out[platform] = {"followers": 0}
            out[platform]["followers"] += int(stat.followers or 0)
        # Retorna objetos simples com atributo .followers para compat.
        return {
            p: type("S", (), {"followers": v["followers"]})()
            for p, v in out.items()
        }

    def _latest_account_stats(self) -> dict:
        """Ultima coleta de PlatformStat por CONTA (account key)."""
        db = self.db
        out: dict = {}
        for acc in list_publishing_accounts():
            key = acc["key"]
            stat = (
                db.query(PlatformStat)
                .filter(PlatformStat.account == key)
                .order_by(PlatformStat.captured_at.desc())
                .first()
            )
            if stat:
                out[key] = stat
        return out

    def _metric_totals(self) -> dict:
        """Soma do ultimo snapshot de cada (video, plataforma)."""
        totals = {"views": 0, "likes": 0, "comments": 0, "shares": 0, "clicks": 0}
        for r in self._latest_video_metrics():
            totals["views"] += r.views or 0
            totals["likes"] += r.likes or 0
            totals["comments"] += r.comments or 0
            totals["shares"] += r.shares or 0
            totals["clicks"] += r.clicks or 0
        return totals

    def _metric_totals_by_platform(self) -> dict:
        """Soma do ultimo snapshot por plataforma (para bater com o topo)."""
        out: dict = {}
        for r in self._latest_video_metrics():
            d = out.setdefault(
                r.platform,
                {"views": 0, "likes": 0, "comments": 0, "shares": 0},
            )
            d["views"] += r.views or 0
            d["likes"] += r.likes or 0
            d["comments"] += r.comments or 0
            d["shares"] += r.shares or 0
        return out

    def by_platform(self) -> list[dict]:
        db = self.db
        latest_stats = self._latest_platform_stats()
        per_platform = self._metric_totals_by_platform()
        out = []
        for platform in PLATFORMS:
            stat = latest_stats.get(platform)
            metrics = per_platform.get(platform, {})
            published = (
                db.query(func.count(Publication.id))
                .filter(
                    Publication.platform == platform,
                    Publication.status == PublicationStatusEnum.PUBLISHED,
                )
                .scalar()
                or 0
            )
            out.append(
                {
                    "platform": platform,
                    "followers": int(stat.followers) if stat else 0,
                    # Views/curtidas por VIDEO (mesma fonte do topo -> os
                    # totais do topo batem com a soma desta coluna).
                    "total_views": int(metrics.get("views", 0)),
                    "total_likes": int(metrics.get("likes", 0)),
                    "total_comments": int(metrics.get("comments", 0)),
                    "published_videos": int(published),
                }
            )
        return out

    def video_metrics(self, video_asset_id: int) -> dict:
        db = self.db
        rows = (
            db.query(VideoMetric)
            .filter(VideoMetric.video_asset_id == video_asset_id)
            .order_by(VideoMetric.captured_at.desc())
            .all()
        )
        latest_by_platform: dict[str, dict] = {}
        for r in rows:
            if r.platform in latest_by_platform:
                continue
            latest_by_platform[r.platform] = {
                "platform": r.platform,
                "views": int(r.views or 0),
                "likes": int(r.likes or 0),
                "comments": int(r.comments or 0),
                "shares": int(r.shares or 0),
                "clicks": int(r.clicks or 0),
                "captured_at": r.captured_at.isoformat() if r.captured_at else None,
            }
        return {
            "video_asset_id": video_asset_id,
            "platforms": list(latest_by_platform.values()),
        }

    def top_videos(self, limit: int = 5) -> list[dict]:
        """Videos com melhor desempenho (soma do ultimo snapshot por
        plataforma), ordenados por visualizacoes. Inclui os cliques do
        link de afiliado quando houver."""
        db = self.db

        subq = (
            db.query(
                VideoMetric.video_asset_id.label("vid"),
                VideoMetric.platform.label("plat"),
                func.max(VideoMetric.captured_at).label("last_at"),
            )
            .group_by(VideoMetric.video_asset_id, VideoMetric.platform)
            .subquery()
        )
        rows = (
            db.query(VideoMetric)
            .join(
                subq,
                (VideoMetric.video_asset_id == subq.c.vid)
                & (VideoMetric.platform == subq.c.plat)
                & (VideoMetric.captured_at == subq.c.last_at),
            )
            .all()
        )

        agg: dict[int, dict] = {}
        for r in rows:
            item = agg.setdefault(
                r.video_asset_id,
                {"views": 0, "likes": 0, "comments": 0, "shares": 0},
            )
            item["views"] += r.views or 0
            item["likes"] += r.likes or 0
            item["comments"] += r.comments or 0
            item["shares"] += r.shares or 0

        out: list[dict] = []
        for vid, m in agg.items():
            asset = (
                db.query(VideoAsset).filter(VideoAsset.id == vid).first()
            )
            if not asset:
                continue
            clicks = 0
            if asset.short_code:
                link = (
                    db.query(ShortLink)
                    .filter(ShortLink.code == asset.short_code)
                    .first()
                )
                clicks = int(link.clicks) if link else 0
            out.append(
                {
                    "id": asset.id,
                    "title": asset.title,
                    "kind": asset.kind.value
                    if hasattr(asset.kind, "value")
                    else str(asset.kind),
                    "views": m["views"],
                    "likes": m["likes"],
                    "comments": m["comments"],
                    "shares": m["shares"],
                    "clicks": clicks,
                }
            )

        out.sort(key=lambda x: x["views"], reverse=True)
        return out[:limit]

    def platform_videos(self, platform: str) -> dict:
        """Todos os videos PUBLICADOS numa plataforma, com o ultimo
        snapshot de metricas de cada um. Ordenado por visualizacoes
        (do maior para o menor)."""
        db = self.db
        platform = (platform or "").lower()

        # Ultimo snapshot de cada video NESTA plataforma.
        subq = (
            db.query(
                VideoMetric.video_asset_id.label("vid"),
                func.max(VideoMetric.captured_at).label("last_at"),
            )
            .filter(VideoMetric.platform == platform)
            .group_by(VideoMetric.video_asset_id)
            .subquery()
        )
        latest = (
            db.query(VideoMetric)
            .join(
                subq,
                (VideoMetric.video_asset_id == subq.c.vid)
                & (VideoMetric.captured_at == subq.c.last_at),
            )
            .filter(VideoMetric.platform == platform)
            .all()
        )
        metrics_by_video = {m.video_asset_id: m for m in latest}

        pubs = (
            db.query(Publication)
            .filter(
                Publication.platform == platform,
                Publication.status == PublicationStatusEnum.PUBLISHED,
            )
            .all()
        )

        videos: list[dict] = []
        for pub in pubs:
            asset = (
                db.query(VideoAsset)
                .filter(VideoAsset.id == pub.video_asset_id)
                .first()
            )
            if not asset:
                continue
            m = metrics_by_video.get(pub.video_asset_id)
            clicks = 0
            if asset.short_code:
                link = (
                    db.query(ShortLink)
                    .filter(ShortLink.code == asset.short_code)
                    .first()
                )
                clicks = int(link.clicks) if link else 0
            videos.append(
                {
                    "id": asset.id,
                    "title": asset.title or f"Video {asset.id}",
                    "language": asset.language,
                    "country_code": asset.country_code,
                    "thumbnail_path": asset.thumbnail_path,
                    "external_url": pub.external_url,
                    "published_at": (
                        pub.published_at.isoformat()
                        if pub.published_at
                        else (
                            asset.published_at.isoformat()
                            if asset.published_at
                            else None
                        )
                    ),
                    "views": int(m.views or 0) if m else 0,
                    "likes": int(m.likes or 0) if m else 0,
                    "comments": int(m.comments or 0) if m else 0,
                    "shares": int(m.shares or 0) if m else 0,
                    "clicks": clicks,
                }
            )

        videos.sort(key=lambda x: x["views"], reverse=True)

        stat = self._latest_platform_stats().get(platform)
        return {
            "platform": platform,
            "followers": int(stat.followers) if stat else 0,
            "published_videos": len(videos),
            "videos": videos,
        }

    # ----------------------------------------------------------------
    # POR CONTA (todas as contas de todas as plataformas)
    # ----------------------------------------------------------------

    def _asset_map(self) -> dict:
        return {a.id: a for a in self.db.query(VideoAsset).all()}

    @staticmethod
    def _kind(asset) -> str:
        return asset.kind.value if hasattr(asset.kind, "value") else str(asset.kind)

    def _metrics_by_account(self) -> dict:
        """Soma do ultimo snapshot de cada video, agrupado por conta."""
        assets = self._asset_map()
        out: dict = {}
        for r in self._latest_video_metrics():
            asset = assets.get(r.video_asset_id)
            if not asset:
                continue
            acc = account_for_video(
                r.platform, self._kind(asset), asset.country_code, asset.language
            )
            d = out.setdefault(
                acc["key"], {"views": 0, "likes": 0, "comments": 0, "shares": 0}
            )
            d["views"] += r.views or 0
            d["likes"] += r.likes or 0
            d["comments"] += r.comments or 0
            d["shares"] += r.shares or 0
        return out

    def _published_count_by_account(self) -> dict:
        db = self.db
        assets = self._asset_map()
        out: dict = {}
        pubs = (
            db.query(Publication)
            .filter(Publication.status == PublicationStatusEnum.PUBLISHED)
            .all()
        )
        for pub in pubs:
            asset = assets.get(pub.video_asset_id)
            if not asset:
                continue
            acc = account_for_video(
                pub.platform, self._kind(asset), asset.country_code, asset.language
            )
            out[acc["key"]] = out.get(acc["key"], 0) + 1
        return out

    def by_account(self) -> list[dict]:
        """Uma linha por conta configurada (YouTube BR/US, Instagram e
        Facebook Afiliados/Trends BR/US, TikTok BR/US), com seguidores da
        ultima coleta e as metricas dos videos publicados naquela conta."""
        accounts = list_publishing_accounts()
        acc_stats = self._latest_account_stats()
        per_account = self._metrics_by_account()
        pub_counts = self._published_count_by_account()

        # Inclui contas "orfas": possuem videos publicados ou metricas mas o
        # canal dedicado ainda nao foi configurado no .env (ex.: afiliados do
        # YouTube, que hoje sobem no canal de trends). Sem isso, esses videos
        # e suas visualizacoes sumiriam do Analytics por conta.
        known_keys = {a["key"] for a in accounts}
        extra_keys = (set(pub_counts) | set(per_account)) - known_keys
        for key in sorted(extra_keys):
            parts = key.split(".")
            platform = parts[0] if parts else key
            role = parts[1] if len(parts) > 1 and parts[1] != "all" else None
            market = parts[2] if len(parts) > 2 else ""
            accounts.append(
                {
                    "key": key,
                    "platform": platform,
                    "role": role,
                    "market": market,
                    "label": _account_label(platform, role, market),
                    "external_id": "",
                    "connected": False,
                }
            )

        out = []
        for acc in accounts:
            key = acc["key"]
            stat = acc_stats.get(key)
            m = per_account.get(key, {})
            out.append(
                {
                    "key": key,
                    "platform": acc["platform"],
                    "role": acc["role"],
                    "market": acc["market"],
                    "label": acc["label"],
                    "connected": bool(acc["connected"]),
                    "followers": int(stat.followers) if stat else 0,
                    "total_views": int(m.get("views", 0)),
                    "total_likes": int(m.get("likes", 0)),
                    "total_comments": int(m.get("comments", 0)),
                    "published_videos": int(pub_counts.get(key, 0)),
                }
            )

        # Agrupa as contas por plataforma (YouTube, Instagram, Facebook,
        # TikTok) e, dentro de cada plataforma, mostra primeiro as que tem
        # mais videos publicados. Assim as contas de afiliados do YouTube
        # ficam junto das de trends (e nao perdidas no fim da lista).
        platform_order = {"youtube": 0, "instagram": 1, "facebook": 2, "tiktok": 3}
        out.sort(
            key=lambda a: (
                platform_order.get(a["platform"], 9),
                -a["published_videos"],
                -a["total_views"],
                a["label"],
            )
        )
        return out

    def account_videos(self, key: str) -> dict:
        """Videos publicados numa CONTA especifica, ordenados por views."""
        db = self.db
        accounts = {a["key"]: a for a in list_publishing_accounts()}
        acc = accounts.get(key)
        platform = key.split(".", 1)[0]
        assets = self._asset_map()
        metrics = {
            m.video_asset_id: m
            for m in self._latest_video_metrics()
            if m.platform == platform
        }
        pubs = (
            db.query(Publication)
            .filter(
                Publication.platform == platform,
                Publication.status == PublicationStatusEnum.PUBLISHED,
            )
            .all()
        )
        videos: list[dict] = []
        for pub in pubs:
            asset = assets.get(pub.video_asset_id)
            if not asset:
                continue
            vacc = account_for_video(
                platform, self._kind(asset), asset.country_code, asset.language
            )
            if vacc["key"] != key:
                continue
            m = metrics.get(pub.video_asset_id)
            clicks = 0
            if asset.short_code:
                link = (
                    db.query(ShortLink)
                    .filter(ShortLink.code == asset.short_code)
                    .first()
                )
                clicks = int(link.clicks) if link else 0
            videos.append(
                {
                    "id": asset.id,
                    "title": asset.title or f"Video {asset.id}",
                    "language": asset.language,
                    "country_code": asset.country_code,
                    "thumbnail_path": asset.thumbnail_path,
                    "external_url": pub.external_url,
                    "published_at": (
                        pub.published_at.isoformat()
                        if pub.published_at
                        else (
                            asset.published_at.isoformat()
                            if asset.published_at
                            else None
                        )
                    ),
                    "views": int(m.views or 0) if m else 0,
                    "likes": int(m.likes or 0) if m else 0,
                    "comments": int(m.comments or 0) if m else 0,
                    "shares": int(m.shares or 0) if m else 0,
                    "clicks": clicks,
                }
            )
        videos.sort(key=lambda x: x["views"], reverse=True)
        stat = self._latest_account_stats().get(key)
        return {
            "key": key,
            "label": acc["label"] if acc else key,
            "platform": platform,
            "market": acc["market"] if acc else "",
            "role": acc["role"] if acc else None,
            "connected": bool(acc["connected"]) if acc else False,
            "followers": int(stat.followers) if stat else 0,
            "published_videos": len(videos),
            "videos": videos,
        }
