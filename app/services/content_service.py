import html
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

import yt_dlp
from dotenv import load_dotenv
from openai import OpenAI

try:
    from google import genai
except Exception:
    genai = None


load_dotenv()


class ContentService:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")

        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.groq.com/openai/v1",
            )
        else:
            self.client = None

        # --- Google Gemini (fallback inteligente) ---
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.gemini_model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.gemini_client = None
        
        if self.gemini_key and genai is not None:
            try:
                self.gemini_client = genai.Client(api_key=self.gemini_key)
                print(f"✅ [CONTENT ENGINE] Google Gemini pronto como fallback: {self.gemini_model_name}")
            except Exception as e:
                print(f"⚠️ [CONTENT ENGINE] Falha ao iniciar Gemini: {e}")
                self.gemini_client = None


        self.max_research_items = self._env_int("ATLAS_CONTENT_RESEARCH_ITEMS", 6)

        self.last_research_context = ""

        self.target_min_words = self._env_int("ATLAS_SCRIPT_MIN_WORDS", 170)
        self.target_max_words = self._env_int("ATLAS_SCRIPT_MAX_WORDS", 240)
        self.absolute_max_words = self._env_int("ATLAS_SCRIPT_ABSOLUTE_MAX_WORDS", 260)

        # Teto de tokens da resposta da IA. Precisa ser alto o bastante para
        # os modelos de raciocinio (gpt-oss) "pensarem" E ainda escreverem o
        # roteiro; caso contrario o texto final volta vazio (0 palavras).
        self.ai_max_tokens = self._env_int("ATLAS_AI_MAX_TOKENS", 1600)

    # ====================================================================
    # ENV / LIMPEZA
    # ====================================================================

    def _env_int(self, name: str, default: int) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return int(value)
        except Exception:
            return default

    def _get_best_model(self):
        if not self.client:
            raise RuntimeError("GROQ_API_KEY não configurada. Não é possível gerar roteiro com IA.")

        try:
            models = self.client.models.list()
            active_models = [m.id for m in models]

            # Removido o modelo llama-3.1-70b-versatile que foi desligado pelo Groq
            priorities = [
                "openai/gpt-oss-120b",
                "openai/gpt-oss-20b",
                "qwen/qwen3.6-27b",
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
            ]


            for model_name in priorities:
                if model_name in active_models:
                    return model_name

            if active_models:
                return active_models[0]

        except Exception as e:
            print(f"⚠️ [CONTENT ENGINE] Aviso ao listar modelos: {e}")

        return "llama-3.1-8b-instant"

    def _clean_text(self, text: Any) -> str:
        if not text:
            return ""
        text = str(text).strip()
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _clean_topic_for_prompt(self, topic: str) -> str:
        text = self._clean_text(topic)
        if not text:
            return "current trending topic"

        text = re.sub(r"[^\w\sÀ-ÿ:;,.!?\"'&+\-/]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text or self._clean_text(topic)

    def _clean_script(self, text: str) -> str:
        if not text:
            return ""

        text = str(text).strip()
        text = text.replace("```", "")

        text = re.sub(
            r"(?im)^\s*(hook|body|intro|title|caption|voiceover|call to action|cta|outro|script|roteiro|narração|narration|final voiceover|final script|texto final|versão final)\s*:\s*",
            "",
            text,
        )

        text = re.sub(r"\[.*?\]", "", text)
        text = re.sub(r"\(.*?camera.*?\)", "", text, flags=re.I)
        text = re.sub(r"\(.*?visual.*?\)", "", text, flags=re.I)
        text = re.sub(r"\(.*?cut.*?\)", "", text, flags=re.I)
        text = re.sub(r"\(.*?pause.*?\)", "", text, flags=re.I)
        text = re.sub(r"\(.*?beat.*?\)", "", text, flags=re.I)
        text = re.sub(r"\(.*?music.*?\)", "", text, flags=re.I)
        text = re.sub(r"\(.*?sound.*?\)", "", text, flags=re.I)

        text = text.strip().strip('"').strip("'")
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s+([,.!?])", r"\1", text)
        text = re.sub(r"\.{2,}", ".", text)

        return text.strip()

    def _word_count(self, text: str) -> int:
        if not text:
            return 0
        return len(re.findall(r"\b\w+\b", text))

    def _trim_to_word_limit(self, text: str, max_words: int = 190) -> str:
        if not text:
            return ""

        words = text.split()
        if len(words) <= max_words:
            return text.strip()

        trimmed = " ".join(words[:max_words])

        last_sentence_end = max(
            trimmed.rfind("."),
            trimmed.rfind("!"),
            trimmed.rfind("?"),
        )

        if last_sentence_end > 55:
            trimmed = trimmed[: last_sentence_end + 1]

        return trimmed.strip()

    def _is_portuguese(self, language: str) -> bool:
        lang = str(language or "").lower()
        return (
            "portuguese" in lang
            or lang.startswith("pt")
            or "brasil" in lang
            or "brazil" in lang
        )

    def _looks_like_bare_name_or_ambiguous_topic(self, topic: str) -> bool:
        topic_clean = self._clean_text(topic)
        if not topic_clean:
            return True

        words = re.findall(r"\b[\w'-]+\b", topic_clean)
        if len(words) <= 3:
            return True

        topic_lower = topic_clean.lower()

        context_terms = [
            "trailer", "official", "testimony", "congress", "hearing",
            "goal", "match", "final", "game", "episode", "season", "album",
            "song", "movie", "series", "release", "announcement", "controversy",
            "injury", "transfer", "election", "court", "senate", "fifa", "nba",
            "nfl", "mlb", "nhl", "anime", "manga", "k-pop", "kpop", "teaser",
            "music video", "live", "mod", "gameplay", "gta", "minecraft",
            "roblox", "fortnite", "world cup", "mundial", "copa", "futebol",
            "football", "soccer", "switzerland", "colombia", "suiza", "colômbia",
        ]

        if any(term in topic_lower for term in context_terms):
            return False

        return len(words) <= 5

    # ====================================================================
    # PESQUISA SOBRE A TREND
    # ====================================================================

    def _search_google_news_rss(self, topic: str, language: str):
        topic = self._clean_text(topic)
        if not topic:
            return []

        is_pt = self._is_portuguese(language)

        params = {
            "q": topic,
            "hl": "pt-BR" if is_pt else "en-US",
            "gl": "BR" if is_pt else "US",
            "ceid": "BR:pt-419" if is_pt else "US:en",
        }

        query = urllib.parse.urlencode(params)
        url = f"https://news.google.com/rss/search?{query}"

        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
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
                    items.append(
                        {
                            "type": "news",
                            "title": title,
                            "source": source,
                            "published": pub_date,
                        }
                    )

                if len(items) >= self.max_research_items:
                    break

            return items

        except Exception as e:
            print(f"⚠️ [CONTENT RESEARCH] Google News RSS indisponível: {e}")
            return []

    def _search_youtube_context(self, topic: str, language: str):
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
                    items.append(
                        {
                            "type": "youtube",
                            "title": title,
                            "source": channel,
                        }
                    )

                if len(items) >= self.max_research_items:
                    break

            return items

        except Exception as e:
            print(f"⚠️ [CONTENT RESEARCH] YouTube search indisponível: {e}")
            return []

    def _collect_research_context(self, topic: str, language: str, trend_source: str = ""):
        print(f"🔎 [CONTENT RESEARCH] Pesquisando contexto atual sobre: '{topic}'...")

        news_items = self._search_google_news_rss(topic, language)
        youtube_items = self._search_youtube_context(topic, language)

        combined = news_items + youtube_items

        if not combined:
            print("⚠️ [CONTENT RESEARCH] Nenhum contexto externo encontrado. IA usará apenas topic/source.")
            self.last_research_context = ""
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
        self.last_research_context = context

        print(f"✅ [CONTENT RESEARCH] Contexto coletado com {len(lines)} linha(s).")
        return context

    # ====================================================================
    # PROMPTS
    # ====================================================================

    def _build_ai_script_prompt(
        self,
        topic: str,
        language: str,
        trend_source: str = "",
        research_context: str = "",
    ) -> str:
        is_pt = self._is_portuguese(language)
        clean_topic = self._clean_topic_for_prompt(topic)
        is_ambiguous = self._looks_like_bare_name_or_ambiguous_topic(clean_topic)

        ambiguity_warning_pt = """
ATENÇÃO ESPECIAL:
Este tema parece curto ou ambíguo.
Use primeiro o CONTEXTO PESQUISADO para identificar sobre o que a trend provavelmente é.
Não afirme profissão, cargo, nacionalidade, idade, evento, acusação, estatística ou fato específico se isso não estiver explicitamente no tema, fonte ou contexto pesquisado.
Não transforme um nome em artista, atleta, político, juiz, cantor, árbitro ou qualquer outra categoria por adivinhação.
Se a pesquisa mostrar contexto consistente, use esse contexto com cuidado.
Se faltar contexto, trate como uma busca em alta e fale com segurança sobre a curiosidade em torno do termo.
""" if is_ambiguous else """
ATENÇÃO ESPECIAL:
Use o contexto pesquisado para entender a trend.
Não invente fatos específicos que não estejam presentes no tema, fonte ou contexto pesquisado.
Use apenas informações apoiadas pelo contexto fornecido.
"""

        ambiguity_warning_en = """
SPECIAL WARNING:
This topic looks short or ambiguous.
Use the RESEARCH CONTEXT first to identify what the trend is probably about.
Do not claim a profession, role, nationality, age, event, accusation, statistic, or specific fact unless it is clearly present in the topic, source, or research context.
Do not turn a name into an artist, athlete, politician, judge, singer, referee, or any other category by guessing.
If the research shows consistent context, use that context carefully.
If context is still missing, treat it as a rising search and speak safely about the curiosity around the term.
""" if is_ambiguous else """
SPECIAL WARNING:
Use the research context to understand the trend.
Do not invent specific facts that are not present in the topic, source, or research context.
Use only information supported by the provided context.
"""

        if is_pt:
            return f"""
Você é um estrategista elite de vídeos curtos, roteirista viral e especialista em retenção para TikTok, YouTube Shorts, Instagram Reels e Facebook Reels.

Sua tarefa é criar uma narração curta, forte, natural e altamente retentiva para um vídeo vertical com foco em assistir até o fim, comentar, salvar e compartilhar.

TEMA/TREND:
{clean_topic}

FONTE DA TREND:
{trend_source or "Não informada"}

CONTEXTO PESQUISADO SOBRE A TREND:
{research_context or "Nenhum contexto externo encontrado."}

IDIOMA:
Português do Brasil.
ESCREVA 100% EM PORTUGUÊS DO BRASIL. Não escreva NENHUMA palavra ou frase em inglês. Todo o roteiro falado deve estar em português natural.

PRONÚNCIA (MUITO IMPORTANTE):
Esta narração será lida em voz alta por uma VOZ BRASILEIRA automática, que pronuncia tudo "ao pé da letra" em português. Se você deixar uma palavra em inglês na grafia original, a voz vai falar errado, letra por letra, soando como um "inglês abrasileirado". Para evitar isso:
- Traduza ou adapte para português qualquer expressão em inglês sempre que possível (ex.: "wild hearts" vira "corações selvagens"; "trending" vira "em alta"; "breaking news" vira "última hora").
- Quando um NOME PRÓPRIO em inglês (pessoa, marca, música, grupo, filme) for realmente necessário e não tiver tradução, ESCREVA-O DE FORMA APORTUGUESADA (foneticamente, do jeito que um brasileiro fala), NUNCA na grafia original em inglês.
  Exemplos de como escrever a pronúncia: "KATSEYE" → "Két-sái"; "WILD HEARTS" → "Uáild Ráts"; "New Liberty" → "Niú Líberti"; "YouTube" → "Iutúbi"; "Shorts" → "Shórts"; "TikTok" → "Tíc-Tóc".
- Nunca escreva uma palavra em inglês na grafia original dentro da narração.
- Quando puder, descreva o assunto em português em vez de repetir o nome estrangeiro várias vezes.

{ambiguity_warning_pt}

OBJETIVO ESTRATÉGICO:
- O vídeo precisa funcionar bem em YouTube Shorts, TikTok e Instagram Reels.
- O tom deve ser humano, nativo, rápido e com energia de internet.
- O roteiro deve parecer uma fala real, não um texto genérico de IA.
- O texto deve criar curiosidade imediata e sustentar atenção até o final.
- O CTA final deve soar natural e estimular comentário, compartilhamento ou salvamento.

NÃO MOSTRE ESSA ANÁLISE.
RETORNE APENAS A NARRAÇÃO FINAL.

REGRAS OBRIGATÓRIAS:
- Escreva apenas as palavras que o narrador vai falar.
- Use tom natural de rede social brasileira.
- Não use rótulos.
- Não use markdown.
- Não use emojis.
- Não inclua instruções visuais.
- O roteiro deve ter entre {self.target_min_words} e {self.target_max_words} palavras.
- Antes de responder, conte internamente as palavras.
- Não entregue menos de {self.target_min_words} palavras.
- A primeira frase deve ter menos de 12 palavras.
- A primeira frase precisa interromper o scroll.
- Use frases curtas e faladas.
- Crie curiosidade nos primeiros 2 segundos.
- Explique rápido por que esse tema pode importar.
- Inclua tensão, contraste, pergunta aberta ou detalhe inesperado.
- Termine com um CTA natural para comentar, compartilhar, salvar ou seguir.
- Não use CTA genérico demais.
- Não invente fatos específicos.
- Se faltar contexto, use linguagem segura.
- Não diga que algo aconteceu se isso não estiver claro no tema, fonte ou pesquisa.
- Evite começar com "No vídeo de hoje", "Vamos falar sobre" ou "Esse assunto está viralizando".
- Se a pesquisa mostrar contexto esportivo, cultural, musical, político ou de entretenimento, use esse ângulo com naturalidade.
- Evite linguagem excessivamente formal.
- Evite repetir a mesma ideia com palavras diferentes.
- O ritmo precisa parecer conversado, não lido.
- O meio do texto precisa criar uma virada ou aprofundamento.
- O final precisa dar recompensa emocional ou prática.

RETORNE SOMENTE O ROTEIRO FINAL DA NARRAÇÃO.
"""
        return f"""
You are an elite short-form video strategist, viral scriptwriter, and retention editor for TikTok, YouTube Shorts, Instagram Reels, and Facebook Reels.

Your task is to create a short, strong, high-retention voiceover for a vertical video built to maximize watch time, replays, comments, shares, saves, and follows.

TOPIC/TREND:
{clean_topic}

TREND SOURCE:
{trend_source or "Not provided"}

RESEARCH CONTEXT ABOUT THE TREND:
{research_context or "No external context found."}

LANGUAGE:
English, natural American social media tone.
WRITE 100% IN ENGLISH. Do not mix in any other language.

{ambiguity_warning_en}

OBJECTIVE:
- The video should perform well on YouTube Shorts, TikTok, and Instagram Reels.
- The voice should feel human, native, fast, and creator-driven.
- The script should sound like real spoken internet content, not generic AI copy.
- The text should create immediate curiosity and hold attention until the end.
- The final CTA should feel natural and encourage comments, shares, saves, or follows.

DO NOT SHOW THIS ANALYSIS.
RETURN ONLY THE FINAL VOICEOVER.

MANDATORY RULES:
- Write only the words the narrator will speak.
- Use a natural American social media voice.
- Do not use labels.
- Do not use markdown.
- Do not use emojis.
- Do not include visual directions.
- The script must be between {self.target_min_words} and {self.target_max_words} words.
- Before answering, internally count the words.
- Do not return fewer than {self.target_min_words} words.
- The first sentence must be under 12 words.
- The first sentence must stop the scroll.
- Use short spoken sentences.
- Create curiosity in the first 2 seconds.
- Explain quickly why this topic may matter.
- Include tension, contrast, an open question, or an unexpected detail.
- End with a natural CTA to comment, share, save, or follow.
- Do not use generic CTAs.
- Do not invent specific facts.
- If context is missing, use safe language.
- Do not claim something happened unless it is clear from the topic, source, or research.
- Avoid openings like "In today's video", "Let's talk about", or "This is going viral".
- If the research shows a sports, music, politics, entertainment, gaming, or culture context, use that angle naturally.
- Avoid overly formal language.
- Avoid repeating the same idea with different words.
- The rhythm should feel conversational, not read aloud from a script.
- The middle of the script should create a twist or deeper layer.
- The ending should deliver emotional or practical payoff.

RETURN ONLY THE FINAL SPOKEN VOICEOVER SCRIPT.
"""

    def _build_ai_repair_prompt(
        self,
        topic: str,
        language: str,
        trend_source: str,
        previous_script: str,
        issue: str,
        research_context: str = "",
    ) -> str:
        is_pt = self._is_portuguese(language)
        clean_topic = self._clean_topic_for_prompt(topic)
        is_ambiguous = self._looks_like_bare_name_or_ambiguous_topic(clean_topic)

        ambiguity_rule_pt = """
REGRA CRÍTICA:
O tema parece ambíguo ou com pouco contexto.
Use o CONTEXTO PESQUISADO para entender a trend.
Remova qualquer profissão, cargo, nacionalidade, evento, idade, acusação ou fato específico que não esteja explicitamente no tema, fonte ou contexto pesquisado.
Não adivinhe quem é a pessoa.
""" if is_ambiguous else """
REGRA CRÍTICA:
Use o CONTEXTO PESQUISADO.
Remova qualquer fato específico que não esteja explicitamente no tema, fonte ou contexto pesquisado.
"""

        ambiguity_rule_en = """
CRITICAL RULE:
The topic looks ambiguous or lacks context.
Use the RESEARCH CONTEXT to understand the trend.
Remove any profession, role, nationality, event, age, accusation, or specific fact that is not explicitly present in the topic, source, or research context.
Do not guess who the person is.
""" if is_ambiguous else """
CRITICAL RULE:
Use the RESEARCH CONTEXT.
Remove any specific fact that is not explicitly present in the topic, source, or research context.
"""

        if is_pt:
            return f"""
Reescreva e expanda a narração abaixo para corrigir este problema:

PROBLEMA:
{issue}

TEMA/TREND:
{clean_topic}

FONTE DA TREND:
{trend_source or "Não informada"}

CONTEXTO PESQUISADO:
{research_context or "Nenhum contexto externo encontrado."}

NARRAÇÃO ANTERIOR:
{previous_script}

{ambiguity_rule_pt}

REGRAS:
- Português do Brasil.
- A narração será lida por uma VOZ BRASILEIRA automática. Não deixe NENHUMA palavra em inglês na grafia original. Traduza ou adapte para português; quando um nome próprio estrangeiro for necessário, escreva-o APORTUGUESADO foneticamente (ex.: "KATSEYE" → "Két-sái"; "WILD HEARTS" → "Uáild Ráts"; "YouTube" → "Iutúbi").
- Retorne apenas a narração final.
- Não use markdown.
- Não use rótulos.
- Não use emojis.
- O roteiro final deve ter entre {self.target_min_words} e {self.target_max_words} palavras.
- Antes de responder, conte internamente as palavras.
- Não entregue menos de {self.target_min_words} palavras.
- Primeira frase com menos de 12 palavras.
- Frases curtas e naturais.
- Mais retenção nos primeiros 2 segundos.
- Mais curiosidade no meio.
- CTA final natural.
- Não invente fatos.
- Use somente fatos apoiados pelo tema, fonte ou contexto pesquisado.
- Se faltar contexto, use linguagem segura.
- Se o roteiro estiver curto, expanda usando:
  curiosidade do público,
  motivo provável da busca conforme pesquisa,
  reação da comunidade,
  dúvida aberta,
  importância do tema,
  sem criar fatos novos.
- Se o roteiro estiver longo, compacte sem perder tensão.
- Mantenha a fala fluida e natural.

RETORNE SOMENTE A NARRAÇÃO FINAL.
"""

        return f"""
Rewrite and expand the voiceover below to fix this issue:

ISSUE:
{issue}

TOPIC/TREND:
{clean_topic}

TREND SOURCE:
{trend_source or "Not provided"}

RESEARCH CONTEXT:
{research_context or "No external context found."}

PREVIOUS VOICEOVER:
{previous_script}

{ambiguity_rule_en}

RULES:
- English, natural American social media tone.
- Return only the final voiceover.
- Do not use markdown.
- Do not use labels.
- Do not use emojis.
- The final script must be between {self.target_min_words} and {self.target_max_words} words.
- Before answering, internally count the words.
- Do not return fewer than {self.target_min_words} words.
- First sentence under 12 words.
- Short natural spoken sentences.
- Stronger retention in the first 2 seconds.
- More curiosity in the middle.
- Natural final CTA.
- Do not invent facts.
- Use only facts supported by the topic, source, or research context.
- If context is missing, use safe language.
- If the script is short, expand using:
  audience curiosity,
  likely search intent based on research,
  community reaction,
  open uncertainty,
  why the topic matters,
  without creating new facts.
- If the script is too long, tighten it without losing the hook or payoff.
- Keep the voice conversational.

RETURN ONLY THE FINAL SPOKEN VOICEOVER.
"""

    def _build_ai_safety_review_prompt(
        self,
        topic: str,
        language: str,
        trend_source: str,
        script_text: str,
        research_context: str = "",
    ) -> str:
        is_pt = self._is_portuguese(language)
        clean_topic = self._clean_topic_for_prompt(topic)
        is_ambiguous = self._looks_like_bare_name_or_ambiguous_topic(clean_topic)

        if is_pt:
            ambiguity_note = """
O tema parece ambíguo ou curto. Seja conservador.
Não afirme quem é a pessoa nem o que aconteceu se isso não estiver explícito no tema, fonte ou contexto pesquisado.
""" if is_ambiguous else """
Se houver qualquer afirmação não confirmada pelo tema, fonte ou contexto pesquisado, reescreva de forma segura.
"""

            return f"""
Revise a narração abaixo para remover qualquer possível alucinação, invenção ou afirmação factual sem suporte.

TEMA/TREND:
{clean_topic}

FONTE DA TREND:
{trend_source or "Não informada"}

CONTEXTO PESQUISADO:
{research_context or "Nenhum contexto externo encontrado."}

NARRAÇÃO:
{script_text}

{ambiguity_note}

TAREFA:
- Se houver profissão, cargo, nacionalidade, idade, evento, acusação ou fato específico não confirmado, remova.
- Preserve retenção, curiosidade e CTA.
- Não encurte demais.
- O texto revisado deve ter pelo menos 55 palavras.
- Se você remover uma afirmação, substitua por linguagem segura baseada no contexto pesquisado.
- Use linguagem segura se faltar contexto.
- Retorne apenas a narração final revisada.
- Não explique o que mudou.
- Não use markdown.
- Não use rótulos.
"""

        ambiguity_note = """
The topic looks ambiguous or short. Be conservative.
Do not claim who the person is or what happened unless it is explicit in the topic, source, or research context.
""" if is_ambiguous else """
If there is any claim not supported by the topic, source, or research context, rewrite it safely.
"""

        return f"""
Review the voiceover below to remove any possible hallucination, invented detail, or unsupported factual claim.

TOPIC/TREND:
{clean_topic}

TREND SOURCE:
{trend_source or "Not provided"}

RESEARCH CONTEXT:
{research_context or "No external context found."}

VOICEOVER:
{script_text}

{ambiguity_note}

TASK:
- If there is a profession, role, nationality, age, event, accusation, or specific fact that is not confirmed, remove it.
- Preserve retention, curiosity, and the CTA.
- Do not make it too short.
- The revised text must have at least 55 words.
- If you remove a claim, replace it with safe language based on the research context.
- Use safe language if context is missing.
- Return only the final revised voiceover.
- Do not explain what changed.
- Do not use markdown.
- Do not use labels.
"""

    def _try_gemini(self, prompt: str, temperature: float = 0.70):
        """Tenta gerar texto com o Google Gemini usando o SDK novo google-genai."""
        if not self.gemini_client:
            return None

        try:
            print(f"🌟 [CONTENT ENGINE] Gerando com Google Gemini ({self.gemini_model_name})...")

            system_instruction = (
                "You are an elite short-form video strategist and retention-focused voiceover writer "
                "for TikTok, YouTube Shorts, Instagram Reels, and Facebook Reels. "
                "You write only clean spoken narration for text-to-speech, with no labels, markdown, "
                "scene directions, or emojis. You never invent facts beyond the topic, source, and "
                "research context. You always satisfy the requested minimum word count."
            )

            response = self.gemini_client.models.generate_content(
                model=self.gemini_model_name,
                contents=f"{system_instruction}\n\n{prompt}",
                config={
                    "temperature": temperature,
                    "top_p": 0.90,
                    "max_output_tokens": 900,
                },
            )

            if response and getattr(response, "text", None):
                print("✅ [CONTENT ENGINE] Gemini gerou o texto com sucesso.")
                return response.text

        except Exception as e:
            print(f"⚠️ [CONTENT ENGINE] Gemini falhou: {e}")

        return None

    def _generate_with_ai(self, prompt: str, active_model: str, temperature: float = 0.70):
        if not self.client:
            raise RuntimeError("GROQ_API_KEY não configurada.")

        # Removido o modelo 3.1-70b-versatile descontinuado
        fallback_models = [
            active_model,
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "qwen/qwen3.6-27b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
        ]

        models_to_try = []
        seen = set()

        for model_name in fallback_models:
            if model_name and model_name not in seen:
                seen.add(model_name)
                models_to_try.append(model_name)

        last_error = None

        for model_name in models_to_try:
            try:
                if model_name != active_model:
                    print(f"⚠️ [CONTENT ENGINE] Tentando modelo alternativo por limite/erro: {model_name}")

                # Os modelos "gpt-oss" do Groq sao de raciocinio: eles gastam
                # tokens "pensando" antes de escrever. Com um teto baixo de
                # tokens, todo o orcamento vai para o raciocinio e o texto final
                # volta VAZIO. Por isso: teto de tokens mais alto e esforco de
                # raciocinio baixo para sobrar espaco para o roteiro.
                request_kwargs = dict(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an elite short-form video strategist and retention-focused voiceover writer. "
                                "You write scripts for TikTok, YouTube Shorts, Instagram Reels, and Facebook Reels. "
                                "You optimize for watch time, replay, comments, shares, saves, and follows. "
                                "You write only clean spoken narration for text-to-speech. "
                                "You never include labels, markdown, scene directions, emojis, or unsupported facts. "
                                "You must use the provided research context when it exists. "
                                "You must not invent facts beyond the topic, trend source, and research context. "
                                "When context is missing, you write safely and never guess identities, professions, roles, events, or facts. "
                                "When asked for a minimum word count, you must satisfy it. "
                                "You should prefer strong hooks, quick tension, natural flow, and a satisfying payoff."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=self.ai_max_tokens,
                    temperature=temperature,
                    top_p=0.90,
                    presence_penalty=0.25,
                    frequency_penalty=0.30,
                )

                if "gpt-oss" in model_name:
                    request_kwargs["reasoning_effort"] = "low"

                response = self.client.chat.completions.create(**request_kwargs)

                return response.choices[0].message.content

            except Exception as e:
                last_error = e
                error_text = str(e).lower()

                if "429" in error_text or "rate_limit" in error_text or "rate limit" in error_text:
                    print(f"⚠️ [CONTENT ENGINE] Limite atingido no modelo {model_name}.")

                    # Antes de cair no modelo fraco, tenta o Gemini
                    gemini_result = self._try_gemini(prompt, temperature)
                    if gemini_result:
                        return gemini_result

                    print(f"⚠️ [CONTENT ENGINE] Gemini indisponível. Tentando próximo modelo Groq...")
                    continue

                # Erro diferente de limite: também tenta o Gemini antes de desistir
                gemini_result = self._try_gemini(prompt, temperature)
                if gemini_result:
                    return gemini_result

                raise

        raise last_error

    # ====================================================================
    # FUNÇÃO PRINCIPAL
    # ====================================================================

    def generate_script(
        self,
        topic: str,
        language: str = "en",
        trend_source: str = "",
        research_context: str = "",
    ):
        if not self.client:
            raise RuntimeError("GROQ_API_KEY não configurada. Roteiro não gerado porque o sistema deve usar IA.")

        try:
            active_model = self._get_best_model()

            print(
                f"🧠 [CONTENT ENGINE] Escrevendo roteiro com IA de alta retenção ({language}) usando: {active_model} | Tema: '{topic}'..."
            )

            if not research_context:
                research_context = self._collect_research_context(
                    topic=topic,
                    language=language,
                    trend_source=trend_source,
                )
            else:
                self.last_research_context = research_context

            prompt = self._build_ai_script_prompt(
                topic=topic,
                language=language,
                trend_source=trend_source,
                research_context=research_context,
            )

            script_text = self._generate_with_ai(
                prompt=prompt,
                active_model=active_model,
                temperature=0.74,
            )

            script_text = self._clean_script(script_text)
            script_text = self._trim_to_word_limit(script_text, max_words=self.absolute_max_words)
            word_count = self._word_count(script_text)

            best_script = script_text
            best_count = word_count

            if word_count < self.target_min_words:
                print(f"⚠️ [CONTENT ENGINE] Roteiro IA curto ({word_count} palavras). Solicitando correção à IA...")

                repair_prompt = self._build_ai_repair_prompt(
                    topic=topic,
                    language=language,
                    trend_source=trend_source,
                    previous_script=script_text,
                    issue="The script is too short. Expand it while keeping it safe, punchy, and retention-focused. Use the research context.",
                    research_context=research_context,
                )

                repaired = self._generate_with_ai(
                    prompt=repair_prompt,
                    active_model=active_model,
                    temperature=0.72,
                )

                repaired = self._clean_script(repaired)
                repaired = self._trim_to_word_limit(repaired, max_words=self.absolute_max_words)
                repaired_count = self._word_count(repaired)

                if repaired_count > best_count:
                    best_script = repaired
                    best_count = repaired_count

                script_text = repaired
                word_count = repaired_count

            if word_count < max(40, self.target_min_words - 10):
                print(f"⚠️ [CONTENT ENGINE] Roteiro IA ainda curto ({word_count} palavras). Pedindo expansão final à IA...")

                expansion_prompt = self._build_ai_repair_prompt(
                    topic=topic,
                    language=language,
                    trend_source=trend_source,
                    previous_script=best_script,
                    issue=f"The script is still too short. Expand to at least {self.target_min_words} words using only supported research context, curiosity, audience reaction, and a natural CTA.",
                    research_context=research_context,
                )

                expanded = self._generate_with_ai(
                    prompt=expansion_prompt,
                    active_model=active_model,
                    temperature=0.70,
                )

                expanded = self._clean_script(expanded)
                expanded = self._trim_to_word_limit(expanded, max_words=self.absolute_max_words)
                expanded_count = self._word_count(expanded)

                if expanded_count > best_count:
                    best_script = expanded
                    best_count = expanded_count

                script_text = expanded
                word_count = expanded_count

            if word_count > self.target_max_words:
                print(f"⚠️ [CONTENT ENGINE] Roteiro IA longo ({word_count} palavras). Solicitando versão mais curta à IA...")

                shorten_prompt = self._build_ai_repair_prompt(
                    topic=topic,
                    language=language,
                    trend_source=trend_source,
                    previous_script=script_text,
                    issue="The script is too long for a short-form vertical video. Rewrite it shorter while keeping the strongest hook, researched context, curiosity, and CTA.",
                    research_context=research_context,
                )

                shortened = self._generate_with_ai(
                    prompt=shorten_prompt,
                    active_model=active_model,
                    temperature=0.66,
                )

                shortened = self._clean_script(shortened)
                shortened = self._trim_to_word_limit(shortened, max_words=self.absolute_max_words)
                shortened_count = self._word_count(shortened)

                script_text = shortened
                word_count = shortened_count

                if shortened_count > best_count:
                    best_script = shortened
                    best_count = shortened_count

            print("🛡️ [CONTENT ENGINE] Revisando roteiro com IA para reduzir alucinação factual...")

            safety_prompt = self._build_ai_safety_review_prompt(
                topic=topic,
                language=language,
                trend_source=trend_source,
                script_text=script_text,
                research_context=research_context,
            )

            reviewed = self._generate_with_ai(
                prompt=safety_prompt,
                active_model=active_model,
                temperature=0.45,
            )

            reviewed = self._clean_script(reviewed)
            reviewed = self._trim_to_word_limit(reviewed, max_words=self.absolute_max_words)
            reviewed_count = self._word_count(reviewed)

            if reviewed_count < 35 and best_count >= 35:
                print(
                    f"⚠️ [CONTENT ENGINE] Revisão de segurança encurtou demais ({reviewed_count} palavras). "
                    f"Mantendo melhor versão IA anterior com {best_count} palavras."
                )
                script_text = best_script
                word_count = best_count
            else:
                script_text = reviewed
                word_count = reviewed_count

            if word_count < self.target_min_words:
                print(f"⚠️ [CONTENT ENGINE] Roteiro final curto ({word_count} palavras). Solicitando expansão segura final à IA...")

                final_expand_prompt = self._build_ai_repair_prompt(
                    topic=topic,
                    language=language,
                    trend_source=trend_source,
                    previous_script=script_text,
                    issue=f"The final script is too short. Expand safely to at least {self.target_min_words} words. Do not add unsupported facts. Use only the research context.",
                    research_context=research_context,
                )

                final_expanded = self._generate_with_ai(
                    prompt=final_expand_prompt,
                    active_model=active_model,
                    temperature=0.64,
                )

                final_expanded = self._clean_script(final_expanded)
                final_expanded = self._trim_to_word_limit(final_expanded, max_words=self.absolute_max_words)
                final_expanded_count = self._word_count(final_expanded)

                if final_expanded_count > word_count:
                    script_text = final_expanded
                    word_count = final_expanded_count

            if word_count < 25:
                raise RuntimeError(
                    f"Roteiro gerado pela IA ficou inutilizável ({word_count} palavras). Produção interrompida porque a IA não entregou texto suficiente."
                )

            if word_count < self.target_min_words:
                print(
                    f"⚠️ [CONTENT ENGINE] Roteiro aprovado, mas curto ({word_count} palavras). "
                    f"Prosseguindo porque o texto é 100% IA e evita derrubar o ciclo."
                )

            print(f"✅ [CONTENT ENGINE] Roteiro IA de retenção pronto com {word_count} palavras.")
            return script_text

        except Exception as e:
            print(f"❌ [CONTENT ENGINE] Erro ao gerar roteiro com IA: {e}")
            raise

    def expand_script(
        self,
        topic: str,
        language: str = "en",
        trend_source: str = "",
        previous_script: str = "",
        research_context: str = "",
    ):
        prompt = self._build_ai_repair_prompt(
            topic=topic,
            language=language,
            trend_source=trend_source,
            previous_script=previous_script,
            issue=f"Expand this script safely so it reaches at least {self.target_min_words} words.",
            research_context=research_context or self.last_research_context,
        )

        active_model = self._get_best_model()
        expanded = self._generate_with_ai(prompt=prompt, active_model=active_model, temperature=0.68)
        expanded = self._clean_script(expanded)
        expanded = self._trim_to_word_limit(expanded, max_words=self.absolute_max_words)
        return expanded

    def generate_hook(
        self,
        topic: str,
        language: str = "en",
        script: str = "",
        trend_source: str = "",
        research_context: str = "",
    ) -> str:
        """Gera um hook curto e chocante (máx ~8 palavras) para os primeiros segundos do vídeo."""
        is_pt = self._is_portuguese(language)
        clean_topic = self._clean_topic_for_prompt(topic)

        if is_pt:
            prompt = f"""
Crie UM único gancho de abertura (hook) para um vídeo curto vertical viral.

TEMA: {clean_topic}
CONTEXTO: {research_context or self.last_research_context or "Não informado"}
ROTEIRO: {script[:300]}

REGRAS:
- Máximo de 8 palavras.
- Deve parar o scroll imediatamente.
- Pode ser pergunta provocativa, choque ou curiosidade.
- Sem emojis, sem hashtags, sem aspas, sem rótulos.
- Não invente fatos que não estejam no contexto.
- Português do Brasil.

Retorne APENAS o texto do gancho, nada mais.
"""
        else:
            prompt = f"""
Create ONE single opening hook for a viral vertical short video.

TOPIC: {clean_topic}
CONTEXT: {research_context or self.last_research_context or "Not provided"}
SCRIPT: {script[:300]}

RULES:
- Maximum 8 words.
- Must stop the scroll immediately.
- Can be a provocative question, shock, or curiosity gap.
- No emojis, no hashtags, no quotes, no labels.
- Do not invent facts not in the context.
- English.

Return ONLY the hook text, nothing else.
"""

        try:
            active_model = self._get_best_model()
            hook = self._generate_with_ai(prompt=prompt, active_model=active_model, temperature=0.85)
            hook = self._clean_script(hook or "").strip().strip('"').strip("'")
            # Segura no máximo 1 linha
            hook = hook.split("\n")[0].strip()
            words = hook.split()
            if len(words) > 10:
                hook = " ".join(words[:10])
            if hook:
                print(f"✅ [CONTENT ENGINE] Hook gerado: '{hook}'")
                return hook
        except Exception as e:
            print(f"⚠️ [CONTENT ENGINE] Falha ao gerar hook por IA: {e}")

        return ""
