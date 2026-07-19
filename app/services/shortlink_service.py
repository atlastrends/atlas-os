# ============================================================
# ATLAS OS - shortlink_service.py
# Cria e resolve links curtos clicaveis para produtos de afiliado.
# Ex.: https://SEU_DOMINIO/go/aB3xY9  ->  https://amazon.com/dp/XXXX?tag=...
# ============================================================

from __future__ import annotations

import hashlib
import os
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from app.models.dashboard import LinkClick, ShortLink

_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


def _public_base_url() -> str:
    return (
        os.getenv("ATLAS_PUBLIC_BASE_URL", "http://localhost:8000")
        .rstrip("/")
    )


def _generate_code(length: int = 6) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


class ShortLinkService:
    def __init__(self, db: Session):
        self.db = db

    def build_public_url(self, code: str) -> str:
        return f"{_public_base_url()}/go/{code}"

    def get_or_create(
        self,
        target_url: str,
        *,
        asin: Optional[str] = None,
        marketplace: Optional[str] = None,
        title: Optional[str] = None,
        video_asset_id: Optional[int] = None,
    ) -> ShortLink:
        target_url = (target_url or "").strip()

        existing = (
            self.db.query(ShortLink)
            .filter(ShortLink.target_url == target_url)
            .first()
        )
        if existing:
            return existing

        # Gera um code unico.
        code = _generate_code()
        while (
            self.db.query(ShortLink)
            .filter(ShortLink.code == code)
            .first()
            is not None
        ):
            code = _generate_code()

        link = ShortLink(
            code=code,
            target_url=target_url,
            asin=asin,
            marketplace=marketplace,
            title=title,
            video_asset_id=video_asset_id,
            clicks=0,
        )
        self.db.add(link)
        self.db.commit()
        self.db.refresh(link)
        return link

    def resolve_and_track(
        self,
        code: str,
        *,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        referer: Optional[str] = None,
    ) -> Optional[ShortLink]:
        link = (
            self.db.query(ShortLink)
            .filter(ShortLink.code == code)
            .first()
        )
        if not link:
            return None

        link.clicks = (link.clicks or 0) + 1

        ip_hash = None
        if ip:
            ip_hash = hashlib.sha256(ip.encode("utf-8")).hexdigest()

        self.db.add(
            LinkClick(
                short_link_id=link.id,
                ip_hash=ip_hash,
                user_agent=(user_agent or "")[:400] or None,
                referer=(referer or "")[:400] or None,
            )
        )
        self.db.commit()
        self.db.refresh(link)
        return link
