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

# Tamanho minimo/maximo de pedaco exigido pelo TikTok e o tamanho padrao que
# usamos quando precisamos dividir um video grande.
_MIN_CHUNK = 5 * 1024 * 1024
_DEFAULT_CHUNK = 20 * 1024 * 1024


def _plan_chunks(video_size: int) -> tuple[int, int]:
    """Decide o tamanho do pedaco e a quantidade de pedacos para o upload.

    Regra do TikTok:
      - Cada pedaco deve ter entre 5MB e 64MB.
      - Se o video couber em 64MB, enviamos tudo num pedaco so.
      - Se for maior, dividimos em pedacos de tamanho fixo e o ultimo
        pedaco absorve o resto (podendo passar um pouco do tamanho padrao,
        mas sempre abaixo de 64MB).
    """
    if video_size <= _MAX_SINGLE_CHUNK:
        return video_size, 1

    chunk_size = _DEFAULT_CHUNK
    total = video_size // chunk_size  # divisao inteira; o resto vai no ultimo
    if total < 1:
        total = 1
    return chunk_size, total


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

        # O TikTok exige que o video seja enviado em "pedacos" (chunks) de
        # 5MB a 64MB. Se o video for ate 64MB, mandamos num pedaco so. Se for
        # maior, dividimos em varios pedacos; o ultimo pedaco leva o resto.
        chunk_size, total_chunk_count = _plan_chunks(video_size)

        # Decide entre "Direct Post" (video.publish, publica direto no perfil)
        # e upload para rascunho/caixa de entrada (video.upload, o usuario
        # finaliza no app do TikTok).
        #
        # IMPORTANTE: enquanto o app estiver EM REVISAO/nao auditado, o Direct
        # Post so funciona para contas privadas e retorna o erro
        # "unaudited_client_can_only_post_to_private_accounts". Por isso o
        # padrao e o modo rascunho (que funciona no sandbox). So ligue o Direct
        # Post depois que o app for APROVADO, definindo TIKTOK_DIRECT_POST=true
        # no .env.
        scopes = (os.getenv("TIKTOK_SCOPES") or "user.info.basic,video.upload").lower()
        direct_enabled = (os.getenv("TIKTOK_DIRECT_POST") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        direct_post = direct_enabled and "video.publish" in scopes

        try:
            if direct_post:
                init_url = f"{API_BASE}/post/publish/video/init/"
                init_body = {
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
                        "chunk_size": chunk_size,
                        "total_chunk_count": total_chunk_count,
                    },
                }
            else:
                # Upload para a "caixa de entrada" do criador (rascunho).
                init_url = f"{API_BASE}/post/publish/inbox/video/init/"
                init_body = {
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": video_size,
                        "chunk_size": chunk_size,
                        "total_chunk_count": total_chunk_count,
                    },
                }

            # 3) Inicia a publicacao/upload com envio direto (FILE_UPLOAD).
            init = requests.post(
                init_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json=init_body,
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

            # 4) Envia os bytes do video para o upload_url (PUT), pedaco a pedaco.
            for index in range(total_chunk_count):
                start = index * chunk_size
                if index == total_chunk_count - 1:
                    # O ultimo pedaco leva todo o resto do arquivo.
                    end = video_size - 1
                else:
                    end = start + chunk_size - 1
                chunk_bytes = video_bytes[start : end + 1]

                put = requests.put(
                    upload_url,
                    data=chunk_bytes,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(chunk_bytes)),
                        "Content-Range": f"bytes {start}-{end}/{video_size}",
                    },
                    timeout=600,
                )
                if put.status_code >= 400:
                    return PublishResult(
                        status="failed",
                        error=(
                            f"Falha ao enviar o video para o TikTok "
                            f"(pedaco {index + 1}/{total_chunk_count}, "
                            f"HTTP {put.status_code}): {put.text[:300]}"
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
                    "direct_post": direct_post,
                    "note": (
                        "Postado direto no perfil."
                        if direct_post
                        else "Enviado como rascunho para o TikTok. "
                        "Abra o app do TikTok (Caixa de entrada > Rascunhos) "
                        "para finalizar a publicacao."
                    ),
                },
            )

        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=f"Erro na publicacao do TikTok: {exc}",
                detail={"platform": self.platform, "market": market},
            )
