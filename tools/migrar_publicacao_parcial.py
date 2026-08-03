# -*- coding: utf-8 -*-
"""Migracao pontual: aplica a NOVA regra de publicacao parcial aos videos ja
existentes. Um video que esta como PUBLISHED mas ainda tem plataforma
BLOQUEADA (rate_limited) passa para RETRY_PENDING (aguardando reenvio).

NAO republica nada: apenas recalcula o status a partir das publicacoes que ja
existem no banco (reaproveita PublishingService._recompute_asset_status).
Read/adjust-only sobre o status do asset."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.models.dashboard import (
    Publication,
    PublicationStatusEnum,
    VideoAsset,
    VideoStatusEnum,
)
from app.services.publishing_service import PublishingService


def main() -> int:
    db = SessionLocal()
    try:
        svc = PublishingService(db)

        # Assets PUBLISHED que tem ao menos UMA publicacao bloqueada (temporaria).
        rate_limited_ids = {
            row[0]
            for row in db.query(Publication.video_asset_id)
            .filter(Publication.status == PublicationStatusEnum.RATE_LIMITED)
            .distinct()
            .all()
        }
        alvos = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.status == VideoStatusEnum.PUBLISHED,
                VideoAsset.id.in_(rate_limited_ids),
            )
            .all()
            if rate_limited_ids
            else []
        )

        print(f"Assets PUBLISHED com plataforma bloqueada: {len(alvos)}")
        movidos = 0
        for a in alvos:
            antes = getattr(a.status, "value", a.status)
            svc._recompute_asset_status(a)
            depois = getattr(a.status, "value", a.status)
            if antes != depois:
                movidos += 1
                print(f"  #{a.id} {antes} -> {depois}  {(a.title or '')[:50]!r}")
            else:
                print(f"  #{a.id} mantido em {depois}  {(a.title or '')[:50]!r}")

        print(f"\nTotal movidos para aguardando reenvio: {movidos}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
