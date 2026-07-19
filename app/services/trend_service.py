import os
import re
import json
import random
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

import yt_dlp
from dotenv import load_dotenv

load_dotenv()


class TrendService:
    # Assuntos que rendem MUITO bem em video curto (entretenimento / viral /
    # curiosidade / esporte / games / tecnologia). Recebem bonus no score.
    _APPEAL_BOOST_TERMS = [
        # entretenimento / cultura pop
        "filme", "serie", "série", "novela", "netflix", "trailer", "estreia",
        "show", "musica", "música", "cantor", "cantora", "banda", "album", "álbum",
        "famoso", "celebridade", "influencer", "youtuber", "bbb", "reality",
        "movie", "series", "trailer", "song", "singer", "celebrity", "actor",
        # esporte
        "futebol", "gol", "jogo", "copa", "campeonato", "final", "olimpiadas",
        "ufc", "nba", "nfl", "formula 1", "f1", "soccer", "football", "goal",
        "match", "championship", "olympics",
        # curiosidade / viral / games / tech
        "curiosidade", "viral", "desafio", "recorde", "incrivel", "incrível",
        "tecnologia", "iphone", "android", "inteligencia artificial", "ia",
        "game", "gameplay", "minecraft", "roblox", "free fire", "gta",
        "challenge", "record", "amazing", "technology", "gaming",
    ]
    # Assuntos "noticia dura" que envelhecem rapido e tem concorrencia gigante.
    # Recebem penalidade no score (nao sao proibidos, so caem no ranking).
    _APPEAL_PENALTY_TERMS = [
        "politica", "política", "presidente", "eleicao", "eleição", "senado",
        "camara", "câmara", "ministro", "governo", "imposto", "dolar", "dólar",
        "morre", "morte", "faleceu", "acidente", "tragedia", "tragédia",
        "assassinato", "tiroteio", "guerra", "ataque", "crise", "golpe",
        "politics", "president", "election", "senate", "government", "war",
        "shooting", "dies", "death", "crash", "attack",
    ]

    def __init__(self):
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY")

    def _appeal_adjustment(self, topic: str, geo: str) -> float:
        """
        Ajusta o score do assunto pensando em video curto:
        - da bonus para entretenimento/esporte/curiosidade/games/tech (rende views);
        - da penalidade para noticia dura/politica/tragedia (envelhece e concorre demais).
        """
        t = self._normalize(topic)
        adjustment = 0.0

        if any(term in t for term in self._APPEAL_BOOST_TERMS):
            adjustment += 6.0
        if any(term in t for term in self._APPEAL_PENALTY_TERMS):
            adjustment -= 8.0

        return adjustment

    def _normalize(self, text: str) -> str:
        if not text:
            return ""

        text = text.lower().strip()
        text = re.sub(r"[^a-zA-Z0-9À-ÿ\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _is_good_topic(self, topic: str) -> bool:
        """
        Evita tópicos vagos, ruins para vídeo ou com alta chance de dar asset errado.
        Exemplo ruim: 'apostador', 'erdogan', 'marcio'.
        Exemplo melhor: 'donovan mitchell trade', 'regina casé novela', 'coco gauff wimbledon'.
        """
        if not topic:
            return False

        topic_norm = self._normalize(topic)
        words = topic_norm.split()

        # Evita termos muito vagos de uma palavra só.
        if len(words) < 2:
            return False

        banned_terms = [
            "official video",
            "full movie",
            "lyrics",
            "karaoke",
            "compilation",
            "live stream",
            "ao vivo",
            "filme completo",
            "música",
            "musica",
            "clipe oficial",
            "video oficial",
            "playlist",
            "podcast completo",
            "episódio completo",
            "episodio completo",
        ]

        if any(term in topic_norm for term in banned_terms):
            return False

        # Evita títulos gigantes demais, geralmente são vídeos e não tópicos.
        if len(words) > 12:
            return False

        return True

    def _make_hashtags(self, topic: str, geo: str):
        """
        Gera hashtags iniciais. Depois o MetadataService vai refinar por plataforma.
        """
        base = self._normalize(topic)
        words = [w for w in base.split() if len(w) >= 3]

        hashtags = []

        joined = "".join([w.capitalize() for w in words[:4]])
        if joined:
            hashtags.append(f"#{joined}")

        for w in words[:5]:
            hashtags.append(f"#{w}")

        if geo == "BR":
            hashtags.extend([
                "#Brasil",
                "#Noticias",
                "#ViralBrasil",
                "#ShortsBrasil",
                "#ReelsBrasil"
            ])
        else:
            hashtags.extend([
                "#Trending",
                "#BreakingNews",
                "#Viral",
                "#Shorts",
                "#Reels"
            ])

        clean = []
        seen = set()

        for h in hashtags:
            h = h.replace(" ", "")
            h_key = h.lower()

            if h_key not in seen:
                seen.add(h_key)
                clean.append(h)

        return clean[:10]

    def _add_trend(self, trends: list, topic: str, score: float, source: str, geo: str):
        """
        Adiciona tendência com validação e deduplicação.
        """
        if not self._is_good_topic(topic):
            return

        # Prioriza assuntos que rendem em video curto (A).
        score = float(score) + self._appeal_adjustment(topic, geo)
        score = max(0.0, min(score, 100.0))

        topic_clean = topic.strip()
        topic_norm = self._normalize(topic_clean)

        for existing in trends:
            existing_norm = self._normalize(existing["topic"])

            if existing_norm == topic_norm:
                existing["score"] = max(existing["score"], float(score))

                if source not in existing["source"]:
                    existing["source"] = f"{existing['source']} + {source}"

                return

        trends.append({
            "topic": topic_clean,
            "score": float(score),
            "source": source,
            "geo": geo,
            "hashtags": self._make_hashtags(topic_clean, geo),
        })

    def _fetch_google_trends(self, geo: str):
        """
        Busca tendências no Google Trends RSS por país.
        """
        trends = []

        try:
            print(f"📈 [TRENDS] Google Trends RSS | Região: {geo}")

            url = f"https://trends.google.com/trending/rss?geo={geo}"

            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                }
            )

            response = urllib.request.urlopen(req, timeout=15)
            root = ET.fromstring(response.read())

            for item in root.findall(".//item")[:20]:
                title_el = item.find("title")

                if title_el is not None and title_el.text:
                    self._add_trend(
                        trends=trends,
                        topic=title_el.text,
                        score=random.uniform(82.0, 94.0),
                        source="Google Trends",
                        geo=geo
                    )

        except Exception as e:
            print(f"⚠️ [TRENDS] Falha Google Trends ({geo}): {e}")

        return trends

    def _fetch_youtube_most_popular(self, geo: str):
        """
        Busca vídeos populares oficiais via YouTube Data API.
        Para funcionar, coloque YOUTUBE_API_KEY no .env.
        """
        trends = []

        if not self.youtube_api_key:
            print("⚠️ [TRENDS] YOUTUBE_API_KEY ausente. Pulando YouTube Data API oficial.")
            return trends

        try:
            print(f"▶️ [TRENDS] YouTube Most Popular oficial | Região: {geo}")

            params = {
                "part": "snippet,statistics,contentDetails",
                "chart": "mostPopular",
                "regionCode": geo,
                "maxResults": "25",
                "key": self.youtube_api_key,
            }

            url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(params)

            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                }
            )

            response = urllib.request.urlopen(req, timeout=15)
            payload = json.loads(response.read().decode("utf-8"))

            for item in payload.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})

                title = snippet.get("title", "")
                channel_title = snippet.get("channelTitle", "")

                try:
                    views = int(stats.get("viewCount", 0))
                except Exception:
                    views = 0

                try:
                    likes = int(stats.get("likeCount", 0))
                except Exception:
                    likes = 0

                score = 88.0

                if views > 250000:
                    score += 2.0

                if views > 500000:
                    score += 3.0

                if views > 1000000:
                    score += 4.0

                if likes > 25000:
                    score += 1.0

                if likes > 50000:
                    score += 2.0

                # Limpeza básica de título para transformar vídeo em tópico.
                topic = title.strip()
                topic = re.sub(r"\|.*$", "", topic).strip()
                topic = re.sub(r"\(.*?official.*?\)", "", topic, flags=re.I).strip()
                topic = re.sub(r"\[.*?official.*?\]", "", topic, flags=re.I).strip()
                topic = re.sub(r"#\w+", "", topic).strip()
                topic = re.sub(r"\s+", " ", topic).strip()

                self._add_trend(
                    trends=trends,
                    topic=topic,
                    score=min(score, 99.0),
                    source=f"YouTube MostPopular / {channel_title}",
                    geo=geo
                )

        except Exception as e:
            print(f"⚠️ [TRENDS] Falha YouTube API ({geo}): {e}")

        return trends

    def _fetch_youtube_categories(self, geo: str):
        """
        (C) Busca os vídeos mais populares POR CATEGORIA de entretenimento,
        para trazer assuntos que rendem em vídeo curto em vez de só notícia:
        24=Entretenimento, 17=Esportes, 20=Games, 28=Ciência & Tecnologia,
        1=Filmes & Animação. Precisa da YOUTUBE_API_KEY.
        """
        trends = []

        if not self.youtube_api_key:
            return trends

        categories = {
            "24": "Entretenimento",
            "17": "Esportes",
            "20": "Games",
            "28": "Ciência & Tecnologia",
            "1": "Filmes & Animação",
        }

        for cat_id, cat_name in categories.items():
            try:
                params = {
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "regionCode": geo,
                    "videoCategoryId": cat_id,
                    "maxResults": "8",
                    "key": self.youtube_api_key,
                }

                url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(params)

                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    }
                )

                response = urllib.request.urlopen(req, timeout=15)
                payload = json.loads(response.read().decode("utf-8"))

                for item in payload.get("items", []):
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})

                    title = snippet.get("title", "")

                    try:
                        views = int(stats.get("viewCount", 0))
                    except Exception:
                        views = 0

                    score = 86.0
                    if views > 250000:
                        score += 2.0
                    if views > 1000000:
                        score += 4.0

                    topic = title.strip()
                    topic = re.sub(r"\|.*$", "", topic).strip()
                    topic = re.sub(r"#\w+", "", topic).strip()
                    topic = re.sub(r"\s+", " ", topic).strip()

                    self._add_trend(
                        trends=trends,
                        topic=topic,
                        score=min(score, 99.0),
                        source=f"YouTube {cat_name}",
                        geo=geo
                    )

            except Exception as e:
                print(f"⚠️ [TRENDS] Falha categoria {cat_name} ({geo}): {e}")

        return trends

    def _fetch_youtube_short_signals(self, geo: str):
        """
        Busca sinais de Shorts como fonte complementar.
        Usa VÁRIAS buscas diferentes (rotativas) para trazer assuntos variados
        de vídeo curto, em vez de sempre o mesmo tipo de conteúdo (B).
        """
        trends = []

        if geo == "BR":
            query_pool = [
                "shorts virais brasil hoje",
                "curiosidades incriveis shorts brasil",
                "shorts engracados brasil viral",
                "desafios virais shorts brasil",
                "esporte shorts brasil hoje",
                "tecnologia e games shorts brasil",
                "famosos e novela shorts brasil",
                "fatos surpreendentes shorts brasil",
            ]
        else:
            query_pool = [
                "viral shorts today usa",
                "amazing facts shorts",
                "funny viral shorts usa",
                "trending challenges shorts",
                "sports shorts today usa",
                "tech and gaming shorts usa",
                "celebrity shorts today",
                "satisfying oddly shorts viral",
            ]

        # Escolhe 3 buscas aleatórias por ciclo -> variedade sem estourar tempo.
        selected = random.sample(query_pool, k=min(3, len(query_pool)))

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "default_search": "ytsearch10",
            "noplaylist": True,
        }

        for query in selected:
            try:
                print(f"🎬 [TRENDS] Sinais de Shorts | Região: {geo} | Busca: {query}")

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(query, download=False)

                entries = info.get("entries", []) if info else []

                for entry in entries[:8]:
                    if not entry:
                        continue

                    title = entry.get("title", "")

                    if not title:
                        continue

                    topic = title.strip()
                    topic = re.sub(r"#\w+", "", topic).strip()
                    topic = re.sub(r"\|.*$", "", topic).strip()
                    topic = re.sub(r"\s+", " ", topic).strip()

                    self._add_trend(
                        trends=trends,
                        topic=topic,
                        score=random.uniform(76.0, 88.0),
                        source="YouTube Shorts Search Signal",
                        geo=geo
                    )

            except Exception as e:
                print(f"⚠️ [TRENDS] Falha Shorts signal ({geo}) na busca '{query}': {e}")

        return trends

    def fetch_trends(self, geo: str = "US"):
        """
        Retorna lista ranqueada de tendências qualificadas.
        O loop_worker.py vai selecionar 3 a 5 tópicos dessa lista.
        """
        print("")
        print(f"📊 [DATA ANALYTICS] Varredura de tendências reais | Região: {geo}")

        all_trends = []

        google_trends = self._fetch_google_trends(geo)
        for t in google_trends:
            self._add_trend(
                trends=all_trends,
                topic=t["topic"],
                score=t["score"],
                source=t["source"],
                geo=geo
            )

        youtube_popular = self._fetch_youtube_most_popular(geo)
        for t in youtube_popular:
            self._add_trend(
                trends=all_trends,
                topic=t["topic"],
                score=t["score"],
                source=t["source"],
                geo=geo
            )

        youtube_categories = self._fetch_youtube_categories(geo)
        for t in youtube_categories:
            self._add_trend(
                trends=all_trends,
                topic=t["topic"],
                score=t["score"],
                source=t["source"],
                geo=geo
            )

        shorts_signals = self._fetch_youtube_short_signals(geo)
        for t in shorts_signals:
            self._add_trend(
                trends=all_trends,
                topic=t["topic"],
                score=t["score"],
                source=t["source"],
                geo=geo
            )

        if not all_trends:
            fallback = (
                "Major viral story everyone is talking about today"
                if geo == "US"
                else "Assunto viral que o Brasil inteiro está comentando hoje"
            )

            self._add_trend(
                trends=all_trends,
                topic=fallback,
                score=75.0,
                source="Fallback Editorial",
                geo=geo
            )

        all_trends = sorted(
            all_trends,
            key=lambda x: x["score"],
            reverse=True
        )

        print(f"🎯 [DECISÃO ESTRATÉGICA] {len(all_trends)} tendências qualificadas.")

        for t in all_trends[:8]:
            print(f"   - {t['topic']} | Score: {t['score']:.1f} | Fonte: {t['source']}")

        return all_trends
