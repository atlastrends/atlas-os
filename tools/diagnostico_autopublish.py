# -*- coding: utf-8 -*-
"""Diagnostico (READ-ONLY) de por que os reels de trend nao sobem sozinhos.
Replica a visao do servidor (chama load_env) e mostra flags efetivas,
plataformas com credenciais e o estado real de reels/publicacoes.
Nao altera nada no banco."""
from __future__ import annotations

import os
import sys
from collections import Counter

# Permite rodar a partir da raiz do projeto (onde fica a pasta app/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env, active_env_path, shared_env_path

load_env()

from app.core.database import SessionLocal
from app.models.dashboard import VideoAsset, Publication


def g(name: str) -> str:
    v = os.getenv(name)
    return v if v is not None else "(nao definido -> usa DEFAULT do codigo)"


def main() -> int:
    print("ENV ATIVO:", active_env_path())
    print("ENV COMPARTILHADO:", shared_env_path())
    print()

    print("== FLAGS EFETIVAS (o que o servidor le) ==")
    for n in [
        "ATLAS_ENGINE_ENABLED",
        "ATLAS_AUTO_APPROVE_ENABLED",
        "ATLAS_AUTO_APPROVE_MIN_SCORE",
        "ATLAS_AUTO_APPROVE_KINDS",
        "ATLAS_AUTO_APPROVE_INTERVAL_HOURS",
        "ATLAS_SCHEDULER_ENABLED",
        "ATLAS_BLOCK_RISKY_REELS",
    ]:
        print(f"  {n} = {g(n)}")

    print()
    print("== PLATAFORMAS CONFIGURADAS (tem credencial?) ==")
    try:
        from app.publishing.registry import platform_status

        for p in platform_status():
            print(f"  {str(p.get('platform')):12} configured={p.get('configured')}")
    except Exception as e:  # noqa: BLE001
        print("  erro platform_status:", e)

    print()
    db = SessionLocal()
    try:
        reels = [
            r
            for r in db.query(VideoAsset).all()
            if str(getattr(r.kind, "value", r.kind)) == "reel"
        ]
        print(
            "== REELS por status ==",
            dict(Counter(str(getattr(r.status, "value", r.status)) for r in reels)),
        )

        pubs = db.query(Publication).all()
        print("== PUBLICATIONS total ==", len(pubs))
        print(
            "== PUBLICATIONS por status ==",
            dict(Counter(str(getattr(p.status, "value", p.status)) for p in pubs)),
        )

        byplat = Counter(
            (str(p.platform), str(getattr(p.status, "value", p.status))) for p in pubs
        )
        print("== PUBLICATIONS por (plataforma, status) ==")
        for (plat, st), n in sorted(byplat.items()):
            print(f"   {plat:12} {st:22} {n}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
