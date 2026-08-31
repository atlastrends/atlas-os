from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.services import shopee_catalog_service
from app.services.shopee_catalog_service import ShopeeCatalogError


router = APIRouter(prefix="/api/shopee", tags=["Shopee Affiliate"])


@router.get("/status")
def get_status():
    try:
        return shopee_catalog_service.status()
    except ShopeeCatalogError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/products")
def get_products():
    try:
        return shopee_catalog_service.list_products()
    except ShopeeCatalogError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/catalog/template")
def catalog_template():
    content = (
        "product_id;title;category;price;affiliate_url;image_url;video_url;"
        "commission_rate;commission_amount;sold_count;description;features;"
        "rating;review_count;official_url\r\n"
        "123456;Nome do produto;Categoria;R$ 99,90;"
        "https://shopee.com.br/product/loja/item;"
        "https://cf.shopee.com.br/file/imagem.jpg;"
        "https://cf.shopee.com.br/file/video.mp4;10,5;10,49;2500;"
        "Descricao real do anuncio;"
        "Destaque um|Destaque dois;4,8;1200;https://marca.com/produto\r\n"
    )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="modelo_catalogo_shopee.csv"'
        },
    )


@router.post("/catalog/import")
async def import_catalog(
    file: UploadFile = File(...),
    rights_confirmed: bool = Form(...),
):
    filename = (file.filename or "").lower()
    if not filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Envie um arquivo CSV.")
    content = await file.read()
    try:
        products = shopee_catalog_service.parse_csv(
            content,
            rights_confirmed=rights_confirmed,
        )
        payload = shopee_catalog_service.save_catalog(products)
    except ShopeeCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "imported": len(products),
        "ready": sum(1 for product in products if product.ready_for_video),
        "updated_at": payload["updated_at"],
    }
