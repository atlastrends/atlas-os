from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.affiliate import AffiliateProduct, MarketplaceEnum
from app.repositories.affiliate import affiliate_repo
from app.schemas.affiliate import ProductCreate
from app.services.affiliate_content_governance import (
    create_governed_content,
)


router = APIRouter(prefix="/affiliate", tags=["Affiliate Manual Products"])


class ManualAffiliateProductImport(BaseModel):
    marketplace: MarketplaceEnum
    asin: str
    title: str
    category: Optional[str] = None
    original_url: str
    affiliate_url: str
    associate_tag: str
    price_text: Optional[str] = None
    currency: Optional[str] = None


MARKETPLACE_RULES = {
    MarketplaceEnum.AMAZON_BR: {
        "associate_tag": "achadosatlasb-20",
        "currency": "BRL",
        "label": "Amazon Brasil",
    },
    MarketplaceEnum.AMAZON_US: {
        "associate_tag": "atlasfindsus-20",
        "currency": "USD",
        "label": "Amazon USA",
    },
}


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _serialize_product(product: AffiliateProduct) -> Dict[str, Any]:
    return {
        "id": product.id,
        "marketplace": product.marketplace.value if product.marketplace else None,
        "asin": product.asin,
        "title": product.title,
        "category": product.category,
        "original_url": product.original_url,
        "affiliate_url": product.affiliate_url,
        "associate_tag": product.associate_tag,
        "price_text": product.price_text,
        "currency": product.currency,
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
    }


def _validate_manual_product(payload: ManualAffiliateProductImport) -> Dict[str, str]:
    rules = MARKETPLACE_RULES.get(payload.marketplace)

    if not rules:
        raise HTTPException(
            status_code=400,
            detail="Marketplace inválido. Use amazon_br ou amazon_us.",
        )

    asin = (_clean(payload.asin) or "").upper()
    title = _clean(payload.title)
    original_url = _clean(payload.original_url)
    affiliate_url = _clean(payload.affiliate_url)
    associate_tag = _clean(payload.associate_tag)
    currency = _clean(payload.currency) or rules["currency"]

    if not asin:
        raise HTTPException(status_code=400, detail="asin é obrigatório.")

    if not title:
        raise HTTPException(status_code=400, detail="title é obrigatório.")

    if not original_url:
        raise HTTPException(status_code=400, detail="original_url é obrigatório.")

    if not affiliate_url:
        raise HTTPException(status_code=400, detail="affiliate_url é obrigatório.")

    if not associate_tag:
        raise HTTPException(status_code=400, detail="associate_tag é obrigatório.")

    expected_tag = rules["associate_tag"]
    expected_currency = rules["currency"]

    if associate_tag != expected_tag:
        raise HTTPException(
            status_code=400,
            detail=(
                f"associate_tag inválido para {rules['label']}. "
                f"Esperado: {expected_tag}"
            ),
        )

    if currency != expected_currency:
        raise HTTPException(
            status_code=400,
            detail=(
                f"currency inválida para {rules['label']}. "
                f"Esperado: {expected_currency}"
            ),
        )

    return {
        "asin": asin,
        "title": title,
        "original_url": original_url,
        "affiliate_url": affiliate_url,
        "associate_tag": associate_tag,
        "currency": currency,
    }


@router.post("/products/import-manual")
def import_manual_affiliate_product(
    payload: ManualAffiliateProductImport,
    db: Session = Depends(get_db),
):
    """
    Importa ou atualiza um produto manual usando marketplace e ASIN
    como identidade.

    A validação comercial permanece nesta rota. A persistência e o
    tratamento de concorrência ficam centralizados no repository.
    """
    validated = _validate_manual_product(payload)

    product_input = ProductCreate(
        marketplace=payload.marketplace.value,
        asin=validated["asin"],
        title=validated["title"],
        category=_clean(payload.category),
        original_url=validated["original_url"],
        affiliate_url=validated["affiliate_url"],
        associate_tag=validated["associate_tag"],
        price_text=_clean(payload.price_text),
        currency=validated["currency"],
    )

    try:
        product, action = affiliate_repo.upsert_product(
            db=db,
            product_in=product_input,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno ao importar produto: {error}",
        )

    if action == "created":
        message = "Produto importado com sucesso."
    else:
        message = "Produto já existia e foi atualizado."

    return {
        "ok": True,
        "action": action,
        "message": message,
        "product": _serialize_product(product),
    }

@router.get("/manage/products")
def list_affiliate_products(
    marketplace: Optional[MarketplaceEnum] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(AffiliateProduct)

    if marketplace:
        query = query.filter(AffiliateProduct.marketplace == marketplace)

    total = query.count()

    products = (
        query.order_by(AffiliateProduct.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "ok": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "products": [_serialize_product(product) for product in products],
    }


@router.get("/manage/products/{product_id}")
def get_affiliate_product(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = (
        db.query(AffiliateProduct)
        .filter(AffiliateProduct.id == product_id)
        .first()
    )

    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    return {
        "ok": True,
        "product": _serialize_product(product),
    }

from pydantic import BaseModel as SmartBaseModel
from app.models.affiliate import AffiliateContent, ContentStatusEnum


class SmartAffiliateContentGenerateRequest(SmartBaseModel):
    product_id: int
    platform: str = "tiktok"


def _normalize_platform(platform: str) -> str:
    value = (platform or "tiktok").strip().lower()
    if value in ["tik tok", "tik-tok"]:
        return "tiktok"
    if value in ["youtube shorts", "shorts"]:
        return "youtube"
    if value in ["instagram reels", "reels"]:
        return "instagram"
    return value


def _serialize_content(content: AffiliateContent):
    return {
        "id": content.id,
        "product_id": content.product_id,
        "platform": content.platform,
        "hook_1": content.hook_1,
        "hook_2": content.hook_2,
        "script": content.script,
        "caption": content.caption,
        "trigger_keyword": content.trigger_keyword,
        "seo_tags": content.seo_tags,
        "language": content.language,
        "disclosure": content.disclosure,
        "content_fingerprint": content.content_fingerprint,
        "generation_type": content.generation_type,
        "review_notes": content.review_notes,
        "reviewed_at": (
            content.reviewed_at.isoformat()
            if content.reviewed_at
            else None
        ),
        "approved_at": (
            content.approved_at.isoformat()
            if content.approved_at
            else None
        ),
        "status": content.status.value if content.status else None,
        "created_at": content.created_at.isoformat() if content.created_at else None,
        "updated_at": content.updated_at.isoformat() if content.updated_at else None,
    }


def _build_br_content(product: AffiliateProduct, platform: str):
    price_part = ""
    if product.price_text:
        price_part = f" Ele aparece listado por {product.price_text}."

    category = product.category or "achados da Amazon"

    hook_1 = "Achei um produto na Amazon que muita gente vai querer ver"
    hook_2 = "Esse achado pode facilitar sua rotina"

    script = (
        f"Olha esse achado da Amazon: {product.title}. "
        f"Ele está na categoria {category}.{price_part} "
        f"A ideia aqui é simples: mostrar um produto útil, fácil de entender e que pode resolver uma necessidade do dia a dia. "
        f"Antes de comprar, confira os detalhes, avaliações, prazo de entrega e veja se faz sentido para você. "
        f"Se quiser o link direto, comenta QUERO que eu te envio."
    )

    caption = (
        f"Achado Amazon: {product.title}. "
        f"Comente QUERO para receber o link direto."
    )

    trigger_keyword = "QUERO"

    seo_tags = (
        "#achadosamazon #achadinhos #comprasonline #amazonbrasil "
        "#ofertasamazon #tiktokmademebuyit #produto"
    )

    return hook_1, hook_2, script, caption, trigger_keyword, seo_tags


def _build_us_content(product: AffiliateProduct, platform: str):
    price_part = ""
    if product.price_text:
        price_part = f" It's currently listed at {product.price_text}."

    category = product.category or "Amazon finds"

    hook_1 = "I found an Amazon product you might want to see"
    hook_2 = "This Amazon find could make your routine easier"

    script = (
        f"Check out this Amazon find: {product.title}. "
        f"It's in the {category} category.{price_part} "
        f"The idea is simple: highlight a useful product that is easy to understand and could solve an everyday problem. "
        f"Before buying, make sure to check the details, reviews, delivery options, and decide if it makes sense for you. "
        f"If you want the direct link, comment WANT and I'll send it to you."
    )

    caption = (
        f"Amazon find: {product.title}. "
        f"Comment WANT and I'll send you the direct link."
    )

    trigger_keyword = "WANT"

    seo_tags = (
        "#amazonfinds #amazonmusthaves #tiktokmademebuyit #onlineshopping "
        "#usefulproducts #productfinds #deals"
    )

    return hook_1, hook_2, script, caption, trigger_keyword, seo_tags


@router.post("/content/generate-smart")
def generate_smart_affiliate_content(
    payload: SmartAffiliateContentGenerateRequest,
    db: Session = Depends(get_db),
):
    product = (
        db.query(AffiliateProduct)
        .filter(AffiliateProduct.id == payload.product_id)
        .first()
    )

    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    platform = _normalize_platform(payload.platform)

    if product.marketplace == MarketplaceEnum.AMAZON_US:
        hook_1, hook_2, script, caption, trigger_keyword, seo_tags = _build_us_content(product, platform)
    else:
        hook_1, hook_2, script, caption, trigger_keyword, seo_tags = _build_br_content(product, platform)


    content, _ = create_governed_content(
        db=db,
        product=product,
        platform=platform,
        data={
            "hook_1": hook_1,
            "hook_2": hook_2,
            "script": script,
            "caption": caption,
            "trigger_keyword": trigger_keyword,
            "seo_tags": seo_tags,
        },
        generation_type="smart",
    )

    return _serialize_content(content)


from typing import List as PitchList
from pydantic import BaseModel as PitchBaseModel, Field as PitchField


class PitchAffiliateContentGenerateRequest(PitchBaseModel):
    product_id: int
    platform: str = "tiktok"

    audience: Optional[str] = None
    product_context: Optional[str] = None
    emotional_angle: Optional[str] = None
    urgency_angle: Optional[str] = None

    pain_points: PitchList[str] = PitchField(default_factory=list)
    key_benefits: PitchList[str] = PitchField(default_factory=list)
    proof_points: PitchList[str] = PitchField(default_factory=list)


def _lower_text(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _is_generic_test_product(product: AffiliateProduct) -> bool:
    text = _lower_text(f"{product.title} {product.category} {product.asin}")
    generic_terms = [
        "produto teste",
        "test product",
        "b0teste",
        "b0test",
        "produto genérico",
        "generic product",
    ]
    return any(term in text for term in generic_terms)


def _detect_pitch_profile(product: AffiliateProduct, is_us: bool) -> Dict[str, Any]:
    text = _lower_text(f"{product.title} {product.category}")

    if any(k in text for k in ["microfone", "microphone", "mic", "condensador", "condenser"]):
        if is_us:
            return {
                "audience": "content creators, streamers, remote workers, podcasters, and anyone recording videos",
                "pain": "bad audio makes your content feel cheap before people even care about what you are saying",
                "consequence": "people scroll away, meetings feel less professional, and your message loses impact",
                "benefit": "cleaner, more present voice capture with a simple USB setup",
                "desire": "sound more professional without building a full studio",
                "proof": "USB microphones are popular because they are simple, practical, and easy to use for daily recording",
                "tags": "#microphone #contentcreator #streamingsetup #podcastgear #amazonfinds #tiktokmademebuyit",
            }

        return {
            "audience": "criadores de conteúdo, streamers, pessoas que gravam vídeos, reuniões, aulas ou podcasts",
            "pain": "áudio ruim faz seu vídeo parecer amador antes mesmo da pessoa prestar atenção no que você está falando",
            "consequence": "a pessoa perde interesse, passa para o próximo vídeo e sua mensagem morre ali",
            "benefit": "voz mais limpa, mais presente e com aparência mais profissional usando uma conexão USB simples",
            "desire": "gravar com mais qualidade sem montar um estúdio caro",
            "proof": "microfones USB são populares porque unem praticidade, instalação simples e melhora perceptível na gravação",
            "tags": "#microfone #criadoresdeconteudo #setup #podcastbrasil #achadosamazon #tiktokmademebuyit",
        }

    if any(k in text for k in ["organizador", "organizer", "cable", "cabos", "storage"]):
        if is_us:
            return {
                "audience": "people tired of messy desks, drawers, cables, and small items everywhere",
                "pain": "visual mess makes your space feel chaotic and wastes your time every single day",
                "consequence": "you keep losing things, your desk looks stressful, and your routine starts already messy",
                "benefit": "keeps items easier to find, easier to store, and easier to keep under control",
                "desire": "make your space feel cleaner, calmer, and more organized fast",
                "proof": "simple organizers work because they remove friction from daily routines",
                "tags": "#organization #desksetup #homeorganization #amazonfinds #usefulproducts",
            }

        return {
            "audience": "pessoas cansadas de bagunça na mesa, gaveta, cabos e pequenos objetos espalhados",
            "pain": "bagunça visual deixa sua rotina mais cansativa e faz você perder tempo todos os dias",
            "consequence": "você procura coisas simples, se irrita e sente que o ambiente nunca fica realmente em ordem",
            "benefit": "deixa os itens mais fáceis de guardar, encontrar e manter organizados",
            "desire": "transformar o espaço em algo mais limpo, prático e agradável rapidamente",
            "proof": "organizadores simples funcionam porque removem atrito das tarefas do dia a dia",
            "tags": "#organizacao #casaorganizada #achadosamazon #achadinhos #produtoutil",
        }

    if any(k in text for k in ["cozinha", "kitchen", "cortador", "slicer", "utensil", "air fryer"]):
        if is_us:
            return {
                "audience": "people who cook at home and want faster, easier kitchen routines",
                "pain": "small kitchen tasks steal more time and patience than they should",
                "consequence": "cooking feels harder, cleanup feels annoying, and you avoid making what you actually want",
                "benefit": "helps make food prep simpler, faster, or less frustrating",
                "desire": "make the kitchen feel easier and more satisfying to use",
                "proof": "practical kitchen tools sell because they solve visible everyday problems",
                "tags": "#kitchenfinds #amazonfinds #kitchengadgets #homecooking #tiktokmademebuyit",
            }

        return {
            "audience": "pessoas que cozinham em casa e querem praticidade",
            "pain": "tarefas pequenas na cozinha roubam tempo, paciência e energia todos os dias",
            "consequence": "cozinhar vira uma obrigação chata, a bagunça aumenta e você perde vontade de preparar as coisas",
            "benefit": "ajuda a deixar o preparo mais simples, rápido ou menos irritante",
            "desire": "sentir prazer em usar a cozinha sem sofrer com cada detalhe",
            "proof": "gadgets de cozinha vendem bem porque mostram o benefício de forma visual e imediata",
            "tags": "#cozinha #gadgetsdecozinha #achadosamazon #casapratica #tiktokmademebuyit",
        }

    if any(k in text for k in ["pet", "dog", "cat", "gato", "cachorro", "pelos", "hair remover"]):
        if is_us:
            return {
                "audience": "pet owners tired of fur on clothes, sofas, carpets, and car seats",
                "pain": "pet hair makes your home look dirty even right after cleaning",
                "consequence": "your clothes, couch, and car keep looking messy no matter how much you clean",
                "benefit": "helps remove or control pet hair in a more practical way",
                "desire": "enjoy your pet without feeling like fur has taken over your home",
                "proof": "pet cleaning products are popular because the problem is constant and visible",
                "tags": "#petfinds #dogmom #catmom #amazonfinds #petproducts #cleanhome",
            }

        return {
            "audience": "donos de pets cansados de pelo em roupa, sofá, tapete e banco do carro",
            "pain": "pelo de pet faz a casa parecer suja mesmo depois de limpar",
            "consequence": "você limpa, passa pano, tira pelo, e em pouco tempo parece que voltou tudo de novo",
            "benefit": "ajuda a remover ou controlar pelos de forma mais prática",
            "desire": "curtir seu pet sem sentir que a casa foi dominada por pelos",
            "proof": "produtos para remover pelo vendem porque resolvem um problema constante e visível",
            "tags": "#pets #cachorro #gato #achadosamazon #casalimpa #donosdepet",
        }

    return {}


def _pick_first(values: PitchList[str], fallback: str) -> str:
    for value in values:
        clean = (value or "").strip()
        if clean:
            return clean
    return fallback


def _join_points(values: PitchList[str], fallback: str) -> str:
    cleaned = [v.strip() for v in values if v and v.strip()]
    if cleaned:
        return "; ".join(cleaned[:3])
    return fallback


def _build_pitch_content(
    product: AffiliateProduct,
    payload: PitchAffiliateContentGenerateRequest,
):
    is_us = product.marketplace == MarketplaceEnum.AMAZON_US
    profile = _detect_pitch_profile_v2(product, is_us)

    has_manual_context = any([
        payload.audience,
        payload.product_context,
        payload.emotional_angle,
        payload.urgency_angle,
        payload.pain_points,
        payload.key_benefits,
        payload.proof_points,
    ])

    if not profile and not has_manual_context:
        if _is_generic_test_product(product):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Produto teste ou genérico não permite pitch específico. "
                    "Use um produto real ou envie product_context, pain_points e key_benefits."
                ),
            )

    price = product.price_text or ""
    category = product.category or ("Amazon Finds" if is_us else "Achados Amazon")

    audience = payload.audience or profile.get("audience") or (
        "people who want a practical product that solves a real everyday problem"
        if is_us else
        "pessoas que querem um produto prático para resolver um problema real do dia a dia"
    )

    pain = _pick_first(
        payload.pain_points,
        profile.get("pain") or (
            "you keep dealing with a problem that should have been solved already"
            if is_us else
            "você continua convivendo com um problema que já deveria ter sido resolvido"
        )
    )

    consequence = profile.get("consequence") or (
        "the frustration keeps repeating every day"
        if is_us else
        "a frustração se repete todos os dias"
    )

    benefit = _pick_first(
        payload.key_benefits,
        profile.get("benefit") or (
            "makes the routine simpler, faster, or less stressful"
            if is_us else
            "deixa a rotina mais simples, rápida ou menos estressante"
        )
    )

    benefits_joined = _join_points(
        payload.key_benefits,
        profile.get("benefit") or benefit
    )

    proof = _join_points(
        payload.proof_points,
        profile.get("proof") or (
            "the value is in solving a problem people actually feel"
            if is_us else
            "o valor está em resolver um problema que a pessoa realmente sente"
        )
    )

    desire = payload.emotional_angle or profile.get("desire") or (
        "feel the relief of finally having a simple solution"
        if is_us else
        "sentir o alívio de finalmente ter uma solução simples"
    )

    urgency = payload.urgency_angle or (
        "If this is exactly the problem you keep dealing with, do not ignore it."
        if is_us else
        "Se esse é exatamente o problema que você enfrenta, não ignora isso."
    )

    context = payload.product_context or ""

    if is_us:
        hook_1 = f"If {pain}, this Amazon find deserves your attention."
        hook_2 = f"Stop accepting this problem as normal."

        price_line = f" It's listed at {price}." if price else ""

        script = (
            f"If {pain}, pay attention. "
            f"The worst part is that {consequence}. "
            f"This is where {product.title} comes in. "
            f"It is made for {audience}, especially if you want to {desire}. "
            f"The main reason this makes sense is simple: {benefit}. "
            f"In practical terms, it helps with: {benefits_joined}. "
        )

        if context:
            script += f"Important detail: {context}. "

        script += (
            f"And the proof angle is this: {proof}.{price_line} "
            f"{urgency} Before buying, check the details, reviews, and delivery options. "
            f"If you want the direct link, comment WANT and I will send it to you."
        )

        caption = (
            f"This Amazon find solves a real problem: {product.title}. "
            f"Comment WANT and I will send you the direct link."
        )

        trigger_keyword = "WANT"
        seo_tags = profile.get("tags") or "#amazonfinds #amazonmusthaves #usefulproducts #tiktokmademebuyit #productfinds"

    else:
        hook_1 = f"Se {pain}, você precisa ver esse achado."
        hook_2 = "Para de aceitar esse problema como se fosse normal."

        price_line = f" Ele aparece listado por {price}." if price else ""

        script = (
            f"Se {pain}, presta atenção. "
            f"O pior é que {consequence}. "
            f"É aqui que entra o {product.title}. "
            f"Ele faz sentido para {audience}, principalmente se você quer {desire}. "
            f"O motivo principal é simples: {benefit}. "
            f"Na prática, ele ajuda com: {benefits_joined}. "
        )

        if context:
            script += f"Detalhe importante: {context}. "

        script += (
            f"E o argumento forte é esse: {proof}.{price_line} "
            f"{urgency} Antes de comprar, confira detalhes, avaliações e prazo de entrega. "
            f"Se quiser o link direto, comenta QUERO que eu te envio."
        )

        caption = (
            f"Esse achado resolve uma dor real: {product.title}. "
            f"Comente QUERO para receber o link direto."
        )

        trigger_keyword = "QUERO"
        seo_tags = profile.get("tags") or "#achadosamazon #achadinhos #produtoutil #comprasonline #tiktokmademebuyit"

    return hook_1, hook_2, script, caption, trigger_keyword, seo_tags


@router.post("/content/generate-pitch")
def generate_pitch_affiliate_content(
    payload: PitchAffiliateContentGenerateRequest,
    db: Session = Depends(get_db),
):
    product = (
        db.query(AffiliateProduct)
        .filter(AffiliateProduct.id == payload.product_id)
        .first()
    )

    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    platform = _normalize_platform(payload.platform)

    hook_1, hook_2, script, caption, trigger_keyword, seo_tags = _build_pitch_content(
        product=product,
        payload=payload,
    )


    content, _ = create_governed_content(
        db=db,
        product=product,
        platform=platform,
        data={
            "hook_1": hook_1,
            "hook_2": hook_2,
            "script": script,
            "caption": caption,
            "trigger_keyword": trigger_keyword,
            "seo_tags": seo_tags,
        },
        generation_type="pitch",
    )

    return _serialize_content(content)



def _detect_pitch_profile_v2(product: AffiliateProduct, is_us: bool) -> Dict[str, Any]:
    text = _lower_text(f"{product.title} {product.category}")

    # MICROPHONE / AUDIO
    if any(k in text for k in ["microfone", "microphone", "mic", "condensador", "condenser"]):
        if is_us:
            return {
                "product_type": "microphone",
                "audience": "content creators, streamers, online teachers, sellers, podcasters, and people recording from a computer",
                "pain": "your voice sounds muffled, distant, or amateur",
                "consequence": "people scroll away, your content feels less trustworthy, and your message loses power",
                "benefit": "clearer and more present voice capture with a simple USB setup",
                "desire": "sound more professional without building an expensive studio",
                "proof": "audio quality changes how professional your content feels almost immediately",
                "tags": "#microphone #contentcreator #streamingsetup #podcastgear #amazonfinds #tiktokmademebuyit",
            }

        return {
            "product_type": "microfone",
            "audience": "criadores de conteúdo, streamers, professores online, vendedores, podcasters e pessoas que gravam pelo computador",
            "pain": "seu áudio sai abafado, distante ou com cara de amador",
            "consequence": "as pessoas passam para o próximo vídeo, sua mensagem perde força e seu conteúdo parece menos confiável",
            "benefit": "voz mais clara, mais presente e com aparência mais profissional usando uma conexão USB simples",
            "desire": "gravar com confiança sem precisar montar um estúdio caro",
            "proof": "a qualidade do áudio muda quase imediatamente a percepção profissional do seu conteúdo",
            "tags": "#microfone #criadoresdeconteudo #setup #podcastbrasil #achadosamazon #tiktokmademebuyit",
        }

    # BALL / SPORTS BALL
    if any(k in text for k in ["bola", "ball", "soccer", "football", "basketball", "voleibol", "vôlei", "volei", "basquete", "futebol"]):
        if is_us:
            return {
                "product_type": "sports ball",
                "audience": "people who play sports, train with friends, practice at home, or want a fun gift",
                "pain": "you want to play, train, or have fun but the ball you use feels worn out, weak, or unreliable",
                "consequence": "the game loses quality, the passes feel off, and the fun disappears faster than it should",
                "benefit": "a better ball makes practice, casual games, and weekend matches feel more enjoyable",
                "desire": "feel ready to play anytime without depending on a bad old ball",
                "proof": "a good ball changes touch, control, confidence, and the overall feel of the game",
                "tags": "#sports #soccerball #basketball #sportgear #amazonfinds #active lifestyle",
            }

        return {
            "product_type": "bola",
            "audience": "pessoas que jogam, treinam, brincam com amigos, praticam esporte ou querem um presente útil",
            "pain": "você quer jogar ou treinar, mas a bola velha já está murcha, gasta ou ruim de controlar",
            "consequence": "o jogo perde qualidade, o passe sai estranho, o chute não encaixa e a diversão acaba mais rápido",
            "benefit": "uma bola melhor deixa treino, partidas casuais e brincadeiras muito mais prazerosas",
            "desire": "ter vontade de jogar a qualquer hora sem depender de uma bola ruim",
            "proof": "uma boa bola muda o toque, o controle, a confiança e a experiência do jogo",
            "tags": "#bola #futebol #esporte #treino #achadosamazon #presentescriativos",
        }

    # TV / SMART TV
    if any(k in text for k in ["tv", "televisão", "televisao", "smart tv", "television", "4k", "oled", "qled", "led tv"]):
        if is_us:
            return {
                "product_type": "TV",
                "audience": "people who watch movies, series, sports, YouTube, or play games at home",
                "pain": "your current screen makes movies, games, and shows feel smaller, darker, or less exciting than they should",
                "consequence": "you keep paying for streaming, games, and entertainment but experience it on a screen that does not deliver the full impact",
                "benefit": "a better TV can make your living room feel more immersive for movies, sports, and gaming",
                "desire": "turn your home into a more exciting entertainment space",
                "proof": "screen size, image quality, and smart features directly change how enjoyable home entertainment feels",
                "tags": "#smarttv #hometheater #gamingtv #amazonfinds #techfinds #movie night",
            }

        return {
            "product_type": "TV",
            "audience": "pessoas que assistem filmes, séries, futebol, YouTube ou jogam em casa",
            "pain": "sua tela atual deixa filmes, jogos e séries com menos impacto do que deveriam ter",
            "consequence": "você paga streaming, internet e jogos, mas continua vivendo a experiência numa tela que não entrega emoção",
            "benefit": "uma TV melhor transforma sala, quarto ou área de lazer em uma experiência muito mais imersiva",
            "desire": "sentir clima de cinema, estádio ou game room dentro de casa",
            "proof": "tamanho de tela, qualidade de imagem e recursos smart mudam diretamente o prazer de assistir",
            "tags": "#smarttv #tv4k #cinemaemcasa #tecnologia #achadosamazon #games",
        }

    # HAIR DRYER
    if any(k in text for k in ["secador", "hair dryer", "dryer", "blow dryer", "cabelo", "hair styling"]):
        if is_us:
            return {
                "product_type": "hair dryer",
                "audience": "people who dry or style their hair at home and want faster, better-looking results",
                "pain": "wet hair, frizz, and rushed mornings can make you feel messy before the day even starts",
                "consequence": "you lose time, get frustrated, and still leave the house without the look you wanted",
                "benefit": "a good hair dryer helps make drying and styling faster, easier, and more controlled",
                "desire": "feel like you left the salon without actually going to the salon",
                "proof": "heat, airflow, and styling control make a visible difference in everyday hair routines",
                "tags": "#hairdryer #hairstyling #beautyfinds #amazonfinds #selfcare #haircare",
            }

        return {
            "product_type": "secador de cabelo",
            "audience": "pessoas que secam ou modelam o cabelo em casa e querem resultado mais bonito sem perder tempo",
            "pain": "cabelo molhado, frizz e pressa de manhã acabam com sua paciência antes do dia começar",
            "consequence": "você perde tempo, se irrita e ainda sai de casa sem o visual que queria",
            "benefit": "um bom secador ajuda a secar e modelar com mais rapidez, controle e praticidade",
            "desire": "sentir resultado de salão sem precisar ir ao salão toda vez",
            "proof": "potência, fluxo de ar e controle de temperatura fazem diferença visível na rotina do cabelo",
            "tags": "#secadordecabelo #cabelos #beleza #autocuidado #achadosamazon #rotinadebeleza",
        }

    # HEADPHONES / EARBUDS / HEADSET
    if any(k in text for k in ["fone", "headphone", "earbuds", "earbud", "headset", "bluetooth", "airpods", "fone de ouvido"]):
        if is_us:
            return {
                "product_type": "headphones",
                "audience": "people who listen to music, work, study, train, commute, or play games",
                "pain": "bad headphones ruin music, calls, workouts, and focus",
                "consequence": "you keep dealing with weak sound, annoying noise, uncomfortable fit, or calls where people cannot hear you clearly",
                "benefit": "better headphones can improve focus, sound, calls, and comfort during everyday use",
                "desire": "feel more immersed, focused, and free without fighting with bad audio",
                "proof": "comfort, battery, connection, and sound quality directly affect how often you actually enjoy using headphones",
                "tags": "#headphones #earbuds #techfinds #amazonfinds #workfromhome #music",
            }

        return {
            "product_type": "fone de ouvido",
            "audience": "pessoas que ouvem música, trabalham, estudam, treinam, viajam ou jogam",
            "pain": "fone ruim acaba com música, chamada, treino e concentração",
            "consequence": "você convive com som fraco, ruído irritante, desconforto ou ligação onde ninguém te escuta direito",
            "benefit": "um fone melhor pode melhorar foco, som, chamadas e conforto no dia a dia",
            "desire": "sentir mais imersão, liberdade e concentração sem brigar com áudio ruim",
            "proof": "conforto, bateria, conexão e qualidade sonora mudam totalmente a vontade de usar um fone todos os dias",
            "tags": "#fonedeouvido #bluetooth #tecnologia #achadosamazon #setup #musica",
        }

    # VACUUM / CLEANING
    if any(k in text for k in ["aspirador", "vacuum", "robo", "robô", "robot vacuum", "limpeza", "cleaner"]):
        if is_us:
            return {
                "product_type": "vacuum cleaner",
                "audience": "people tired of dust, crumbs, pet hair, and daily mess at home",
                "pain": "the house gets dirty again right after you clean it",
                "consequence": "dust, crumbs, and hair keep coming back, making your home feel messy even when you try to keep it clean",
                "benefit": "a practical vacuum helps make cleaning faster and less exhausting",
                "desire": "feel like your home stays cleaner with less effort",
                "proof": "cleaning tools sell because they solve a visible problem people face every day",
                "tags": "#cleaning #vacuum #homefinds #amazonfinds #cleanhome #pet hair",
            }

        return {
            "product_type": "aspirador",
            "audience": "pessoas cansadas de poeira, farelo, cabelo, pelo de pet e sujeira diária em casa",
            "pain": "a casa parece sujar de novo logo depois que você limpa",
            "consequence": "poeira, farelo e pelos voltam rápido, e o ambiente parece bagunçado mesmo com esforço",
            "benefit": "um aspirador prático deixa a limpeza mais rápida e menos cansativa",
            "desire": "sentir a casa limpa por mais tempo sem sofrer tanto na faxina",
            "proof": "produtos de limpeza vendem porque resolvem um problema visível e repetitivo",
            "tags": "#aspirador #limpeza #casalimpa #achadosamazon #donadecasa #pets",
        }

    # THERMAL BOTTLE / CUP
    if any(k in text for k in ["garrafa", "copo térmico", "copo termico", "thermal", "tumbler", "water bottle", "bottle", "stanley"]):
        if is_us:
            return {
                "product_type": "thermal bottle",
                "audience": "people who work, study, train, drive, travel, or want drinks at the right temperature",
                "pain": "your drink gets warm, cold, or unpleasant exactly when you wanted to enjoy it",
                "consequence": "you waste drinks, buy more outside, and never have the temperature you actually wanted",
                "benefit": "a good thermal cup or bottle keeps your drink more enjoyable for longer",
                "desire": "have your coffee, water, or drink ready the way you like it during the day",
                "proof": "thermal bottles are popular because they solve a daily comfort problem in a simple way",
                "tags": "#tumbler #waterbottle #amazonfinds #dailyessentials #worksetup #gym",
            }

        return {
            "product_type": "garrafa térmica ou copo térmico",
            "audience": "pessoas que trabalham, estudam, treinam, dirigem, viajam ou gostam de bebida na temperatura certa",
            "pain": "sua bebida esquenta, esfria ou fica ruim justamente quando você queria aproveitar",
            "consequence": "você desperdiça bebida, compra fora e nunca tem a temperatura do jeito que queria",
            "benefit": "um bom copo ou garrafa térmica mantém sua bebida agradável por muito mais tempo",
            "desire": "ter café, água ou bebida pronta do jeito que você gosta durante o dia",
            "proof": "copos e garrafas térmicas vendem porque resolvem um problema diário de conforto e praticidade",
            "tags": "#copotermico #garrafatermica #achadosamazon #rotinapratica #trabalho #academia",
        }

    # BACKPACK
    if any(k in text for k in ["mochila", "backpack", "bag", "bolsa", "laptop bag"]):
        if is_us:
            return {
                "product_type": "backpack",
                "audience": "students, workers, travelers, commuters, and people carrying tech or daily essentials",
                "pain": "carrying your things in a messy or uncomfortable bag makes every trip more annoying",
                "consequence": "your laptop, charger, documents, and small items get mixed up, and your shoulders feel it",
                "benefit": "a better backpack helps organize, protect, and carry your essentials more comfortably",
                "desire": "move through the day feeling prepared instead of messy",
                "proof": "organization, comfort, and compartments make a visible difference in everyday carry",
                "tags": "#backpack #everydaycarry #workbag #studentlife #amazonfinds #travel",
            }

        return {
            "product_type": "mochila",
            "audience": "estudantes, trabalhadores, viajantes e pessoas que carregam notebook ou itens do dia a dia",
            "pain": "carregar tudo em uma bolsa bagunçada ou desconfortável deixa qualquer saída mais irritante",
            "consequence": "notebook, carregador, documentos e objetos pequenos ficam misturados, e quem sente é seu ombro",
            "benefit": "uma mochila melhor ajuda a organizar, proteger e carregar seus itens com mais conforto",
            "desire": "sair de casa preparado, organizado e sem aquela sensação de caos",
            "proof": "organização, conforto e divisórias mudam muito a experiência de carregar coisas todos os dias",
            "tags": "#mochila #trabalho #faculdade #viagem #achadosamazon #organizacao",
        }

    # LAMP / LIGHT
    if any(k in text for k in ["luminária", "luminaria", "lamp", "light", "led", "ring light", "abajur"]):
        if is_us:
            return {
                "product_type": "lamp or light",
                "audience": "people who work, study, read, create content, or want a better-looking room",
                "pain": "bad lighting makes your space look dull, tired, and uncomfortable",
                "consequence": "your desk, videos, reading, or room vibe never feels as good as it could",
                "benefit": "better lighting can improve focus, comfort, and the way your space looks",
                "desire": "make your room or setup feel cleaner, warmer, and more intentional",
                "proof": "lighting changes how a space feels instantly",
                "tags": "#lighting #desksetup #roomdecor #amazonfinds #ledlight #homeoffice",
            }

        return {
            "product_type": "luminária",
            "audience": "pessoas que trabalham, estudam, leem, gravam conteúdo ou querem deixar o ambiente mais bonito",
            "pain": "luz ruim deixa seu ambiente apagado, cansativo e desconfortável",
            "consequence": "sua mesa, seus vídeos, sua leitura ou seu quarto nunca ficam com a aparência que poderiam ter",
            "benefit": "uma iluminação melhor pode melhorar foco, conforto e estética do ambiente",
            "desire": "deixar quarto, setup ou escritório com aparência mais bonita e intencional",
            "proof": "iluminação muda a sensação de um ambiente quase instantaneamente",
            "tags": "#luminaria #setup #decoracao #homeoffice #achadosamazon #led",
        }

    # CHARGER / POWER BANK
    if any(k in text for k in ["carregador", "charger", "power bank", "powerbank", "bateria portátil", "bateria portatil", "usb-c", "magsafe"]):
        if is_us:
            return {
                "product_type": "charger or power bank",
                "audience": "people who use their phone all day, travel, work outside, or hate low battery anxiety",
                "pain": "your battery dies exactly when you need your phone the most",
                "consequence": "you lose access to messages, maps, payments, content, and work at the worst moment",
                "benefit": "a reliable charger or power bank gives you more freedom and less battery anxiety",
                "desire": "leave home knowing your phone will not control your day",
                "proof": "charging accessories are daily essentials because battery anxiety is real",
                "tags": "#charger #powerbank #techfinds #amazonfinds #travelessentials #phoneaccessories",
            }

        return {
            "product_type": "carregador ou power bank",
            "audience": "pessoas que usam celular o dia todo, viajam, trabalham fora ou odeiam ficar sem bateria",
            "pain": "sua bateria acaba justamente quando você mais precisa do celular",
            "consequence": "você fica sem mensagem, mapa, pagamento, conteúdo e trabalho no pior momento possível",
            "benefit": "um carregador ou power bank confiável dá mais liberdade e menos ansiedade com bateria",
            "desire": "sair de casa sabendo que o celular não vai mandar no seu dia",
            "proof": "acessórios de carregamento vendem porque bateria baixa é uma dor diária e real",
            "tags": "#carregador #powerbank #tecnologia #achadosamazon #celular #viagem",
        }

    # ORGANIZER
    if any(k in text for k in ["organizador", "organizer", "cable", "cabos", "storage", "gaveta"]):
        if is_us:
            return {
                "product_type": "organizer",
                "audience": "people tired of messy desks, drawers, cables, and small items everywhere",
                "pain": "visual mess makes your space feel chaotic and wastes your time every day",
                "consequence": "you keep losing things, your desk looks stressful, and your routine starts messy",
                "benefit": "keeps items easier to find, store, and keep under control",
                "desire": "make your space feel cleaner, calmer, and more organized fast",
                "proof": "simple organizers work because they remove friction from daily routines",
                "tags": "#organization #desksetup #homeorganization #amazonfinds #usefulproducts",
            }

        return {
            "product_type": "organizador",
            "audience": "pessoas cansadas de bagunça na mesa, gaveta, cabos e pequenos objetos espalhados",
            "pain": "bagunça visual deixa sua rotina mais cansativa e faz você perder tempo todos os dias",
            "consequence": "você procura coisas simples, se irrita e sente que o ambiente nunca fica realmente em ordem",
            "benefit": "deixa os itens mais fáceis de guardar, encontrar e manter organizados",
            "desire": "transformar o espaço em algo mais limpo, prático e agradável rapidamente",
            "proof": "organizadores simples funcionam porque removem atrito das tarefas do dia a dia",
            "tags": "#organizacao #casaorganizada #achadosamazon #achadinhos #produtoutil",
        }

    # KITCHEN
    if any(k in text for k in ["cozinha", "kitchen", "cortador", "slicer", "utensil", "air fryer", "panela", "frigideira"]):
        if is_us:
            return {
                "product_type": "kitchen tool",
                "audience": "people who cook at home and want faster, easier kitchen routines",
                "pain": "small kitchen tasks steal more time and patience than they should",
                "consequence": "cooking feels harder, cleanup feels annoying, and you avoid making what you actually want",
                "benefit": "helps make food prep simpler, faster, or less frustrating",
                "desire": "make the kitchen feel easier and more satisfying to use",
                "proof": "practical kitchen tools sell because they solve visible everyday problems",
                "tags": "#kitchenfinds #amazonfinds #kitchengadgets #homecooking #tiktokmademebuyit",
            }

        return {
            "product_type": "produto de cozinha",
            "audience": "pessoas que cozinham em casa e querem praticidade",
            "pain": "tarefas pequenas na cozinha roubam tempo, paciência e energia todos os dias",
            "consequence": "cozinhar vira uma obrigação chata, a bagunça aumenta e você perde vontade de preparar as coisas",
            "benefit": "ajuda a deixar o preparo mais simples, rápido ou menos irritante",
            "desire": "sentir prazer em usar a cozinha sem sofrer com cada detalhe",
            "proof": "gadgets de cozinha vendem bem porque mostram o benefício de forma visual e imediata",
            "tags": "#cozinha #gadgetsdecozinha #achadosamazon #casapratica #tiktokmademebuyit",
        }

    # PET
    if any(k in text for k in ["pet", "dog", "cat", "gato", "cachorro", "pelos", "hair remover"]):
        if is_us:
            return {
                "product_type": "pet product",
                "audience": "pet owners tired of fur, mess, odor, or daily pet care problems",
                "pain": "pet care problems keep coming back no matter how much you try to stay on top of them",
                "consequence": "your clothes, couch, car, or routine keep getting messy again and again",
                "benefit": "helps make pet care cleaner, easier, or more practical",
                "desire": "enjoy your pet without feeling like the mess is controlling your home",
                "proof": "pet products sell because the problem is emotional, constant, and visible",
                "tags": "#petfinds #dogmom #catmom #amazonfinds #petproducts #cleanhome",
            }

        return {
            "product_type": "produto pet",
            "audience": "donos de pets cansados de pelos, sujeira, cheiro ou problemas diários de cuidado",
            "pain": "problemas com pet voltam todos os dias mesmo quando você tenta manter tudo em ordem",
            "consequence": "roupa, sofá, carro ou rotina ficam bagunçados de novo e de novo",
            "benefit": "ajuda a deixar o cuidado com o pet mais limpo, fácil ou prático",
            "desire": "curtir seu pet sem sentir que a bagunça domina sua casa",
            "proof": "produtos pet vendem porque a dor é emocional, constante e visível",
            "tags": "#pets #cachorro #gato #achadosamazon #casalimpa #donosdepet",
        }

    return {}




# ============================================================
# PRODUCT INTELLIGENCE ENGINE
# ============================================================

import json as product_json
import os as product_os
import re as product_re

from google import genai as product_genai


class AffiliateProductAnalyzeRequest(PitchBaseModel):
    product_id: int
    additional_context: Optional[str] = None


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    text = (raw_text or "").strip()

    text = product_re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=product_re.IGNORECASE,
    )
    text = product_re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")

    if start < 0 or end < 0 or end <= start:
        raise ValueError("A IA não retornou um objeto JSON válido.")

    return product_json.loads(text[start:end + 1])


def _normalize_analysis_list(value: Any) -> PitchList[str]:
    if not isinstance(value, list):
        return []

    result = []

    for item in value:
        clean = str(item or "").strip()

        if clean:
            result.append(clean)

    return result[:6]


def _validate_product_analysis(
    analysis: Dict[str, Any],
    product: AffiliateProduct,
) -> Dict[str, Any]:
    is_us = product.marketplace == MarketplaceEnum.AMAZON_US

    required_text_fields = [
        "product_type",
        "product_summary",
        "target_audience",
        "main_problem",
        "emotional_consequence",
        "main_desire",
        "main_benefit",
        "sales_angle",
        "recommended_hook",
        "recommended_cta",
    ]

    normalized = {}

    for field in required_text_fields:
        normalized[field] = str(analysis.get(field) or "").strip()

    normalized["features"] = _normalize_analysis_list(
        analysis.get("features")
    )
    normalized["benefits"] = _normalize_analysis_list(
        analysis.get("benefits")
    )
    normalized["pain_points"] = _normalize_analysis_list(
        analysis.get("pain_points")
    )
    normalized["proof_points"] = _normalize_analysis_list(
        analysis.get("proof_points")
    )
    normalized["video_scenes"] = _normalize_analysis_list(
        analysis.get("video_scenes")
    )

    normalized["product_id"] = product.id
    normalized["marketplace"] = (
        product.marketplace.value if product.marketplace else None
    )
    normalized["asin"] = product.asin
    normalized["title"] = product.title
    normalized["category"] = product.category
    normalized["price_text"] = product.price_text
    normalized["language"] = "en-US" if is_us else "pt-BR"
    normalized["trigger_keyword"] = "WANT" if is_us else "QUERO"

    if not normalized["product_type"]:
        raise ValueError("A IA não identificou o tipo do produto.")

    if not normalized["product_summary"]:
        raise ValueError("A IA não explicou o produto.")

    if not normalized["main_benefit"]:
        raise ValueError("A IA não identificou o benefício principal.")

    return normalized


def _analyze_product_with_profile(
    product: AffiliateProduct,
) -> Dict[str, Any]:
    is_us = product.marketplace == MarketplaceEnum.AMAZON_US
    profile = _detect_pitch_profile_v2(product, is_us)

    if not profile:
        return {}

    if is_us:
        return {
            "product_type": profile.get("product_type", "product"),
            "product_summary": (
                f"{product.title} is a product in the "
                f"{product.category or 'Amazon Finds'} category."
            ),
            "target_audience": profile.get("audience", ""),
            "main_problem": profile.get("pain", ""),
            "emotional_consequence": profile.get("consequence", ""),
            "main_desire": profile.get("desire", ""),
            "main_benefit": profile.get("benefit", ""),
            "sales_angle": profile.get("desire", ""),
            "recommended_hook": (
                f"If {profile.get('pain', 'this problem affects your routine')}, "
                f"you need to see this."
            ),
            "recommended_cta": "Comment WANT for the direct link.",
            "features": [],
            "benefits": [profile.get("benefit", "")],
            "pain_points": [profile.get("pain", "")],
            "proof_points": [profile.get("proof", "")],
            "video_scenes": [
                profile.get("pain", ""),
                profile.get("consequence", ""),
                product.title,
                profile.get("benefit", ""),
                profile.get("desire", ""),
                "Comment WANT for the direct link.",
            ],
        }

    return {
        "product_type": profile.get("product_type", "produto"),
        "product_summary": (
            f"{product.title} é um produto da categoria "
            f"{product.category or 'Achados Amazon'}."
        ),
        "target_audience": profile.get("audience", ""),
        "main_problem": profile.get("pain", ""),
        "emotional_consequence": profile.get("consequence", ""),
        "main_desire": profile.get("desire", ""),
        "main_benefit": profile.get("benefit", ""),
        "sales_angle": profile.get("desire", ""),
        "recommended_hook": (
            f"Se {profile.get('pain', 'esse problema atrapalha sua rotina')}, "
            f"você precisa ver isso."
        ),
        "recommended_cta": "Comente QUERO para receber o link.",
        "features": [],
        "benefits": [profile.get("benefit", "")],
        "pain_points": [profile.get("pain", "")],
        "proof_points": [profile.get("proof", "")],
        "video_scenes": [
            profile.get("pain", ""),
            profile.get("consequence", ""),
            product.title,
            profile.get("benefit", ""),
            profile.get("desire", ""),
            "Comente QUERO para receber o link.",
        ],
    }


def _analyze_product_with_ai(
    product: AffiliateProduct,
    additional_context: Optional[str],
) -> Dict[str, Any]:
    is_us = product.marketplace == MarketplaceEnum.AMAZON_US
    language = "American English" if is_us else "Brazilian Portuguese"
    trigger = "WANT" if is_us else "QUERO"

    api_key = (
        product_os.getenv("GEMINI_API_KEY")
        or product_os.getenv("GOOGLE_API_KEY")
    )

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY ou GOOGLE_API_KEY não está configurada."
        )

    model_name = product_os.getenv(
        "GEMINI_MODEL",
        "gemini-3.5-flash",
    )

    client = product_genai.Client(
        api_key=api_key,
        http_options={
            "timeout": 120000,
            "retry_options": {
                "attempts": 4,
                "initial_delay": 2.0,
                "max_delay": 15.0,
                "exp_base": 2.0,
                "jitter": 1.0,
                "http_status_codes": [408, 429, 500, 502, 503, 504],
            },
        },
    )

    prompt = f"""
You are the Product Intelligence Engine of an affiliate video system.

Analyze the exact product below.

PRODUCT:
Title: {product.title}
Category: {product.category or "Not provided"}
Price: {product.price_text or "Not provided"}
Marketplace: {product.marketplace.value if product.marketplace else "Unknown"}
ASIN: {product.asin}
Additional context: {additional_context or "Not provided"}

MANDATORY RULES:

1. Write every response field in {language}.
2. Analyze this exact product, not a generic product.
3. Identify what the product physically is and what it is used for.
4. Every pain point and benefit must make sense for this exact product.
5. Do not invent technical specifications.
6. Do not invent ratings, reviews, discounts, stock, guarantees or results.
7. Do not claim the product has a feature unless the title or context supports it.
8. Create emotional urgency based on the real problem or desire.
9. Never use false scarcity.
10. Avoid generic expressions such as:
   - useful product
   - makes life easier
   - practical option
   unless you explain exactly how.
11. The video scenes must be short enough to display on a vertical video.
12. The CTA keyword must be {trigger}.
13. Return only valid JSON.
14. Do not use Markdown.

Return exactly this structure:

{{
  "product_type": "specific product type",
  "product_summary": "clear explanation of what this exact product is",
  "target_audience": "specific audience",
  "features": [
    "only features supported by the product data"
  ],
  "benefits": [
    "specific product benefit",
    "specific product benefit",
    "specific product benefit"
  ],
  "pain_points": [
    "specific pain solved by this product",
    "specific pain solved by this product"
  ],
  "main_problem": "main real problem",
  "emotional_consequence": "how this problem makes the customer feel",
  "main_desire": "what the customer wants to feel or achieve",
  "main_benefit": "strongest specific benefit",
  "proof_points": [
    "logical reason the benefit makes sense without inventing facts"
  ],
  "sales_angle": "best emotional and commercial angle",
  "recommended_hook": "short and strong product-specific hook",
  "recommended_cta": "CTA using the keyword {trigger}",
  "video_scenes": [
    "short hook",
    "specific pain",
    "emotional consequence",
    "product introduction",
    "specific benefit",
    "desire",
    "CTA"
  ]
}}
"""

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
        },
    )

    raw_text = getattr(response, "text", None)

    if not raw_text:
        raise ValueError("A IA retornou uma resposta vazia.")

    return _extract_json_object(raw_text)


@router.post("/products/analyze")
def analyze_affiliate_product(
    payload: AffiliateProductAnalyzeRequest,
    db: Session = Depends(get_db),
):
    product = (
        db.query(AffiliateProduct)
        .filter(AffiliateProduct.id == payload.product_id)
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Produto não encontrado.",
        )

    analysis_source = "ai"

    try:
        analysis = _analyze_product_with_ai(
            product=product,
            additional_context=payload.additional_context,
        )
    except Exception as ai_error:
        print(
            f"⚠️ [PRODUCT INTELLIGENCE] Gemini falhou: "
            f"{type(ai_error).__name__}: {ai_error}",
            flush=True,
        )

        analysis = _analyze_product_with_profile(product)
        analysis_source = "profile_fallback"

        if not analysis:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Não foi possível analisar o produto.",
                    "ai_error": str(ai_error),
                    "suggestion": (
                        "Informe additional_context com descrição, "
                        "características e uso do produto."
                    ),
                },
            )

    try:
        normalized = _validate_product_analysis(
            analysis=analysis,
            product=product,
        )
    except Exception as validation_error:
        raise HTTPException(
            status_code=502,
            detail=f"Análise inválida: {validation_error}",
        )

    return {
        "ok": True,
        "source": analysis_source,
        "analysis": normalized,
    }






# ============================================================
# ANALYSIS -> CONVERSION CONTENT
# ============================================================

import unicodedata as affiliate_unicodedata


class GenerateContentFromAnalysisRequest(PitchBaseModel):
    product_id: int
    platform: str = "tiktok"
    additional_context: Optional[str] = None
    include_price: bool = False


def _compact_scene_text(
    value: Optional[str],
    max_chars: int = 118,
) -> str:
    text = product_re.sub(
        r"\s+",
        " ",
        str(value or "").strip(),
    )

    if not text:
        return ""

    if len(text) <= max_chars:
        return text.rstrip(" .!?") + "."

    shortened = text[:max_chars].rsplit(" ", 1)[0].strip()

    return shortened.rstrip(" .,:;!?") + "..."


def _unique_scene_values(values: PitchList[str]) -> PitchList[str]:
    result = []
    seen = set()

    for value in values:
        clean = product_re.sub(
            r"\s+",
            " ",
            str(value or "").strip(),
        )

        if not clean:
            continue

        key = clean.lower().rstrip(" .!?")

        if key in seen:
            continue

        seen.add(key)
        result.append(clean)

    return result


def _hashtag_token(value: Optional[str]) -> str:
    text = affiliate_unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        character
        for character in text
        if not affiliate_unicodedata.combining(character)
    )

    text = product_re.sub(
        r"[^a-zA-Z0-9]+",
        "",
        text,
    ).lower()

    return text[:35]


def _build_analysis_tags(
    analysis: Dict[str, Any],
    product: AffiliateProduct,
    is_us: bool,
) -> str:
    specific_tokens = []

    for value in [
        analysis.get("product_type"),
        product.category,
    ]:
        token = _hashtag_token(value)

        if token and token not in specific_tokens:
            specific_tokens.append(token)

    if is_us:
        base_tags = [
            "amazonfinds",
            "productfinds",
            "tiktokmademebuyit",
            "onlineshopping",
        ]
    else:
        base_tags = [
            "achadosamazon",
            "achadinhos",
            "comprasonline",
            "tiktokmademebuyit",
        ]

    all_tags = []

    for tag in specific_tokens + base_tags:
        if tag and tag not in all_tags:
            all_tags.append(tag)

    return " ".join(f"#{tag}" for tag in all_tags[:7])


def _build_content_from_product_analysis(
    product: AffiliateProduct,
    analysis: Dict[str, Any],
    include_price: bool,
) -> Dict[str, str]:
    is_us = product.marketplace == MarketplaceEnum.AMAZON_US

    product_title = str(product.title or "").strip()

    hook_1 = _compact_scene_text(
        analysis.get("recommended_hook")
        or analysis.get("main_problem"),
        max_chars=125,
    )

    sales_angle = (
        analysis.get("sales_angle")
        or analysis.get("main_desire")
        or analysis.get("main_benefit")
    )

    hook_2 = _compact_scene_text(
        sales_angle,
        max_chars=105,
    )

    benefits = _unique_scene_values(
        analysis.get("benefits") or []
    )

    proof_points = _unique_scene_values(
        analysis.get("proof_points") or []
    )

    if is_us:
        product_introduction = (
            f"This is where {product_title} comes in."
        )

        benefit_scene = (
            f"The main benefit: {analysis.get('main_benefit', '')}"
        )

        desire_scene = (
            f"The result you want: {analysis.get('main_desire', '')}"
        )

        price_scene = (
            f"Price registered for this product: {product.price_text}. "
            f"Check the current Amazon price before buying."
        )

        trigger_keyword = "WANT"

        caption = (
            f"{product_title}: "
            f"{analysis.get('main_benefit', '')}. "
            f"Comment WANT for the direct link."
        )

    else:
        product_introduction = (
            f"É aqui que entra o {product_title}."
        )

        benefit_scene = (
            f"O principal benefício: {analysis.get('main_benefit', '')}"
        )

        desire_scene = (
            f"O resultado que você busca: "
            f"{analysis.get('main_desire', '')}"
        )

        price_scene = (
            f"Preço registrado para este produto: "
            f"{product.price_text}. "
            f"Confira o valor atual na Amazon antes de comprar."
        )

        trigger_keyword = "QUERO"

        caption = (
            f"{product_title}: "
            f"{analysis.get('main_benefit', '')}. "
            f"Comente QUERO para receber o link direto."
        )

    scene_candidates = [
        analysis.get("emotional_consequence"),
        product_introduction,
        benefit_scene,
    ]

    for benefit in benefits[:2]:
        if benefit.lower() not in str(
            analysis.get("main_benefit") or ""
        ).lower():
            scene_candidates.append(benefit)

    if proof_points:
        scene_candidates.append(proof_points[0])

    scene_candidates.append(desire_scene)

    if include_price and product.price_text:
        scene_candidates.append(price_scene)

    unique_scenes = _unique_scene_values(scene_candidates)

    compact_scenes = []

    for scene in unique_scenes:
        compact = _compact_scene_text(
            scene,
            max_chars=112,
        )

        if compact:
            compact_scenes.append(compact)

    # O Video Engine atual mostra no máximo cinco cenas de roteiro.
    compact_scenes = compact_scenes[:5]

    if not compact_scenes:
        raise ValueError(
            "A análise não produziu cenas válidas para o vídeo."
        )

    script = " ".join(compact_scenes)

    seo_tags = _build_analysis_tags(
        analysis=analysis,
        product=product,
        is_us=is_us,
    )

    return {
        "hook_1": hook_1,
        "hook_2": hook_2,
        "script": script,
        "caption": _compact_scene_text(
            caption,
            max_chars=220,
        ),
        "trigger_keyword": trigger_keyword,
        "seo_tags": seo_tags,
        "video_scenes": compact_scenes,
    }


@router.post("/content/generate-from-analysis")
def generate_content_from_analysis(
    payload: GenerateContentFromAnalysisRequest,
    db: Session = Depends(get_db),
):
    product = (
        db.query(AffiliateProduct)
        .filter(AffiliateProduct.id == payload.product_id)
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Produto não encontrado.",
        )

    analysis_source = "ai"

    try:
        raw_analysis = _analyze_product_with_ai(
            product=product,
            additional_context=payload.additional_context,
        )

    except Exception as ai_error:
        print(
            f"⚠️ [PRODUCT INTELLIGENCE] "
            f"Generate-from-analysis usando fallback: "
            f"{type(ai_error).__name__}: {ai_error}",
            flush=True,
        )

        raw_analysis = _analyze_product_with_profile(product)
        analysis_source = "profile_fallback"

        if not raw_analysis:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": (
                        "A IA não respondeu e não existe um perfil "
                        "local para este produto."
                    ),
                    "suggestion": (
                        "Forneça uma descrição detalhada em "
                        "additional_context ou tente novamente mais tarde."
                    ),
                    "ai_error": str(ai_error),
                },
            )

    try:
        analysis = _validate_product_analysis(
            analysis=raw_analysis,
            product=product,
        )

        generated = _build_content_from_product_analysis(
            product=product,
            analysis=analysis,
            include_price=payload.include_price,
        )

    except Exception as generation_error:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Não foi possível construir o conteúdo: "
                f"{generation_error}"
            ),
        )

    platform = _normalize_platform(payload.platform)


    content, _ = create_governed_content(
        db=db,
        product=product,
        platform=platform,
        data=generated,
        generation_type="analysis",
    )

    return {
        "ok": True,
        "source": analysis_source,
        "product_analysis": analysis,
        "video_scenes": generated["video_scenes"],
        "content": _serialize_content(content),
    }







