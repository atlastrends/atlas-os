# -*- coding: utf-8 -*-
"""Descobre por que os NOVOS (CREATED) - inclusive afiliados - nao sobem no
reenvio automatico. Hipotese: o lote (limite 4) enche primeiro com a fila de
REENVIO (bloqueada por TikTok/Meta) e nunca sobra espaco para os novos.

READ-ONLY: nao publica nada, so simula a montagem do proximo lote.
"""
from __future__ import annotations

import os
import sys
from collections import Counter

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


def _int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def main() -> int:
    db = SessionLocal()
    try:
        svc = PublishingService(db)
        limit = _int("ATLAS_AUTO_RETRY_BATCH", 4)

        # 1) Novos por tipo
        created = (
            db.query(VideoAsset)
            .filter(VideoAsset.status == VideoStatusEnum.CREATED)
            .order_by(VideoAsset.id.asc())
            .all()
        )
        by_kind = Counter(getattr(a.kind, "value", a.kind) for a in created)
        print(f"NOVOS (CREATED): {len(created)}  ->  por tipo: {dict(by_kind)}")

        # 2) Fila de reenvio (o que compete pelas vagas do lote)
        retry_assets = svc._awaiting_retry_query().all()
        print(f"FILA DE REENVIO (_awaiting_retry_query): {len(retry_assets)} assets")
        rk = Counter(getattr(a.kind, "value", a.kind) for a in retry_assets)
        rs = Counter(getattr(a.status, "value", a.status) for a in retry_assets)
        print(f"  por tipo: {dict(rk)}  |  por status: {dict(rs)}")

        # 3) SIMULA a montagem do proximo lote (NOVA logica: reserva vagas p/ novos)
        limit_ = max(1, limit)
        new_waiting = len(created)
        reserved_new = 0
        if new_waiting > 0:
            default_reserved = max(1, limit_ // 2)
            reserved_new = _int("ATLAS_AUTO_RETRY_MIN_NEW", default_reserved)
            reserved_new = max(1, min(reserved_new, limit_))
        retry_slots = max(0, limit_ - reserved_new)

        seen: set[int] = set()
        batch_retry: list[int] = []
        for a in retry_assets:
            if len(batch_retry) >= retry_slots:
                break
            if a.id not in seen:
                seen.add(a.id)
                batch_retry.append(a.id)
        batch_novos: list[int] = []
        for a in created:
            if len(batch_retry) + len(batch_novos) >= limit_:
                break
            if a.id not in seen:
                seen.add(a.id)
                batch_novos.append(a.id)
        # completa com mais reenvios se sobrou espaco
        for a in retry_assets:
            if len(batch_retry) + len(batch_novos) >= limit_:
                break
            if a.id not in seen:
                seen.add(a.id)
                batch_retry.append(a.id)

        print("\n== PROXIMO LOTE (limite {}, reserva p/ novos={}） ==".format(limit_, reserved_new))
        print(f"  reenvios no lote: {len(batch_retry)} -> {batch_retry}")
        print(f"  NOVOS no lote:    {len(batch_novos)} -> {batch_novos}")
        if batch_novos:
            print("\n  >>> OK: os NOVOS agora entram no lote (reserva garante vaga).")
        else:
            print("\n  >>> Nenhum novo entrou (verifique se ha novos esperando).")

        # 4) Por que cada reenvio esta preso (plataformas nao concluidas)
        print("\n== Por que a fila de reenvio nao esvazia (amostra) ==")
        for a in retry_assets[:10]:
            pubs = (
                db.query(Publication)
                .filter(Publication.video_asset_id == a.id)
                .all()
            )
            pend = [
                f"{p.platform}={getattr(p.status,'value',p.status)}"
                for p in pubs
                if p.status
                not in (PublicationStatusEnum.PUBLISHED, PublicationStatusEnum.SKIPPED)
            ]
            print(f"  #{a.id} ({getattr(a.kind,'value',a.kind)}): {', '.join(pend) or '(sem pendencia?)'}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
