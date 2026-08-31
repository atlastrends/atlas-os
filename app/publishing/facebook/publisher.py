# ATLAS OS - Conector Facebook (Graph API - Reels / Video)
from __future__ import annotations

import os
import time

import requests

from app.publishing.base import (
    BasePublisher,
    MetaGraphTransientError,
    PublishRequest,
    PublishResult,
    get_page_access_token,
    local_media_file,
    public_media_url,
    resolve_meta_targets,
)

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def _is_reels_frequency_block(payload: dict) -> bool:
    error = payload.get("error") if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        return False
    message = str(error.get("message") or "").lower()
    return (
        error.get("code") == 368
        or error.get("error_subcode") == 1390008
        or "limitamos a frequência" in message
        or "limitamos a frequencia" in message
    )


class FacebookPublisher(BasePublisher):
    platform = "facebook"
    required_env = (
        "META_ACCESS_TOKEN",
    )

    def _publish_standard_video(
        self,
        page_id: str,
        token: str,
        description: str,
        local_file: str,
        video_url: str,
    ) -> dict:
        """Fallback para /videos quando o endpoint de Reels bloqueia por
        frequencia. Envia os BYTES locais (multipart 'source') quando possivel,
        evitando a URL publica/robots.txt; so usa file_url se nao houver arquivo."""
        try:
            if local_file:
                with open(local_file, "rb") as fh:
                    return requests.post(
                        f"{GRAPH_BASE}/{page_id}/videos",
                        data={
                            "description": description,
                            "published": "true",
                            "access_token": token,
                        },
                        files={"source": (os.path.basename(local_file), fh, "video/mp4")},
                        timeout=600,
                    ).json()
            return requests.post(
                f"{GRAPH_BASE}/{page_id}/videos",
                data={
                    "file_url": video_url,
                    "description": description,
                    "published": "true",
                    "access_token": token,
                },
                timeout=180,
            ).json()
        except Exception as exc:  # noqa: BLE001
            return {"error": {"message": f"fallback /videos falhou: {exc}"}}

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
        try:
            token = get_page_access_token(page_id)
        except MetaGraphTransientError as exc:
            return PublishResult(
                status="failed",
                error=f"Bloqueio temporario do Graph API (Meta): {exc}",
                detail={"platform": self.platform, "role": role, "market": market},
            )

        # Preferimos enviar os BYTES locais direto para a Meta (sem URL publica):
        # isso elimina de vez o erro "403 Restricted by robots.txt". So caimos
        # para URL publica se o arquivo local nao existir (ex.: ja foi purgado).
        local_file = local_media_file(request.video_path)
        video_url = public_media_url(request.video_path)
        if not local_file and (not video_url or video_url.startswith("http://localhost")):
            return PublishResult(
                status="failed",
                error=(
                    "O arquivo local do video nao existe e nao ha URL PUBLICA "
                    "para o Facebook baixar. Mantenha o MP4 no disco (nao purgar "
                    "antes de publicar) ou defina ATLAS_PUBLIC_BASE_URL HTTPS."
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
                if _is_reels_frequency_block(start):
                    fallback = self._publish_standard_video(
                        page_id, token, description, local_file, video_url
                    )
                    fallback_id = fallback.get("id")
                    if fallback_id:
                        permalink = (
                            f"https://www.facebook.com/{page_id}/videos/"
                            f"{fallback_id}"
                        )
                        info = requests.get(
                            f"{GRAPH_BASE}/{fallback_id}",
                            params={
                                "fields": "permalink_url",
                                "access_token": token,
                            },
                            timeout=30,
                        ).json()
                        real = (info or {}).get("permalink_url")
                        if real:
                            permalink = (
                                real
                                if real.startswith("http")
                                else f"https://www.facebook.com{real}"
                            )
                        return PublishResult(
                            status="published",
                            external_id=str(fallback_id),
                            external_url=permalink,
                            detail={
                                "platform": self.platform,
                                "publishing_mode": "standard_video_fallback",
                                "reels_error": start.get("error"),
                            },
                        )
                    return PublishResult(
                        status="failed",
                        error=(
                            "Facebook bloqueou temporariamente o endpoint de "
                            f"Reels e o fallback de video normal falhou: {fallback}"
                        ),
                        detail={
                            "platform": self.platform,
                            "reels_error": start.get("error"),
                            "fallback": fallback,
                        },
                    )
                return PublishResult(
                    status="failed",
                    error=f"Falha ao iniciar o Reel do Facebook: {start}",
                    detail={"platform": self.platform},
                )

            # 2) Upload do arquivo. Preferimos enviar os BYTES locais direto
            #    (resumable, sem URL/robots.txt); so usamos file_url se nao houver
            #    arquivo local.
            if local_file:
                file_size = os.path.getsize(local_file)
                with open(local_file, "rb") as fh:
                    upload = requests.post(
                        f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}/{video_id}",
                        headers={
                            "Authorization": f"OAuth {token}",
                            "offset": "0",
                            "file_size": str(file_size),
                        },
                        data=fh,
                        timeout=600,
                    )
                upload_mode = "local_bytes"
            else:
                upload = requests.post(
                    f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}/{video_id}",
                    headers={
                        "Authorization": f"OAuth {token}",
                        "file_url": video_url,
                    },
                    timeout=120,
                )
                upload_mode = "file_url"
            if upload.status_code >= 400:
                return PublishResult(
                    status="failed",
                    error=f"Falha no upload do Reel ({upload_mode}): {upload.text}",
                    detail={"platform": self.platform, "upload_mode": upload_mode},
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
