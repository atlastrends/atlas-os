# -*- coding: utf-8 -*-
"""Estado ATUAL (READ-ONLY): quantos 'novos' (CREATED), quantos aguardando
reenvio, e as publicacoes nao concluidas agrupadas por (plataforma, status)
para responder QUAL plataforma esta bloqueando agora."""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.models.dashboard import Publication, PublicationStatusEnum, VideoAsset, VideoStatusEnum

DONE = {PublicationStatusEnum.PUBLISHED, PublicationStatusEnum.SKIPPED}


def main() -> int:
    db = SessionLocal()
    try:
        novos = db.query(VideoAsset).filter(VideoAsset.status == VideoStatusEnum.CREATED).count()
        retry = db.query(VideoAsset).filter(VideoAsset.status == VideoStatusEnum.RETRY_PENDING).count()
        print(f"Videos 'novos' (CREATED):        {novos}")
        print(f"Videos aguardando reenvio:       {retry}")

        pubs = db.query(Publication).filter(Publication.status.notin_(DONE)).all()
        by = Counter((p.platform, getattr(p.status, "value", p.status)) for p in pubs)
        print(f"\nPublicacoes nao concluidas: {len(pubs)}")
        print("== por (plataforma, status) ==")
        for (plat, st), n in by.most_common():
            print(f"  {plat:10s} {st:20s} {n}")

        # Uma amostra de erro por plataforma (o mais recente que houver).
        print("\n== motivo atual por plataforma (amostra) ==")
        seen = set()
        for p in sorted(pubs, key=lambda x: x.id, reverse=True):
            if p.platform in seen or not p.error:
                continue
            seen.add(p.platform)
            print(f"  {p.platform:10s}: {(p.error or '')[:110]}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
