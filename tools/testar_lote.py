# -*- coding: utf-8 -*-
"""Testa o reenvio em LOTE espacado (run_scheduled_batch) publicando um lote
pequeno de verdade. Use: python tools/testar_lote.py [limite]  (padrao 1).
Mostra o resumo (quantos publicados, quantos ainda aguardando, quanto sobrou)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.services.publishing_service import PublishingService


def main() -> int:
    try:
        limite = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    except (TypeError, ValueError):
        limite = 1

    db = SessionLocal()
    try:
        svc = PublishingService(db)
        print(f"Publicando lote de teste (limite={limite}, espacamento=0s)...")
        summary = svc.run_scheduled_batch(limit=limite, spacing_seconds=0)
        print("\n== RESUMO ==")
        for k in ("batch", "published", "still_pending", "remaining_retry", "remaining_created"):
            print(f"  {k}: {summary.get(k)}")
        print("\n  detalhe:")
        for r in summary.get("results", []):
            print(f"    #{r['asset_id']}: {r['status']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
