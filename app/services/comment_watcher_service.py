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
# IMPORTANTE (24/jul/2026): a resposta NAO e mais um comentario publico.
# Instagram/Facebook NAO transformam links em texto clicavel dentro de
# comentarios publicos -- so em mensagens diretas (DM). Por isso usamos a
# API de "resposta privada" (private reply) da Meta: POST /{ig_id ou
# page_id}/messages com recipient={"comment_id": ...}. Isso manda uma
# mensagem direta para quem comentou (sem precisar seguir a pagina nem ter
# conversa anterior), com o link clicavel de verdade. Requer que o
# comentario tenha no maximo ~7 dias (janela de resposta privada da Meta) e
# as permissoes instagram_manage_messages / pages_messaging no token.
#
# Cada comentario respondido fica registrado em AnsweredComment para
# NUNCA responder duas vezes o mesmo comentario entre um ciclo e outro.
# ============================================================

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.models.dashboard import AnsweredComment, Publication, PublicationStatusEnum
from app.publishing.base import (
    MetaGraphTransientError,
    get_page_access_token,
    is_meta_app_limit,
    meta_app_cooldown_remaining,
    resolve_meta_targets,
    trip_meta_app_cooldown,
)
from app.services.shortlink_service import ShortLinkService

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# So verifica publicacoes publicadas nos ultimos N dias (evita varrer
# posts antigos pra sempre). Configuravel via .env.
WATCH_WINDOW_DAYS = int(os.getenv("COMMENT_WATCH_WINDOW_DAYS", "30"))

REPLY_TEMPLATE_PT = "Aqui esta o link do produto \U0001F449 {url}"
REPLY_TEMPLATE_EN = "Here's the product link \U0001F449 {url}"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", ""}


def _is_public_url(url: str) -> bool:
    """True se o host do link NAO for localhost/loopback -- usado para
    garantir que nunca mandamos um link inacessivel de fora para
    comentarios de usuarios reais."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host not in _LOCAL_HOSTS


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

        # O robo de comentarios tambem consome a cota do app da Meta ((#4)).
        # Se ela ja estourou (cooldown aberto por publicacao/metricas), NAO
        # batemos no Graph nesta rodada -- deixamos a cota se recuperar.
        if meta_app_cooldown_remaining() > 0:
            errors.append(
                "meta: cooldown do (#4) ativo (~"
                f"{int(meta_app_cooldown_remaining())}s) - pulei os comentarios "
                "nesta rodada."
            )
            return {
                "publications_checked": 0,
                "replies_sent": 0,
                "errors": errors,
            }

        for pub in publications:
            try:
                replied += self._watch_publication(pub)
                checked += 1
            except MetaGraphTransientError:
                # (#4) do app inteiro: abre o cooldown e PARA a rodada, para
                # nao esgotar ainda mais a cota varrendo o resto dos posts.
                trip_meta_app_cooldown()
                errors.append(
                    "meta: (#4) detectado -> abri cooldown e parei os "
                    "comentarios nesta rodada (retoma sozinho na proxima)."
                )
                break
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
        page_id, ig_id, _role, _market = resolve_meta_targets(
            kind, video.country_code or "", video.language or ""
        )
        if not page_id:
            return 0
        if pub.platform == "instagram" and not ig_id:
            return 0

        # Se der MetaGraphTransientError (rate limit do app (#4)), deixamos
        # propagar para run() abrir o cooldown e parar a rodada -- assim a cota
        # se recupera em vez de continuar apanhando.
        token = get_page_access_token(page_id)

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
                    self._send_instagram_private_reply(ig_id, comment_id, reply_text, token)
                else:
                    self._send_facebook_private_reply(page_id, comment_id, reply_text, token)
                sent += 1
            except MetaGraphTransientError:
                # (#4) do app: propaga para run() abrir o cooldown e parar tudo.
                raise
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
        # SEMPRE preferimos o link de afiliado bruto (dominio publico da
        # Amazon) -- ele nunca depende deste painel estar acessivel de fora.
        # So usamos o link curto interno (/go/codigo) como alternativa, e
        # apenas quando ATLAS_PUBLIC_BASE_URL for mesmo um endereco publico
        # (ex.: tunel Cloudflare ativo). Isso evita mandar para comentarios
        # reais um link tipo "http://localhost:8000/go/xxxx", que so funciona
        # na propria maquina e quebra a experiencia do usuario.
        affiliate_url = (video.affiliate_url or "").strip()
        if affiliate_url:
            return affiliate_url

        if video.short_code:
            short_url = ShortLinkService(self.db).build_public_url(video.short_code)
            if _is_public_url(short_url):
                return short_url

        return ""

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
            if is_meta_app_limit(resp.get("error")):
                raise MetaGraphTransientError(str(resp.get("error")))
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
            if is_meta_app_limit(resp.get("error")):
                raise MetaGraphTransientError(str(resp.get("error")))
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
    # RESPOSTA (mensagem privada/DM para quem comentou -- link fica clicavel;
    # NAO responde publicamente no comentario)
    # ----------------------------------------------------------------

    def _send_instagram_private_reply(
        self, ig_id: str, comment_id: str, message: str, token: str
    ) -> None:
        resp = requests.post(
            f"{GRAPH_BASE}/{ig_id}/messages",
            json={
                "recipient": {"comment_id": comment_id},
                "message": {"text": message},
            },
            params={"access_token": token},
            timeout=30,
        ).json()
        if "error" in resp:
            if is_meta_app_limit(resp.get("error")):
                raise MetaGraphTransientError(str(resp.get("error")))
            raise RuntimeError(f"Erro Graph API (IG DM privada): {resp['error']}")

    def _send_facebook_private_reply(
        self, page_id: str, comment_id: str, message: str, token: str
    ) -> None:
        resp = requests.post(
            f"{GRAPH_BASE}/{page_id}/messages",
            json={
                "recipient": {"comment_id": comment_id},
                "message": {"text": message},
            },
            params={"access_token": token},
            timeout=30,
        ).json()
        if "error" in resp:
            if is_meta_app_limit(resp.get("error")):
                raise MetaGraphTransientError(str(resp.get("error")))
            raise RuntimeError(f"Erro Graph API (FB DM privada): {resp['error']}")
