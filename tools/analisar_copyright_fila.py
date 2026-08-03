# -*- coding: utf-8 -*-
"""
Analisa (DRY-RUN, sem alterar o banco) todos os videos de TREND (reel) que
estao na fila para publicar e mostra quais seriam RETIDOS por risco de
direitos autorais (b-roll de origem nao licenciada / desconhecida).

Objetivo: "analisar todos os videos de trends antes de enviar".

Uso:
    .venv-dash\\Scripts\\python.exe tools\\analisar_copyright_fila.py

Nao publica nada e nao grava no banco. Apenas relatorio.
Para de fato RETER os videos arriscados, use o botao "Reenviar pendentes"
no dashboard (que chama hold_risky_reels) ou a rotina de publicacao.
"""
from __future__ import annotations

import os
import sys

# Permite rodar a partir da raiz do projeto (onde fica a pasta app/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.dashboard import VideoAsset, VideoKindEnum, VideoStatusEnum
from app.services.publishing_service import PublishingService, _env_bool

# Status que ainda NAO foram publicados (a "fila" antes do envio).
_FILA_STATUSES = [
    VideoStatusEnum.CREATED,
    VideoStatusEnum.APPROVED,
    VideoStatusEnum.RETRY_PENDING,
]


def _asset_source(asset: VideoAsset) -> str:
    payload = asset.payload if isinstance(asset.payload, dict) else {}
    cr = payload.get("copyright") if isinstance(payload.get("copyright"), dict) else {}
    src = cr.get("asset_source") or payload.get("asset_source") or "sem_proveniencia"
    return str(src).strip().lower() or "sem_proveniencia"


def main() -> int:
    ativo = _env_bool("ATLAS_BLOCK_RISKY_REELS", True)
    print("=" * 68)
    print(" ANALISE DE DIREITOS AUTORAIS - FILA DE TRENDS (reel)")
    print("=" * 68)
    print(f" Guard ATLAS_BLOCK_RISKY_REELS: {'LIGADO' if ativo else 'DESLIGADO'}")
    print("-" * 68)

    db = SessionLocal()
    try:
        svc = PublishingService(db)
        assets = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.kind == VideoKindEnum.REEL,
                VideoAsset.status.in_(_FILA_STATUSES),
            )
            .order_by(VideoAsset.id.asc())
            .all()
        )

        total = len(assets)
        retidos = []
        liberados = []
        por_fonte: dict[str, int] = {}

        for asset in assets:
            fonte = _asset_source(asset)
            por_fonte[fonte] = por_fonte.get(fonte, 0) + 1
            # DRY-RUN: apenas avalia, NAO altera status nem faz commit.
            reason = svc._copyright_hold_reason(asset)
            if reason:
                retidos.append((asset, fonte, reason))
            else:
                liberados.append((asset, fonte))

        print(f" Reels na fila (nao publicados): {total}")
        print(f"   - LIBERADOS (midia segura):   {len(liberados)}")
        print(f"   - RETIDOS  (risco de claim):  {len(retidos)}")
        print("-" * 68)
        print(" Por fonte de midia de fundo:")
        for fonte, qtd in sorted(por_fonte.items(), key=lambda kv: -kv[1]):
            print(f"   {qtd:>4}  {fonte}")
        print("-" * 68)

        if retidos:
            print(" Exemplos de reels que seriam RETIDOS antes do envio:")
            for asset, fonte, reason in retidos[:15]:
                titulo = (asset.external_key or "")[:48]
                print(f"   #{asset.id} [{fonte}] {titulo}")
                print(f"        -> {reason}")
            if len(retidos) > 15:
                print(f"   ... e mais {len(retidos) - 15} reel(s).")
        else:
            print(" Nenhum reel da fila seria retido. Tudo com midia segura.")

        print("=" * 68)
        print(" DRY-RUN concluido: nenhuma alteracao foi feita no banco.")
        print("=" * 68)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
