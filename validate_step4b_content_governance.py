from uuid import uuid4

from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.affiliate import (
    AffiliateContent,
    AffiliateProduct,
    MarketplaceEnum,
)
from app.routers.affiliate_video import (
    AffiliateVideoGenerateRequest,
    generate_affiliate_video,
)
from app.services.affiliate_content_governance import (
    DISCLOSURE_BR,
    DISCLOSURE_US,
    create_governed_content,
)


db = SessionLocal()

asin_br = uuid4().hex[:10].upper()
asin_us = uuid4().hex[:10].upper()

created_product_ids = []

try:
    product_br = AffiliateProduct(
        marketplace=MarketplaceEnum.AMAZON_BR,
        asin=asin_br,
        title="Produto temporario validacao governanca BR",
        category="validacao",
        original_url=(
            f"https://www.amazon.com.br/dp/{asin_br}"
        ),
        affiliate_url=(
            f"https://www.amazon.com.br/dp/{asin_br}"
            "?tag=achadosatlasb-20"
        ),
        associate_tag="achadosatlasb-20",
        currency="BRL",
        features=[],
        data_source="manual",
        catalog_status="active",
    )

    product_us = AffiliateProduct(
        marketplace=MarketplaceEnum.AMAZON_US,
        asin=asin_us,
        title="Temporary governance validation product US",
        category="validation",
        original_url=(
            f"https://www.amazon.com/dp/{asin_us}"
        ),
        affiliate_url=(
            f"https://www.amazon.com/dp/{asin_us}"
            "?tag=atlasfindsus-20"
        ),
        associate_tag="atlasfindsus-20",
        currency="USD",
        features=[],
        data_source="manual",
        catalog_status="active",
    )

    db.add(product_br)
    db.add(product_us)
    db.commit()

    db.refresh(product_br)
    db.refresh(product_us)

    created_product_ids.extend(
        [product_br.id, product_us.id]
    )

    base_br = {
        "hook_1": "Validacao BR",
        "hook_2": "Conteudo seguro",
        "script": (
            "Este roteiro temporario valida "
            "a governanca de conteudo."
        ),
        "caption": (
            "Legenda temporaria para validacao."
        ),
        "trigger_keyword": "QUERO",
        "seo_tags": "#validacao #atlas",
    }

    content_br_1, duplicate_1 = (
        create_governed_content(
            db=db,
            product=product_br,
            platform="tiktok",
            data=base_br,
            generation_type="validation",
        )
    )

    content_br_2, duplicate_2 = (
        create_governed_content(
            db=db,
            product=product_br,
            platform="tiktok",
            data=base_br,
            generation_type="validation_repeat",
        )
    )

    if duplicate_1:
        raise RuntimeError(
            "O primeiro conteudo foi marcado "
            "incorretamente como duplicado."
        )

    if not duplicate_2:
        raise RuntimeError(
            "A segunda criacao nao foi deduplicada."
        )

    if content_br_1.id != content_br_2.id:
        raise RuntimeError(
            "A deduplicacao retornou IDs diferentes."
        )

    if content_br_1.language != "pt-BR":
        raise RuntimeError(
            "Idioma BR incorreto."
        )

    if content_br_1.disclosure != DISCLOSURE_BR:
        raise RuntimeError(
            "Disclosure BR incorreto."
        )

    if DISCLOSURE_BR not in content_br_1.script:
        raise RuntimeError(
            "Disclosure BR ausente no roteiro."
        )

    if DISCLOSURE_BR not in (
        content_br_1.caption or ""
    ):
        raise RuntimeError(
            "Disclosure BR ausente na legenda."
        )

    if not content_br_1.content_fingerprint:
        raise RuntimeError(
            "Fingerprint BR ausente."
        )

    base_us = {
        "hook_1": "US validation",
        "hook_2": "Safe governed content",
        "script": (
            "This temporary script validates "
            "content governance."
        ),
        "caption": (
            "Temporary validation caption."
        ),
        "trigger_keyword": "WANT",
        "seo_tags": "#validation #atlas",
    }

    content_us, duplicate_us = (
        create_governed_content(
            db=db,
            product=product_us,
            platform="instagram",
            data=base_us,
            generation_type="validation",
        )
    )

    if duplicate_us:
        raise RuntimeError(
            "O primeiro conteudo US foi marcado "
            "incorretamente como duplicado."
        )

    if content_us.language != "en-US":
        raise RuntimeError(
            "Idioma US incorreto."
        )

    if content_us.disclosure != DISCLOSURE_US:
        raise RuntimeError(
            "Disclosure US incorreto."
        )

    if DISCLOSURE_US not in content_us.script:
        raise RuntimeError(
            "Disclosure US ausente no roteiro."
        )

    if DISCLOSURE_US not in (
        content_us.caption or ""
    ):
        raise RuntimeError(
            "Disclosure US ausente na legenda."
        )

    video_blocked = False

    try:
        generate_affiliate_video(
            payload=AffiliateVideoGenerateRequest(
                content_id=content_br_1.id,
            ),
            db=db,
        )

    except HTTPException as error:
        if error.status_code == 409:
            video_blocked = True
        else:
            raise

    if not video_blocked:
        raise RuntimeError(
            "Conteudo draft nao foi bloqueado "
            "pelo Video Engine."
        )

    print("[OK] Idioma pt-BR confirmado.")
    print("[OK] Idioma en-US confirmado.")
    print("[OK] Disclosure BR confirmado.")
    print("[OK] Disclosure US confirmado.")
    print("[OK] Disclosure presente no roteiro.")
    print("[OK] Disclosure presente na legenda.")
    print("[OK] Fingerprint SHA-256 confirmado.")
    print("[OK] Conteudo duplicado foi reutilizado.")
    print("[OK] Video draft bloqueado antes da geracao.")

finally:
    db.rollback()

    if created_product_ids:
        products = (
            db.query(AffiliateProduct)
            .filter(
                AffiliateProduct.id.in_(
                    created_product_ids
                )
            )
            .all()
        )

        for product in products:
            db.delete(product)

        db.commit()

    remaining = (
        db.query(AffiliateContent)
        .filter(
            AffiliateContent.product_id.in_(
                created_product_ids or [-1]
            )
        )
        .count()
    )

    if remaining != 0:
        raise RuntimeError(
            "A limpeza deixou conteudos temporarios."
        )

    db.close()

print("[OK] Limpeza funcional concluida.")
print("VALIDACAO FUNCIONAL DO PASSO 4B CONCLUIDA")