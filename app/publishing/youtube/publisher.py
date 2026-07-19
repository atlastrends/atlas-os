# ATLAS OS - Conector YouTube (YouTube Data API v3 - videos.insert)
from __future__ import annotations

import os

from app.publishing.base import (
    BasePublisher,
    PublishRequest,
    PublishResult,
    resolve_youtube_channel,
)

TOKEN_URI = "https://oauth2.googleapis.com/token"
UPLOAD_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _privacy_status() -> str:
    """Privacidade do video ao subir. Padrao PUBLICO para o video ja aparecer
    para todos (e o link da descricao poder ser clicavel). Pode trocar por
    "unlisted" ou "private" via env YOUTUBE_PRIVACY_STATUS. Lido no momento do
    upload para respeitar o .env carregado depois do import."""
    value = (os.getenv("YOUTUBE_PRIVACY_STATUS") or "public").strip().lower()
    if value not in ("public", "unlisted", "private"):
        value = "public"
    return value


def _category_id() -> str:
    # Categoria 22 = "People & Blogs" (categoria generica e sempre valida).
    return (os.getenv("YOUTUBE_CATEGORY_ID") or "22").strip()


def _language_code(country_code: str | None, language: str | None) -> str:
    """Idioma do video para os campos defaultLanguage/defaultAudioLanguage."""
    market = (country_code or "").strip().upper()
    lang = (language or "").strip().lower()
    if market == "US" or lang.startswith("en"):
        return "en-US"
    return "pt-BR"


def _project_root() -> str:
    return os.path.abspath(os.getenv("ATLAS_ROOT", os.getcwd()))


def _resolve_video_path(video_path: str) -> str:
    if not video_path:
        return ""
    if os.path.isabs(video_path):
        return video_path
    return os.path.abspath(os.path.join(_project_root(), video_path))


class YouTubePublisher(BasePublisher):
    platform = "youtube"
    required_env = (
        "YOUTUBE_CLIENT_ID",
        "YOUTUBE_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
    )

    def _do_publish(self, request: PublishRequest) -> PublishResult:
        abs_path = _resolve_video_path(request.video_path)
        if not abs_path or not os.path.isfile(abs_path):
            return PublishResult(
                status="failed",
                error=f"Arquivo de video nao encontrado: {request.video_path}",
                detail={"platform": self.platform},
            )

        try:
            from google.auth.transport.requests import Request as GoogleRequest
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=(
                    "Dependencias do Google ausentes. Instale "
                    "google-api-python-client google-auth google-auth-oauthlib. "
                    f"({exc})"
                ),
                detail={"platform": self.platform},
            )

        # Seleciona o canal correto pelo mercado (BR/US) do video.
        # Afiliados e trends do mesmo pais vao para o MESMO canal.
        # Cada canal exige o seu proprio login (refresh token).
        refresh_token, client_id, client_secret, market, channel_id = resolve_youtube_channel(
            request.country_code,
            request.language,
            request.kind,
        )
        if not refresh_token:
            hint = (
                f"Nao ha login do YouTube para o canal {market}. "
                f"Autorize o canal {market} e defina YOUTUBE_REFRESH_TOKEN_{market} "
                "no .env (assim o video vai para o canal certo)."
            )
            return PublishResult(
                status="credentials_missing",
                error=hint,
                detail={"platform": self.platform, "market": market},
            )

        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri=TOKEN_URI,
            scopes=UPLOAD_SCOPES,
        )

        try:
            credentials.refresh(GoogleRequest())
        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=f"Falha ao renovar o token do YouTube: {exc}",
                detail={"platform": self.platform},
            )

        title = (request.title or "Atlas OS").strip()[:100]
        # A descricao ja vem com o link clicavel do afiliado injetado.
        description = (request.description or request.caption or "").strip()[:4900]
        tags = [str(t).lstrip("#") for t in (request.hashtags or []) if str(t).strip()][:15]

        privacy = _privacy_status()
        language = _language_code(request.country_code, request.language)

        body = {
            "snippet": {
                "title": title or "Atlas OS",
                "description": description,
                "tags": tags,
                "categoryId": _category_id(),
                "defaultLanguage": language,
                "defaultAudioLanguage": language,
            },
            "status": {
                # PUBLICO: o video ja fica visivel para todos e o link da
                # descricao pode ser clicavel (nao fica preso em "privado").
                "privacyStatus": privacy,
                # NAO e conteudo para criancas (se fosse, o YouTube desligaria
                # os links clicaveis, cards e comentarios).
                "selfDeclaredMadeForKids": False,
                # Permite embutir o video e mostrar as estatisticas publicas.
                "embeddable": True,
                "publicStatsViewable": True,
                "license": "youtube",
            },
        }

        try:
            youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
            media = MediaFileUpload(abs_path, chunksize=-1, resumable=True, mimetype="video/*")
            insert_request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                _status, response = insert_request.next_chunk()

        except HttpError as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=f"Erro da API do YouTube: {exc}",
                detail={"platform": self.platform},
            )
        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=f"Falha no upload para o YouTube: {exc}",
                detail={"platform": self.platform},
            )

        video_id = response.get("id") if isinstance(response, dict) else None
        if not video_id:
            return PublishResult(
                status="failed",
                error="Upload concluido, mas o YouTube nao retornou o ID do video.",
                detail={"platform": self.platform, "response": response},
            )

        return PublishResult(
            status="published",
            external_id=video_id,
            external_url=f"https://www.youtube.com/watch?v={video_id}",
            detail={"platform": self.platform, "privacy": privacy},
        )
