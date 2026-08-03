# -*- coding: utf-8 -*-
"""Publica AGORA um lote espacado dos videos (aguardando reenvio + novos).

Uso:
    python tools/publicar_agora.py [LIMITE] [ESPACAMENTO_SEG]

Padrao: LIMITE=12, ESPACAMENTO=20s. Publica de verdade nas plataformas.
YouTube costuma aceitar na hora; Instagram/Facebook podem recusar enquanto
o limite (#4) da Meta esfria; TikTok recusa enquanto houver rascunhos demais.
Os que recusarem ficam como 'aguardando reenvio' e o robo horario completa depois.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.services.publishing_service import PublishingService


def main() -> int:
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    espac = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    print(f"Publicando agora: limite={limite}, espacamento={espac}s")
    db = SessionLocal()
    try:
        res = PublishingService(db).run_scheduled_batch(
            limit=limite, spacing_seconds=espac, include_new=True
        )
        print("\n== RESULTADO ==")
        print(f"  no lote:            {res.get('batch')}")
        print(f"  publicados (video): {res.get('published')}")
        print(f"  ainda pendentes:    {res.get('still_pending')}")
        print(f"  resta reenvio:      {res.get('remaining_retry')}")
        print(f"  resta novos:        {res.get('remaining_created')}")
        for r in res.get("results", []):
            print(f"  video {r.get('asset_id')}: {r.get('status')}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
