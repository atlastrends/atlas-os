# -*- coding: utf-8 -*-
"""Investiga (READ-ONLY) os videos em status CREATED ("novos"): quantos sao
afiliado x reel, e se ALGUM ja tem publicacao (ja foi enviado) apesar de constar
como 'novo'. Nao altera nada."""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.models.dashboard import Publication, PublicationStatusEnum, VideoAsset, VideoStatusEnum


def main() -> int:
    db = SessionLocal()
    try:
        created = (
            db.query(VideoAsset)
            .filter(VideoAsset.status == VideoStatusEnum.CREATED)
            .all()
        )
        print(f"Videos em CREATED ('novos'): {len(created)}")
        by_kind = Counter(getattr(a.kind, "value", a.kind) for a in created)
        print("  por tipo:", dict(by_kind))

        com_pub_publicada = 0
        com_pub_qualquer = 0
        sem_pub = 0
        exemplos_ja_enviados = []
        for a in created:
            pubs = (
                db.query(Publication)
                .filter(Publication.video_asset_id == a.id)
                .all()
            )
            if not pubs:
                sem_pub += 1
                continue
            com_pub_qualquer += 1
            publicadas = [p for p in pubs if p.status == PublicationStatusEnum.PUBLISHED]
            if publicadas:
                com_pub_publicada += 1
                if len(exemplos_ja_enviados) < 8:
                    plats = ", ".join(
                        f"{p.platform}={getattr(p.status,'value',p.status)}" for p in pubs
                    )
                    exemplos_ja_enviados.append((a.id, plats))

        print("\n== Esses 'novos' ja foram enviados? ==")
        print(f"  SEM nenhuma publicacao (realmente novos):        {sem_pub}")
        print(f"  COM alguma publicacao (mas nao publicada):       {com_pub_qualquer - com_pub_publicada}")
        print(f"  COM publicacao PUBLICADA (ja enviados de fato):  {com_pub_publicada}")

        if exemplos_ja_enviados:
            print("\n  Exemplos de 'novos' que JA foram publicados:")
            for aid, plats in exemplos_ja_enviados:
                print(f"    #{aid}: {plats}")

        # Datas de criacao (amostra) para entender de quando sao.
        datas = sorted(
            (getattr(a, "created_at", None) for a in created if getattr(a, "created_at", None)),
        )
        if datas:
            print(f"\n  Criados entre: {datas[0]}  ..  {datas[-1]}")
        print(f"  Com published_at preenchido: {sum(1 for a in created if getattr(a,'published_at',None))}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
