# -*- coding: utf-8 -*-
"""Diagnostico (READ-ONLY) das FALHAS de reenvio.
Agrupa as publicacoes NAO concluidas (failed / rate_limited / credentials_missing)
por (plataforma, status) e mostra a mensagem de erro mais comum de cada grupo,
para sabermos EXATAMENTE por que o reenvio nao completa."""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.models.dashboard import Publication, PublicationStatusEnum


PENDING = {
    PublicationStatusEnum.FAILED,
    PublicationStatusEnum.RATE_LIMITED,
    PublicationStatusEnum.CREDENTIALS_MISSING,
    PublicationStatusEnum.UPLOADING,
}


def _norm(err: str | None) -> str:
    if not err:
        return "(sem mensagem)"
    e = str(err)
    # normaliza tirando ids variaveis para agrupar
    for cut in ("fbtrace_id", "creation_id", "container", "{'id'"):
        idx = e.find(cut)
        if idx > 0:
            e = e[:idx]
    return e.strip()[:180]


def main() -> int:
    db = SessionLocal()
    try:
        pubs = db.query(Publication).all()
        pend = [p for p in pubs if p.status in PENDING]
        print(f"Publicacoes NAO concluidas: {len(pend)} de {len(pubs)} totais\n")

        by_ps = Counter(
            (str(p.platform), getattr(p.status, "value", p.status)) for p in pend
        )
        print("== POR (plataforma, status) ==")
        for (plat, st), n in sorted(by_ps.items(), key=lambda x: -x[1]):
            print(f"  {plat:10} {st:20} {n}")

        print("\n== MENSAGENS DE ERRO MAIS COMUNS (por plataforma) ==")
        by_plat_err = defaultdict(Counter)
        for p in pend:
            by_plat_err[str(p.platform)][_norm(p.error)] += 1
        for plat in sorted(by_plat_err):
            print(f"\n-- {plat} --")
            for msg, n in by_plat_err[plat].most_common(4):
                print(f"  [{n}x] {msg}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
