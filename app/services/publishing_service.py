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

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.dashboard import (
    Publication,
    PublicationStatusEnum,
    VideoAsset,
    VideoKindEnum,
    VideoStatusEnum,
)
from app.publishing.base import PublishRequest
from app.publishing.registry import PLATFORMS, get_publisher
from app.services.shortlink_service import ShortLinkService


def _now():
    return datetime.now(timezone.utc)


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
)


def _is_rate_limited(error_text: str | None) -> bool:
    """True se o erro for um bloqueio TEMPORARIO da plataforma (limite/cota),
    que tende a resolver reenviando mais tarde (ex.: no dia seguinte)."""
    if not error_text:
        return False
    text = str(error_text).lower()
    return any(hint in text for hint in _RATE_LIMIT_HINTS)


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

    def retry_pending(self, *, kind: str | None = None) -> dict:
        """Reenvia os videos que ficaram AGUARDANDO REENVIO (bloqueio temporario
        da plataforma). Tenta publicar de novo apenas nas plataformas que ainda
        nao subiram; as que ja publicaram sao preservadas (nao duplica)."""
        query = self.db.query(VideoAsset).filter(
            VideoAsset.status == VideoStatusEnum.RETRY_PENDING
        )
        if kind:
            try:
                query = query.filter(VideoAsset.kind == VideoKindEnum(kind))
            except ValueError:
                pass

        assets = query.all()
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
        """Quantos videos estao aguardando reenvio."""
        query = self.db.query(VideoAsset).filter(
            VideoAsset.status == VideoStatusEnum.RETRY_PENDING
        )
        if kind:
            try:
                query = query.filter(VideoAsset.kind == VideoKindEnum(kind))
            except ValueError:
                pass
        return query.count()

    def approve_and_publish(
        self,
        asset: VideoAsset,
        *,
        platforms: list[str] | None = None,
        notes: str | None = None,
    ) -> dict:
        """Aprova e tenta publicar nas plataformas alvo."""
        asset.status = VideoStatusEnum.PUBLISHING
        asset.review_notes = notes
        asset.reviewed_at = _now()
        self.db.commit()

        targets = [p for p in (platforms or PLATFORMS) if p in PLATFORMS]

        results = []
        any_published = False
        any_failed = False
        any_rate_limited = False

        for platform in targets:
            pub = self._get_or_create_publication(asset, platform)

            # Ja publicado antes: nao reenvia (evita duplicar no canal).
            if pub.status == PublicationStatusEnum.PUBLISHED:
                any_published = True
                results.append(self._pub_dict(pub))
                continue

            request = self._build_request(asset, platform)

            publisher = get_publisher(platform)
            if publisher is None:
                pub.status = PublicationStatusEnum.SKIPPED
                pub.error = "Plataforma sem conector."
                self.db.commit()
                results.append(self._pub_dict(pub))
                continue

            pub.status = PublicationStatusEnum.UPLOADING
            self.db.commit()

            result = publisher.publish(request)

            if result.status == "published":
                pub.status = PublicationStatusEnum.PUBLISHED
                pub.external_id = result.external_id
                pub.external_url = result.external_url
                pub.error = None
                pub.published_at = _now()
                any_published = True
            elif result.status == "credentials_missing":
                pub.status = PublicationStatusEnum.CREDENTIALS_MISSING
                pub.error = result.error
            elif _is_rate_limited(result.error):
                # Bloqueio TEMPORARIO da plataforma (limite diario/cota).
                # NAO e erro: fica aguardando reenvio.
                pub.status = PublicationStatusEnum.RATE_LIMITED
                pub.error = result.error
                any_rate_limited = True
            else:
                pub.status = PublicationStatusEnum.FAILED
                pub.error = result.error
                any_failed = True

            self.db.commit()
            results.append(self._pub_dict(pub))

        # Status consolidado do asset.
        if any_published:
            asset.status = VideoStatusEnum.PUBLISHED
            asset.published_at = _now()
        elif any_rate_limited:
            # A plataforma bloqueou por limite. Guarda para reenviar depois,
            # sem marcar como erro.
            asset.status = VideoStatusEnum.RETRY_PENDING
        elif any_failed:
            asset.status = VideoStatusEnum.FAILED
        else:
            # Nada publicou (ex.: faltam credenciais). Continua aprovado, na fila.
            asset.status = VideoStatusEnum.APPROVED

        self.db.commit()
        self.db.refresh(asset)

        # Atualiza a bio (link na bio) automaticamente quando um AFILIADO e
        # publicado: regenera a pagina e publica no GitHub Pages em segundo plano.
        if (
            any_published
            and asset.kind == VideoKindEnum.AFFILIATE
            and getattr(asset, "affiliate_url", None)
        ):
            try:
                from app.services.bio_updater import trigger_bio_update

                trigger_bio_update()
            except Exception:  # nunca bloqueia a publicacao por causa da bio
                pass

        return {
            "asset_id": asset.id,
            "status": asset.status.value if hasattr(asset.status, "value") else str(asset.status),
            "publications": results,
        }

    # ----------------------------------------------------------------
    # HELPERS
    # ----------------------------------------------------------------

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
