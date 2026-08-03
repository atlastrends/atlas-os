# -*- coding: utf-8 -*-
"""Classifica (READ-ONLY) TODAS as publicacoes nao concluidas em baldes
acionaveis, dizendo o que e terminal (nunca sobe), o que e transitorio
(reenviar depois resolve) e o que precisa de acao do usuario (reconectar
conta / ajuste na plataforma). Tambem separa por arquivo local presente x
purgado, porque arquivo purgado nunca sobe em nenhuma rede."""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

from app.core.database import SessionLocal
from app.models.dashboard import Publication, PublicationStatusEnum, VideoAsset
from app.publishing.base import resolve_video_path

DONE = {PublicationStatusEnum.PUBLISHED, PublicationStatusEnum.SKIPPED}


def _purged(asset: VideoAsset) -> bool:
    payload = asset.payload if isinstance(asset.payload, dict) else {}
    if payload.get("file_purged"):
        return True
    path = resolve_video_path(asset.video_path or "")
    return not (path and os.path.isfile(path))


def _bucket(err: str) -> str:
    e = (err or "").lower()
    # Reconectar conta (token revogado/expirado ou credencial ausente)
    if "invalid_grant" in e or "expired or revoked" in e or "token has been" in e:
        return "RECONECTAR (token expirou/revogado)"
    if "credenciais ausentes" in e or "credentials" in e:
        return "RECONECTAR (credencial ausente)"
    # Ajuste de conta na plataforma (nao e codigo)
    if "unaudited_client" in e:
        return "AJUSTE CONTA (app TikTok nao auditado)"
    if "(#200)" in e or "does not have permission" in e:
        return "AJUSTE CONTA (sem permissao na pagina)"
    # Transitorio (reenviar depois resolve)
    if "spam_risk" in e or "too_many_pending" in e:
        return "TRANSITORIO (rascunhos demais no TikTok)"
    if "(#4)" in e or "application request limit" in e or "rate limit" in e:
        return "TRANSITORIO (limite temporario da Meta)"
    if "exceeded the number of videos" in e or "quota" in e:
        return "TRANSITORIO (cota diaria)"
    if "tempo esgotado" in e or "timeout" in e:
        return "TRANSITORIO (timeout no processamento)"
    if "url publica" in e:
        return "ARQUIVO PURGADO (sem midia p/ subir)"
    if "arquivo de video nao encontrado" in e or "removido (purgado" in e:
        return "ARQUIVO PURGADO (sem midia p/ subir)"
    return "OUTRO"


def main() -> int:
    db = SessionLocal()
    try:
        pubs = (
            db.query(Publication)
            .filter(Publication.status.notin_(DONE))
            .all()
        )
        asset_cache: dict[int, VideoAsset] = {}
        buckets: Counter[str] = Counter()
        purged_terminal = 0
        file_present = 0
        for p in pubs:
            a = asset_cache.get(p.video_asset_id)
            if a is None:
                a = db.query(VideoAsset).filter(VideoAsset.id == p.video_asset_id).first()
                asset_cache[p.video_asset_id] = a
            is_purged = _purged(a) if a else True
            if is_purged:
                purged_terminal += 1
                buckets["ARQUIVO PURGADO (sem midia p/ subir)"] += 1
            else:
                file_present += 1
                buckets[_bucket(p.error or "")] += 1

        total = len(pubs)
        print(f"Publicacoes NAO concluidas: {total}\n")
        print(f"  ARQUIVO PURGADO (terminal, vira SKIPPED): {purged_terminal}")
        print(f"  Com arquivo local presente:               {file_present}\n")
        print("== BALDES (somente com arquivo presente + os purgados) ==")
        for name, n in buckets.most_common():
            print(f"  [{n:>3}] {name}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
