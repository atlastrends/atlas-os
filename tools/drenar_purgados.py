# -*- coding: utf-8 -*-
"""DRENA a fila de reenvio: limpa de uma vez os videos cujo arquivo foi PURGADO
(terminal, nunca sobem) e reclassifica erros de conta/permissao. Usa a mesma
logica corrigida do servico (skip_purged_pending + recompute), sem republicar
nada nem regenerar video. Mostra o antes/depois."""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.models.dashboard import Publication, PublicationStatusEnum, VideoAsset, VideoStatusEnum
from app.services.publishing_service import PublishingService, _needs_reconnect

DONE = {PublicationStatusEnum.PUBLISHED, PublicationStatusEnum.SKIPPED}


def _snapshot(db) -> tuple[int, Counter]:
    pend = db.query(Publication).filter(Publication.status.notin_(DONE)).count()
    by_status = Counter(
        s for (s,) in db.query(VideoAsset.status).all()
    )
    return pend, by_status


def main() -> int:
    db = SessionLocal()
    try:
        antes_pend, antes_status = _snapshot(db)
        print(f"ANTES: publicacoes nao concluidas = {antes_pend}")
        print(f"       videos RETRY_PENDING = {antes_status.get(VideoStatusEnum.RETRY_PENDING, 0)}")

        svc = PublishingService(db)

        # 1) Reclassifica publicacoes FAILED antigas cujo erro e de CONTA
        #    (token revogado/expirado, app nao auditado, sem permissao) para
        #    CREDENTIALS_MISSING - saem da fila de reenvio (nao republica nada).
        failed = (
            db.query(Publication)
            .filter(Publication.status == PublicationStatusEnum.FAILED)
            .all()
        )
        reclass = 0
        touched_assets: set[int] = set()
        for p in failed:
            if _needs_reconnect(p.error or ""):
                p.status = PublicationStatusEnum.CREDENTIALS_MISSING
                reclass += 1
                touched_assets.add(p.video_asset_id)
        if reclass:
            db.commit()
        for aid in touched_assets:
            a = db.query(VideoAsset).filter(VideoAsset.id == aid).first()
            if a:
                svc._recompute_asset_status(a)
        print(f"\nReclassificadas (conta/permissao -> credencial pendente): {reclass}")

        # 2) Drena TODOS os purgados (fila inteira, qualquer kind/status).
        res = svc.skip_purged_pending()
        print(
            f"Purgados limpos: publicacoes SKIPPED = {res['publications_skipped']}, "
            f"videos ajustados = {res['assets_cleaned']}"
        )

        depois_pend, depois_status = _snapshot(db)
        print(f"\nDEPOIS: publicacoes nao concluidas = {depois_pend}")
        print(f"        videos RETRY_PENDING = {depois_status.get(VideoStatusEnum.RETRY_PENDING, 0)}")
        print("\n== Distribuicao de status dos videos (depois) ==")
        for st, n in depois_status.most_common():
            nome = getattr(st, "value", st)
            print(f"  [{n:>4}] {nome}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
