# ============================================================
# ATLAS OS - amazon_sales.py (router)
# Pagina "Vendas Amazon": importar o relatorio de afiliado baixado
# no Amazon Associates e ver as estatisticas (ganhos, mais vendidos,
# mais clicados, conversao, por periodo, por mercado).
# ============================================================

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.amazon_sales import AmazonSale
from app.services import amazon_report_service, amazon_scraper_service

router = APIRouter(prefix="/api/affiliate/amazon-sales", tags=["Amazon Sales"])

_MAX_BYTES = 15 * 1024 * 1024  # 15 MB


@router.post("/import")
async def import_amazon_sales(
    file: UploadFile = File(...),
    market: str = Form(default="auto"),
    db: Session = Depends(get_db),
):
    """Recebe o relatorio (CSV ou XLSX) e grava as linhas novas."""
    filename = str(file.filename or "")
    low = filename.lower()
    if not (low.endswith(".csv") or low.endswith(".xlsx") or low.endswith(".txt")):
        raise HTTPException(
            status_code=400,
            detail="Envie o relatorio da Amazon em .csv ou .xlsx.",
        )

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="O arquivo deve ter no maximo 15 MB.")
    if not data:
        raise HTTPException(status_code=400, detail="O arquivo esta vazio.")

    default_market = (market or "auto").strip().upper()
    if default_market not in ("BR", "US"):
        default_market = "BR"  # so e usado quando nao da pra deduzir pelo tracking id

    try:
        result = amazon_report_service.import_report(
            db, filename, data, default_market=default_market
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result["total_rows"] == 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Nao encontrei linhas de dados no arquivo. Confirme que baixou "
                "um relatorio de afiliado da Amazon (Ganhos, Pedidos ou Cliques)."
            ),
        )
    return {"ok": True, **result}


@router.get("/stats")
def amazon_sales_stats(
    market: Optional[str] = Query(default=None),
    days: Optional[int] = Query(default=None),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """Estatisticas agregadas para a pagina.

    Ao clicar em "Atualizar" (refresh=1), o ATLAS loga sozinho no Amazon
    Associates (BR e/ou US, conforme credenciais configuradas no .env) e
    baixa o relatorio de ganhos mais recente - o usuario nao precisa baixar
    nada na mao. Tambem mantem, como reforco, a varredura de pastas
    (Downloads etc.) para o caso de o login automatico falhar.
    """
    scraped = None
    if refresh:
        scraped = amazon_scraper_service.fetch_all_configured_markets(db)

    auto = amazon_report_service.auto_scan_and_import(db, force=bool(refresh))
    mkt = (market or "").strip().upper() or None
    if mkt not in (None, "BR", "US"):
        mkt = None
    stats = amazon_report_service.compute_stats(db, market=mkt, days=days)

    imported_rows = auto.get("imported_rows", 0) + (scraped.get("imported_rows", 0) if scraped else 0)
    auto["imported_rows"] = imported_rows
    if scraped is not None:
        auto["scraper_ran"] = scraped["ran"]
        auto["scraper_errors"] = scraped["errors"]
    stats["auto_import"] = auto
    return stats


@router.delete("/clear")
def clear_amazon_sales(
    market: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Apaga os dados importados (tudo ou de um mercado)."""
    q = db.query(AmazonSale)
    mkt = (market or "").strip().upper()
    if mkt in ("BR", "US"):
        q = q.filter(AmazonSale.market == mkt)
    deleted = q.delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "deleted": int(deleted or 0)}
