from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.affiliate import affiliate_repo
from app.schemas.affiliate import (
    ContentGenerateRequest,
    ContentResponse,
    ProductCreate,
    ProductResponse,
    ProductUpsertResponse,
)
from app.services.affiliate_service import affiliate_service


router = APIRouter(
    prefix="/affiliate",
    tags=["Affiliate Commerce"],
)


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
):
    """
    Cria ou atualiza um produto usando marketplace e ASIN como identidade.

    A resposta permanece compatível com o endpoint original.
    """
    try:
        saved_product, _ = affiliate_repo.upsert_product(db, product)
        return saved_product
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno ao salvar produto: {error}",
        )


@router.put(
    "/products/upsert",
    response_model=ProductUpsertResponse,
)
def upsert_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
):
    """
    Cria ou atualiza um produto e informa a ação executada.
    """
    try:
        saved_product, action = affiliate_repo.upsert_product(db, product)

        return {
            "action": action,
            "product": saved_product,
        }
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno ao salvar produto: {error}",
        )


@router.get(
    "/products",
    response_model=List[ProductResponse],
)
def list_products(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return affiliate_repo.list_products(
        db,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/products/{product_id}",
    response_model=ProductResponse,
)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = affiliate_repo.get_product(db, product_id)

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Produto não encontrado.",
        )

    return product


@router.post(
    "/content/generate",
    response_model=ContentResponse,
)
def generate_content(
    request: ContentGenerateRequest,
    db: Session = Depends(get_db),
):
    try:
        return affiliate_service.generate_sales_content(db, request)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno ao gerar conteúdo: {error}",
        )
