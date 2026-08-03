# -*- coding: utf-8 -*-
"""Diagnostico (READ-ONLY) dos videos presos em PUBLISHING.
Mostra cada asset em PUBLISHING, ha quanto tempo, e o status/erro de cada
publicacao (por plataforma). Nao altera nada."""
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
)


def _age(dt) -> str:
    if not dt:
        return "?"
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
        return f"{int(secs//60)}min {int(secs%60)}s atras"
    except Exception:  # noqa: BLE001
        return str(dt)


def main() -> int:
    db = SessionLocal()
    try:
        assets = (
            db.query(VideoAsset)
            .filter(VideoAsset.status == VideoStatusEnum.PUBLISHING)
            .all()
        )
        print(f"== ASSETS em PUBLISHING: {len(assets)} ==")

        if not assets:
            print("\n== 6 ASSETS MAIS RECENTES (por updated_at) ==")
            assets = (
                db.query(VideoAsset)
                .order_by(VideoAsset.updated_at.desc())
                .limit(6)
                .all()
            )
            for a in assets:
                st = getattr(a.status, "value", a.status)
                print(f"   #{a.id} status={st:14} upd={a.updated_at} ({_age(a.updated_at)}) title={(a.title or '')[:45]!r}")
            print()

        for a in assets:
            print(
                f"\n#{a.id} kind={getattr(a.kind,'value',a.kind)} "
                f"title={ (a.title or '')[:60]!r}"
            )
            print(f"   updated_at={a.updated_at}  ({_age(a.updated_at)})")
            print(f"   reviewed_at={getattr(a,'reviewed_at',None)}")
            print(f"   video_path={a.video_path}")
            pubs = (
                db.query(Publication)
                .filter(Publication.video_asset_id == a.id)
                .all()
            )
            if not pubs:
                print("   (sem registros de publicacao)")
            for p in pubs:
                st = getattr(p.status, "value", p.status)
                print(
                    f"   - {str(p.platform):10} {str(st):20} "
                    f"upd={p.updated_at} ({_age(p.updated_at)})"
                )
                if p.error:
                    print(f"        erro: {str(p.error)[:200]}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
