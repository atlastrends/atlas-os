import json
import os
import re
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.affiliate import AffiliateProduct, AffiliateContent
from app.schemas.affiliate import ProductCreate, ContentGenerateRequest
from app.services.content_service import ContentService
from app.services.affiliate_content_governance import (
    create_governed_content,
)

try:
    from google import genai
except Exception:
    genai = None


class AffiliateService:
    def __init__(self):
        self.content_service = ContentService()

        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.gemini_model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.gemini_client = None

        if self.gemini_key and genai is not None:
            try:
                self.gemini_client = genai.Client(api_key=self.gemini_key)
                print(f"✅ [AFFILIATE] Gemini fallback pronto: {self.gemini_model_name}")
            except Exception as e:
                print(f"⚠️ [AFFILIATE] Gemini fallback não iniciou: {e}")
                self.gemini_client = None
        else:
            print("⚠️ [AFFILIATE] Gemini fallback indisponível: GEMINI_API_KEY ausente ou google-genai não instalado.")

    def create_product(self, db: Session, product_data: ProductCreate):
        new_product = AffiliateProduct(
            marketplace=product_data.marketplace,
            asin=product_data.asin,
            title=product_data.title,
            original_url=product_data.original_url,
            category=product_data.category,
            price_text=product_data.price_text,
            currency=product_data.currency,
            affiliate_url=product_data.affiliate_url,
            associate_tag=product_data.associate_tag,
        )
        db.add(new_product)
        db.commit()
        db.refresh(new_product)
        return new_product

    def list_products(self, db: Session, skip: int = 0, limit: int = 100):
        return db.query(AffiliateProduct).offset(skip).limit(limit).all()

    def _normalize_platform(self, platform: str) -> str:
        value = str(platform or "").strip().lower()

        aliases = {
            "tik": "tiktok",
            "tik tok": "tiktok",
            "tt": "tiktok",
            "tiktok": "tiktok",
            "instagram": "instagram",
            "insta": "instagram",
            "ig": "instagram",
            "youtube": "youtube",
            "yt": "youtube",
            "shorts": "youtube",
            "facebook": "facebook",
            "fb": "facebook",
        }

        return aliases.get(value, value or "tiktok")

    def _build_prompt(self, product: AffiliateProduct, platform: str) -> str:
        price = f"{product.price_text or ''} {product.currency or ''}".strip()
        category = product.category or "produto de consumo"

        return f"""
Você é um copywriter especialista em marketing de afiliados e vídeos curtos para {platform}.

Crie um pacote de conteúdo em Português do Brasil para vender este produto de forma natural:

PRODUTO:
{product.title}

CATEGORIA:
{category}

PREÇO:
{price or "não informado"}

REGRAS:
- Gere conteúdo persuasivo, mas sem prometer resultado garantido.
- Não invente especificações técnicas que não foram fornecidas.
- Não diga que é o menor preço, promoção, desconto ou oferta limitada.
- Use linguagem de criador de conteúdo brasileiro.
- Foque em dor, desejo, benefício prático e CTA.
- O CTA deve pedir para comentar uma palavra-chave para receber o link.
- Retorne APENAS JSON válido.
- Não use markdown.
- Não use bloco ```json.
- Não escreva explicações fora do JSON.

Formato obrigatório:

{{
  "hook_1": "gancho curto de até 8 palavras",
  "hook_2": "segundo gancho curto de até 8 palavras",
  "script": "roteiro falado de 80 a 120 palavras",
  "caption": "legenda persuasiva com CTA",
  "trigger_keyword": "palavra-chave curta em maiúsculas",
  "seo_tags": "#tag1 #tag2 #tag3 #tag4 #tag5"
}}
"""

    def _extract_json(self, text: str) -> Dict[str, Any]:
        if not text:
            raise ValueError("Resposta vazia da IA.")

        cleaned = str(text).strip()

        cleaned = cleaned.replace("```json", "").replace("```JSON", "").replace("```", "").strip()

        try:
            return json.loads(cleaned)
        except Exception:
            pass

        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise ValueError(f"Não encontrei JSON na resposta da IA: {cleaned[:300]}")

        return json.loads(match.group(0))

    def _generate_with_groq(self, prompt: str) -> Optional[str]:
        try:
            active_model = self.content_service._get_best_model()
            print(f"🧠 [AFFILIATE] Tentando Groq: {active_model}")

            return self.content_service._generate_with_ai(
                prompt=prompt,
                active_model=active_model,
                temperature=0.75,
            )

        except Exception as e:
            print(f"⚠️ [AFFILIATE] Groq falhou. Continuando sem derrubar API: {e}")
            return None

    def _generate_with_gemini(self, prompt: str) -> Optional[str]:
        if not self.gemini_client:
            return None

        try:
            print(f"🌟 [AFFILIATE] Tentando Gemini: {self.gemini_model_name}")

            response = self.gemini_client.models.generate_content(
                model=self.gemini_model_name,
                contents=prompt,
                config={
                    "temperature": 0.75,
                    "top_p": 0.9,
                    "max_output_tokens": 900,
                    "response_mime_type": "application/json",
                },
            )

            if response and getattr(response, "text", None):
                print("✅ [AFFILIATE] Gemini gerou conteúdo com sucesso.")
                return response.text

            print("⚠️ [AFFILIATE] Gemini retornou resposta vazia.")
            return None

        except Exception as e:
            print(f"⚠️ [AFFILIATE] Gemini falhou. Continuando sem derrubar API: {e}")
            return None

    def _local_fallback_content(self, product: AffiliateProduct, platform: str) -> Dict[str, str]:
        title = product.title or "esse produto"
        category = product.category or "produto"
        price = f"{product.price_text or ''} {product.currency or ''}".strip()

        price_sentence = f" Ele está listado por {price}." if price else ""

        return {
            "hook_1": "Você precisa ver isso aqui",
            "hook_2": "Isso resolve um problema chato",
            "script": (
                f"Se você estava procurando uma opção prática dentro de {category}, olha esse aqui: {title}. "
                f"A ideia é simples: mostrar um produto que pode facilitar sua rotina sem enrolação.{price_sentence} "
                f"O ponto principal é entender se ele combina com o que você precisa agora. "
                f"Se você gosta de descobrir achados úteis antes de comprar, vale dar uma olhada com calma, comparar os detalhes e decidir se faz sentido para você. "
                f"Quer o link direto? Comenta QUERO que eu te envio."
            ),
            "caption": (
                f"Achei esse produto e pode ser útil para quem procura algo em {category}. "
                f"Comente QUERO para receber o link direto."
            ),
            "trigger_keyword": "QUERO",
            "seo_tags": "#achadinhos #comprasonline #afiliados #produto #tiktokmademebuyit",
        }

    def _validate_payload(self, data: Dict[str, Any], product: AffiliateProduct, platform: str) -> Dict[str, str]:
        fallback = self._local_fallback_content(product, platform)

        hook_1 = str(data.get("hook_1") or fallback["hook_1"]).strip()
        hook_2 = str(data.get("hook_2") or fallback["hook_2"]).strip()
        script = str(data.get("script") or fallback["script"]).strip()
        caption = str(data.get("caption") or fallback["caption"]).strip()
        trigger_keyword = str(data.get("trigger_keyword") or fallback["trigger_keyword"]).strip().upper()
        seo_tags = str(data.get("seo_tags") or fallback["seo_tags"]).strip()

        if len(hook_1.split()) > 10:
            hook_1 = " ".join(hook_1.split()[:10])

        if len(hook_2.split()) > 10:
            hook_2 = " ".join(hook_2.split()[:10])

        if not trigger_keyword:
            trigger_keyword = "QUERO"

        return {
            "hook_1": hook_1,
            "hook_2": hook_2,
            "script": script,
            "caption": caption,
            "trigger_keyword": trigger_keyword,
            "seo_tags": seo_tags,
        }

    def generate_sales_content(self, db: Session, request: ContentGenerateRequest):
        product = (
            db.query(AffiliateProduct)
            .filter(AffiliateProduct.id == request.product_id)
            .first()
        )

        if not product:
            raise ValueError(f"Produto ID {request.product_id} não encontrado")

        platform = self._normalize_platform(request.platform)
        prompt = self._build_prompt(product, platform)

        parsed_data = None

        # 1. Tenta Gemini primeiro para NÃO gastar Groq quando ele já está no limite.
        gemini_response = self._generate_with_gemini(prompt)
        if gemini_response:
            try:
                parsed_data = self._extract_json(gemini_response)
            except Exception as e:
                print(f"⚠️ [AFFILIATE] Gemini retornou JSON inválido: {e}")

        # 2. Se Gemini falhar, tenta Groq.
        if parsed_data is None:
            groq_response = self._generate_with_groq(prompt)
            if groq_response:
                try:
                    parsed_data = self._extract_json(groq_response)
                except Exception as e:
                    print(f"⚠️ [AFFILIATE] Groq retornou JSON inválido: {e}")

        # 3. Se tudo falhar, usa fallback local e NÃO derruba API.
        if parsed_data is None:
            print("🛟 [AFFILIATE] Usando fallback local. Nenhum provedor de IA disponível.")
            parsed_data = self._local_fallback_content(product, platform)

        final_data = self._validate_payload(parsed_data, product, platform)


        content, duplicate = create_governed_content(
            db=db,
            product=product,
            platform=platform,
            data=final_data,
            generation_type="standard",
        )

        print(
            "[AFFILIATE] Conteudo governado salvo. "
            f"Duplicado: {duplicate}"
        )

        return content


affiliate_service = AffiliateService()
