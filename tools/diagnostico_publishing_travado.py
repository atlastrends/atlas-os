# -*- coding: utf-8 -*-
"""Diagnostico (READ-ONLY) dos videos presos em PUBLISHING/UPLOADING.
Mostra ha quanto tempo estao presos e o status de CADA publicacao/plataforma,
com o erro. Nao altera nada."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.models.dashboard import (
    VideoAsset,
    VideoStatusEnum,
    Publication,
    PublicationStatusEnum,
)


def _age(dt) -> str:
    if dt is None:
        return "?"
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:  # noqa: BLE001
        return "?"
    if secs < 90:
        return f"{int(secs)}s atras"
    if secs < 5400:
        return f"{int(secs / 60)}min atras"
    return f"{secs / 3600:.1f}h atras"


def main() -> int:
    db = SessionLocal()
    try:
        assets = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.status.in_(
                    [VideoStatusEnum.PUBLISHING, VideoStatusEnum.APPROVED]
                )
            )
            .order_by(VideoAsset.updated_at.desc())
            .limit(10)
            .all()
        )
        print(f"== VIDEOS em PUBLISHING/APPROVED: {len(assets)} ==")
        for a in assets:
            st = str(getattr(a.status, "value", a.status))
            print(
                f"\n#{a.id} status={st} kind={getattr(a.kind,'value',a.kind)} "
                f"reviewed={_age(a.reviewed_at)} updated={_age(a.updated_at)}"
            )
            print(f"    titulo: {(a.title or '')[:70]!r}")
            pubs = (
                db.query(Publication)
                .filter(Publication.video_asset_id == a.id)
                .all()
            )
            if not pubs:
                print("    (sem registros de publicacao)")
            for p in pubs:
                pst = str(getattr(p.status, "value", p.status))
                err = (p.error or "")[:110]
                print(
                    f"    - {str(p.platform):10} {pst:20} updated={_age(p.updated_at)}"
                    + (f"  ERRO: {err}" if err else "")
                )

        # Tambem conta publicacoes UPLOADING presas em geral.
        up = (
            db.query(Publication)
            .filter(Publication.status == PublicationStatusEnum.UPLOADING)
            .all()
        )
        print(f"\n== PUBLICATIONS presas em UPLOADING (global): {len(up)} ==")
        for p in up[:20]:
            print(
                f"    pub#{p.id} asset#{p.video_asset_id} {str(p.platform):10} "
                f"updated={_age(p.updated_at)}"
            )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
