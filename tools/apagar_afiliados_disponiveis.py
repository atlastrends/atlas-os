# -*- coding: utf-8 -*-
"""Apaga os videos de AFILIADO 'disponiveis' no painel (status != PUBLISHED),
porque foram gerados com o roteiro antigo (narracao com inicio generico e fim
fora do assunto do produto). Remove BANCO + ARQUIVOS para eles nao voltarem no
sync() (o painel recria afiliado a partir do .mp4 em storage/video_pipeline/
outputs, entao apagar so o banco nao basta).

PRESERVA os afiliados JA PUBLICADOS (registros + estatisticas): esses ja foram
ao ar e seus arquivos ja foram liberados; nao sao tocados.

Uso:
    python tools/apagar_afiliados_disponiveis.py           # DRY-RUN (so mostra)
    python tools/apagar_afiliados_disponiveis.py apply      # APAGA de verdade
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
    VideoAsset,
    VideoKindEnum,
    VideoMetric,
    VideoStatusEnum,
)
from app.services.video_library_service import (
    AFFILIATE_OUTPUT_DIRS,
    PROJECT_ROOT,
)


def _abs(rel: str | None) -> str | None:
    if not rel:
        return None
    return os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))


def _status(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _outputs_dir() -> str:
    # storage/video_pipeline/outputs (primeiro dir de afiliados)
    return AFFILIATE_OUTPUT_DIRS[0]


def _approval_dirs() -> list[str]:
    base = os.path.join(PROJECT_ROOT, "storage", "approval")
    return [os.path.join(base, "pending"), os.path.join(base, "processed")]


def _files_for_asset(asset: VideoAsset) -> list[str]:
    """Todos os arquivos em disco ligados a este afiliado."""
    files: list[str] = []
    # 1) Caminhos guardados no banco.
    for rel in (asset.video_path, asset.metadata_path, asset.thumbnail_path):
        p = _abs(rel)
        if p:
            files.append(p)
    # 2) Mesmo stem na pasta de outputs: sidecar, video, variante de live.
    stem = (asset.external_key or "").strip()
    if stem:
        outs = _outputs_dir()
        files.append(os.path.join(outs, stem + ".mp4"))       # video (se faltou no banco)
        files.append(os.path.join(outs, stem + ".json"))      # sidecar (se faltou no banco)
        files.append(os.path.join(outs, stem + ".live.mp4"))  # variante de live
        files.append(os.path.join(outs, stem + ".live.json")) # sidecar da live
        # 3) Registro de aprovacao (pending/processed) com o mesmo stem.
        for adir in _approval_dirs():
            files.append(os.path.join(adir, stem + ".json"))
    # dedup preservando ordem
    seen: set[str] = set()
    uniq: list[str] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def main() -> int:
    apply = len(sys.argv) > 1 and sys.argv[1].strip().lower() in {
        "apply", "--apply", "-y", "sim",
    }
    db = SessionLocal()
    try:
        # Alvo: afiliados DISPONIVEIS = tudo que NAO esta PUBLISHED.
        targets = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.kind == VideoKindEnum.AFFILIATE,
                VideoAsset.status != VideoStatusEnum.PUBLISHED,
            )
            .order_by(VideoAsset.id.asc())
            .all()
        )
        published = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.kind == VideoKindEnum.AFFILIATE,
                VideoAsset.status == VideoStatusEnum.PUBLISHED,
            )
            .count()
        )

        by_status = Counter(_status(a.status) for a in targets)
        ids = [a.id for a in targets]

        # Descobre arquivos existentes.
        existing_files: list[str] = []
        total_bytes = 0
        for a in targets:
            for f in _files_for_asset(a):
                if os.path.isfile(f):
                    existing_files.append(f)
                    try:
                        total_bytes += os.path.getsize(f)
                    except OSError:
                        pass

        print("=" * 64)
        print("AFILIADOS DISPONIVEIS (status != PUBLISHED) -> ALVO DE EXCLUSAO")
        print("=" * 64)
        print(f"Assets alvo........: {len(targets)}")
        for st, n in sorted(by_status.items()):
            print(f"  - {st:14}: {n}")
        print(
            f"Arquivos em disco..: {len(existing_files)} "
            f"({round(total_bytes / 1024 / 1024, 1)} MB)"
        )
        print(f"PUBLICADOS preservados (intocados): {published}")
        print("-" * 64)
        for a in targets[:8]:
            print(f"  #{a.id} [{_status(a.status)}] {a.external_key}")
        if len(targets) > 8:
            print(f"  ... (+{len(targets) - 8} outros)")
        print("-" * 64)

        if not apply:
            print("DRY-RUN: nada foi apagado. Rode com 'apply' para excluir.")
            return 0

        if not ids:
            print("Nada a apagar.")
            return 0

        # 1) Apaga arquivos em disco.
        removed_files = 0
        for f in existing_files:
            try:
                os.remove(f)
                removed_files += 1
            except OSError as exc:
                print(f"  ! falhou apagar {f}: {exc}")

        # 2) Apaga filhos no banco (publicacoes + metricas) e depois os assets.
        db.query(Publication).filter(
            Publication.video_asset_id.in_(ids)
        ).delete(synchronize_session=False)
        db.query(VideoMetric).filter(
            VideoMetric.video_asset_id.in_(ids)
        ).delete(synchronize_session=False)
        removed_assets = (
            db.query(VideoAsset)
            .filter(VideoAsset.id.in_(ids))
            .delete(synchronize_session=False)
        )
        db.commit()

        print("=" * 64)
        print(f"APAGADOS: {removed_assets} afiliados | {removed_files} arquivos")
        print(f"PRESERVADOS (publicados): {published}")
        print("=" * 64)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
