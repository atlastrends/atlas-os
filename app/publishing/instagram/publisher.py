# ATLAS OS - Conector Instagram (Instagram Graph API - Reels)
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


class InstagramPublisher(BasePublisher):
    platform = "instagram"
    required_env = (
        "META_ACCESS_TOKEN",
    )

    def _do_publish(self, request: PublishRequest) -> PublishResult:
        page_id, ig_id, role, market = resolve_meta_targets(
            request.kind,
            request.country_code,
            request.language,
        )

        if not ig_id:
            return PublishResult(
                status="credentials_missing",
                error=(
                    "Conta do Instagram nao configurada para "
                    f"{role}/{market}. Defina IG_{role}_{market} no .env."
                ),
                detail={"platform": self.platform, "role": role, "market": market},
            )

        # O Instagram Graph API tambem exige o token da Pagina do Facebook
        # conectada aquela conta do Instagram (nao o token de usuario puro).
        token = get_page_access_token(page_id)

        video_url = public_media_url(request.video_path)
        if not video_url or video_url.startswith("http://localhost"):
            return PublishResult(
                status="failed",
                error=(
                    "O Instagram precisa baixar o video por uma URL PUBLICA. "
                    "Defina ATLAS_PUBLIC_BASE_URL com um dominio HTTPS acessivel."
                ),
                detail={"platform": self.platform, "video_url": video_url},
            )

        caption = (request.caption or request.description or "").strip()

        try:
            # 1) Cria o container de midia (REELS).
            create = requests.post(
                f"{GRAPH_BASE}/{ig_id}/media",
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                    "access_token": token,
                },
                timeout=60,
            )
            create_data = create.json()
            if create.status_code >= 400 or "id" not in create_data:
                return PublishResult(
                    status="failed",
                    error=f"Falha ao criar container do Reels: {create_data}",
                    detail={"platform": self.platform},
                )
            container_id = create_data["id"]

            # 2) Aguarda o processamento do video ficar pronto.
            for _ in range(30):
                status = requests.get(
                    f"{GRAPH_BASE}/{container_id}",
                    params={"fields": "status_code", "access_token": token},
                    timeout=30,
                ).json()
                code = status.get("status_code")
                if code == "FINISHED":
                    break
                if code == "ERROR":
                    return PublishResult(
                        status="failed",
                        error=f"Instagram falhou ao processar o video: {status}",
                        detail={"platform": self.platform},
                    )
                time.sleep(5)
            else:
                return PublishResult(
                    status="failed",
                    error="Tempo esgotado aguardando o Instagram processar o video.",
                    detail={"platform": self.platform},
                )

            # 3) Publica o container.
            publish = requests.post(
                f"{GRAPH_BASE}/{ig_id}/media_publish",
                data={"creation_id": container_id, "access_token": token},
                timeout=60,
            )
            publish_data = publish.json()
            media_id = publish_data.get("id")
            if publish.status_code >= 400 or not media_id:
                return PublishResult(
                    status="failed",
                    error=f"Falha ao publicar o Reels: {publish_data}",
                    detail={"platform": self.platform},
                )

            # 4) Busca o link real (permalink) para conferir o Reels.
            #    O ID numerico NAO forma uma URL valida; o permalink usa
            #    um codigo curto que so a API do Instagram devolve.
            permalink = f"https://www.instagram.com/reel/{media_id}"
            try:
                info = requests.get(
                    f"{GRAPH_BASE}/{media_id}",
                    params={"fields": "permalink", "access_token": token},
                    timeout=30,
                ).json()
                real = (info or {}).get("permalink")
                if real:
                    permalink = real
            except Exception:  # noqa: BLE001
                pass

            return PublishResult(
                status="published",
                external_id=media_id,
                external_url=permalink,
                detail={"platform": self.platform},
            )

        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=f"Erro na publicacao do Instagram: {exc}",
                detail={"platform": self.platform},
            )
