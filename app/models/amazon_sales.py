# ============================================================
# ATLAS OS - amazon_sales.py
# Modelo que guarda as linhas dos relatorios de afiliado da Amazon
# (importados pelo usuario). Cada linha = um item vendido, um pedido
# ou uma linha de cliques, conforme o relatorio baixado no Amazon
# Associates. As estatisticas da pagina "Vendas Amazon" saem daqui.
# ============================================================

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class AmazonSale(Base):
    """Uma linha de relatorio de afiliado da Amazon (venda/pedido/clique)."""

    __tablename__ = "amazon_sales"

    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_amazon_sales_dedupe"),
        Index("ix_amazon_sales_market", "market"),
        Index("ix_amazon_sales_asin", "asin"),
    )

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        index=True,
    )

    # Mercado: "BR" (achadosatlasb-20) ou "US" (atlasfindsus-20).
    market = Column(String(4), nullable=False, default="BR")

    # Tipo do relatorio de origem: "earnings" (ganhos), "orders" (pedidos)
    # ou "clicks" (cliques). Ajuda a somar as coisas certas.
    report_type = Column(String(20), nullable=True)

    category = Column(String(200), nullable=True)
    product_name = Column(String(500), nullable=True)
    asin = Column(String(20), nullable=True)
    tracking_id = Column(String(80), nullable=True)

    # Data no formato AAAA-MM-DD (texto, para simplificar).
    sale_date = Column(String(20), nullable=True)

    qty = Column(Integer, default=0, nullable=False)          # itens vendidos
    returns = Column(Integer, default=0, nullable=False)      # devolucoes
    revenue = Column(Float, default=0.0, nullable=False)      # receita (vendas)
    commission = Column(Float, default=0.0, nullable=False)   # comissao (ganhos)
    clicks = Column(BigInteger, default=0, nullable=False)    # cliques

    currency = Column(String(8), nullable=True)               # BRL / USD
    source_file = Column(String(300), nullable=True)          # nome do arquivo

    # Chave anti-duplicata: reimportar o mesmo relatorio nao duplica linhas.
    dedupe_key = Column(String(64), nullable=False, index=True)

    imported_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
