# ============================================================
# ATLAS OS - publishing_service.py
# Orquestra a publicacao de um VideoAsset aprovado nas plataformas.
#
# Fluxo:
#   approve(asset) -> cria/atualiza Publication (queued) por plataforma
#                  -> dispara cada conector (publisher)
#                  -> grava resultado (published / failed / credentials_missing)
#
# Para videos de afiliado, a legenda recebe o LINK CLICAVEL do produto,
# para que o espectador no celular consiga clicar e ir direto ao produto.
# ============================================================

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.dashboard import (
    Publication,
    PublicationStatusEnum,
    VideoAsset,
    VideoKindEnum,
    VideoStatusEnum,
)
from app.publishing.base import PublishRequest, project_root, resolve_video_path
from app.publishing.registry import PLATFORMS, get_publisher
from app.services.shortlink_service import ShortLinkService


def _now():
    return datetime.now(timezone.utc)


def _env_bool(name: str, default: bool = False) -> bool:
    """Le uma flag booleana do ambiente (aceita 1/true/yes/on/sim)."""
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "sim"}


def _env_int(name: str, default: int) -> int:
    """Le um inteiro do ambiente; volta ao default se ausente/invalido."""
    try:
        return int((os.getenv(name) or "").strip() or default)
    except (TypeError, ValueError):
        return default


# Trechos que indicam BLOQUEIO TEMPORARIO da plataforma (limite diario/cota),
# NAO um erro real. Nesses casos o video deve aguardar reenvio, e nao virar
# "erro". So retentar amanha resolve.
_RATE_LIMIT_HINTS = (
    "uploadlimitexceeded",
    "exceeded the number of videos",
    "quotaexceeded",
    "ratelimitexceeded",
    "rate limit",
    "user rate limit",
    "too many requests",
    "please retry",
    "try again later",
    "temporarily blocked",
    "daily limit",
    "limit exceeded",
    "429",
    # Especificos do Graph API (Meta / Facebook / Instagram): rate limit do
    # APP inteiro (nao do usuario), costuma se resolver sozinho apos alguns
    # minutos - ver bloqueio temporario em get_page_access_token().
    "application request limit",
    "request limit reached",
    "(#4)",
    "bloqueio temporario do graph api",
    # TikTok: quando acumulam rascunhos pendentes demais na caixa de entrada
    # do criador, o TikTok bloqueia novos envios (spam_risk). E temporario:
    # basta o usuario postar/apagar os rascunhos no app (ou esperar) e o
    # reenvio automatico volta a funcionar - nao e erro permanente.
    "spam_risk",
    "too_many_pending",
    "pending_share",
    "rascunhos demais pendentes",
)


def _is_rate_limited(error_text: str | None) -> bool:
    """True se o erro for um bloqueio TEMPORARIO da plataforma (limite/cota),
    que tende a resolver reenviando mais tarde (ex.: no dia seguinte)."""
    if not error_text:
        return False
    text = str(error_text).lower()
    return any(hint in text for hint in _RATE_LIMIT_HINTS)


# Trechos que indicam que a CONTA precisa de acao do usuario para voltar a
# publicar (reconectar/renovar token, permissao na pagina ou auditoria do app).
# Reenviar automatico NAO resolve: sai da fila de reenvio e vira "credenciais/
# permissao pendentes" ate o usuario reconectar a conta - assim para de reportar
# "falha ao reenviar" para sempre.
_NEEDS_RECONNECT_HINTS = (
    "invalid_grant",
    "expired or revoked",
    "token has been expired",
    "token has been revoked",
    "unauthorized_client",
    "unaudited_client",
    "does not have permission to post",
    "subject does not have permission",
    "(#200)",
    "(#10)",
    "(#803)",
)


def _needs_reconnect(error_text: str | None) -> bool:
    """True se a falha for de CONTA/permissao (token revogado/expirado, app nao
    auditado, sem permissao na pagina). Reenviar nao resolve; precisa de acao do
    usuario. Tratamos como 'credenciais pendentes' para SAIR da fila de reenvio
    e nao virar falha eterna."""
    if not error_text:
        return False
    text = str(error_text).lower()
    return any(hint in text for hint in _NEEDS_RECONNECT_HINTS)


# ----------------------------------------------------------------------------
# CIRCUIT BREAKER do limite do APP da Meta ((#4) Application request limit).
# O (#4) e um limite do APP INTEIRO (todas as chamadas IG+FB somadas), NAO do
# usuario, e some sozinho apos alguns minutos. Publicar um Reels gasta VARIAS
# chamadas (cria container + varias checagens de processamento + publica), entao
# um lote estoura a cota rapido. Quando isso acontece, PARAMOS de chamar o Graph
# por uma janela (cooldown) para a cota se recuperar, em vez de martelar e manter
# o bloqueio para sempre. O estado fica num arquivo (cross-processo: servidor +
# scripts). Complementa o guarda de 120s do /me/accounts (base.py), que so cobre
# a resolucao do token da Pagina, nao as checagens do Reels (onde o (#4) aparece).
# ----------------------------------------------------------------------------
_META_PLATFORMS = {"instagram", "facebook"}

_META_APP_LIMIT_HINTS = (
    "application request limit",
    "request limit reached",
    "(#4)",
)


def _is_meta_app_limit(error_text: str | None) -> bool:
    """True se o erro for o rate-limit do APP da Meta (#4) (temporario)."""
    if not error_text:
        return False
    text = str(error_text).lower()
    return any(h in text for h in _META_APP_LIMIT_HINTS)


def _meta_cooldown_file() -> str:
    return os.path.join(project_root(), "storage", "state", "meta_app_cooldown")


def _meta_cooldown_remaining() -> float:
    """Segundos restantes do cooldown do app da Meta (0.0 se nao ha)."""
    try:
        with open(_meta_cooldown_file(), "r", encoding="utf-8") as fh:
            expiry = float((fh.read() or "0").strip() or "0")
    except (OSError, ValueError):
        return 0.0
    remaining = expiry - time.time()
    return remaining if remaining > 0 else 0.0


def _meta_trip_cooldown() -> None:
    """Abre a janela de cooldown apos um (#4). Duracao em
    ATLAS_META_COOLDOWN_MINUTES (padrao 20 min)."""
    try:
        minutes = int(os.getenv("ATLAS_META_COOLDOWN_MINUTES", "20") or "20")
    except ValueError:
        minutes = 20
    minutes = max(1, minutes)
    path = _meta_cooldown_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(time.time() + minutes * 60))
    except OSError:
        pass


class PublishingService:
    def __init__(self, db: Session):
        self.db = db
        self.shortlinks = ShortLinkService(db)

    # ----------------------------------------------------------------
    # APROVACAO / REJEICAO
    # ----------------------------------------------------------------

    def reject(self, asset: VideoAsset, notes: str | None = None) -> VideoAsset:
        asset.status = VideoStatusEnum.REJECTED
        asset.review_notes = notes
        asset.reviewed_at = _now()
        self.db.commit()
        self.db.refresh(asset)
        return asset

    # ----------------------------------------------------------------
    # GUARD ANTI-DIREITOS AUTORAIS (so REEL/trend; afiliado nao e afetado)
    # ----------------------------------------------------------------

    # Fontes de midia consideradas SEGURAS (sem risco de Content ID).
    _SAFE_ASSET_SOURCES = {
        "stock_pexels",
        "stock_pixabay",
        "stock",
        "procedural_gradient",
        "generated",
    }

    def _copyright_hold_reason(self, asset: VideoAsset) -> str | None:
        """Retorna o MOTIVO para reter o video antes de publicar, ou None se
        estiver liberado.

        Regra (so vale para REEL/trend; afiliado nao e afetado):
          - Se ATLAS_BLOCK_RISKY_REELS estiver desligado -> nunca retem.
          - Retem quando a midia de fundo tem origem NAO licenciada:
              * risco 'high'/'medium' (ex.: b-roll do YouTube), OU
              * fonte fora da lista segura / desconhecida (reels antigos que
                usavam b-roll do YouTube nao tem proveniencia e sao tratados
                como risco, por seguranca).
        """
        if not _env_bool("ATLAS_BLOCK_RISKY_REELS", True):
            return None

        kind = asset.kind
        kind_value = kind.value if hasattr(kind, "value") else str(kind)
        if kind_value != VideoKindEnum.REEL.value:
            return None

        payload = asset.payload if isinstance(asset.payload, dict) else {}
        copyright_info = payload.get("copyright") if isinstance(payload.get("copyright"), dict) else {}

        asset_source = (
            copyright_info.get("asset_source")
            or payload.get("asset_source")
            or ""
        )
        asset_source = str(asset_source).strip().lower()
        risk = str(copyright_info.get("risk", "")).strip().lower()

        # O usuario autorizou EXPLICITAMENTE publicar footage do YouTube (video
        # real do assunto, mais visto e validado por imagens + narracao),
        # assumindo o risco de Content ID. Nesse caso, NAO retem.
        if asset_source in {"youtube_search", "youtube"} and _env_bool(
            "ATLAS_ALLOW_YOUTUBE_REEL_PUBLISH", False
        ):
            return None

        if risk in {"high", "medium"}:
            return (
                "Retido por direitos autorais: midia de fundo de origem nao "
                f"licenciada (risco '{risk}', fonte '{asset_source or 'desconhecida'}'). "
                "Gere novamente com banco livre (Pexels/Pixabay) ou fundo original."
            )

        if asset_source not in self._SAFE_ASSET_SOURCES:
            return (
                "Retido por direitos autorais: origem da midia de fundo "
                f"desconhecida/nao verificada ('{asset_source or 'sem proveniencia'}'). "
                "Reels antigos usavam b-roll do YouTube (risco de Content ID). "
                "Regere o video com o pipeline seguro antes de publicar."
            )

        return None

    def hold_risky_reels(self, *, kind: str | None = None) -> dict:
        """Analisa os videos de TREND (reel) na fila e RETEM (marca REJECTED) os
        que teriam b-roll de origem nao licenciada (YouTube) ou proveniencia
        desconhecida, ANTES de publicar. Evita reivindicacao de Content ID
        (ex.: trailer de estudio). Nao mexe em afiliados nem no que ja subiu."""
        if not _env_bool("ATLAS_BLOCK_RISKY_REELS", True):
            return {"held": 0, "reasons": []}
        if kind and kind != VideoKindEnum.REEL.value:
            return {"held": 0, "reasons": []}

        query = self.db.query(VideoAsset).filter(
            VideoAsset.kind == VideoKindEnum.REEL,
            VideoAsset.status.in_(
                [
                    VideoStatusEnum.CREATED,
                    VideoStatusEnum.APPROVED,
                    VideoStatusEnum.RETRY_PENDING,
                ]
            ),
        )
        held = 0
        reasons = []
        for asset in query.all():
            reason = self._copyright_hold_reason(asset)
            if not reason:
                continue
            asset.status = VideoStatusEnum.REJECTED
            asset.review_notes = reason
            asset.reviewed_at = _now()
            held += 1
            reasons.append({"asset_id": asset.id, "reason": reason})
        if held:
            self.db.commit()
        return {"held": held, "reasons": reasons}

    def _awaiting_retry_query(self, kind: str | None = None):
        """Query dos assets a reenviar: os marcados como RETRY_PENDING E TAMBEM
        qualquer asset com ALGUMA publicacao em RATE_LIMITED (bloqueio temporario
        da plataforma), mesmo que outra plataforma ja tenha publicado. Assim o
        botao "Reenviar pendentes" tambem completa as plataformas que faltaram
        num video que ja subiu em outra rede (ex.: YouTube publicou, mas o
        Instagram/TikTok ficaram bloqueados). Na publicacao PARCIAL o asset fica
        em RETRY_PENDING (aguardando reenvio) ate TODAS as plataformas alvo
        completarem; as ja publicadas nunca sao reenviadas (nao duplica)."""
        rate_limited_asset_ids = (
            self.db.query(Publication.video_asset_id)
            .filter(Publication.status == PublicationStatusEnum.RATE_LIMITED)
            .distinct()
        )
        query = self.db.query(VideoAsset).filter(
            or_(
                VideoAsset.status == VideoStatusEnum.RETRY_PENDING,
                VideoAsset.id.in_(rate_limited_asset_ids),
            )
        )
        if kind:
            try:
                query = query.filter(VideoAsset.kind == VideoKindEnum(kind))
            except ValueError:
                pass
        return query

    def retry_pending(self, *, kind: str | None = None) -> dict:
        """Reenvia os videos que ficaram AGUARDANDO REENVIO (bloqueio temporario
        da plataforma). Tenta publicar de novo apenas nas plataformas que ainda
        nao subiram; as que ja publicaram sao preservadas (nao duplica)."""
        # Antes de reenviar, HIGIENIZA a fila para nao travar:
        #  1) destrava envios presos em andamento (processo que caiu no meio);
        #  2) marca como SKIPPED os videos cujo arquivo foi purgado (nunca vao
        #     subir). Isso e feito na fila INTEIRA (sem filtrar por kind), pois
        #     arquivo purgado e terminal em qualquer tipo - era o que entupia a
        #     fila e fazia o reenvio reportar 'falha' sem parar.
        self.reset_stale_inprogress()
        self.skip_purged_pending()
        # Retem (antes de enviar) os reels de trend cuja midia de fundo tem
        # origem nao licenciada / desconhecida -> evita claim de Content ID.
        self.hold_risky_reels(kind=kind)
        assets = self._awaiting_retry_query(kind).all()
        retried = 0
        published = 0
        still_pending = 0
        results = []
        for asset in assets:
            outcome = self.approve_and_publish(asset, notes=asset.review_notes)
            retried += 1
            status = outcome.get("status")
            if status == VideoStatusEnum.PUBLISHED.value:
                published += 1
            elif status == VideoStatusEnum.RETRY_PENDING.value:
                still_pending += 1
            results.append({"asset_id": asset.id, "status": status})

        return {
            "retried": retried,
            "published": published,
            "still_pending": still_pending,
            "results": results,
        }

    def count_pending(self, *, kind: str | None = None) -> int:
        """Quantos videos estao aguardando reenvio (inclui os que ja publicaram
        em alguma rede mas ainda tem uma plataforma bloqueada)."""
        return self._awaiting_retry_query(kind).count()

    def run_scheduled_batch(
        self,
        *,
        limit: int = 4,
        spacing_seconds: int = 30,
        include_new: bool = True,
        kinds: list[str] | None = None,
    ) -> dict:
        """Publica um LOTE PEQUENO e ESPACADO de videos, para o reenvio
        automatico (agendado de hora em hora) NAO estourar o limite da Meta
        ((#4) application request limit) nem o spam_risk do TikTok.

        Ordem de prioridade:
          1) RETRY_PENDING / RATE_LIMITED  -> reenvio: completa so as plataformas
             que faltaram (as ja publicadas nunca sao reenviadas, nao duplica);
          2) CREATED (novos ainda nao publicados) -> so quando include_new=True.

        'limit' = quantos videos por execucao (rajada controlada). 'spacing_seconds'
        = pausa entre um video e o proximo (espaca as chamadas ao Graph API). A
        guarda anti-direitos autorais continua valendo (segura reels de origem
        nao segura). Arquivos purgados sao removidos da fila antes de tentar.
        """
        import time

        # Higieniza a fila antes: destrava presos + remove purgados terminais.
        self.reset_stale_inprogress()
        self.skip_purged_pending()
        self.hold_risky_reels()

        limit = max(1, limit)

        # Query dos NOVOS (CREATED) a publicar (respeitando 'kinds', se dado).
        created_q = self.db.query(VideoAsset).filter(
            VideoAsset.status == VideoStatusEnum.CREATED
        )
        if kinds:
            wanted = []
            for k in kinds:
                try:
                    wanted.append(VideoKindEnum(k))
                except ValueError:
                    pass
            if wanted:
                created_q = created_q.filter(VideoAsset.kind.in_(wanted))
        created_q = created_q.order_by(VideoAsset.id.asc())

        # RESERVA DE VAGAS PARA NOVOS: a fila de reenvio pode ficar presa por
        # tempo indeterminado em plataformas bloqueadas (TikTok spam_risk, Meta
        # (#4)). Sem reservar vagas, esses reenvios presos ocupam TODO o lote
        # toda hora e os NOVOS nunca sobem (starvation). Reservamos metade do
        # lote (min 1) para novos sempre que houver novos esperando. Ajustavel
        # por ATLAS_AUTO_RETRY_MIN_NEW.
        new_waiting = created_q.count() if include_new else 0
        reserved_new = 0
        if include_new and new_waiting > 0:
            default_reserved = max(1, limit // 2)
            reserved_new = _env_int("ATLAS_AUTO_RETRY_MIN_NEW", default_reserved)
            reserved_new = max(1, min(reserved_new, limit))
        retry_slots = max(0, limit - reserved_new)

        retry_list = self._awaiting_retry_query().all()
        batch: list[VideoAsset] = []
        seen: set[int] = set()

        # 1) Reenvio: ocupa ATE retry_slots (deixa as vagas reservadas p/ novos).
        if retry_slots > 0:
            for asset in retry_list:
                if asset.id not in seen:
                    seen.add(asset.id)
                    batch.append(asset)
                if len(batch) >= retry_slots:
                    break

        # 2) Novos (CREATED): preenchem o restante do lote (inclui a reserva).
        if include_new and len(batch) < limit:
            for asset in created_q.all():
                if asset.id not in seen:
                    seen.add(asset.id)
                    batch.append(asset)
                if len(batch) >= limit:
                    break

        # 3) Sobrou espaco (poucos novos)? Completa com mais reenvios, para nao
        #    desperdicar vagas do lote.
        if len(batch) < limit:
            for asset in retry_list:
                if asset.id not in seen:
                    seen.add(asset.id)
                    batch.append(asset)
                if len(batch) >= limit:
                    break

        published = 0
        still_pending = 0
        results = []
        for i, asset in enumerate(batch):
            # Espaca as publicacoes: pausa ANTES de cada uma (menos a primeira)
            # para nao disparar varias chamadas ao Graph API em rajada.
            if i > 0 and spacing_seconds > 0:
                time.sleep(spacing_seconds)
            outcome = self.approve_and_publish(asset, notes=asset.review_notes)
            status = outcome.get("status")
            if status == VideoStatusEnum.PUBLISHED.value:
                published += 1
            elif status == VideoStatusEnum.RETRY_PENDING.value:
                still_pending += 1
            results.append({"asset_id": asset.id, "status": status})

        remaining_created = (
            self.db.query(VideoAsset)
            .filter(VideoAsset.status == VideoStatusEnum.CREATED)
            .count()
        )
        return {
            "batch": len(batch),
            "published": published,
            "still_pending": still_pending,
            "remaining_retry": self.count_pending(),
            "remaining_created": remaining_created,
            "results": results,
        }

    def approve_and_publish(
        self,
        asset: VideoAsset,
        *,
        platforms: list[str] | None = None,
        notes: str | None = None,
    ) -> dict:
        """Aprova e tenta publicar nas plataformas alvo."""
        # Guard anti-direitos autorais: nao publica reel com midia de origem
        # nao licenciada/desconhecida (ex.: b-roll do YouTube = Content ID).
        hold_reason = self._copyright_hold_reason(asset)
        if hold_reason:
            asset.status = VideoStatusEnum.REJECTED
            asset.review_notes = hold_reason
            asset.reviewed_at = _now()
            self.db.commit()
            return {
                "asset_id": asset.id,
                "status": asset.status.value if hasattr(asset.status, "value") else str(asset.status),
                "publications": [],
                "held": True,
                "reason": hold_reason,
            }

        asset.status = VideoStatusEnum.PUBLISHING
        asset.review_notes = notes
        asset.reviewed_at = _now()
        self.db.commit()

        targets = [p for p in (platforms or PLATFORMS) if p in PLATFORMS]

        results = []
        for platform in targets:
            pub = self._get_or_create_publication(asset, platform)

            # Ja publicado antes: nao reenvia (evita duplicar no canal).
            if pub.status == PublicationStatusEnum.PUBLISHED:
                results.append(self._pub_dict(pub))
                continue

            self._publish_to_platform(asset, pub, platform)
            results.append(self._pub_dict(pub))

        self._recompute_asset_status(asset)

        return {
            "asset_id": asset.id,
            "status": asset.status.value if hasattr(asset.status, "value") else str(asset.status),
            "publications": results,
        }

    def retry_single_publication(self, publication_id: int) -> dict:
        """Reenvia SOMENTE a plataforma que falhou (nao mexe nas outras).

        Usado pelo botao "Reenviar" na aba de publicacoes com erro. Se falhar
        de novo, o registro CONTINUA existindo (nao e descartado) com o novo
        erro, pronto para nova tentativa ou exclusao manual.
        """
        pub = self.db.query(Publication).filter(Publication.id == publication_id).first()
        if pub is None:
            raise ValueError("Publicacao nao encontrada.")

        asset = self.db.query(VideoAsset).filter(VideoAsset.id == pub.video_asset_id).first()
        if asset is None:
            raise ValueError("Video nao encontrado.")

        if pub.status == PublicationStatusEnum.PUBLISHED:
            # Ja publicado: nao reenvia (evita duplicar no canal).
            return {"asset_id": asset.id, "publication": self._pub_dict(pub)}

        # Guard anti-direitos autorais tambem no reenvio de uma unica plataforma.
        hold_reason = self._copyright_hold_reason(asset)
        if hold_reason:
            asset.status = VideoStatusEnum.REJECTED
            asset.review_notes = hold_reason
            asset.reviewed_at = _now()
            self.db.commit()
            return {
                "asset_id": asset.id,
                "held": True,
                "reason": hold_reason,
                "publication": self._pub_dict(pub),
            }

        self._publish_to_platform(asset, pub, pub.platform)
        self._recompute_asset_status(asset)

        return {"asset_id": asset.id, "publication": self._pub_dict(pub)}

    def delete_publication(self, publication_id: int) -> dict:
        """Remove um registro de publicacao (usado na aba de reenvio para
        limpar tentativas que o usuario decidiu nao repetir mais).
        Nao apaga o video, so o historico daquela plataforma."""
        pub = self.db.query(Publication).filter(Publication.id == publication_id).first()
        if pub is None:
            raise ValueError("Publicacao nao encontrada.")

        asset_id = pub.video_asset_id
        self.db.delete(pub)
        self.db.commit()

        asset = self.db.query(VideoAsset).filter(VideoAsset.id == asset_id).first()
        if asset is not None:
            self._recompute_asset_status(asset)

        return {"deleted": True, "asset_id": asset_id}

    # ----------------------------------------------------------------
    # HELPERS
    # ----------------------------------------------------------------

    def _publish_to_platform(
        self,
        asset: VideoAsset,
        pub: Publication,
        platform: str,
    ) -> Publication:
        """Executa a tentativa de publicacao de UMA publicacao/plataforma e
        grava o resultado (published / failed / credentials_missing /
        rate_limited). Nao mexe no status do asset (isso e feito por quem
        chama, via _recompute_asset_status, ja que um asset pode ter varias
        publicacoes)."""
        # GUARDA DE ARQUIVO PURGADO: se o video foi removido (purgado depois de
        # publicar), NENHUMA plataforma consegue enviar. Marca SKIPPED (terminal)
        # e sai - evita retentar para sempre um arquivo inexistente, que era a
        # causa principal dos travamentos no reenvio.
        if self._is_video_purged(asset):
            pub.status = PublicationStatusEnum.SKIPPED
            pub.error = (
                "Arquivo do video foi removido (purgado apos publicacao). "
                "Nada a reenviar nesta plataforma."
            )
            self.db.commit()
            return pub

        # CIRCUIT BREAKER META: se levamos (#4) (limite do app) ha pouco, NAO
        # chamamos o Graph de novo ate a janela expirar - martelar so mantem o
        # bloqueio e nunca deixa a cota se recuperar. Marca rate_limited
        # (aguarda reenvio) sem gastar nenhuma chamada de API.
        if platform in _META_PLATFORMS:
            remaining = _meta_cooldown_remaining()
            if remaining > 0:
                pub.status = PublicationStatusEnum.RATE_LIMITED
                pub.error = (
                    "Em espera: limite de requisicoes do app da Meta (#4) "
                    "atingido ha pouco. Retomando automaticamente em "
                    f"~{int(remaining // 60) + 1} min (nao chamo o Graph API "
                    "agora para nao piorar o bloqueio e deixar a cota recuperar)."
                )
                self.db.commit()
                return pub

        request = self._build_request(asset, platform)

        publisher = get_publisher(platform)
        if publisher is None:
            pub.status = PublicationStatusEnum.SKIPPED
            pub.error = "Plataforma sem conector."
            self.db.commit()
            return pub

        pub.status = PublicationStatusEnum.UPLOADING
        self.db.commit()

        result = publisher.publish(request)

        if result.status == "published":
            pub.status = PublicationStatusEnum.PUBLISHED
            pub.external_id = result.external_id
            pub.external_url = result.external_url
            pub.error = None
            pub.published_at = _now()
        elif result.status == "credentials_missing":
            pub.status = PublicationStatusEnum.CREDENTIALS_MISSING
            pub.error = result.error
        elif _is_rate_limited(result.error):
            # Bloqueio TEMPORARIO da plataforma (limite diario/cota).
            # NAO e erro: fica aguardando reenvio.
            pub.status = PublicationStatusEnum.RATE_LIMITED
            pub.error = result.error
            # Se foi o limite do APP da Meta (#4), abre o cooldown para as
            # proximas publicacoes de IG/FB nao martelarem o Graph e deixarem a
            # cota se recuperar (circuit breaker acima).
            if platform in _META_PLATFORMS and _is_meta_app_limit(result.error):
                _meta_trip_cooldown()
        elif _needs_reconnect(result.error):
            # Conta precisa de acao do usuario (token revogado/expirado, app nao
            # auditado, sem permissao). Reenviar nao resolve: marca como
            # credencial pendente para SAIR da fila de reenvio (nao vira falha
            # eterna) e sinalizar que precisa reconectar a conta.
            pub.status = PublicationStatusEnum.CREDENTIALS_MISSING
            pub.error = result.error
        else:
            pub.status = PublicationStatusEnum.FAILED
            pub.error = result.error

        self.db.commit()

        # Atualiza a bio (link na bio) automaticamente quando um AFILIADO e
        # publicado: regenera a pagina e publica no GitHub Pages em segundo plano.
        if (
            pub.status == PublicationStatusEnum.PUBLISHED
            and asset.kind == VideoKindEnum.AFFILIATE
            and getattr(asset, "affiliate_url", None)
        ):
            try:
                from app.services.bio_updater import trigger_bio_update

                trigger_bio_update()
            except Exception:  # nunca bloqueia a publicacao por causa da bio
                pass

        return pub

    def _recompute_asset_status(self, asset: VideoAsset) -> VideoAsset:
        """Recalcula o status do video a partir de TODAS as publicacoes dele.
        Usado apos aprovar/publicar, reenviar uma plataforma ou apagar um
        registro de publicacao.

        REGRA DE PUBLICACAO PARCIAL: o video so fica PUBLISHED quando NAO sobra
        nenhuma plataforma para reenviar. Se subiu em ALGUMAS redes mas outras
        ficaram BLOQUEADAS (rate_limited) ou com ERRO (failed), o video vai para
        RETRY_PENDING ("aguardando reenvio") -> aparece na fila de reenvio e
        completa SO as plataformas que faltaram (as ja publicadas nunca sao
        reenviadas, para nao duplicar no canal)."""
        pubs = (
            self.db.query(Publication)
            .filter(Publication.video_asset_id == asset.id)
            .all()
        )

        any_published = any(p.status == PublicationStatusEnum.PUBLISHED for p in pubs)
        any_rate_limited = any(p.status == PublicationStatusEnum.RATE_LIMITED for p in pubs)
        any_failed = any(p.status == PublicationStatusEnum.FAILED for p in pubs)

        # Plataformas que ainda PRECISAM de reenvio (nao concluidas): bloqueio
        # temporario (rate_limited) ou erro (failed). SKIPPED e terminal (nada
        # a reenviar) e nao conta aqui.
        needs_resend = any_rate_limited or any_failed

        if any_published and needs_resend:
            # Subiu em ALGUMAS redes, mas outras ficaram bloqueadas/com erro.
            # NAO marca como concluido: fica aguardando reenvio para completar
            # somente as plataformas que faltaram.
            asset.status = VideoStatusEnum.RETRY_PENDING
            if not asset.published_at:
                asset.published_at = _now()
        elif any_published:
            # Todas as plataformas alvo concluiram (publicado ou skipped): pronto.
            asset.status = VideoStatusEnum.PUBLISHED
            if not asset.published_at:
                asset.published_at = _now()
            # POLITICA: nao guardar video ja publicado. Apaga o arquivo pesado
            # (.mp4 + miniatura) mantendo o metadata (.json + banco, p/ dedup) e
            # a versao de live (.live.mp4). O file_purged e persistido no commit
            # abaixo, junto com o status PUBLISHED.
            self._purge_after_publish(asset)
        elif any_rate_limited:
            # A plataforma bloqueou por limite. Guarda para reenviar depois,
            # sem marcar como erro.
            asset.status = VideoStatusEnum.RETRY_PENDING
        elif any_failed:
            asset.status = VideoStatusEnum.FAILED
        else:
            # Se TODAS as publicacoes foram SKIPPED (ex.: arquivo purgado, sem
            # o que enviar), o video nao tem como subir -> estado TERMINAL, sai
            # do loop de reenvio. Senao (ex.: faltam credenciais), fica na fila.
            if pubs and all(
                p.status == PublicationStatusEnum.SKIPPED for p in pubs
            ):
                asset.status = VideoStatusEnum.FAILED
            else:
                asset.status = VideoStatusEnum.APPROVED

        self.db.commit()
        self.db.refresh(asset)
        return asset

    def _purge_after_publish(self, asset: VideoAsset) -> None:
        """Apaga o arquivo pesado (.mp4 + miniatura) assim que o video conclui
        em TODAS as redes, liberando disco. MANTEM:
          - o metadata (.json ao lado + registro no banco) para dedup (nao
            recriar o mesmo produto);
          - a VERSAO DE LIVE (.live.mp4), que NAO e referenciada pelo asset
            (video_path aponta so para o reels), entao nunca e tocada aqui -- a
            montagem da live continua usando.
        Controlado por ATLAS_AUTO_PURGE_AFTER_PUBLISH (padrao: ligado). Nunca
        levanta excecao: uma falha ao apagar jamais quebra a publicacao."""
        if not _env_bool("ATLAS_AUTO_PURGE_AFTER_PUBLISH", True):
            return
        payload = asset.payload if isinstance(asset.payload, dict) else {}
        if payload.get("file_purged"):
            return  # ja purgado antes: idempotente, nada a fazer.
        for rel in (asset.video_path, asset.thumbnail_path):
            if not rel:
                continue
            try:
                full = resolve_video_path(rel)
                if full and os.path.isfile(full):
                    os.remove(full)
            except OSError:
                pass  # arquivo em uso/sem permissao: ignora (tenta de novo depois).
        # Marca purgado mesmo se o arquivo ja nao existia, para o painel mostrar
        # "arquivo liberado" e o reenvio tratar como terminal. Reatribui o dict
        # inteiro para o SQLAlchemy detectar a mudanca na coluna JSON.
        new_payload = dict(payload)
        new_payload["file_purged"] = True
        asset.payload = new_payload

    # ----------------------------------------------------------------
    # MANUTENCAO DA FILA (evita travamentos no reenvio)
    # ----------------------------------------------------------------

    def _is_video_purged(self, asset: VideoAsset) -> bool:
        """True se o arquivo de video nao existe mais. O Atlas PURGA o arquivo
        depois de publicar; sem o arquivo LOCAL nao ha o que enviar em nenhuma
        plataforma (ate o upload para o Supabase precisa do arquivo local),
        entao reenviar so geraria falha eterna e travaria a fila."""
        payload = asset.payload if isinstance(asset.payload, dict) else {}
        if payload.get("file_purged"):
            return True
        path = resolve_video_path(asset.video_path or "")
        if not (path and os.path.isfile(path)):
            return True
        # Arquivo existe mas esta VAZIO (0 bytes): tambem nao ha o que enviar
        # (ex.: geracao interrompida deixou o .mp4 zerado). Sem isso a fila
        # tentaria publicar para sempre um video que nenhuma plataforma aceita.
        try:
            if os.path.getsize(path) == 0:
                return True
        except OSError:
            return True
        return False

    def reset_stale_inprogress(self, *, max_age_minutes: int = 30) -> dict:
        """Destrava publicacoes/videos presos EM ANDAMENTO ha muito tempo
        (UPLOADING/PUBLISHING orfaos de um processo que caiu no meio do envio).
        Sem isso o registro fica preso para sempre - nem reenvia, nem conclui.
        Recoloca na fila de reenvio (marca como bloqueio temporario)."""
        cutoff = _now() - timedelta(minutes=max_age_minutes)
        stale_pubs = (
            self.db.query(Publication)
            .filter(
                Publication.status == PublicationStatusEnum.UPLOADING,
                Publication.updated_at < cutoff,
            )
            .all()
        )
        touched: set[int] = set()
        for pub in stale_pubs:
            pub.status = PublicationStatusEnum.RATE_LIMITED
            pub.error = (
                "Envio interrompido (o processo caiu antes de concluir); "
                "recolocado na fila de reenvio."
            )
            touched.add(pub.video_asset_id)
        if stale_pubs:
            self.db.commit()

        stale_assets = (
            self.db.query(VideoAsset)
            .filter(
                VideoAsset.status == VideoStatusEnum.PUBLISHING,
                VideoAsset.updated_at < cutoff,
            )
            .all()
        )
        for asset in stale_assets:
            self._recompute_asset_status(asset)
            touched.add(asset.id)

        return {
            "publications_reset": len(stale_pubs),
            "assets_touched": len(touched),
        }

    def skip_purged_pending(self, *, kind: str | None = None) -> dict:
        """Marca como SKIPPED (terminal) as publicacoes pendentes cujo arquivo
        de video foi PURGADO. Elas nunca vao subir (nao ha midia local para
        enviar em NENHUMA rede - ate o upload para o Supabase precisa do arquivo
        local) e so travam o loop de reenvio - era a causa de 99% das 'falhas ao
        reenviar'. NAO publica nada; apenas limpa a fila.

        Varre TODOS os assets que tenham QUALQUER publicacao ainda nao concluida
        (nao so os que estao em RETRY_PENDING/RATE_LIMITED), porque um arquivo
        purgado e terminal em qualquer status. Sem 'kind', limpa a fila inteira;
        com 'kind', limita aquele tipo."""
        pending_asset_ids = (
            self.db.query(Publication.video_asset_id)
            .filter(
                Publication.status.notin_(
                    [
                        PublicationStatusEnum.PUBLISHED,
                        PublicationStatusEnum.SKIPPED,
                    ]
                )
            )
            .distinct()
        )
        query = self.db.query(VideoAsset).filter(VideoAsset.id.in_(pending_asset_ids))
        if kind:
            try:
                query = query.filter(VideoAsset.kind == VideoKindEnum(kind))
            except ValueError:
                pass

        skipped = 0
        cleaned_assets = 0
        for asset in query.all():
            if not self._is_video_purged(asset):
                continue
            pubs = (
                self.db.query(Publication)
                .filter(
                    Publication.video_asset_id == asset.id,
                    Publication.status.notin_(
                        [
                            PublicationStatusEnum.PUBLISHED,
                            PublicationStatusEnum.SKIPPED,
                        ]
                    ),
                )
                .all()
            )
            for pub in pubs:
                pub.status = PublicationStatusEnum.SKIPPED
                pub.error = (
                    "Arquivo do video foi removido (purgado apos publicacao). "
                    "Nada a reenviar."
                )
                skipped += 1
            if pubs:
                self.db.commit()
            self._recompute_asset_status(asset)
            cleaned_assets += 1
        return {
            "publications_skipped": skipped,
            "assets_cleaned": cleaned_assets,
        }

    def _get_or_create_publication(
        self,
        asset: VideoAsset,
        platform: str,
    ) -> Publication:
        pub = (
            self.db.query(Publication)
            .filter(
                Publication.video_asset_id == asset.id,
                Publication.platform == platform,
            )
            .first()
        )
        if pub is None:
            pub = Publication(
                video_asset_id=asset.id,
                platform=platform,
                status=PublicationStatusEnum.QUEUED,
            )
            self.db.add(pub)
            self.db.commit()
            self.db.refresh(pub)
        return pub

    def _affiliate_caption(self, asset: VideoAsset, platform: str | None = None) -> tuple[str, str, list]:
        """Cria legenda + hashtags para um video de afiliado.

        Retorna (caption, description, hashtags). As hashtags tambem sao
        embutidas no texto, porque Instagram e Facebook so mostram o que
        estiver dentro da legenda/descricao.

        A quantidade de hashtags e ajustada por plataforma (ajuste inteligente):
        Instagram usa mais (a hashtag ajuda na descoberta), TikTok/YouTube/Facebook
        usam poucas e relevantes (passar do ponto vira spam e reduz alcance).
        """
        import html
        import re
        import unicodedata

        payload = asset.payload or {}

        def deslug(text: str) -> str:
            """Converte um 'slug' (br-m40..-Filtro-de-Linha-9dbf) em texto legivel."""
            parts = [p for p in str(text or "").split("-") if p]
            keep = []
            for i, p in enumerate(parts):
                low = p.lower()
                # Descarta prefixo de mercado (2 letras) e ids/hex no comeco/fim.
                if i == 0 and len(p) <= 3:
                    continue
                if re.fullmatch(r"[0-9a-f]{6,}", low) or re.fullmatch(r"m[0-9a-f]{6,}", low):
                    continue
                keep.append(p)
            return " ".join(keep).strip()

        # Prefere o nome real do produto (payload). A coluna title costuma ser slug.
        raw = payload.get("title") or ""
        if not raw:
            raw = deslug(asset.title) or (asset.title or "")
        title = html.unescape(str(raw).strip())

        # Titulo da Amazon costuma ser bem longo: encurta para a legenda.
        short = title
        if len(short) > 90:
            short = short[:90].rsplit(" ", 1)[0] + "\u2026"

        market = (asset.country_code or payload.get("marketplace_code") or "").strip().upper()
        lang = (asset.language or payload.get("language") or "").lower()
        is_en = market == "US" or lang.startswith("en")

        def slug(text: str) -> str:
            s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
            return re.sub(r"[^A-Za-z0-9]+", "", s).lower()

        if is_en:
            base_tags = [
                "#amazonfinds", "#amazondeals", "#founditonamazon",
                "#tiktokmademebuyit", "#dealsoftheday", "#amazonmusthaves",
                "#onlineshopping",
            ]
            caption_text = f"{short} \U0001f60d\nAmazon find you need \u2014 grab it before it's gone! \U0001f525\U0001f447"
        else:
            base_tags = [
                "#achadosdaamazon", "#achadinhos", "#ofertas", "#promocao",
                "#amazonbrasil", "#comprasonline", "#ofertadodia",
            ]
            caption_text = f"{short} \U0001f60d\nAchadinho que vale a pena \u2014 corre que o pre\u00e7o t\u00e1 bom! \U0001f525\U0001f447"

        tags: list[str] = list(base_tags)

        # Hashtag da categoria do produto.
        cat = payload.get("category_label") or payload.get("category") or ""
        cat_slug = slug(cat)
        if len(cat_slug) >= 3:
            tag = f"#{cat_slug}"
            if tag not in tags:
                tags.append(tag)

        # Hashtag da marca (primeira palavra do titulo do produto).
        first = title.split(" ")[0] if title else ""
        brand_slug = slug(first)
        if 3 <= len(brand_slug) <= 20 and not brand_slug.isdigit():
            tag = f"#{brand_slug}"
            if tag not in tags:
                tags.append(tag)

        # Ajuste inteligente da quantidade por plataforma. As primeiras da lista
        # sao as mais fortes/relevantes; cada rede recebe a sua quantidade ideal.
        platform_limits = {
            "instagram": 15,
            "tiktok": 5,
            "youtube": 4,
            "facebook": 4,
        }
        limit = platform_limits.get((platform or "").strip().lower(), 15)
        tags = tags[:limit]
        tag_line = " ".join(tags)
        caption_full = f"{caption_text}\n\n{tag_line}"
        return caption_full, caption_full, tags

    def _build_request(
        self,
        asset: VideoAsset,
        platform: str,
    ) -> PublishRequest:
        import html

        payload = asset.payload or {}
        platforms_meta = payload.get("platforms", {}) or {}
        pdata = platforms_meta.get(platform, {}) or {}

        hashtags = pdata.get("hashtags") or payload.get("hashtags") or []
        caption = (
            pdata.get("caption")
            or pdata.get("description")
            or asset.title
            or ""
        )
        title = pdata.get("title") or asset.title or (asset.topic or "")
        description = pdata.get("description") or caption

        # Videos de AFILIADO (produtos Amazon) nao passam pelo gerador de
        # legenda/hashtags dos Reels de tendencia. Se vierem sem hashtags,
        # criamos aqui uma legenda com chamada + hashtags, para o post ter
        # alcance (senao sairia so com o titulo cru do produto e sem hashtag).
        is_affiliate = asset.kind == VideoKindEnum.AFFILIATE or str(
            getattr(asset, "kind", "")
        ).lower().endswith("affiliate")
        if is_affiliate and not hashtags:
            caption, description, hashtags = self._affiliate_caption(asset, platform)
            title = title or asset.title or ""

        # Limpa entidades HTML (ex.: "&amp;" -> "&") vindas do titulo da Amazon.
        title = html.unescape(str(title or ""))
        caption = html.unescape(str(caption or ""))
        description = html.unescape(str(description or ""))

        # ---- LINK CLICAVEL PARA AFILIADOS ----
        affiliate_link = None
        if asset.kind == VideoKindEnum.AFFILIATE and asset.affiliate_url:
            import os

            # So usa o link curto se existir um DOMINIO PUBLICO HTTPS de verdade.
            # Sem isso, o "localhost" nao abre para ninguem: entao usamos o
            # proprio link da Amazon (ja com a tag de afiliado, funciona e paga).
            # ATENCAO: o tunel (trycloudflare.com) TROCA de endereco a cada vez
            # que o painel abre. Ele serve para o IG/FB BAIXAREM o video na hora,
            # mas NAO pode virar link de legenda (quebraria depois). Por isso,
            # com tunel, o link clicavel continua sendo o da Amazon (permanente).
            public_base = (os.getenv("ATLAS_PUBLIC_BASE_URL") or "").strip()
            has_public_domain = (
                public_base.lower().startswith("https://")
                and "trycloudflare.com" not in public_base.lower()
            )

            if has_public_domain:
                link = self.shortlinks.get_or_create(
                    asset.affiliate_url,
                    title=asset.title,
                    video_asset_id=asset.id,
                )
                affiliate_link = self.shortlinks.build_public_url(link.code)
                if not asset.short_code:
                    asset.short_code = link.code
                    self.db.commit()
            else:
                # Link direto da Amazon (com a tag de afiliado ja embutida).
                affiliate_link = asset.affiliate_url

            # Texto no idioma do mercado: US = ingles, BR = portugues.
            market = (asset.country_code or "").strip().upper()
            is_en = market == "US" or (asset.language or "").lower().startswith("en")
            buy_label = "Buy it here:" if is_en else "Compre aqui:"
            link_block = f"{buy_label}\n{affiliate_link}"

            if platform == "youtube":
                # No YouTube o link vai no TOPO (aparece antes do "mostrar mais")
                # e tambem no fim, sempre em linha propria = clicavel.
                description = f"{link_block}\n\n{description}\n\n{link_block}"
                caption = description
            elif platform == "tiktok":
                # TikTok NAO deixa link clicavel na legenda: manda para a BIO,
                # que tem todos os produtos com o link direto da Amazon.
                if is_en:
                    cta = "\n\n\U0001f517 Full link in our BIO \u2014 tap our profile \u2b06\ufe0f"
                else:
                    cta = "\n\n\U0001f517 Link completo na nossa BIO \u2014 toca no nosso perfil \u2b06\ufe0f"
                caption = f"{caption}{cta}"
                description = f"{description}{cta}"
            else:
                # Instagram/Facebook: o link completo fica na BIO do perfil
                # (a bio tem todos os produtos com o link direto da Amazon).
                if is_en:
                    cta = "\n\n\U0001f517 Full link in our BIO \u2014 tap our profile \u2b06\ufe0f"
                else:
                    cta = "\n\n\U0001f517 Link completo na nossa BIO \u2014 toca no nosso perfil \u2b06\ufe0f"
                caption = f"{caption}{cta}"
                description = f"{description}{cta}"

        return PublishRequest(
            video_path=asset.video_path or "",
            title=title,
            description=description,
            caption=caption,
            hashtags=hashtags,
            kind=asset.kind.value if hasattr(asset.kind, "value") else str(asset.kind or ""),
            language=asset.language or "",
            country_code=asset.country_code or "",
            affiliate_url=affiliate_link or asset.affiliate_url,
        )

    def _pub_dict(self, pub: Publication) -> dict:
        return {
            "id": pub.id,
            "platform": pub.platform,
            "status": pub.status.value if hasattr(pub.status, "value") else str(pub.status),
            "external_url": pub.external_url,
            "error": pub.error,
        }

    def list_publications(self) -> list[dict]:
        rows = (
            self.db.query(Publication)
            .order_by(Publication.updated_at.desc())
            .limit(300)
            .all()
        )
        out = []
        for pub in rows:
            item = self._pub_dict(pub)
            item["video_asset_id"] = pub.video_asset_id
            item["updated_at"] = (
                pub.updated_at.isoformat() if pub.updated_at else None
            )
            out.append(item)
        return out
