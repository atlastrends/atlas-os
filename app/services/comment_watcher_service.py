# ============================================================
# ATLAS OS - comment_watcher_service.py
# Robo de resposta automatica por COMENTARIO, via POLLING (sem depender
# de webhook em tempo real da Meta).
#
# CONTEXTO: o webhook em tempo real so entrega comentarios de usuarios
# reais se o app da Meta estiver PUBLICADO, o que exige Verificacao de
# Empresa (CNPJ/MEI) -- pausado por decisao do usuario (ver
# /memories/repo/atlas-dm-bot.md). Como alternativa, este servico busca
# periodicamente (Graph API) os comentarios de cada post/reel JA
# publicado no Instagram/Facebook e responde automaticamente com o link
# do produto daquele post. Isso funciona mesmo com o app "Em
# desenvolvimento", pois le dados das PROPRIAS paginas/contas
# administradas pelo token (nao depende de push de eventos de terceiros).
#
# Cada comentario respondido fica registrado em AnsweredComment para
# NUNCA responder duas vezes o mesmo comentario entre um ciclo e outro.
# ============================================================

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.orm import Session

from app.models.dashboard import AnsweredComment, Publication, PublicationStatusEnum
from app.publishing.base import (
    MetaGraphTransientError,
    get_page_access_token,
    resolve_meta_targets,
)
from app.services.shortlink_service import ShortLinkService

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# So verifica publicacoes publicadas nos ultimos N dias (evita varrer
# posts antigos pra sempre). Configuravel via .env.
WATCH_WINDOW_DAYS = int(os.getenv("COMMENT_WATCH_WINDOW_DAYS", "30"))

REPLY_TEMPLATE_PT = "Aqui esta o link do produto \U0001F449 {url}"
REPLY_TEMPLATE_EN = "Here's the product link \U0001F449 {url}"


class CommentWatcherService:
    def __init__(self, db: Session):
        self.db = db

    def run(self) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(days=WATCH_WINDOW_DAYS)
        publications = (
            self.db.query(Publication)
            .filter(
                Publication.platform.in_(("instagram", "facebook")),
                Publication.status == PublicationStatusEnum.PUBLISHED,
                Publication.external_id.isnot(None),
                Publication.published_at.isnot(None),
                Publication.published_at >= cutoff,
            )
            .all()
        )

        checked = 0
        replied = 0
        errors: list[str] = []

        for pub in publications:
            try:
                replied += self._watch_publication(pub)
                checked += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{pub.platform}:{pub.external_id} -> {exc}")

        self.db.commit()

        return {
            "publications_checked": checked,
            "replies_sent": replied,
            "errors": errors,
        }

    # ----------------------------------------------------------------
    def _watch_publication(self, pub: Publication) -> int:
        video = pub.video
        if video is None:
            return 0

        kind = video.kind.value if hasattr(video.kind, "value") else video.kind
        page_id, _ig_id, _role, _market = resolve_meta_targets(
            kind, video.country_code or "", video.language or ""
        )
        if not page_id:
            return 0

        try:
            token = get_page_access_token(page_id)
        except MetaGraphTransientError:
            # Rate limit temporario do Graph API -- tenta de novo no proximo ciclo.
            return 0

        if pub.platform == "instagram":
            comments = self._fetch_instagram_comments(pub.external_id, token)
        else:
            comments = self._fetch_facebook_comments(pub.external_id, token)

        if not comments:
            return 0

        link = self._product_link(video)
        if not link:
            return 0

        language = (video.language or "").lower()
        template = REPLY_TEMPLATE_EN if language.startswith("en") else REPLY_TEMPLATE_PT
        reply_text = template.format(url=link)

        sent = 0
        for comment in comments:
            comment_id = comment.get("id")
            if not comment_id:
                continue

            already = (
                self.db.query(AnsweredComment)
                .filter(
                    AnsweredComment.platform == pub.platform,
                    AnsweredComment.external_comment_id == comment_id,
                )
                .first()
            )
            if already:
                continue

            status = "sent"
            error = None
            try:
                if pub.platform == "instagram":
                    self._reply_instagram(comment_id, reply_text, token)
                else:
                    self._reply_facebook(comment_id, reply_text, token)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                error = str(exc)

            self.db.add(
                AnsweredComment(
                    publication_id=pub.id,
                    platform=pub.platform,
                    external_comment_id=comment_id,
                    commenter=comment.get("commenter"),
                    comment_text=comment.get("text"),
                    reply_status=status,
                    reply_error=error,
                )
            )
            # Salva a cada comentario (evita reprocessar se algo falhar no meio).
            self.db.flush()

        return sent

    # ----------------------------------------------------------------
    def _product_link(self, video) -> str:
        if video.short_code:
            return ShortLinkService(self.db).build_public_url(video.short_code)
        return (video.affiliate_url or "").strip()

    # ----------------------------------------------------------------
    # LEITURA DE COMENTARIOS
    # ----------------------------------------------------------------

    def _fetch_instagram_comments(self, media_id: str, token: str) -> list[dict]:
        resp = requests.get(
            f"{GRAPH_BASE}/{media_id}/comments",
            params={"fields": "id,text,username,timestamp", "access_token": token},
            timeout=30,
        ).json()
        if "error" in resp:
            raise RuntimeError(f"Erro Graph API (IG comments): {resp['error']}")
        return [
            {
                "id": item.get("id"),
                "text": item.get("text"),
                "commenter": item.get("username"),
            }
            for item in resp.get("data", [])
        ]

    def _fetch_facebook_comments(self, post_id: str, token: str) -> list[dict]:
        resp = requests.get(
            f"{GRAPH_BASE}/{post_id}/comments",
            params={"fields": "id,message,from{name,id}", "access_token": token},
            timeout=30,
        ).json()
        if "error" in resp:
            raise RuntimeError(f"Erro Graph API (FB comments): {resp['error']}")
        return [
            {
                "id": item.get("id"),
                "text": item.get("message"),
                "commenter": (item.get("from") or {}).get("name"),
            }
            for item in resp.get("data", [])
        ]

    # ----------------------------------------------------------------
    # RESPOSTA (reply publica no proprio comentario)
    # ----------------------------------------------------------------

    def _reply_instagram(self, comment_id: str, message: str, token: str) -> None:
        resp = requests.post(
            f"{GRAPH_BASE}/{comment_id}/replies",
            data={"message": message, "access_token": token},
            timeout=30,
        ).json()
        if "error" in resp:
            raise RuntimeError(f"Erro Graph API (IG reply): {resp['error']}")

    def _reply_facebook(self, comment_id: str, message: str, token: str) -> None:
        resp = requests.post(
            f"{GRAPH_BASE}/{comment_id}/comments",
            data={"message": message, "access_token": token},
            timeout=30,
        ).json()
        if "error" in resp:
            raise RuntimeError(f"Erro Graph API (FB reply): {resp['error']}")
