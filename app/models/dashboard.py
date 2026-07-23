# ============================================================
# ATLAS OS - dashboard.py
# Modelos que suportam o painel web de monitoramento:
# - VideoAsset      : registro unico de cada video produzido (reel ou afiliado)
# - Publication     : status de publicacao por plataforma
# - VideoMetric     : serie temporal de metricas por video/plataforma
# - PlatformStat    : seguidores / estatisticas por conta de plataforma
# - ShortLink       : link curto clicavel para produtos de afiliado
# - LinkClick       : registro de cada clique nos links de afiliado
# ============================================================

import enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class VideoKindEnum(str, enum.Enum):
    REEL = "reel"
    AFFILIATE = "affiliate"


class VideoStatusEnum(str, enum.Enum):
    CREATED = "created"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    # A plataforma bloqueou por limite diario/temporario. NAO e erro real:
    # fica aguardando reenvio (botao "Reenviar pendentes" no dia seguinte).
    RETRY_PENDING = "retry_pending"


class PublicationStatusEnum(str, enum.Enum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    PUBLISHED = "published"
    FAILED = "failed"
    CREDENTIALS_MISSING = "credentials_missing"
    SKIPPED = "skipped"
    # Limite/bloqueio temporario da plataforma (ex.: YouTube uploadLimitExceeded).
    RATE_LIMITED = "rate_limited"


class AdCampaignStatusEnum(str, enum.Enum):
    """Ciclo de vida de uma campanha de anuncio pago."""

    DRAFT = "draft"                              # rascunho salvo
    REVIEW = "review"                            # aguardando revisao manual
    LAUNCHING = "launching"                      # enviando para a plataforma
    PAUSED = "paused"                            # criada na plataforma, pausada
    ACTIVE = "active"                            # rodando (gastando)
    FAILED = "failed"                            # erro ao publicar
    CREDENTIALS_MISSING = "credentials_missing"  # falta conta de anuncios


class VideoAsset(Base):
    """
    Registro unico de cada video produzido pela fabrica.
    Alimentado pelo VideoLibraryService a partir de output_videos/
    e output_metadata/ (reels) e do pipeline de afiliados.
    """

    __tablename__ = "video_assets"

    __table_args__ = (
        UniqueConstraint(
            "kind",
            "external_key",
            name="uq_video_assets_kind_external_key",
        ),
        Index("ix_video_assets_status", "status"),
        Index("ix_video_assets_kind", "kind"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # "reel" ou "affiliate"
    kind = Column(
        Enum(VideoKindEnum, native_enum=False, length=20),
        nullable=False,
    )

    # Chave estavel de origem (ex.: content_id do reel, asin do produto).
    external_key = Column(String(120), nullable=False)

    title = Column(String(500), nullable=True)
    topic = Column(String(500), nullable=True)
    language = Column(String(10), nullable=True)
    country_code = Column(String(8), nullable=True)

    # Caminhos relativos ao root do projeto.
    video_path = Column(Text, nullable=True)
    thumbnail_path = Column(Text, nullable=True)
    metadata_path = Column(Text, nullable=True)

    # Para videos de afiliado: link clicavel do produto.
    affiliate_url = Column(Text, nullable=True)
    short_code = Column(String(32), nullable=True)

    performance_score = Column(Integer, nullable=True)

    status = Column(
        Enum(VideoStatusEnum, native_enum=False, length=20),
        nullable=False,
        default=VideoStatusEnum.CREATED,
        server_default=VideoStatusEnum.CREATED.value,
    )

    review_notes = Column(Text, nullable=True)

    # Pacote de metadados / captions por plataforma.
    payload = Column(JSON, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    publications = relationship(
        "Publication",
        back_populates="video",
        cascade="all, delete-orphan",
    )
    metrics = relationship(
        "VideoMetric",
        back_populates="video",
        cascade="all, delete-orphan",
    )


class Publication(Base):
    """Uma linha por (video, plataforma) representando a publicacao."""

    __tablename__ = "publications"

    __table_args__ = (
        UniqueConstraint(
            "video_asset_id",
            "platform",
            name="uq_publications_video_platform",
        ),
        Index("ix_publications_status", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)

    video_asset_id = Column(
        Integer,
        ForeignKey("video_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # youtube | tiktok | instagram | facebook
    platform = Column(String(30), nullable=False)

    status = Column(
        Enum(PublicationStatusEnum, native_enum=False, length=30),
        nullable=False,
        default=PublicationStatusEnum.QUEUED,
        server_default=PublicationStatusEnum.QUEUED.value,
    )

    external_id = Column(String(255), nullable=True)
    external_url = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    published_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    video = relationship("VideoAsset", back_populates="publications")


class VideoMetric(Base):
    """Snapshot temporal das metricas de um video em uma plataforma."""

    __tablename__ = "video_metrics"

    __table_args__ = (
        Index(
            "ix_video_metrics_video_platform",
            "video_asset_id",
            "platform",
        ),
    )

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        index=True,
    )

    video_asset_id = Column(
        Integer,
        ForeignKey("video_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    platform = Column(String(30), nullable=False)

    views = Column(BigInteger, default=0, nullable=False)
    likes = Column(BigInteger, default=0, nullable=False)
    comments = Column(BigInteger, default=0, nullable=False)
    shares = Column(BigInteger, default=0, nullable=False)
    clicks = Column(BigInteger, default=0, nullable=False)

    captured_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    video = relationship("VideoAsset", back_populates="metrics")


class PlatformStat(Base):
    """Snapshot de estatisticas de uma conta/plataforma (ex.: seguidores)."""

    __tablename__ = "platform_stats"

    __table_args__ = (
        Index("ix_platform_stats_platform", "platform"),
    )

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        index=True,
    )

    platform = Column(String(30), nullable=False)
    account = Column(String(120), nullable=True)

    followers = Column(BigInteger, default=0, nullable=False)
    following = Column(BigInteger, default=0, nullable=False)
    total_views = Column(BigInteger, default=0, nullable=False)
    total_likes = Column(BigInteger, default=0, nullable=False)

    captured_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ShortLink(Base):
    """
    Link curto clicavel para um produto de afiliado.
    Redireciona /go/{code} -> affiliate_url e contabiliza cliques.
    """

    __tablename__ = "short_links"

    __table_args__ = (
        UniqueConstraint("code", name="uq_short_links_code"),
    )

    id = Column(Integer, primary_key=True, index=True)

    code = Column(String(32), nullable=False, index=True)
    target_url = Column(Text, nullable=False)

    asin = Column(String(20), nullable=True)
    marketplace = Column(String(20), nullable=True)
    title = Column(String(500), nullable=True)

    clicks = Column(BigInteger, default=0, nullable=False)

    video_asset_id = Column(
        Integer,
        ForeignKey("video_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class LinkClick(Base):
    """Registro individual de cada clique num link curto."""

    __tablename__ = "link_clicks"

    __table_args__ = (
        Index("ix_link_clicks_short_link", "short_link_id"),
    )

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        index=True,
    )

    short_link_id = Column(
        Integer,
        ForeignKey("short_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ip_hash = Column(String(64), nullable=True)
    user_agent = Column(String(400), nullable=True)
    referer = Column(String(400), nullable=True)

    clicked_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class AdCampaign(Base):
    """
    Campanha de anuncio pago (Marketing) para impulsionar um video.

    O plano (objetivo, publico, posicionamentos, textos) e preenchido
    automaticamente pelo MarketingService com base no tipo do video
    (afiliado -> vendas/cliques; reel/trend -> alcance/engajamento) e no
    mercado (BR/US). O valor do orcamento e a decisao de publicar sao
    sempre MANUAIS.
    """

    __tablename__ = "ad_campaigns"

    __table_args__ = (
        Index("ix_ad_campaigns_status", "status"),
        Index("ix_ad_campaigns_video", "video_asset_id"),
    )

    id = Column(Integer, primary_key=True, index=True)

    video_asset_id = Column(
        Integer,
        ForeignKey("video_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # "meta" (Facebook + Instagram) ou "tiktok"
    platform = Column(String(20), nullable=False, default="meta")

    name = Column(String(255), nullable=True)

    # "sales" (vendas/cliques) ou "reach" (alcance/engajamento)
    goal = Column(String(20), nullable=False, default="reach")
    # Codigo do objetivo na API (ex.: OUTCOME_TRAFFIC, OUTCOME_ENGAGEMENT)
    objective = Column(String(40), nullable=True)
    optimization_goal = Column(String(60), nullable=True)

    # Mercado alvo: BR ou US
    market = Column(String(8), nullable=True)

    # Orcamento informado pelo usuario (manual).
    budget_amount = Column(Float, nullable=False, default=0.0)
    budget_period = Column(String(10), nullable=False, default="weekly")  # weekly | monthly
    currency = Column(String(8), nullable=False, default="BRL")
    daily_budget = Column(Float, nullable=True)

    # Plano preenchido automaticamente.
    audience = Column(JSON, nullable=True)       # paises, idade, genero, interesses
    placements = Column(JSON, nullable=True)     # posicionamentos
    primary_text = Column(Text, nullable=True)
    headline = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    cta = Column(String(40), nullable=True)      # SHOP_NOW, LEARN_MORE, WATCH_MORE
    link_url = Column(Text, nullable=True)

    status = Column(
        Enum(AdCampaignStatusEnum, native_enum=False, length=30),
        nullable=False,
        default=AdCampaignStatusEnum.DRAFT,
        server_default=AdCampaignStatusEnum.DRAFT.value,
    )

    external_campaign_id = Column(String(255), nullable=True)
    external_url = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    launched_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    video = relationship("VideoAsset")


class AnsweredComment(Base):
    """
    Registro de cada comentario ja respondido automaticamente pelo robo
    de comentarios (CommentWatcherService).

    Este robo funciona por POLLING (busca periodica via Graph API), nao
    por webhook -- o webhook em tempo real da Meta so entrega comentarios
    de usuarios reais se o app estiver PUBLICADO (exige Verificacao de
    Empresa/CNPJ, pausada por decisao do usuario). O polling le os
    comentarios das PROPRIAS paginas/contas administradas pelo token,
    entao funciona mesmo com o app "Em desenvolvimento".

    Guarda o id do comentario ja tratado para NUNCA responder duas vezes
    o mesmo comentario entre um ciclo e outro.
    """

    __tablename__ = "answered_comments"

    __table_args__ = (
        UniqueConstraint(
            "platform",
            "external_comment_id",
            name="uq_answered_comments_platform_comment",
        ),
        Index("ix_answered_comments_publication", "publication_id"),
    )

    id = Column(Integer, primary_key=True, index=True)

    publication_id = Column(
        Integer,
        ForeignKey("publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # instagram | facebook
    platform = Column(String(30), nullable=False)
    external_comment_id = Column(String(255), nullable=False)

    commenter = Column(String(255), nullable=True)
    comment_text = Column(Text, nullable=True)

    # sent | failed | skipped
    reply_status = Column(String(20), nullable=False, default="sent")
    reply_error = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    publication = relationship("Publication")
