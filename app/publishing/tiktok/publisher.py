# ATLAS OS - Conector TikTok (Content Posting API)
from __future__ import annotations

import os

import requests

from app.publishing.base import (
    BasePublisher,
    PublishRequest,
    PublishResult,
    public_media_url,
)

API_BASE = "https://open.tiktokapis.com/v2"

# Nivel de privacidade do post. Enquanto o app estiver em modo sandbox/auditoria,
# use SELF_ONLY (privado). Depois de aprovado, PUBLIC_TO_EVERYONE.
DEFAULT_PRIVACY = os.getenv("TIKTOK_PRIVACY_LEVEL", "SELF_ONLY")


class TikTokPublisher(BasePublisher):
    platform = "tiktok"
    required_env = (
        "TIKTOK_CLIENT_KEY",
        "TIKTOK_CLIENT_SECRET",
        "TIKTOK_ACCESS_TOKEN",
    )

    def _do_publish(self, request: PublishRequest) -> PublishResult:
        token = os.getenv("TIKTOK_ACCESS_TOKEN")

        video_url = public_media_url(request.video_path)
        if not video_url or video_url.startswith("http://localhost"):
            return PublishResult(
                status="failed",
                error=(
                    "O TikTok (PULL_FROM_URL) precisa de uma URL PUBLICA e de um "
                    "dominio verificado no TikTok. Defina ATLAS_PUBLIC_BASE_URL."
                ),
                detail={"platform": self.platform, "video_url": video_url},
            )

        title = (request.caption or request.title or "").strip()[:2200]

        try:
            resp = requests.post(
                f"{API_BASE}/post/publish/video/init/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={
                    "post_info": {
                        "title": title,
                        "privacy_level": DEFAULT_PRIVACY,
                        "disable_comment": False,
                        "disable_duet": False,
                        "disable_stitch": False,
                    },
                    "source_info": {
                        "source": "PULL_FROM_URL",
                        "video_url": video_url,
                    },
                },
                timeout=60,
            )
            data = resp.json()
            err = (data.get("error") or {})
            if resp.status_code >= 400 or (err.get("code") and err.get("code") != "ok"):
                return PublishResult(
                    status="failed",
                    error=f"Falha ao iniciar publicacao no TikTok: {data}",
                    detail={"platform": self.platform},
                )

            publish_id = (data.get("data") or {}).get("publish_id")
            if not publish_id:
                return PublishResult(
                    status="failed",
                    error=f"TikTok nao retornou publish_id: {data}",
                    detail={"platform": self.platform},
                )

            # O upload/processamento e assincrono no TikTok. O status pode ser
            # consultado depois em /post/publish/status/fetch/ com o publish_id.
            return PublishResult(
                status="published",
                external_id=publish_id,
                external_url=None,
                detail={"platform": self.platform, "publish_id": publish_id, "async": True},
            )

        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=f"Erro na publicacao do TikTok: {exc}",
                detail={"platform": self.platform},
            )
