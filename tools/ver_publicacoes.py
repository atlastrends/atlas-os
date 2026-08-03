# -*- coding: utf-8 -*-
"""Mostra (READ-ONLY) o status de cada publicacao de assets especificos."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.models.dashboard import Publication, VideoAsset


def main() -> int:
    ids = [int(x) for x in sys.argv[1:]] or [371, 372, 143]
    db = SessionLocal()
    try:
        for aid in ids:
            a = db.query(VideoAsset).filter(VideoAsset.id == aid).first()
            if not a:
                print(f"#{aid}: (nao encontrado)")
                continue
            print(f"#{aid} status={getattr(a.status,'value',a.status)} kind={getattr(a.kind,'value',a.kind)}")
            pubs = db.query(Publication).filter(Publication.video_asset_id == aid).all()
            for p in pubs:
                err = (p.error or "")[:90]
                print(f"    {p.platform:10s} {getattr(p.status,'value',p.status):20s} {err}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
