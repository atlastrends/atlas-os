# ATLAS OS - Conector Facebook (Graph API - Reels / Video)
from __future__ import annotations

import os
import time

import requests

from app.publishing.base import (
    BasePublisher,
    PublishRequest,
    PublishResult,
    get_page_access_token,
    public_media_url,
    resolve_meta_targets,
)

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


class FacebookPublisher(BasePublisher):
    platform = "facebook"
    required_env = (
        "META_ACCESS_TOKEN",
    )

    def _do_publish(self, request: PublishRequest) -> PublishResult:
        page_id, _ig_id, role, market = resolve_meta_targets(
            request.kind,
            request.country_code,
            request.language,
        )

        if not page_id:
            return PublishResult(
                status="credentials_missing",
                error=(
                    "Pagina do Facebook nao configurada para "
                    f"{role}/{market}. Defina FB_PAGE_{role}_{market} no .env."
                ),
                detail={"platform": self.platform, "role": role, "market": market},
            )

        # O Graph API exige o token ESPECIFICO da Pagina para publicar
        # (o token de usuario sozinho recebe 403, mesmo com as permissoes).
        token = get_page_access_token(page_id)

        video_url = public_media_url(request.video_path)
        if not video_url or video_url.startswith("http://localhost"):
            return PublishResult(
                status="failed",
                error=(
                    "O Facebook precisa baixar o video por uma URL PUBLICA. "
                    "Defina ATLAS_PUBLIC_BASE_URL com um dominio HTTPS acessivel."
                ),
                detail={"platform": self.platform, "video_url": video_url},
            )

        description = (request.description or request.caption or "").strip()

        try:
            # 1) Inicia o upload do Reel (fase start).
            start = requests.post(
                f"{GRAPH_BASE}/{page_id}/video_reels",
                data={"upload_phase": "start", "access_token": token},
                timeout=60,
            ).json()
            video_id = start.get("video_id")
            if not video_id:
                return PublishResult(
                    status="failed",
                    error=f"Falha ao iniciar o Reel do Facebook: {start}",
                    detail={"platform": self.platform},
                )

            # 2) Faz o upload informando a URL publica do arquivo (hosted file).
            upload = requests.post(
                f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}/{video_id}",
                headers={
                    "Authorization": f"OAuth {token}",
                    "file_url": video_url,
                },
                timeout=120,
            )
            if upload.status_code >= 400:
                return PublishResult(
                    status="failed",
                    error=f"Falha no upload do Reel: {upload.text}",
                    detail={"platform": self.platform},
                )

            # 3) Finaliza e publica.
            finish = requests.post(
                f"{GRAPH_BASE}/{page_id}/video_reels",
                data={
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "video_state": "PUBLISHED",
                    "description": description,
                    "access_token": token,
                },
                timeout=60,
            ).json()
            if not finish.get("success", False) and "post_id" not in finish:
                return PublishResult(
                    status="failed",
                    error=f"Falha ao finalizar o Reel do Facebook: {finish}",
                    detail={"platform": self.platform},
                )

            # Aguarda um instante para o post ficar disponivel.
            time.sleep(2)

            # Busca o link real (permalink) do Reel para conferir.
            permalink = f"https://www.facebook.com/reel/{video_id}"
            try:
                info = requests.get(
                    f"{GRAPH_BASE}/{video_id}",
                    params={"fields": "permalink_url", "access_token": token},
                    timeout=30,
                ).json()
                real = (info or {}).get("permalink_url")
                if real:
                    permalink = real if real.startswith("http") else f"https://www.facebook.com{real}"
            except Exception:  # noqa: BLE001
                pass

            return PublishResult(
                status="published",
                external_id=str(video_id),
                external_url=permalink,
                detail={"platform": self.platform, "finish": finish},
            )

        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=f"Erro na publicacao do Facebook: {exc}",
                detail={"platform": self.platform},
            )
