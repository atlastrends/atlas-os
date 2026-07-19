# ATLAS OS - Registro central de conectores de publicacao
from __future__ import annotations

from app.publishing.base import BasePublisher
from app.publishing.facebook.publisher import FacebookPublisher
from app.publishing.instagram.publisher import InstagramPublisher
from app.publishing.tiktok.publisher import TikTokPublisher
from app.publishing.youtube.publisher import YouTubePublisher

# Ordem/plataformas suportadas pela fabrica.
PLATFORMS: tuple[str, ...] = (
    "youtube",
    "tiktok",
    "instagram",
    "facebook",
)

_PUBLISHERS: dict[str, BasePublisher] = {
    "youtube": YouTubePublisher(),
    "tiktok": TikTokPublisher(),
    "instagram": InstagramPublisher(),
    "facebook": FacebookPublisher(),
}


def get_publisher(platform: str) -> BasePublisher | None:
    return _PUBLISHERS.get((platform or "").lower().strip())


def platform_status() -> list[dict]:
    """Estado de configuracao de cada plataforma (para o painel)."""
    result = []
    for name in PLATFORMS:
        pub = _PUBLISHERS[name]
        result.append(
            {
                "platform": name,
                "configured": pub.is_configured(),
                "missing_env": pub.missing_credentials(),
            }
        )
    return result
