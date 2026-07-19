# ============================================================
# ATLAS OS - video_library_service.py
# Descobre videos ja produzidos (reels e afiliados) e os sincroniza
# na tabela video_assets, servindo de fonte unica para o painel.
#
# - Reels:     output_metadata/metadata_*.json + output_videos/video_*.mp4
# - Afiliados: storage/video_pipeline/outputs/*.mp4 (+ .json ao lado)
#              e storage/approval/** (pending/processed)
# ============================================================

from __future__ import annotations

import json
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.models.dashboard import (
    VideoAsset,
    VideoKindEnum,
    VideoStatusEnum,
)
from app.services.shortlink_service import ShortLinkService

PROJECT_ROOT = os.getenv("ATLAS_ROOT", os.getcwd())

OUTPUT_METADATA_DIR = os.path.join(PROJECT_ROOT, "output_metadata")
OUTPUT_VIDEOS_DIR = os.path.join(PROJECT_ROOT, "output_videos")
AFFILIATE_OUTPUT_DIRS = [
    os.path.join(PROJECT_ROOT, "storage", "video_pipeline", "outputs"),
    os.path.join(PROJECT_ROOT, "output_videos", "affiliate"),
]


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, PROJECT_ROOT).replace("\\", "/")
    except Exception:
        return path.replace("\\", "/")


def _safe_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class VideoLibraryService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------------------------------------------------------
    # SINCRONIZACAO
    # ----------------------------------------------------------------

    def sync(self) -> dict:
        created = 0
        created += self._sync_reels()
        created += self._sync_affiliate()
        return {"new_assets": created}

    def _upsert(
        self,
        *,
        kind: VideoKindEnum,
        external_key: str,
        defaults: dict,
    ) -> tuple[VideoAsset, bool]:
        asset = (
            self.db.query(VideoAsset)
            .filter(
                VideoAsset.kind == kind,
                VideoAsset.external_key == external_key,
            )
            .first()
        )
        if asset:
            # Atualiza somente campos "descritivos" e o caminho do video,
            # preservando status/review definidos pelo usuario.
            for field in (
                "title",
                "topic",
                "language",
                "country_code",
                "video_path",
                "thumbnail_path",
                "metadata_path",
                "affiliate_url",
                "performance_score",
                "payload",
            ):
                if field in defaults and defaults[field] is not None:
                    setattr(asset, field, defaults[field])
            self.db.commit()
            return asset, False

        asset = VideoAsset(
            kind=kind,
            external_key=external_key,
            status=VideoStatusEnum.CREATED,
            **defaults,
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset, True

    def _sync_reels(self) -> int:
        if not os.path.isdir(OUTPUT_METADATA_DIR):
            return 0

        new_count = 0
        for name in sorted(os.listdir(OUTPUT_METADATA_DIR)):
            if not name.startswith("metadata_") or not name.endswith(".json"):
                continue

            meta_path = os.path.join(OUTPUT_METADATA_DIR, name)
            data = _safe_json(meta_path)
            if not data:
                continue

            content_id = str(data.get("content_id") or name)
            platforms = data.get("platforms", {}) or {}
            yt = platforms.get("youtube", {}) or {}

            video_path = data.get("video_path") or ""
            abs_video = os.path.join(PROJECT_ROOT, video_path) if video_path else ""

            defaults = {
                "title": yt.get("title") or data.get("topic"),
                "topic": data.get("topic"),
                "language": data.get("language"),
                "country_code": data.get("country_code"),
                "video_path": video_path if os.path.exists(abs_video) else video_path,
                "metadata_path": _rel(meta_path),
                "performance_score": int(float(data.get("performance_score") or 0)),
                "payload": {
                    "platforms": platforms,
                    "hashtags": (data.get("content", {}) or {}).get("base_hashtags", []),
                },
            }

            _, is_new = self._upsert(
                kind=VideoKindEnum.REEL,
                external_key=content_id,
                defaults=defaults,
            )
            if is_new:
                new_count += 1

        return new_count

    def _sync_affiliate(self) -> int:
        new_count = 0
        shortlinks = ShortLinkService(self.db)

        for base_dir in AFFILIATE_OUTPUT_DIRS:
            if not os.path.isdir(base_dir):
                continue

            for name in sorted(os.listdir(base_dir)):
                if not name.lower().endswith(".mp4"):
                    continue

                video_path = os.path.join(base_dir, name)
                stem = os.path.splitext(name)[0]

                sidecar = os.path.join(base_dir, stem + ".json")
                data = _safe_json(sidecar) if os.path.exists(sidecar) else {}

                affiliate_url = (
                    data.get("affiliate_url")
                    or data.get("detail_url")
                    or (data.get("product", {}) or {}).get("affiliate_url")
                )
                asin = data.get("asin") or (data.get("product", {}) or {}).get("asin")
                title = data.get("title") or (data.get("product", {}) or {}).get("title") or stem

                short_code = None
                if affiliate_url:
                    link = shortlinks.get_or_create(
                        affiliate_url,
                        asin=asin,
                        title=title,
                    )
                    short_code = link.code

                # Rede de segurança: se o arquivo do afiliado nao trouxe o pais,
                # deduz pelo comeco do nome ("br-..." / "us-...") para o video
                # nao cair no canal errado (ex.: video em portugues no canal em ingles).
                inferred_market = ""
                prefix = stem.split("-", 1)[0].strip().lower()
                if prefix in ("br", "us"):
                    inferred_market = prefix.upper()

                country_code = (
                    data.get("marketplace_code")
                    or data.get("market")
                    or inferred_market
                    or None
                )
                language = data.get("language")
                if not language and inferred_market:
                    language = "pt-BR" if inferred_market == "BR" else "en-US"

                defaults = {
                    "title": title,
                    "topic": title,
                    "language": language,
                    "country_code": country_code,
                    "video_path": _rel(video_path),
                    "metadata_path": _rel(sidecar) if os.path.exists(sidecar) else None,
                    "affiliate_url": affiliate_url,
                    "payload": data,
                }

                asset, is_new = self._upsert(
                    kind=VideoKindEnum.AFFILIATE,
                    external_key=stem,
                    defaults=defaults,
                )
                if short_code and asset.short_code != short_code:
                    asset.short_code = short_code
                    self.db.commit()
                if is_new:
                    new_count += 1

        return new_count

    # ----------------------------------------------------------------
    # LIMPEZA (apagar reels trending)
    # ----------------------------------------------------------------

    def clear_reels(self) -> dict:
        """
        Apaga TODOS os reels de assuntos em alta (kind=reel):
        - remove os registros no banco (e suas publicacoes);
        - apaga os arquivos .mp4 em output_videos/ (nivel raiz, sem tocar
          na subpasta affiliate/);
        - apaga os metadados em output_metadata/;
        - zera a memoria de assuntos usados para permitir nova busca.
        NAO afeta os videos de afiliados.
        """
        from app.models.dashboard import Publication

        removed_assets = 0
        removed_files = 0

        # 1) Banco: apaga publicacoes e assets do tipo reel.
        reel_assets = (
            self.db.query(VideoAsset)
            .filter(VideoAsset.kind == VideoKindEnum.REEL)
            .all()
        )
        reel_ids = [a.id for a in reel_assets]

        if reel_ids:
            (
                self.db.query(Publication)
                .filter(Publication.video_asset_id.in_(reel_ids))
                .delete(synchronize_session=False)
            )
            (
                self.db.query(VideoAsset)
                .filter(VideoAsset.id.in_(reel_ids))
                .delete(synchronize_session=False)
            )
            removed_assets = len(reel_ids)
            self.db.commit()

        # 2) Arquivos de video no nivel raiz de output_videos (nao afiliados).
        if os.path.isdir(OUTPUT_VIDEOS_DIR):
            for name in os.listdir(OUTPUT_VIDEOS_DIR):
                full = os.path.join(OUTPUT_VIDEOS_DIR, name)
                if os.path.isfile(full) and name.lower().endswith(
                    (".mp4", ".mov", ".webm")
                ):
                    try:
                        os.remove(full)
                        removed_files += 1
                    except Exception:
                        pass

        # 3) Metadados dos reels.
        if os.path.isdir(OUTPUT_METADATA_DIR):
            for name in os.listdir(OUTPUT_METADATA_DIR):
                full = os.path.join(OUTPUT_METADATA_DIR, name)
                if not os.path.isfile(full):
                    continue
                if name.startswith("metadata_") and name.endswith(".json"):
                    try:
                        os.remove(full)
                        removed_files += 1
                    except Exception:
                        pass
                elif name == "used_topics_memory.json":
                    # Zera a memoria para liberar novos assuntos.
                    try:
                        with open(full, "w", encoding="utf-8") as fh:
                            fh.write("{}")
                    except Exception:
                        pass

        return {
            "removed_assets": removed_assets,
            "removed_files": removed_files,
        }

    def clear_rejected(self, kind: Optional[str] = None) -> dict:
        """
        Apaga os videos REJEITADOS (arquivos + banco). Se `kind` for
        informado ('reel' ou 'affiliate'), limita-se aquele tipo; caso
        contrario, apaga os rejeitados de todos os tipos.
        Remove tambem os arquivos .mp4, metadados/sidecars e as publicacoes.
        """
        from app.models.dashboard import Publication

        removed_assets = 0
        removed_files = 0

        query = self.db.query(VideoAsset).filter(
            VideoAsset.status == VideoStatusEnum.REJECTED
        )
        if kind:
            query = query.filter(VideoAsset.kind == kind)

        rejected = query.all()
        ids = [a.id for a in rejected]

        # 1) Apaga os arquivos em disco (video, metadados e thumbnail).
        for asset in rejected:
            for rel in (
                asset.video_path,
                asset.metadata_path,
                asset.thumbnail_path,
            ):
                if not rel:
                    continue
                full = os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))
                try:
                    if os.path.isfile(full):
                        os.remove(full)
                        removed_files += 1
                except Exception:
                    pass

        # 2) Apaga as publicacoes e os registros no banco.
        if ids:
            (
                self.db.query(Publication)
                .filter(Publication.video_asset_id.in_(ids))
                .delete(synchronize_session=False)
            )
            (
                self.db.query(VideoAsset)
                .filter(VideoAsset.id.in_(ids))
                .delete(synchronize_session=False)
            )
            removed_assets = len(ids)
            self.db.commit()

        return {
            "removed_assets": removed_assets,
            "removed_files": removed_files,
        }

    def delete_published_files(self, kind: Optional[str] = None) -> dict:
        """
        Libera espaco no computador apagando SO O ARQUIVO de video (.mp4)
        e a miniatura dos videos JA PUBLICADOS.

        IMPORTANTE: NAO apaga o registro no banco nem as ESTATISTICAS
        (views, curtidas etc.) e NAO apaga o arquivinho .json ao lado
        (usado para nao gerar o mesmo produto de novo). Ou seja, o video
        continua publicado nas redes e as estatisticas continuam sendo
        coletadas normalmente — so o arquivo pesado sai do seu computador.
        """
        removed_files = 0
        freed_bytes = 0
        affected_assets = 0

        query = self.db.query(VideoAsset).filter(
            VideoAsset.status == VideoStatusEnum.PUBLISHED
        )
        if kind:
            query = query.filter(VideoAsset.kind == kind)

        for asset in query.all():
            purged = False
            # So arquivos pesados: video e miniatura. (NAO o .json/metadados.)
            for rel in (asset.video_path, asset.thumbnail_path):
                if not rel:
                    continue
                full = os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))
                try:
                    if os.path.isfile(full):
                        freed_bytes += os.path.getsize(full)
                        os.remove(full)
                        removed_files += 1
                        purged = True
                except Exception:
                    pass

            # Tambem limpa "sujeira": registros JA PUBLICADOS cujo arquivo de
            # video ja nao existe mais no disco (apagado antes, ou nome
            # divergente). Sem isso, eles continuariam aparecendo quebrados
            # (player 404) na lista de videos.
            main_rel = asset.video_path
            main_full = (
                os.path.join(PROJECT_ROOT, main_rel.replace("/", os.sep))
                if main_rel
                else ""
            )
            main_missing = (not main_rel) or (not os.path.isfile(main_full))

            if purged or main_missing:
                affected_assets += 1
                # Marca que o arquivo foi removido (estatisticas preservadas).
                payload = dict(asset.payload or {})
                payload["file_purged"] = True
                asset.payload = payload

        if affected_assets:
            self.db.commit()

        return {
            "affected_assets": affected_assets,
            "removed_files": removed_files,
            "freed_mb": round(freed_bytes / (1024 * 1024), 1),
        }

    # ----------------------------------------------------------------
    # CONSULTA
    # ----------------------------------------------------------------

    def list_assets(
        self,
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> list[VideoAsset]:
        query = self.db.query(VideoAsset)

        if kind:
            query = query.filter(VideoAsset.kind == kind)
        if status:
            query = query.filter(VideoAsset.status == status)

        return (
            query.order_by(VideoAsset.created_at.desc())
            .limit(limit)
            .all()
        )

    def get(self, asset_id: int) -> Optional[VideoAsset]:
        return (
            self.db.query(VideoAsset)
            .filter(VideoAsset.id == asset_id)
            .first()
        )

    def is_file_present(self, asset: VideoAsset) -> bool:
        """True se o arquivo de video do asset existe no disco."""
        rel = asset.video_path
        if not rel:
            return False
        full = os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))
        return os.path.isfile(full)
