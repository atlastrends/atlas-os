# -*- coding: utf-8 -*-
"""Diagnostico (READ-ONLY) da URL publica e dos arquivos locais.
Responde: Supabase esta ligado? Qual ATLAS_PUBLIC_BASE_URL? cloudflared existe?
Dos videos que falharam por "URL PUBLICA", quantos ainda tem o arquivo local
(da para reenviar) e quantos foram purgados (terminais, nunca vao subir)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.models.dashboard import Publication, PublicationStatusEnum, VideoAsset
from app.publishing.base import resolve_video_path
from app.services import media_storage


def main() -> int:
    print("== URL PUBLICA / ARMAZENAMENTO ==")
    print("  Supabase is_enabled():", media_storage.is_enabled())
    print("  ATLAS_PUBLIC_BASE_URL:", os.getenv("ATLAS_PUBLIC_BASE_URL") or "(nao definido -> localhost)")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cf = Path(root) / "bin" / "cloudflared.exe"
    print("  cloudflared.exe existe:", cf.is_file(), f"({cf})")
    print("  ATLAS_USE_TUNNEL:", os.getenv("ATLAS_USE_TUNNEL") or "(nao definido)")

    db = SessionLocal()
    try:
        # Publicacoes que falharam por falta de URL publica.
        pubs = (
            db.query(Publication)
            .filter(Publication.status == PublicationStatusEnum.FAILED)
            .all()
        )
        url_fail = [p for p in pubs if p.error and "URL PUBLICA" in str(p.error)]
        print(f"\n== FALHAS por 'URL PUBLICA': {len(url_fail)} ==")

        com_arquivo = 0
        sem_arquivo = 0
        asset_cache: dict[int, VideoAsset] = {}
        for p in url_fail:
            a = asset_cache.get(p.video_asset_id)
            if a is None:
                a = db.query(VideoAsset).filter(VideoAsset.id == p.video_asset_id).first()
                asset_cache[p.video_asset_id] = a
            path = resolve_video_path(a.video_path or "") if a else ""
            if path and os.path.isfile(path):
                com_arquivo += 1
            else:
                sem_arquivo += 1
        print(f"  COM arquivo local (da para reenviar): {com_arquivo}")
        print(f"  SEM arquivo (purgado -> terminal):    {sem_arquivo}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
