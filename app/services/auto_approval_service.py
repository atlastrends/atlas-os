# ============================================================
# ATLAS OS - auto_approval_service.py
# Aprova e publica automaticamente os videos cuja QUALIDADE for boa.
#
# A qualidade e calculada por uma heuristica 0-100 combinando:
#   - performance_score do reel (quando existir)
#   - existencia e tamanho do arquivo de video
#   - presenca de titulo, legenda e hashtags
#   - (afiliados) presenca do link de afiliado (link clicavel)
#
# Controle por variaveis de ambiente:
#   ATLAS_AUTO_APPROVE_ENABLED   (default: false)
#   ATLAS_AUTO_APPROVE_MIN_SCORE (default: 70)
#   ATLAS_AUTO_APPROVE_KINDS     (default: "reel,affiliate")
# ============================================================

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.models.dashboard import VideoAsset, VideoKindEnum, VideoStatusEnum
from app.publishing.base import resolve_video_path
from app.publishing.registry import platform_status
from app.services.publishing_service import PublishingService
from app.services.subject_match_service import (
    gate_enabled as subject_gate_enabled,
    verify_subject_match,
)
from app.services.video_library_service import VideoLibraryService

MIN_VIDEO_BYTES = 50 * 1024  # 50 KB


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _allowed_kinds() -> set[str]:
    raw = os.getenv("ATLAS_AUTO_APPROVE_KINDS", "reel,affiliate")
    return {k.strip().lower() for k in raw.split(",") if k.strip()}


class AutoApprovalService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------------------------------------------------------
    # AVALIACAO DE QUALIDADE
    # ----------------------------------------------------------------

    def evaluate_quality(self, asset: VideoAsset) -> tuple[int, list[str]]:
        """Retorna (score 0-100, motivos). score 0 = reprovado direto."""
        reasons: list[str] = []
        payload = asset.payload or {}
        kind = asset.kind.value if hasattr(asset.kind, "value") else str(asset.kind)

        # 1) Arquivo de video precisa existir e ter tamanho minimo.
        abs_path = resolve_video_path(asset.video_path or "")
        if not abs_path or not os.path.isfile(abs_path):
            return 0, ["arquivo de video ausente"]
        try:
            size = os.path.getsize(abs_path)
        except OSError:
            size = 0
        if size < MIN_VIDEO_BYTES:
            return 0, [f"arquivo muito pequeno ({size} bytes)"]

        # 2) Afiliado sem link clicavel nao passa (requisito do produto).
        if kind == "affiliate" and not (asset.affiliate_url or "").strip():
            return 0, ["afiliado sem link clicavel (affiliate_url)"]

        # 3) Pontuacao base.
        base = int(asset.performance_score or 0)
        if kind == "reel" and base > 0:
            score = min(base, 100)
        else:
            score = 60  # baseline para itens sem performance_score
            reasons.append("sem performance_score; baseline 60")

        # 4) Bonus por completude de metadados.
        title = (asset.title or "").strip()
        if len(title) >= 5:
            score += 10
        else:
            reasons.append("titulo curto/ausente")

        hashtags = payload.get("hashtags") or []
        if isinstance(hashtags, list) and len(hashtags) >= 3:
            score += 10
        else:
            reasons.append("poucas hashtags")

        platforms_meta = payload.get("platforms") or {}
        has_caption = any(
            (p or {}).get("caption") or (p or {}).get("description")
            for p in platforms_meta.values()
        )
        if has_caption or kind == "affiliate":
            score += 10
        else:
            reasons.append("sem legenda/descricao")

        score = max(0, min(score, 100))
        return score, reasons

    # ----------------------------------------------------------------
    # EXECUCAO
    # ----------------------------------------------------------------

    def run(self, *, min_score: int | None = None) -> dict:
        if min_score is None:
            min_score = _env_int("ATLAS_AUTO_APPROVE_MIN_SCORE", 70)

        allowed = _allowed_kinds()

        # Garante que a biblioteca esteja atualizada com os arquivos novos.
        VideoLibraryService(self.db).sync()

        # Plataformas com credenciais configuradas (publica so onde da).
        configured = [p["platform"] for p in platform_status() if p["configured"]]

        candidates = (
            self.db.query(VideoAsset)
            .filter(VideoAsset.status == VideoStatusEnum.CREATED)
            .all()
        )

        publisher = PublishingService(self.db)
        approved, skipped, published = 0, 0, 0
        details = []

        for asset in candidates:
            kind = asset.kind.value if hasattr(asset.kind, "value") else str(asset.kind)
            if kind not in allowed:
                continue

            score, reasons = self.evaluate_quality(asset)
            if score < min_score:
                skipped += 1
                details.append(
                    {"id": asset.id, "score": score, "approved": False, "reasons": reasons}
                )
                continue

            # PORTAO DE ASSUNTO (so afiliados): so publica sozinho quando a IA
            # tem CERTEZA ALTA de que a narracao fala exatamente do produto.
            # Qualquer duvida -> deixa para aprovacao manual (como hoje).
            if kind == "affiliate" and subject_gate_enabled():
                confident, confidence, why = verify_subject_match(asset)
                if not confident:
                    skipped += 1
                    details.append(
                        {
                            "id": asset.id,
                            "score": score,
                            "approved": False,
                            "subject_confidence": confidence,
                            "reasons": [f"assunto nao confirmado: {why}"],
                        }
                    )
                    continue
                reasons.append(why)

            result = publisher.approve_and_publish(
                asset,
                platforms=configured or [],
                notes=f"Aprovacao automatica (qualidade={score}).",
            )
            approved += 1
            if result.get("status") == "published":
                published += 1
            details.append(
                {
                    "id": asset.id,
                    "score": score,
                    "approved": True,
                    "status": result.get("status"),
                }
            )

        return {
            "min_score": min_score,
            "kinds": sorted(allowed),
            "configured_platforms": configured,
            "candidates": len(candidates),
            "approved": approved,
            "published": published,
            "skipped": skipped,
            "details": details[:100],
        }
