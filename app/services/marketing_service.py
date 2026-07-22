# ============================================================
# ATLAS OS - marketing_service.py
# "O melhor marqueteiro do mundo" em codigo.
#
# Dado um video, monta AUTOMATICAMENTE o melhor plano de anuncio:
#  - objetivo (afiliado -> cliques/vendas | reel/trend -> alcance/views)
#  - publico-alvo (pais, idade, genero, interesses) por mercado (BR/US)
#  - posicionamentos (Reels, Stories, Feed) com Advantage+ automatico
#  - textos do anuncio (texto principal, titulo, CTA) e o link
#  - sugestao de orcamento diario a partir do valor semanal/mensal
#
# O VALOR do orcamento e a decisao de PUBLICAR sao sempre MANUAIS.
# A publicacao real so acontece quando existir uma Conta de Anuncios
# (META_AD_ACCOUNT_ID_BR / _US); sem ela o plano fica pronto e a
# campanha aguarda revisao, sem gastar nada.
# ============================================================

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.dashboard import (
    AdCampaign,
    AdCampaignStatusEnum,
    ShortLink,
    VideoAsset,
    VideoKindEnum,
    VideoMetric,
    VideoStatusEnum,
)
from app.publishing.base import market_code
from app.services.analytics_service import AnalyticsService
from app.services.shortlink_service import ShortLinkService

try:
    from google import genai
except Exception:  # pragma: no cover - Gemini opcional
    genai = None

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Orcamento diario minimo recomendado por mercado (evita "budget too low").
MIN_DAILY = {"BR": 6.0, "US": 3.0}

# --- Referencias para ESTIMAR o ROI de afiliado (valores aproximados) ---
# Comissao media da Amazon (afiliados) sobre o preco do produto.
AMAZON_COMMISSION_RATE = 0.04
# Fracao dos cliques no link que viram compra (conversao tipica de afiliado).
CLICK_TO_SALE_RATE = 0.05
# Custo de referencia por 1000 impressoes de anuncio (CPM) por mercado.
# Usado so para estimar o ROAS -- nao e cobranca real.
AD_CPM = {"BR": 18.0, "US": 9.0}

# Interesses recomendados por categoria de produto (nomes amigaveis).
# Para afiliados usamos a categoria; para reels usamos o publico amplo.
CATEGORY_INTERESTS = {
    "electronics": ["Tecnologia", "Gadgets", "Eletronicos de consumo"],
    "eletronicos": ["Tecnologia", "Gadgets", "Eletronicos de consumo"],
    "kitchen": ["Culinaria", "Cozinha", "Utensilios domesticos"],
    "cozinha": ["Culinaria", "Cozinha", "Utensilios domesticos"],
    "home": ["Decoracao", "Casa e jardim", "Organizacao"],
    "casa": ["Decoracao", "Casa e jardim", "Organizacao"],
    "beauty": ["Beleza", "Cuidados pessoais", "Cosmeticos"],
    "beleza": ["Beleza", "Cuidados pessoais", "Cosmeticos"],
    "toys": ["Brinquedos", "Familia", "Criancas"],
    "sports": ["Fitness", "Vida saudavel", "Esportes"],
    "fashion": ["Moda", "Compras", "Estilo"],
    "moda": ["Moda", "Compras", "Estilo"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MarketingService:
    def __init__(self, db: Session):
        self.db = db
        self.shortlinks = ShortLinkService(db)
        # Motor de IA (carregado sob demanda para nao pesar quando nao usado).
        self._content = None
        self._content_ready = False
        self._gemini = None
        self._gemini_ready = False
        self._gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

    # ----------------------------------------------------------------
    # ESCOLHA AUTOMATICA DO MELHOR VIDEO (pelos numeros)
    # ----------------------------------------------------------------
    def best_video(self) -> Optional[dict]:
        """Escolhe o video com melhores numeros para anunciar.

        Prioridade: maior desempenho real (views/engajamento/cliques).
        Sem metricas ainda -> usa performance_score; por fim, o mais
        recente ja publicado.
        """
        tops = AnalyticsService(self.db).top_videos(limit=1)
        if tops:
            return tops[0]

        # Sem metricas: melhor performance_score entre publicados/aprovados.
        asset = (
            self.db.query(VideoAsset)
            .filter(
                VideoAsset.status.in_(
                    [VideoStatusEnum.PUBLISHED, VideoStatusEnum.APPROVED]
                )
            )
            .order_by(
                VideoAsset.performance_score.desc().nullslast(),
                VideoAsset.created_at.desc(),
            )
            .first()
        )
        if asset is None:
            asset = (
                self.db.query(VideoAsset)
                .order_by(VideoAsset.created_at.desc())
                .first()
            )
        if asset is None:
            return None
        return {
            "id": asset.id,
            "title": asset.title,
            "kind": asset.kind.value if hasattr(asset.kind, "value") else str(asset.kind),
            "views": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "clicks": 0,
        }

    # ----------------------------------------------------------------
    # RANKING DE ROI (qual video vale mais a pena anunciar)
    # ----------------------------------------------------------------
    def roi_ranking(self, limit: int = 10) -> list[dict]:
        """Ordena os videos pelo POTENCIAL DE ROI para anuncio.

        Como ainda nao ha gasto real de anuncio (trafego organico), o ROI e
        uma ESTIMATIVA baseada em sinais que ja temos:
          - CTR (cliques no link / views): o quanto o video leva a pessoa a
            clicar no produto -- e o que mais decide ROI de afiliado.
          - Engajamento (curtidas+comentarios+compart. / views): valida o
            criativo; criativo bom = distribuicao mais barata (CPM menor).
          - Valor do produto (preco -> comissao estimada): quanto cada clique
            pode render.
        Com isso estimamos o retorno por 1000 views e comparamos com um custo
        de anuncio de referencia (CPM) para chegar num ROAS/ROI estimado.
        """
        metrics = AnalyticsService(self.db).top_videos(limit=200)
        by_id = {m["id"]: m for m in metrics}

        # Considera videos publicados/aprovados (candidatos a anuncio).
        assets = (
            self.db.query(VideoAsset)
            .filter(
                VideoAsset.status.in_(
                    [VideoStatusEnum.PUBLISHED, VideoStatusEnum.APPROVED]
                )
            )
            .all()
        )

        out: list[dict] = []
        for asset in assets:
            kind = (
                asset.kind.value if hasattr(asset.kind, "value") else str(asset.kind or "")
            )
            is_affiliate = kind == VideoKindEnum.AFFILIATE.value
            market = market_code(asset.country_code or "", asset.language or "")
            currency = "BRL" if market == "BR" else "USD"

            m = by_id.get(asset.id, {})
            views = int(m.get("views", 0) or 0)
            likes = int(m.get("likes", 0) or 0)
            comments = int(m.get("comments", 0) or 0)
            shares = int(m.get("shares", 0) or 0)
            clicks = int(m.get("clicks", 0) or 0)

            ctr = (clicks / views) if views else 0.0
            engagement = ((likes + comments + shares) / views) if views else 0.0

            price = self._parse_price(asset)
            commission_per_sale = price * AMAZON_COMMISSION_RATE if price else 0.0
            value_per_click = commission_per_sale * CLICK_TO_SALE_RATE

            # Retorno estimado por 1000 views (so afiliado gera receita direta).
            if is_affiliate and views:
                est_value_per_1000 = ctr * value_per_click * 1000.0
                cpm = AD_CPM.get(market, AD_CPM["US"])
                est_roas = (est_value_per_1000 / cpm) if cpm else 0.0
            else:
                est_value_per_1000 = 0.0
                est_roas = 0.0

            # Confianca: precisa de views suficientes para o CTR fazer sentido.
            confidence = "alta" if views >= 500 else "media" if views >= 50 else "baixa"

            # Score 0-100 para ordenar (combina ROAS estimado, CTR e engajamento).
            # ROAS pesa mais; CTR e engajamento entram como qualidade do criativo.
            score = (
                min(est_roas, 10.0) / 10.0 * 60.0  # ate 60 pts pelo ROAS estimado
                + min(ctr * 100.0, 10.0) / 10.0 * 25.0  # ate 25 pts pelo CTR
                + min(engagement * 100.0, 15.0) / 15.0 * 15.0  # ate 15 pts engajamento
            )
            if views < 50:
                score *= 0.5  # pouca amostra -> menos confiavel

            out.append(
                {
                    "id": asset.id,
                    "title": asset.title or asset.topic or f"Video {asset.id}",
                    "kind": kind,
                    "market": market,
                    "currency": currency,
                    "views": views,
                    "clicks": clicks,
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                    "ctr_pct": round(ctr * 100.0, 2),
                    "engagement_pct": round(engagement * 100.0, 2),
                    "price": round(price, 2) if price else 0.0,
                    "est_value_per_click": round(value_per_click, 2),
                    "est_roas": round(est_roas, 2),
                    "roi_score": round(score, 1),
                    "confidence": confidence,
                    "reason": self._roi_reason(
                        is_affiliate, views, ctr, engagement, est_roas, price
                    ),
                }
            )

        out.sort(key=lambda x: (x["roi_score"], x["clicks"], x["views"]), reverse=True)
        return out[:limit]

    @staticmethod
    def _parse_price(asset: VideoAsset) -> float:
        """Extrai o preco numerico do produto a partir do payload."""
        import re

        payload = asset.payload or {}
        raw = (
            payload.get("price_value")
            or payload.get("price")
            or payload.get("price_text")
            or payload.get("preco")
            or ""
        )
        if isinstance(raw, (int, float)):
            return float(raw)
        s = str(raw)
        # Remove simbolos de moeda e espacos; trata "1.299,90" e "1,299.90".
        s = re.sub(r"[^\d,.]", "", s)
        if not s:
            return 0.0
        if "," in s and "." in s:
            # O ultimo separador e o decimal.
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return 0.0

    @staticmethod
    def _roi_reason(
        is_affiliate: bool,
        views: int,
        ctr: float,
        engagement: float,
        est_roas: float,
        price: float,
    ) -> str:
        """Frase curta explicando por que este video tem (ou nao) bom ROI."""
        if not is_affiliate:
            return "Reel/trend: serve para crescer o canal, nao gera comissao direta."
        if views < 50:
            return "Poucos dados ainda: espere mais views para medir o ROI com seguranca."
        parts = []
        if ctr >= 0.03:
            parts.append("otimo CTR (muita gente clica no link)")
        elif ctr >= 0.01:
            parts.append("CTR razoavel")
        else:
            parts.append("CTR baixo (poucos cliques)")
        if engagement >= 0.05:
            parts.append("criativo forte (bom engajamento)")
        if price >= 150:
            parts.append("produto de ticket alto (comissao maior)")
        if est_roas >= 3:
            parts.append("ROI estimado alto")
        elif est_roas >= 1:
            parts.append("ROI estimado positivo")
        else:
            parts.append("ROI estimado ainda baixo")
        return "; ".join(parts) + "."

    # ----------------------------------------------------------------
    # PLANO AUTOMATICO (o "cerebro" do marqueteiro)
    # ----------------------------------------------------------------
    def recommend_for_video(self, asset: VideoAsset, *, force_ai: bool = False) -> dict:
        kind = asset.kind.value if hasattr(asset.kind, "value") else str(asset.kind or "")
        is_affiliate = kind == VideoKindEnum.AFFILIATE.value
        market = market_code(asset.country_code or "", asset.language or "")
        currency = "BRL" if market == "BR" else "USD"

        # ---- Objetivo (a melhor escolha por tipo de video) ----
        if is_affiliate:
            goal = "sales"
            # Amazon nao permite pixel de conversao -> otimizar por CLIQUES no
            # link / visualizacoes da pagina e a melhor jogada para afiliado.
            objective = "OUTCOME_TRAFFIC"
            optimization_goal = "LINK_CLICKS"
            cta = "SHOP_NOW"
            goal_label = "Mais vendas (cliques no link de afiliado)"
        else:
            goal = "reach"
            # Reels/trend: crescer os canais -> otimizar por ThruPlay (views de
            # video assistidas) gera mais alcance qualificado e novos seguidores.
            objective = "OUTCOME_ENGAGEMENT"
            optimization_goal = "THRUPLAY"
            cta = "WATCH_MORE"
            goal_label = "Mais alcance e visualizacoes (crescer o canal)"

        # ---- Publico-alvo ----
        country = "BR" if market == "BR" else "US"
        locale_lang = "pt" if market == "BR" else "en"
        # Afiliado: publico com intencao de compra (25-54). Reel: amplo (18-45).
        age_min, age_max = (25, 54) if is_affiliate else (18, 45)

        interests = self._interests_for(asset, is_affiliate)

        audience = {
            "countries": [country],
            "age_min": age_min,
            "age_max": age_max,
            "genders": "todos",
            "languages": [locale_lang],
            "interests": interests,
            "advantage_audience": True,  # deixa a IA da Meta expandir o publico
        }

        # ---- Posicionamentos (Advantage+ automatico, foco em video vertical) ----
        placements = {
            "mode": "automatico",  # Advantage+ Placements
            "recomendados": [
                "Instagram Reels",
                "Facebook Reels",
                "Stories (Instagram + Facebook)",
                "Feed (Instagram + Facebook)",
                "Explorar",
            ],
        }

        # ---- Textos do anuncio ----
        primary_text, headline, description, link_url = self._copy_for(
            asset, is_affiliate, market
        )

        # ---- IA: melhores pitches para ESTE video (automatico) ----
        # Gera com IA a melhor copy para cada campo e variacoes de pitch,
        # aplicando as melhores praticas mundiais de anuncios em video.
        # Fica em cache no proprio video para nao gastar cota a cada abertura;
        # so gera de novo quando o video muda ou quando o usuario pede "gerar
        # novos pitches" (force_ai).
        ai = self._ai_ad_copy(
            asset,
            is_affiliate=is_affiliate,
            market=market,
            goal_label=goal_label,
            cta=cta,
            interests=interests,
            force=force_ai,
        )
        pitches: list[dict] = []
        ai_generated = False
        if ai:
            ai_generated = True
            primary_text = ai.get("primary_text") or primary_text
            headline = ai.get("headline") or headline
            description = ai.get("description") or description
            cta = ai.get("cta") or cta
            pitches = ai.get("pitches") or []

        return {
            "video_id": asset.id,
            "video_title": asset.title,
            "kind": kind,
            "platform": "meta",
            "market": market,
            "currency": currency,
            "goal": goal,
            "goal_label": goal_label,
            "objective": objective,
            "optimization_goal": optimization_goal,
            "cta": cta,
            "audience": audience,
            "placements": placements,
            "primary_text": primary_text,
            "headline": headline,
            "description": description,
            "link_url": link_url,
            "pitches": pitches,
            "ai_generated": ai_generated,
            "min_daily_budget": MIN_DAILY.get(market, 3.0),
            "budget_suggestions": self._budget_suggestions(market),
        }

    # ----------------------------------------------------------------
    # IA: MELHORES PITCHES PARA CADA VIDEO (automatico, por campo)
    # ----------------------------------------------------------------
    def _get_content_engine(self):
        """Carrega o motor Groq sob demanda (uma vez por request)."""
        if self._content_ready:
            return self._content
        self._content_ready = True
        try:
            from app.services.content_service import ContentService

            self._content = ContentService()
        except Exception as exc:  # pragma: no cover
            print(f"⚠️ [MARKETING IA] Groq indisponivel: {exc}")
            self._content = None
        return self._content

    def _get_gemini(self):
        """Carrega o Gemini (fallback) sob demanda."""
        if self._gemini_ready:
            return self._gemini
        self._gemini_ready = True
        key = os.getenv("GEMINI_API_KEY")
        if key and genai is not None:
            try:
                self._gemini = genai.Client(api_key=key)
            except Exception as exc:  # pragma: no cover
                print(f"⚠️ [MARKETING IA] Gemini indisponivel: {exc}")
                self._gemini = None
        return self._gemini

    def _product_facts(self, asset: VideoAsset) -> dict:
        """Reune o que sabemos do produto/video para alimentar a IA."""
        payload = asset.payload or {}
        price = (
            payload.get("price_text")
            or payload.get("price")
            or payload.get("preco")
            or ""
        )
        currency = payload.get("currency") or ""
        features = (
            payload.get("features")
            or payload.get("bullets")
            or payload.get("benefits")
            or []
        )
        if isinstance(features, str):
            features = [features]
        features = [str(f).strip() for f in features if str(f).strip()][:6]
        category = (
            payload.get("category_label")
            or payload.get("category")
            or asset.topic
            or ""
        )
        return {
            "title": asset.title or asset.topic or "Produto",
            "category": str(category).strip(),
            "price": f"{price} {currency}".strip(),
            "features": features,
        }

    def _ai_signature(self, facts: dict, market: str, is_affiliate: bool) -> str:
        """Assinatura para saber se precisa gerar de novo (mudou o video)."""
        import hashlib

        base = "|".join(
            [
                facts.get("title", ""),
                facts.get("category", ""),
                facts.get("price", ""),
                " ".join(facts.get("features", [])),
                market,
                "aff" if is_affiliate else "reel",
                "v2",  # versao do prompt; muda se melhorarmos a IA
            ]
        )
        return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()[:16]

    def _ai_ad_copy(
        self,
        asset: VideoAsset,
        *,
        is_affiliate: bool,
        market: str,
        goal_label: str,
        cta: str,
        interests: list[str],
        force: bool = False,
    ) -> Optional[dict]:
        """Gera com IA a melhor copy do anuncio e variacoes de pitch para ESTE
        video. Usa cache no proprio video (payload) para nao gastar cota a cada
        abertura. Retorna None se a IA nao estiver disponivel."""
        facts = self._product_facts(asset)
        signature = self._ai_signature(facts, market, is_affiliate)

        payload = asset.payload or {}
        cached = payload.get("ad_copy_ai")
        if (
            not force
            and isinstance(cached, dict)
            and cached.get("sig") == signature
            and isinstance(cached.get("data"), dict)
        ):
            return cached["data"]

        prompt = self._ai_prompt(
            facts, is_affiliate=is_affiliate, market=market, goal_label=goal_label
        )

        raw = self._ai_generate(prompt)
        if not raw:
            # Sem IA agora: se houver cache antigo, usa como ultimo recurso.
            if isinstance(cached, dict) and isinstance(cached.get("data"), dict):
                return cached["data"]
            return None

        data = self._ai_parse(raw, facts, cta)
        if not data:
            return None

        # Salva no proprio video para reutilizar (cache por video).
        try:
            new_payload = dict(payload)
            new_payload["ad_copy_ai"] = {"sig": signature, "data": data}
            asset.payload = new_payload
            self.db.commit()
        except Exception as exc:  # pragma: no cover
            print(f"⚠️ [MARKETING IA] Nao consegui salvar cache: {exc}")
            self.db.rollback()

        return data

    def _ai_prompt(
        self, facts: dict, *, is_affiliate: bool, market: str, goal_label: str
    ) -> str:
        lang = "Português do Brasil" if market == "BR" else "English (US)"
        features_txt = "; ".join(facts.get("features", [])) or "não informado"
        objetivo = (
            "gerar o MAIOR número de CLIQUES no link de afiliado pelo menor custo"
            if is_affiliate
            else "gerar o MAIOR número de VISUALIZAÇÕES e novos seguidores pelo menor custo"
        )
        return f"""
Você é o melhor estrategista de anúncios em vídeo do mundo (Meta Ads / Reels).
Sua missão: {objetivo}.

Escreva TUDO em {lang}.

PRODUTO / VÍDEO:
- Título: {facts.get('title')}
- Categoria: {facts.get('category') or 'não informado'}
- Preço: {facts.get('price') or 'não informado'}
- Características: {features_txt}

APLIQUE AS MELHORES PRÁTICAS MUNDIAIS DE CONVERSÃO:
- Gancho forte nos 3 primeiros segundos (curiosidade, número ou resultado).
- Foque no BENEFÍCIO (o que a pessoa ganha), não só nas características.
- Prova social quando fizer sentido (sem inventar números específicos).
- UM único pedido de ação (CTA) claro e direto.
- Linguagem de criador de conteúdo, natural, escaneável, com poucos emojis.
- Crie urgência/desejo de forma honesta (não prometa resultado garantido).
- Pensado para celular e vídeo vertical.

REGRAS:
- NÃO invente especificações técnicas que não foram fornecidas.
- NÃO diga "menor preço", "promoção" ou "desconto" se não foi informado.
- Retorne APENAS JSON válido, sem markdown, sem crase tripla.

Formato obrigatório (exatamente estas chaves):
{{
  "primary_text": "texto principal do anúncio, 2 a 4 linhas, com gancho + benefício + CTA",
  "headline": "título curto de até 6 palavras, alto impacto",
  "description": "linha de apoio curta (uma frase)",
  "cta": "SHOP_NOW ou LEARN_MORE ou WATCH_MORE",
  "pitches": [
    {{"name": "Nome do ângulo 1", "angle": "fórmula usada (ex.: AIDA, Dor-Solução, Prova social)", "text": "texto pronto do anúncio, 2 a 4 linhas"}},
    {{"name": "Nome do ângulo 2", "angle": "outra fórmula", "text": "texto pronto do anúncio"}},
    {{"name": "Nome do ângulo 3", "angle": "outra fórmula", "text": "texto pronto do anúncio"}}
  ]
}}
"""

    def _ai_generate(self, prompt: str) -> Optional[str]:
        # 1) Groq (rapido). 2) Gemini (fallback).
        engine = self._get_content_engine()
        if engine is not None:
            try:
                model = engine._get_best_model()
                text = engine._generate_with_ai(
                    prompt=prompt, active_model=model, temperature=0.8
                )
                if text and text.strip():
                    return text
            except Exception as exc:  # pragma: no cover
                print(f"⚠️ [MARKETING IA] Groq falhou: {exc}")

        gem = self._get_gemini()
        if gem is not None:
            try:
                resp = gem.models.generate_content(
                    model=self._gemini_model,
                    contents=prompt,
                    config={
                        "temperature": 0.8,
                        "top_p": 0.9,
                        "max_output_tokens": 1200,
                        "response_mime_type": "application/json",
                    },
                )
                if resp and getattr(resp, "text", None):
                    return resp.text
            except Exception as exc:  # pragma: no cover
                print(f"⚠️ [MARKETING IA] Gemini falhou: {exc}")

        return None

    def _ai_parse(self, raw: str, facts: dict, cta_default: str) -> Optional[dict]:
        import json
        import re

        cleaned = str(raw).strip()
        cleaned = cleaned.replace("```json", "").replace("```JSON", "").replace("```", "").strip()
        data = None
        try:
            data = json.loads(cleaned)
        except Exception:
            match = re.search(r"\{.*\}", cleaned, flags=re.S)
            if match:
                try:
                    data = json.loads(match.group(0))
                except Exception:
                    data = None
        if not isinstance(data, dict):
            return None

        def _clean(v) -> str:
            return str(v or "").strip()

        primary = _clean(data.get("primary_text"))
        headline = _clean(data.get("headline"))
        description = _clean(data.get("description"))
        cta = _clean(data.get("cta")).upper() or cta_default
        if cta not in ("SHOP_NOW", "LEARN_MORE", "WATCH_MORE", "SIGN_UP"):
            cta = cta_default

        pitches_in = data.get("pitches")
        pitches: list[dict] = []
        if isinstance(pitches_in, list):
            for p in pitches_in[:4]:
                if not isinstance(p, dict):
                    continue
                text = _clean(p.get("text"))
                if not text:
                    continue
                pitches.append(
                    {
                        "name": _clean(p.get("name")) or "Pitch",
                        "angle": _clean(p.get("angle")),
                        "text": text,
                    }
                )

        if not primary and not pitches:
            return None

        # Se faltar o texto principal mas houver pitches, usa o 1o pitch.
        if not primary and pitches:
            primary = pitches[0]["text"]

        return {
            "primary_text": primary,
            "headline": headline,
            "description": description,
            "cta": cta,
            "pitches": pitches,
        }

    def _interests_for(self, asset: VideoAsset, is_affiliate: bool) -> list[str]:
        payload = asset.payload or {}
        cat = (
            payload.get("category")
            or payload.get("category_label")
            or asset.topic
            or ""
        )
        key = str(cat).strip().lower()
        for k, vals in CATEGORY_INTERESTS.items():
            if k in key:
                return vals
        if is_affiliate:
            return ["Compras online", "Ofertas e promocoes", "Amazon"]
        return ["Videos virais", "Tendencias", "Entretenimento"]

    def _copy_for(
        self, asset: VideoAsset, is_affiliate: bool, market: str
    ) -> tuple[str, str, str, Optional[str]]:
        payload = asset.payload or {}
        title = asset.title or asset.topic or "Confira este video"
        hashtags = payload.get("hashtags") or []
        tags_txt = " ".join(
            h if str(h).startswith("#") else f"#{h}" for h in hashtags[:5]
        )

        link_url = None
        if is_affiliate and asset.affiliate_url:
            link = self.shortlinks.get_or_create(
                asset.affiliate_url,
                title=asset.title,
                video_asset_id=asset.id,
            )
            link_url = self.shortlinks.build_public_url(link.code)

        if market == "BR":
            if is_affiliate:
                primary = (
                    f"🔥 {title}\n\n"
                    "Achado imperdivel com entrega rapida. Toque em COMPRAR "
                    "AGORA e garanta o seu antes que acabe!"
                )
                headline = "Oferta por tempo limitado"
                description = "Compre agora na Amazon"
            else:
                primary = (
                    f"🚀 {title}\n\nVoce precisa ver isso ate o final! "
                    "Segue o canal pra nao perder os proximos."
                )
                headline = "Assista agora"
                description = "Novos videos toda semana"
        else:
            if is_affiliate:
                primary = (
                    f"🔥 {title}\n\nTop pick with fast shipping. Tap SHOP NOW "
                    "and grab yours before it sells out!"
                )
                headline = "Limited-time deal"
                description = "Buy now on Amazon"
            else:
                primary = (
                    f"🚀 {title}\n\nWatch till the end! Follow for more "
                    "videos like this every week."
                )
                headline = "Watch now"
                description = "New videos every week"

        if tags_txt:
            primary = f"{primary}\n\n{tags_txt}"
        return primary, headline, description, link_url

    def _budget_suggestions(self, market: str) -> list[dict]:
        """Pacotes de orcamento prontos (o usuario ainda ajusta manualmente)."""
        if market == "BR":
            base = [70, 150, 350]  # semana em BRL
        else:
            base = [35, 70, 175]  # semana em USD
        labels = ["Teste", "Recomendado", "Escala"]
        recommended = 1
        out = []
        for i, weekly in enumerate(base):
            out.append(
                {
                    "label": labels[i],
                    "period": "weekly",
                    "amount": weekly,
                    "daily": round(weekly / 7, 2),
                    "recommended": i == recommended,
                }
            )
        return out

    # ----------------------------------------------------------------
    # CRIAR / SALVAR CAMPANHA (valor manual + revisar/publicar)
    # ----------------------------------------------------------------
    def create_campaign(
        self,
        *,
        video_id: int,
        budget_amount: float,
        budget_period: str = "weekly",
        publish: bool = False,
    ) -> dict:
        asset = self.db.query(VideoAsset).filter(VideoAsset.id == video_id).first()
        if asset is None:
            raise ValueError("Video nao encontrado.")

        plan = self.recommend_for_video(asset)

        period = "monthly" if str(budget_period).lower().startswith("month") else "weekly"
        divisor = 30.0 if period == "monthly" else 7.0
        amount = max(float(budget_amount or 0), 0.0)
        daily = round(amount / divisor, 2) if amount > 0 else 0.0

        campaign = AdCampaign(
            video_asset_id=asset.id,
            platform="meta",
            name=f"{plan['goal_label']} — {asset.title or asset.topic or asset.id}",
            goal=plan["goal"],
            objective=plan["objective"],
            optimization_goal=plan["optimization_goal"],
            market=plan["market"],
            budget_amount=amount,
            budget_period=period,
            currency=plan["currency"],
            daily_budget=daily,
            audience=plan["audience"],
            placements=plan["placements"],
            primary_text=plan["primary_text"],
            headline=plan["headline"],
            description=plan["description"],
            cta=plan["cta"],
            link_url=plan["link_url"],
            status=AdCampaignStatusEnum.REVIEW,
        )
        self.db.add(campaign)
        self.db.commit()
        self.db.refresh(campaign)

        if publish:
            return self.launch_campaign(campaign.id)

        return self._serialize(campaign)

    # ----------------------------------------------------------------
    # PUBLICAR (envia para a Meta como campanha PAUSADA, por seguranca)
    # ----------------------------------------------------------------
    def launch_campaign(self, campaign_id: int) -> dict:
        campaign = (
            self.db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
        )
        if campaign is None:
            raise ValueError("Campanha nao encontrada.")

        if not campaign.budget_amount or campaign.budget_amount <= 0:
            campaign.status = AdCampaignStatusEnum.FAILED
            campaign.error = "Defina um valor de orcamento antes de publicar."
            self.db.commit()
            return self._serialize(campaign)

        token = os.getenv("META_ACCESS_TOKEN")
        market = (campaign.market or "BR").upper()
        ad_account = (
            os.getenv(f"META_AD_ACCOUNT_ID_{market}")
            or os.getenv("META_AD_ACCOUNT_ID")
            or ""
        ).strip()

        if not token or not ad_account:
            campaign.status = AdCampaignStatusEnum.CREDENTIALS_MISSING
            campaign.error = (
                "Falta a Conta de Anuncios da Meta. Crie no Gerenciador de "
                f"Anuncios e defina META_AD_ACCOUNT_ID_{market} no .env. "
                "O plano ja esta pronto para publicar quando a conta existir."
            )
            self.db.commit()
            return self._serialize(campaign)

        campaign.status = AdCampaignStatusEnum.LAUNCHING
        self.db.commit()

        try:
            external_id, external_url = self._create_meta_campaign(
                campaign, token, ad_account
            )
            # Criada PAUSADA de proposito: nada gasta ate voce ativar no
            # Gerenciador de Anuncios (protecao contra gasto acidental).
            campaign.external_campaign_id = external_id
            campaign.external_url = external_url
            campaign.status = AdCampaignStatusEnum.PAUSED
            campaign.error = None
            campaign.launched_at = _now()
            campaign.notes = (
                "Campanha criada PAUSADA no Gerenciador de Anuncios. "
                "Revise e clique em Ativar para comecar a rodar."
            )
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            campaign.status = AdCampaignStatusEnum.FAILED
            campaign.error = str(exc)
            self.db.commit()

        return self._serialize(campaign)

    def _create_meta_campaign(
        self, campaign: AdCampaign, token: str, ad_account: str
    ) -> tuple[str, str]:
        import requests

        acct = ad_account if ad_account.startswith("act_") else f"act_{ad_account}"
        url = f"{GRAPH_BASE}/{acct}/campaigns"
        resp = requests.post(
            url,
            data={
                "name": (campaign.name or "ATLAS OS")[:400],
                "objective": campaign.objective or "OUTCOME_ENGAGEMENT",
                "status": "PAUSED",  # SEGURANCA: nunca comeca gastando
                "special_ad_categories": "[]",
                "access_token": token,
            },
            timeout=30,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "id" not in data:
            err = (data.get("error") or {}).get("message") or resp.text
            raise RuntimeError(f"Meta API: {err}")
        camp_id = data.get("id")
        if not camp_id:
            raise RuntimeError(f"Meta API sem id: {resp.text}")
        manager_url = (
            "https://adsmanager.facebook.com/adsmanager/manage/campaigns"
            f"?act={acct.replace('act_', '')}"
        )
        return camp_id, manager_url

    # ----------------------------------------------------------------
    # LEITURA
    # ----------------------------------------------------------------
    def list_campaigns(self) -> list[dict]:
        rows = (
            self.db.query(AdCampaign)
            .order_by(AdCampaign.created_at.desc())
            .all()
        )
        return [self._serialize(c) for c in rows]

    def get_campaign(self, campaign_id: int) -> Optional[dict]:
        c = self.db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
        return self._serialize(c) if c else None

    def status(self) -> dict:
        """Prontidao da area de marketing (para o painel)."""
        token = bool(os.getenv("META_ACCESS_TOKEN"))
        acct_br = bool(
            os.getenv("META_AD_ACCOUNT_ID_BR") or os.getenv("META_AD_ACCOUNT_ID")
        )
        acct_us = bool(
            os.getenv("META_AD_ACCOUNT_ID_US") or os.getenv("META_AD_ACCOUNT_ID")
        )
        public_base = (os.getenv("ATLAS_PUBLIC_BASE_URL") or "").strip()
        public_ready = public_base.startswith("https://")
        return {
            "meta_token": token,
            "ad_account_br": acct_br,
            "ad_account_us": acct_us,
            "tiktok_ads": bool(os.getenv("TIKTOK_ADVERTISER_ID")),
            "public_url": public_base or None,
            "public_url_ready": public_ready,
            "can_launch": token and (acct_br or acct_us),
        }

    def _serialize(self, c: AdCampaign) -> dict:
        return {
            "id": c.id,
            "video_id": c.video_asset_id,
            "video_title": c.video.title if c.video else None,
            "platform": c.platform,
            "name": c.name,
            "goal": c.goal,
            "objective": c.objective,
            "optimization_goal": c.optimization_goal,
            "market": c.market,
            "budget_amount": c.budget_amount,
            "budget_period": c.budget_period,
            "currency": c.currency,
            "daily_budget": c.daily_budget,
            "audience": c.audience,
            "placements": c.placements,
            "primary_text": c.primary_text,
            "headline": c.headline,
            "description": c.description,
            "cta": c.cta,
            "link_url": c.link_url,
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
            "external_campaign_id": c.external_campaign_id,
            "external_url": c.external_url,
            "error": c.error,
            "notes": c.notes,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "launched_at": c.launched_at.isoformat() if c.launched_at else None,
        }
