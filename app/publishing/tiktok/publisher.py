# ATLAS OS - Conector TikTok (Content Posting API)
from __future__ import annotations

import os

import requests

from app.publishing.base import (
    BasePublisher,
    PublishRequest,
    PublishResult,
    market_code,
    resolve_tiktok_token,
)
from app.services import tiktok_oauth_service

API_BASE = "https://open.tiktokapis.com/v2"

# Tamanho de cada pedaco no upload direto (FILE_UPLOAD). O TikTok aceita ate
# 64MB por pedaco; usamos o arquivo inteiro num pedaco so quando cabe.
_MAX_SINGLE_CHUNK = 64 * 1024 * 1024

# Nivel de privacidade do post. Enquanto o app estiver em modo sandbox/auditoria,
# use SELF_ONLY (privado). Depois de aprovado, PUBLIC_TO_EVERYONE.
DEFAULT_PRIVACY = os.getenv("TIKTOK_PRIVACY_LEVEL", "SELF_ONLY")


class TikTokPublisher(BasePublisher):
    platform = "tiktok"
    required_env = (
        "TIKTOK_CLIENT_KEY",
        "TIKTOK_CLIENT_SECRET",
        "TIKTOK_ACCESS_TOKEN",
    )

    def missing_credentials(self) -> list[str]:
        """Aceita o token unico (TIKTOK_ACCESS_TOKEN) OU os tokens por
        mercado (TIKTOK_ACCESS_TOKEN_BR / _US)."""
        missing: list[str] = []
        if not (os.getenv("TIKTOK_CLIENT_KEY") or "").strip():
            missing.append("TIKTOK_CLIENT_KEY")
        if not (os.getenv("TIKTOK_CLIENT_SECRET") or "").strip():
            missing.append("TIKTOK_CLIENT_SECRET")
        has_token = any(
            (os.getenv(name) or "").strip()
            for name in (
                "TIKTOK_ACCESS_TOKEN",
                "TIKTOK_ACCESS_TOKEN_BR",
                "TIKTOK_ACCESS_TOKEN_US",
                "TIKTOK_REFRESH_TOKEN_BR",
                "TIKTOK_REFRESH_TOKEN_US",
            )
        )
        if not has_token:
            missing.append("TIKTOK_ACCESS_TOKEN")
        return missing

    def _do_publish(self, request: PublishRequest) -> PublishResult:
        market = market_code(request.country_code, request.language)

        # 1) Pega um token valido (renova sozinho se estiver perto de vencer).
        token = tiktok_oauth_service.get_access_token(market)
        if not token:
            # Fallback: token estatico antigo, se existir.
            token, market = resolve_tiktok_token(
                request.country_code, request.language
            )
        if not token:
            return PublishResult(
                status="credentials_missing",
                error=(
                    f"Conta do TikTok nao conectada para o mercado {market}. "
                    "Clique em 'Conectar TikTok' no painel para autorizar a conta."
                ),
                detail={"platform": self.platform, "market": market},
            )

        # 2) Le o arquivo de video local (envio direto, sem precisar de URL publica).
        video_path = request.video_path or ""
        if not video_path or not os.path.isfile(video_path):
            return PublishResult(
                status="failed",
                error=f"Arquivo de video nao encontrado: {video_path}",
                detail={"platform": self.platform, "market": market},
            )

        try:
            with open(video_path, "rb") as fh:
                video_bytes = fh.read()
        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=f"Nao consegui ler o video: {exc}",
                detail={"platform": self.platform, "market": market},
            )

        video_size = len(video_bytes)
        if video_size <= 0:
            return PublishResult(
                status="failed",
                error="O arquivo de video esta vazio.",
                detail={"platform": self.platform, "market": market},
            )

        title = (request.caption or request.title or "").strip()[:2200]

        try:
            # 3) Inicia a publicacao com upload direto (FILE_UPLOAD).
            #    Enviamos o arquivo inteiro num unico pedaco.
            init = requests.post(
                f"{API_BASE}/post/publish/video/init/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={
                    "post_info": {
                        "title": title,
                        "privacy_level": DEFAULT_PRIVACY,
                        "disable_comment": False,
                        "disable_duet": False,
                        "disable_stitch": False,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": video_size,
                        "chunk_size": video_size,
                        "total_chunk_count": 1,
                    },
                },
                timeout=60,
            )
            data = init.json()
            err = (data.get("error") or {})
            if init.status_code >= 400 or (err.get("code") and err.get("code") != "ok"):
                return PublishResult(
                    status="failed",
                    error=f"Falha ao iniciar publicacao no TikTok: {data}",
                    detail={"platform": self.platform, "market": market},
                )

            payload = data.get("data") or {}
            publish_id = payload.get("publish_id")
            upload_url = payload.get("upload_url")
            if not publish_id or not upload_url:
                return PublishResult(
                    status="failed",
                    error=f"TikTok nao retornou upload_url/publish_id: {data}",
                    detail={"platform": self.platform, "market": market},
                )

            # 4) Envia os bytes do video para o upload_url (PUT).
            put = requests.put(
                upload_url,
                data=video_bytes,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(video_size),
                    "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
                },
                timeout=600,
            )
            if put.status_code >= 400:
                return PublishResult(
                    status="failed",
                    error=(
                        f"Falha ao enviar o video para o TikTok "
                        f"(HTTP {put.status_code}): {put.text[:300]}"
                    ),
                    detail={"platform": self.platform, "market": market},
                )

            # O processamento e assincrono no TikTok. O status pode ser
            # consultado depois em /post/publish/status/fetch/ com o publish_id.
            return PublishResult(
                status="published",
                external_id=publish_id,
                external_url=None,
                detail={
                    "platform": self.platform,
                    "market": market,
                    "publish_id": publish_id,
                    "async": True,
                },
            )

        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=f"Erro na publicacao do TikTok: {exc}",
                detail={"platform": self.platform, "market": market},
            )
