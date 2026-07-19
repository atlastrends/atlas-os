import hashlib
import os
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.affiliate import MarketplaceEnum
from app.repositories.amazon_catalog import (
    amazon_catalog_repository,
)
from app.schemas.amazon_catalog import (
    AmazonCatalogListResponse,
    AmazonCatalogStatus,
    AmazonConfigResponse,
    AmazonCsvImportResponse,
    AmazonCsvRowResult,
    AmazonMarketplace,
    AmazonProductInput,
    AmazonProductResponse,
    AmazonProductUpsertResponse,
    AmazonStatusUpdate,
)
from app.services.amazon_catalog_service import (
    MARKETPLACE_CONFIG,
    amazon_catalog_service,
)


router = APIRouter(
    prefix="/affiliate/amazon",
    tags=["Amazon Catalog"],
)


def serialize_product(product) -> dict:
    data = {
        "id": product.id,
        "marketplace": (
            product.marketplace.value
            if product.marketplace
            else None
        ),
        "asin": product.asin,
        "title": product.title,
        "category": product.category,
        "description": product.description,
        "features": product.features or [],
        "original_url": product.original_url,
        "product_url": product.product_url,
        "affiliate_url": product.affiliate_url,
        "associate_tag": product.associate_tag,
        "image_url": product.image_url,
        "price_text": product.price_text,
        "currency": product.currency,
        "price_observed_at": product.price_observed_at,
        "affiliate_url_verified_at": (
            product.affiliate_url_verified_at
        ),
        "last_verified_at": product.last_verified_at,
        "data_source": product.data_source,
        "catalog_status": product.catalog_status,
        "notes": product.notes,
        "click_count": product.click_count or 0,
        "is_short_affiliate_url": (
            product.is_short_affiliate_url
        ),
        "created_at": product.created_at,
        "updated_at": product.updated_at,
        "atlas_link": (
            amazon_catalog_service
            .affiliate_link_with_tracking(product.id)
        ),
    }

    return data


def database_marketplace(
    marketplace: Optional[AmazonMarketplace],
) -> Optional[MarketplaceEnum]:
    if marketplace is None:
        return None

    return MARKETPLACE_CONFIG[
        marketplace
    ]["database_enum"]


@router.get(
    "/config",
    response_model=AmazonConfigResponse,
)
def get_amazon_catalog_config():
    br_tag = os.getenv(
        "AMAZON_BR_ASSOCIATE_TAG",
        "",
    ).strip()

    us_tag = os.getenv(
        "AMAZON_US_ASSOCIATE_TAG",
        "",
    ).strip()

    return {
        "public_base_url": (
            amazon_catalog_service.public_base_url()
        ),
        "amazon_br_configured": bool(br_tag),
        "amazon_us_configured": bool(us_tag),
        "csv_max_rows": (
            amazon_catalog_service.csv_max_rows()
        ),
        "supported_marketplaces": [
            "amazon_br",
            "amazon_us",
        ],
        "accepted_sources": [
            "manual",
            "csv",
            "creators_api",
        ],
    }


@router.post(
    "/products/manual",
    response_model=AmazonProductUpsertResponse,
    status_code=status.HTTP_200_OK,
)
def upsert_manual_amazon_product(
    payload: AmazonProductInput,
    db: Session = Depends(get_db),
):
    try:
        validated = amazon_catalog_service.validate_product(
            payload
        )

        product, action = (
            amazon_catalog_repository.upsert(
                db=db,
                data=validated,
                source="manual",
                now=amazon_catalog_service.utc_now(),
            )
        )

        db.commit()
        db.refresh(product)

        return {
            "ok": True,
            "action": action,
            "warnings": validated.warnings,
            "product": serialize_product(product),
        }

    except ValueError as error:
        db.rollback()

        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    except IntegrityError as error:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail=(
                "Conflito ao salvar o produto. "
                "Verifique marketplace e ASIN."
            ),
        ) from error

    except Exception as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Erro ao salvar produto Amazon: {error}",
        ) from error


@router.post(
    "/products/import-csv",
    response_model=AmazonCsvImportResponse,
)
async def import_amazon_products_csv(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    filename = str(file.filename or "").lower()

    if not filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Envie um arquivo com extensao .csv.",
        )

    raw_content = await file.read()

    if len(raw_content) > 2 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="O CSV deve possuir no maximo 2 MB.",
        )

    try:
        csv_text = raw_content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="O CSV deve estar em UTF-8.",
        ) from error

    try:
        rows = amazon_catalog_service.parse_csv_text(
            csv_text
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    maximum_rows = amazon_catalog_service.csv_max_rows()

    if len(rows) > maximum_rows:
        raise HTTPException(
            status_code=400,
            detail=(
                f"O CSV possui {len(rows)} linhas. "
                f"Maximo permitido: {maximum_rows}."
            ),
        )

    created = 0
    updated = 0
    failed = 0
    results = []

    for row_number, row in enumerate(rows, start=2):
        savepoint = db.begin_nested()

        try:
            payload = (
                amazon_catalog_service.csv_row_to_payload(
                    row
                )
            )

            validated = (
                amazon_catalog_service.validate_product(
                    payload
                )
            )

            existing = (
                amazon_catalog_repository.get_by_identity(
                    db=db,
                    marketplace=validated.marketplace,
                    asin=validated.asin,
                )
            )

            predicted_action = (
                "updated"
                if existing is not None
                else "created"
            )

            if dry_run:
                action = predicted_action
                savepoint.rollback()
            else:
                _, action = (
                    amazon_catalog_repository.upsert(
                        db=db,
                        data=validated,
                        source="csv",
                        now=amazon_catalog_service.utc_now(),
                    )
                )

                savepoint.commit()

            if action == "created":
                created += 1
            else:
                updated += 1

            results.append(
                AmazonCsvRowResult(
                    row=row_number,
                    action=action,
                    marketplace=payload.marketplace.value,
                    asin=payload.asin,
                    title=payload.title,
                    warnings=validated.warnings,
                )
            )

        except Exception as error:
            savepoint.rollback()
            failed += 1

            results.append(
                AmazonCsvRowResult(
                    row=row_number,
                    marketplace=row.get("marketplace"),
                    asin=row.get("asin"),
                    title=row.get("title"),
                    error=str(error),
                )
            )

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "ok": failed == 0,
        "dry_run": dry_run,
        "processed": len(rows),
        "created": created,
        "updated": updated,
        "failed": failed,
        "results": results,
    }


@router.get(
    "/products",
    response_model=AmazonCatalogListResponse,
)
def list_amazon_products(
    marketplace: Optional[AmazonMarketplace] = Query(
        default=None
    ),
    catalog_status: Optional[AmazonCatalogStatus] = Query(
        default=None
    ),
    search: Optional[str] = Query(
        default=None,
        max_length=200,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(get_db),
):
    total, products = amazon_catalog_repository.list(
        db=db,
        marketplace=database_marketplace(marketplace),
        catalog_status=(
            catalog_status.value
            if catalog_status
            else None
        ),
        query_text=search,
        limit=limit,
        offset=offset,
    )

    return {
        "ok": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "products": [
            serialize_product(product)
            for product in products
        ],
    }


@router.get(
    "/products/template.csv",
    response_class=PlainTextResponse,
)
def download_amazon_csv_template():
    content = (
        "marketplace,asin,title,category,description,features,"
        "original_url,affiliate_url,associate_tag,image_url,"
        "price_text,currency,notes\n"
        "amazon_us,B012345678,Example Product,Electronics,"
        "Controlled description,"
        "\"Feature one|Feature two\","
        "https://www.amazon.com/dp/B012345678,"
        "PASTE_SITESTRIPE_LINK_HERE,,,"
        ",USD,Imported manually\n"
    )

    return PlainTextResponse(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="amazon_products_template.csv"'
            )
        },
    )


@router.get(
    "/products/{product_id}",
    response_model=AmazonProductResponse,
)
def get_amazon_product(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = amazon_catalog_repository.get(
        db=db,
        product_id=product_id,
    )

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Produto Amazon nao encontrado.",
        )

    return serialize_product(product)


@router.patch(
    "/products/{product_id}/status",
    response_model=AmazonProductResponse,
)
def update_amazon_product_status(
    product_id: int,
    payload: AmazonStatusUpdate,
    db: Session = Depends(get_db),
):
    product = amazon_catalog_repository.get(
        db=db,
        product_id=product_id,
    )

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Produto Amazon nao encontrado.",
        )

    try:
        amazon_catalog_repository.update_status(
            db=db,
            product=product,
            status=payload.status.value,
        )

        db.commit()
        db.refresh(product)

        return serialize_product(product)

    except Exception as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Erro ao atualizar status: {error}",
        ) from error


@router.delete(
    "/products/{product_id}",
    response_model=AmazonProductResponse,
)
def archive_amazon_product(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = amazon_catalog_repository.get(
        db=db,
        product_id=product_id,
    )

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Produto Amazon nao encontrado.",
        )

    try:
        amazon_catalog_repository.update_status(
            db=db,
            product=product,
            status="archived",
        )

        db.commit()
        db.refresh(product)

        return serialize_product(product)

    except Exception as error:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Erro ao arquivar produto: {error}",
        ) from error


@router.get(
    "/go/{product_id}",
    include_in_schema=True,
)
def redirect_to_amazon(
    product_id: int,
    request: Request,
    platform: Optional[str] = Query(
        default=None,
        max_length=50,
    ),
    campaign: Optional[str] = Query(
        default=None,
        max_length=100,
    ),
    db: Session = Depends(get_db),
):
    product = amazon_catalog_repository.get(
        db=db,
        product_id=product_id,
    )

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Produto Amazon nao encontrado.",
        )

    if product.catalog_status != "active":
        raise HTTPException(
            status_code=410,
            detail="Este link nao esta ativo.",
        )

    client_ip = (
        request.client.host
        if request.client
        else ""
    )

    ip_hash = None

    if client_ip:
        salt = os.getenv(
            "ATLAS_CLICK_HASH_SALT",
            "atlas-local-development",
        )

        ip_hash = hashlib.sha256(
            f"{salt}:{client_ip}".encode("utf-8")
        ).hexdigest()

    try:
        amazon_catalog_repository.register_click(
            db=db,
            product=product,
            platform=platform,
            campaign=campaign,
            referrer=request.headers.get("referer"),
            user_agent=request.headers.get("user-agent"),
            ip_hash=ip_hash,
        )

        db.commit()

    except Exception:
        db.rollback()

    return RedirectResponse(
        url=product.affiliate_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )