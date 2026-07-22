import os
import re
import json
import html
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import yt_dlp
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class MetadataService:
    def __init__(self):
        self.max_youtube_title = 95
        self.max_youtube_description = 4900
        self.max_tiktok_caption = 2200
        self.max_instagram_caption = 2200
        self.max_facebook_caption = 3000

        # Quantidade IDEAL de hashtags por plataforma (ajuste inteligente).
        # Mais hashtags NAO da proporcionalmente mais views: cada rede tem um
        # ponto ideal e passar dele pode cheirar a spam e reduzir alcance.
        #   - Instagram: hashtag ajuda de verdade na descoberta (8-15).
        #   - TikTok: algoritmo entende pelo conteudo/audio; poucas e relevantes (3-6).
        #   - YouTube Shorts: so as ~3 primeiras contam de verdade (3-5).
        #   - Facebook: hashtag tem pouco efeito no alcance (2-5).
        self.max_hashtags_instagram = 15
        self.max_hashtags_tiktok = 5
        self.max_hashtags_youtube = 4
        self.max_hashtags_facebook = 4
        # Teto da lista-mestre (a maior das redes define o limite de geracao).
        self.max_hashtags_master = 15

        self.api_key = os.getenv("GROQ_API_KEY")

        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.groq.com/openai/v1"
            )
        else:
            self.client = None

        self.max_research_items = self._env_int("ATLAS_METADATA_RESEARCH_ITEMS", 5)

    # ====================================================================
    # ENV / LIMPEZA
    # ====================================================================

    def _env_int(self, name: str, default: int) -> int:
        try:
            return int(os.getenv(name, default))
        except Exception:
            return default

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""

        text = str(text).strip()
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _normalize(self, text: str) -> str:
        if not text:
            return ""

        text = text.lower().strip()
        text = re.sub(r"[^a-zA-Z0-9À-ÿ\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _truncate(self, text: str, limit: int) -> str:
        text = self._clean_text(text)

        if len(text) <= limit:
            return text

        shortened = text[:limit].rstrip()
        shortened = shortened.rsplit(" ", 1)[0].strip()

        return shortened or text[:limit].rstrip()

    def _dedupe_list(self, items):
        result = []
        seen = set()

        for item in items or []:
            item = self._clean_text(str(item))

            if not item:
                continue

            key = item.lower()

            if key in seen:
                continue

            seen.add(key)
            result.append(item)

        return result

    def _dedupe_hashtags(self, hashtags):
        result = []
        seen = set()

        for hashtag in hashtags or []:
            if not hashtag:
                continue

            hashtag = str(hashtag).strip()
            hashtag = hashtag.replace(" ", "")
            hashtag = re.sub(r"[^#a-zA-Z0-9À-ÿ_]", "", hashtag)

            if not hashtag:
                continue

            if not hashtag.startswith("#"):
                hashtag = f"#{hashtag}"

            if len(hashtag) <= 1:
                continue

            key = hashtag.lower()

            if key in seen:
                continue

            seen.add(key)
            result.append(hashtag)

        return result

    def _extract_first_sentence(self, script: str):
        if not script:
            return ""

        script = str(script).strip()

        script = re.sub(
            r"(?im)^\s*(hook|body|intro|title|caption|voiceover|call to action|cta|breaking news|script|roteiro)\s*:\s*",
            "",
            script
        )

        script = script.replace('"', "")
        script = script.replace("'", "")
        script = re.sub(r"\s+", " ", script).strip()

        if not script:
            return ""

        parts = re.split(r"(?<=[.!?])\s+", script)

        if parts:
            return parts[0].strip()[:220]

        return script[:220]

    def _geo_language_label(self, geo: str) -> str:
        geo = str(geo or "US").upper().strip()

        if geo == "BR":
            return "Portuguese (Brazil), natural Brazilian social media tone"

        return "English, natural American social media tone"

    # ====================================================================
    # MODELO IA
    # ====================================================================

    def _get_best_model(self):
        if not self.client:
            raise RuntimeError("GROQ_API_KEY não configurada. Metadata deve ser gerada por IA.")

        try:
            models = self.client.models.list()
            active_models = [m.id for m in models]

            priorities = [
                "llama-3.3-70b-versatile",
                "llama-3.1-70b-versatile",
                "llama-3.1-8b-instant",
                "llama-3.1-8b-instant",
            ]

            for model_name in priorities:
                if model_name in active_models:
                    return model_name

            if active_models:
                return active_models[0]

        except Exception as e:
            print(f"⚠️ [METADATA ENGINE] Aviso ao listar modelos: {e}")

        return "llama-3.1-8b-instant"

    def _generate_with_ai(self, prompt: str, active_model: str, temperature: float = 0.55):
        """
        Gera metadata com fallback automático se o modelo principal bater limite.
        """
        if not self.client:
            raise RuntimeError("GROQ_API_KEY não configurada.")

        fallback_models = [
            active_model,
            "llama-3.1-8b-instant"
        ]

        models_to_try = []
        seen = set()

        for model_name in fallback_models:
            if not model_name:
                continue

            if model_name in seen:
                continue

            seen.add(model_name)
            models_to_try.append(model_name)

        last_error = None

        for model_name in models_to_try:
            try:
                if model_name != active_model:
                    print(f"⚠️ [METADATA ENGINE] Tentando modelo alternativo por limite/erro: {model_name}")

                response = self.client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an expert social video metadata strategist. "
                                "Return valid JSON only. No markdown. No explanation. "
                                "Use only the provided topic, script, source, and research context."
                            )
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    max_tokens=700,
                    temperature=temperature,
                    top_p=0.90,
                    presence_penalty=0.10,
                    frequency_penalty=0.25
                )

                return response.choices[0].message.content

            except Exception as e:
                last_error = e
                error_text = str(e).lower()

                if "429" in error_text or "rate_limit" in error_text or "rate limit" in error_text:
                    print(f"⚠️ [METADATA ENGINE] Limite atingido no modelo {model_name}. Tentando próximo modelo...")
                    continue

                raise

        raise last_error

    # ====================================================================
    # PESQUISA SOBRE A TREND
    # ====================================================================

    def _search_google_news_rss(self, topic: str, geo: str):
        """
        Pesquisa leve em Google News RSS.
        Não gera texto final. Apenas coleta contexto para a IA.
        """
        topic = self._clean_text(topic)

        if not topic:
            return []

        geo = str(geo or "US").upper().strip()

        if geo == "BR":
            params = {
                "q": topic,
                "hl": "pt-BR",
                "gl": "BR",
                "ceid": "BR:pt-419"
            }
        else:
            params = {
                "q": topic,
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en"
            }

        query = urllib.parse.urlencode(params)
        url = f"https://news.google.com/rss/search?{query}"

        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            with urllib.request.urlopen(request, timeout=8) as response:
                raw_xml = response.read()

            root = ET.fromstring(raw_xml)

            items = []

            for item in root.findall(".//item"):
                title = self._clean_text(item.findtext("title") or "")
                source = ""

                source_node = item.find("source")
                if source_node is not None and source_node.text:
                    source = self._clean_text(source_node.text)

                pub_date = self._clean_text(item.findtext("pubDate") or "")

                if title:
                    items.append({
                        "type": "news",
                        "title": title,
                        "source": source,
                        "published": pub_date
                    })

                if len(items) >= self.max_research_items:
                    break

            return items

        except Exception as e:
            print(f"⚠️ [METADATA RESEARCH] Google News RSS indisponível: {e}")
            return []

    def _search_youtube_context(self, topic: str, geo: str):
        """
        Pesquisa leve no YouTube via yt-dlp.
        Não baixa vídeo. Apenas coleta títulos/canais para contexto.
        """
        topic = self._clean_text(topic)

        if not topic:
            return []

        search_count = max(5, min(self.max_research_items, 15))
        search_query = f"ytsearch{search_count}:{topic}"

        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "noplaylist": True,
            "default_search": f"ytsearch{search_count}",
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_query, download=False)

            entries = info.get("entries", []) if info else []

            items = []

            for entry in entries:
                if not entry:
                    continue

                title = self._clean_text(entry.get("title", "") or "")
                channel = self._clean_text(
                    entry.get("uploader", "")
                    or entry.get("channel", "")
                    or entry.get("creator", "")
                    or ""
                )

                if title:
                    items.append({
                        "type": "youtube",
                        "title": title,
                        "source": channel
                    })

                if len(items) >= self.max_research_items:
                    break

            return items

        except Exception as e:
            print(f"⚠️ [METADATA RESEARCH] YouTube search indisponível: {e}")
            return []

    def _collect_research_context(self, topic: str, geo: str, trend_source: str = ""):
        """
        Coleta contexto real antes de chamar a IA.

        Importante:
        - Esta função não escreve metadata.
        - Ela só fornece material pesquisado para a IA.
        """
        print(f"🔎 [METADATA RESEARCH] Pesquisando contexto atual sobre: '{topic}'...")

        news_items = self._search_google_news_rss(topic, geo)
        youtube_items = self._search_youtube_context(topic, geo)

        combined = []

        for item in news_items:
            combined.append(item)

        for item in youtube_items:
            combined.append(item)

        if not combined:
            print("⚠️ [METADATA RESEARCH] Nenhum contexto externo encontrado. IA usará apenas topic/script/source.")
            return ""

        lines = []

        if trend_source:
            lines.append(f"Trend source provided by system: {trend_source}")

        for index, item in enumerate(combined[: self.max_research_items], start=1):
            item_type = item.get("type", "source")
            title = self._clean_text(item.get("title", ""))
            source = self._clean_text(item.get("source", ""))
            published = self._clean_text(item.get("published", ""))

            line = f"{index}. [{item_type}] {title}"

            if source:
                line += f" | Source: {source}"

            if published:
                line += f" | Published: {published}"

            lines.append(line)

        context = "\n".join(lines)

        print(f"✅ [METADATA RESEARCH] Contexto coletado com {len(lines)} item(ns).")

        return context

    # ====================================================================
    # PROMPTS
    # ====================================================================

    def _build_metadata_prompt(
        self,
        topic: str,
        script: str,
        geo: str,
        base_hashtags,
        trend_source: str,
        research_context: str
    ):
        language_label = self._geo_language_label(geo)
        hook = self._extract_first_sentence(script)
        base_hashtag_line = " ".join(base_hashtags or [])

        if str(geo or "US").upper().strip() == "BR":
            return f"""
Você é um estrategista especialista em metadata para YouTube Shorts, TikTok, Instagram Reels e Facebook Reels.

Sua tarefa é gerar metadata completa, natural, específica e otimizada para descoberta.

IDIOMA:
{language_label}

TEMA/TREND:
{topic}

FONTE DA TREND:
{trend_source or "Não informada"}

ROTEIRO DO VÍDEO:
{script}

HOOK/PRIMEIRA FRASE:
{hook}

HASHTAGS BASE EXISTENTES:
{base_hashtag_line or "Nenhuma"}

CONTEXTO PESQUISADO SOBRE A TREND:
{research_context or "Nenhum contexto externo encontrado."}

REGRAS CRÍTICAS:
- Use a pesquisa acima para entender o contexto real.
- Não invente fatos que não estejam no tema, roteiro, fonte ou contexto pesquisado.
- Não use frases genéricas como:
  "o assunto que está explodindo agora",
  "todo mundo está falando disso",
  "entenda o que está acontecendo",
  "você viu isso vindo?"
- Não use tom de telejornal.
- Não use clickbait falso.
- Não use emojis.
- Não use markdown.
- Não mencione que foi feito por IA.
- Não mencione ferramentas digitais.
- Não use frases fixas.
- Adapte cada campo à plataforma.
- O título precisa ser específico, curto e clicável.
- As captions precisam soar humanas.
- Hashtags devem ser relevantes ao assunto, não só genéricas.
- Tags do YouTube devem incluir termos relacionados encontrados na pesquisa.
- Retorne somente JSON válido.

FORMATO JSON OBRIGATÓRIO:
{{
  "youtube_title": "string com no máximo 95 caracteres",
  "youtube_description": "descrição natural com 2 a 4 parágrafos curtos",
  "youtube_tags": ["tag 1", "tag 2", "tag 3"],
  "tiktok_caption": "caption curta e forte com hashtags",
  "instagram_caption": "caption natural com quebra de linhas e hashtags",
  "facebook_caption": "caption natural para Facebook com hashtags",
  "hashtags": ["#Hashtag1", "#Hashtag2"]
}}
"""

        return f"""
You are an expert metadata strategist for YouTube Shorts, TikTok, Instagram Reels, and Facebook Reels.

Your task is to generate complete, natural, specific, discovery-optimized metadata.

LANGUAGE:
{language_label}

TOPIC/TREND:
{topic}

TREND SOURCE:
{trend_source or "Not provided"}

VIDEO SCRIPT:
{script}

HOOK/FIRST SENTENCE:
{hook}

EXISTING BASE HASHTAGS:
{base_hashtag_line or "None"}

RESEARCHED CONTEXT ABOUT THE TREND:
{research_context or "No external context found."}

CRITICAL RULES:
- Use the research above to understand the real context.
- Do not invent facts that are not supported by the topic, script, source, or research context.
- Do not use generic phrases like:
  "why everyone is talking about it",
  "everyone is talking about this",
  "here is a quick breakdown",
  "did you see this coming?"
- Do not sound like a generic news anchor.
- Do not use fake clickbait.
- Do not use emojis.
- Do not use markdown.
- Do not mention AI.
- Do not mention digital tools.
- Do not use fixed phrases.
- Adapt each field to the platform.
- The title must be specific, short, and clickable.
- Captions must sound human and platform-native.
- Hashtags must be relevant to the actual topic, not just generic.
- YouTube tags must include related terms found in the research.
- Return valid JSON only.

REQUIRED JSON FORMAT:
{{
  "youtube_title": "string max 95 characters",
  "youtube_description": "natural description with 2 to 4 short paragraphs",
  "youtube_tags": ["tag 1", "tag 2", "tag 3"],
  "tiktok_caption": "short strong caption with hashtags",
  "instagram_caption": "natural caption with line breaks and hashtags",
  "facebook_caption": "natural Facebook caption with hashtags",
  "hashtags": ["#Hashtag1", "#Hashtag2"]
}}
"""

    def _build_repair_prompt(self, previous_response: str, issue: str):
        return f"""
The previous response was invalid or incomplete.

ISSUE:
{issue}

PREVIOUS RESPONSE:
{previous_response}

Return only valid JSON with this exact structure:
{{
  "youtube_title": "string max 95 characters",
  "youtube_description": "string",
  "youtube_tags": ["tag 1", "tag 2"],
  "tiktok_caption": "string",
  "instagram_caption": "string",
  "facebook_caption": "string",
  "hashtags": ["#Hashtag1", "#Hashtag2"]
}}

Rules:
- Valid JSON only.
- No markdown.
- No explanation.
- No generic filler.
- No unsupported facts.
"""

    # ====================================================================
    # JSON / VALIDAÇÃO
    # ====================================================================

    def _extract_json_object(self, text: str):
        if not text:
            raise RuntimeError("IA retornou metadata vazia.")

        text = text.strip()

        text = text.replace("```json", "")
        text = text.replace("```", "")
        text = text.strip()

        # strict=False permite caracteres de controle (quebras de linha reais,
        # tabs) dentro das strings, que a IA às vezes devolve.
        try:
            return json.loads(text, strict=False)
        except Exception:
            pass

        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("IA não retornou JSON válido para metadata.")

        candidate = text[start:end + 1]

        try:
            return json.loads(candidate, strict=False)
        except Exception:
            pass

        # Última tentativa: escapar caracteres de controle que ficaram
        # soltos dentro das strings (quebras de linha, tabs, etc.).
        sanitized = self._escape_control_chars(candidate)

        try:
            return json.loads(sanitized, strict=False)
        except Exception as e:
            raise RuntimeError(f"Falha ao interpretar JSON da IA: {e}")

    def _escape_control_chars(self, text: str) -> str:
        """Escapa caracteres de controle (0x00-0x1F) que aparecem dentro de
        strings JSON, preservando os que já estão escapados corretamente."""
        result = []
        in_string = False
        escaped = False
        for ch in text:
            if escaped:
                result.append(ch)
                escaped = False
                continue
            if ch == "\\":
                result.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
                continue
            if in_string and ch < " ":
                if ch == "\n":
                    result.append("\\n")
                elif ch == "\r":
                    result.append("\\r")
                elif ch == "\t":
                    result.append("\\t")
                else:
                    result.append(f"\\u{ord(ch):04x}")
                continue
            result.append(ch)
        return "".join(result)

    def _validate_metadata_payload(self, payload):
        if not isinstance(payload, dict):
            raise RuntimeError("Metadata IA inválida: payload não é objeto JSON.")

        required_keys = [
            "youtube_title",
            "youtube_description",
            "youtube_tags",
            "tiktok_caption",
            "instagram_caption",
            "facebook_caption",
            "hashtags"
        ]

        missing = [key for key in required_keys if key not in payload]

        if missing:
            raise RuntimeError(f"Metadata IA incompleta. Campos ausentes: {missing}")

        if not isinstance(payload.get("youtube_tags"), list):
            raise RuntimeError("Metadata IA inválida: youtube_tags precisa ser lista.")

        if not isinstance(payload.get("hashtags"), list):
            raise RuntimeError("Metadata IA inválida: hashtags precisa ser lista.")

        return True

    def _sanitize_metadata_payload(self, payload, geo: str, base_hashtags=None):
        youtube_title = self._truncate(payload.get("youtube_title", ""), self.max_youtube_title)

        youtube_description = str(payload.get("youtube_description", "") or "").strip()
        youtube_description = youtube_description.replace("\r\n", "\n")
        youtube_description = re.sub(r"\n{3,}", "\n\n", youtube_description)
        youtube_description = youtube_description[: self.max_youtube_description].rstrip()

        youtube_tags = self._dedupe_list(payload.get("youtube_tags", []))[:24]

        ai_hashtags = self._dedupe_hashtags(payload.get("hashtags", []))

        if base_hashtags:
            hashtags = self._dedupe_hashtags(ai_hashtags + list(base_hashtags))
        else:
            hashtags = ai_hashtags

        hashtags = hashtags[: self.max_hashtags_master]

        # Ajuste inteligente: cada rede recebe a quantidade IDEAL de hashtags
        # (as primeiras da lista sao as mais fortes/relevantes).
        tiktok_hashtag_line = " ".join(hashtags[: self.max_hashtags_tiktok])
        instagram_hashtag_line = " ".join(hashtags[: self.max_hashtags_instagram])
        facebook_hashtag_line = " ".join(hashtags[: self.max_hashtags_facebook])
        youtube_hashtag_line = " ".join(hashtags[: self.max_hashtags_youtube])

        tiktok_caption = str(payload.get("tiktok_caption", "") or "").strip()
        instagram_caption = str(payload.get("instagram_caption", "") or "").strip()
        facebook_caption = str(payload.get("facebook_caption", "") or "").strip()

        # Se a IA retornou caption sem hashtags, apenas anexamos as hashtags geradas por IA.
        # Não cria frase nova. Cada rede usa a quantidade ideal para ela.
        if tiktok_hashtag_line and "#" not in tiktok_caption:
            tiktok_caption = f"{tiktok_caption} {tiktok_hashtag_line}".strip()

        if instagram_hashtag_line and "#" not in instagram_caption:
            instagram_caption = f"{instagram_caption}\n\n{instagram_hashtag_line}".strip()

        if facebook_hashtag_line and "#" not in facebook_caption:
            facebook_caption = f"{facebook_caption}\n\n{facebook_hashtag_line}".strip()

        if youtube_hashtag_line and "#" not in youtube_description:
            youtube_description = f"{youtube_description}\n\n{youtube_hashtag_line}".strip()

        tiktok_caption = self._truncate(tiktok_caption, self.max_tiktok_caption)
        instagram_caption = instagram_caption[: self.max_instagram_caption].rstrip()
        facebook_caption = facebook_caption[: self.max_facebook_caption].rstrip()

        return {
            "title": youtube_title,
            "youtube_title": youtube_title,
            "youtube_description": youtube_description,
            "youtube_tags": youtube_tags,
            "tiktok_caption": tiktok_caption,
            "instagram_caption": instagram_caption,
            "facebook_caption": facebook_caption,
            "hashtags": hashtags,
            "geo": str(geo or "US").upper().strip(),
            "ai_generated": True,
            "metadata_researched": True,
            "made_for_shorts": True,
            "format": "vertical_1080x1920"
        }

    # ====================================================================
    # FUNÇÃO PRINCIPAL
    # ====================================================================

    def build_metadata(
        self,
        topic: str,
        script: str,
        geo: str = "US",
        base_hashtags=None,
        trend_source: str = "",
        research_context: str = ""
    ):
        """
        Retorna metadata pronta para upload.

        Plataformas:
        - YouTube Shorts
        - TikTok
        - Instagram Reels
        - Facebook Reels

        Importante:
        - A metadata final é gerada por IA.
        - O serviço pesquisa contexto antes da geração.
        - Não há caption hard coded.
        - Se a IA falhar, levanta erro.
        """
        if not self.client:
            raise RuntimeError("GROQ_API_KEY não configurada. Metadata não gerada porque deve usar IA.")

        topic = self._clean_text(topic)
        script = self._clean_text(script)
        geo = str(geo or "US").upper().strip()

        if not topic:
            raise RuntimeError("Metadata não gerada: topic vazio.")

        if not script:
            raise RuntimeError("Metadata não gerada: script vazio.")

        active_model = self._get_best_model()

        if not research_context:
            research_context = self._collect_research_context(
                topic=topic,
                geo=geo,
                trend_source=trend_source
            )

        print(f"🏷️ [METADATA ENGINE] Gerando metadata com IA usando: {active_model}")

        prompt = self._build_metadata_prompt(
            topic=topic,
            script=script,
            geo=geo,
            base_hashtags=base_hashtags or [],
            trend_source=trend_source,
            research_context=research_context
        )

        raw_response = self._generate_with_ai(
            prompt=prompt,
            active_model=active_model,
            temperature=0.52
        )

        try:
            payload = self._extract_json_object(raw_response)
            self._validate_metadata_payload(payload)
        except Exception as first_error:
            print(f"⚠️ [METADATA ENGINE] Metadata IA inválida. Tentando reparar: {first_error}")

            repair_prompt = self._build_repair_prompt(
                previous_response=raw_response,
                issue=str(first_error)
            )

            repaired_response = self._generate_with_ai(
                prompt=repair_prompt,
                active_model=active_model,
                temperature=0.30
            )

            payload = self._extract_json_object(repaired_response)
            self._validate_metadata_payload(payload)

        metadata = self._sanitize_metadata_payload(
            payload=payload,
            geo=geo,
            base_hashtags=base_hashtags or []
        )

        print("✅ [METADATA ENGINE] Metadata IA pronta.")

        return metadata
