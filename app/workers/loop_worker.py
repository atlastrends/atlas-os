import os
import time
import random
import re
import json

from app.core.database import SessionLocal
from app.models.content import Content
from app.services.trend_service import TrendService
from app.services.content_service import ContentService
from app.services.media_service import MediaService
from app.services.metadata_service import MetadataService
from app.services.metadata_storage_service import MetadataStorageService


# =====================================================================
# 🌍 MASTER CONFIG: ATLAS OS MULTI-CANAL
# =====================================================================
# Estratégia atual:
#
# - 1 vídeo por canal a cada ciclo.
# - Ciclo padrão a cada 15 minutos.
# - Resultado esperado: cerca de 4 vídeos por hora para cada canal.
#
# Se o ciclo demorar mais que 15 minutos por causa da renderização,
# o próximo ciclo começa imediatamente.
#
# Para aumentar volume:
# - Reduza ATLAS_CYCLE_INTERVAL_SECONDS.
# - Ou aumente ATLAS_VIDEOS_PER_CHANNEL_PER_CYCLE.
#
# Recomendação atual:
# - Manter 1 vídeo por canal por ciclo.
# - Usar intervalo de 15 minutos.
# =====================================================================

CHANNELS_CONFIG = [
    {
        "channel_name": "EUA - Top Trending",
        "country_code": "US",
        "language": "English (US), natural American social media tone",
        "language_code": "en",
        "tts_voice": "en-US-ChristopherNeural",

        # 1 vídeo por ciclo.
        # Com ciclo de 15 minutos, gera cerca de 4 vídeos/hora/canal.
        "videos_min": 1,
        "videos_max": 1,
    },
    {
        "channel_name": "BRASIL - Top Trending",
        "country_code": "BR",
        "language": "Portuguese (Brazil), natural Brazilian tone, clear and engaging",
        "language_code": "pt",
        "tts_voice": "pt-BR-AntonioNeural",

        # 1 vídeo por ciclo.
        # Com ciclo de 15 minutos, gera cerca de 4 vídeos/hora/canal.
        "videos_min": 1,
        "videos_max": 1,
    },

    # Exemplo futuro:
    # {
    #     "channel_name": "ESPANHA - Top Trending",
    #     "country_code": "ES",
    #     "language": "Spanish (Spain), natural social media tone",
    #     "language_code": "es",
    #     "tts_voice": "es-ES-AlvaroNeural",
    #     "videos_min": 1,
    #     "videos_max": 1,
    # },
]


class Engine:
    def __init__(self):
        self.trend_service = TrendService()
        self.content_service = ContentService()
        self.media_service = MediaService()
        self.metadata_service = MetadataService()
        self.metadata_storage_service = MetadataStorageService()

        # ============================================================
        # CONFIGURAÇÃO DE PRODUÇÃO CONTÍNUA
        # ============================================================
        # 900 segundos = 15 minutos.
        # 1 vídeo por canal a cada 15 minutos = cerca de 4 vídeos/hora/canal.
        self.cycle_interval_seconds = int(
            os.getenv("ATLAS_CYCLE_INTERVAL_SECONDS", "900")
        )

        # Se definido no .env, sobrescreve videos_min/videos_max dos canais.
        # Recomendado manter 1.
        self.videos_per_channel_per_cycle_override = int(
            os.getenv("ATLAS_VIDEOS_PER_CHANNEL_PER_CYCLE", "1")
        )

        # Evita repetir o mesmo assunto no mesmo canal por 12 horas.
        self.topic_cooldown_seconds = int(
            os.getenv("ATLAS_TOPIC_COOLDOWN_SECONDS", "43200")
        )

        # Pausa pequena entre vídeos para aliviar APIs/CPU.
        self.pause_between_videos_seconds = int(
            os.getenv("ATLAS_PAUSE_BETWEEN_VIDEOS_SECONDS", "10")
        )

        # Score mínimo para aceitar tendência.
        self.min_trend_score = float(
            os.getenv("ATLAS_MIN_TREND_SCORE", "80")
        )

        # Arquivo persistente de memória de assuntos usados.
        self.memory_dir = "output_metadata"
        os.makedirs(self.memory_dir, exist_ok=True)

        self.used_topics_memory_path = os.path.join(
            self.memory_dir,
            "used_topics_memory.json"
        )

        self.used_topics_memory = self._load_used_topics_memory()
        self._cleanup_used_topics_memory()

    # =====================================================================
    # MEMÓRIA DE ASSUNTOS USADOS
    # =====================================================================

    def _load_used_topics_memory(self) -> dict:
        """
        Carrega memória persistente de assuntos usados recentemente.
        Isso evita repetir o mesmo tema mesmo depois de reiniciar o container.
        """
        if not os.path.exists(self.used_topics_memory_path):
            return {}

        try:
            with open(self.used_topics_memory_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                return data

            return {}

        except Exception as e:
            print(f"⚠️ [ATLAS ENGINE] Não foi possível carregar memória de assuntos: {e}")
            return {}

    def _save_used_topics_memory(self):
        """
        Salva a memória de assuntos usados recentemente.
        """
        try:
            os.makedirs(self.memory_dir, exist_ok=True)

            with open(self.used_topics_memory_path, "w", encoding="utf-8") as f:
                json.dump(
                    self.used_topics_memory,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

        except Exception as e:
            print(f"⚠️ [ATLAS ENGINE] Não foi possível salvar memória de assuntos: {e}")

    def _normalize_topic_key(self, country_code: str, topic: str) -> str:
        """
        Cria chave única por país/canal + tópico.
        Assim US e BR podem usar o mesmo tema em idiomas diferentes,
        mas o mesmo canal não repete o assunto dentro do cooldown.
        """
        clean_country = str(country_code or "GLOBAL").upper().strip()

        clean_topic = str(topic or "").lower().strip()
        clean_topic = re.sub(r"[^a-z0-9À-ÿ\s-]", " ", clean_topic)
        clean_topic = re.sub(r"\s+", "-", clean_topic)
        clean_topic = clean_topic.strip("-")

        return f"{clean_country}:{clean_topic}"

    def _cleanup_used_topics_memory(self):
        """
        Remove da memória assuntos cujo cooldown já expirou.
        """
        now = time.time()
        expired_keys = []

        for key, used_at in self.used_topics_memory.items():
            try:
                used_at_float = float(used_at)
            except Exception:
                expired_keys.append(key)
                continue

            if now - used_at_float > self.topic_cooldown_seconds:
                expired_keys.append(key)

        for key in expired_keys:
            self.used_topics_memory.pop(key, None)

        if expired_keys:
            self._save_used_topics_memory()

    def _was_topic_used_recently(self, country_code: str, topic: str) -> bool:
        """
        Verifica se o tópico já foi usado recentemente no mesmo país/canal.
        """
        self._cleanup_used_topics_memory()

        topic_key = self._normalize_topic_key(country_code, topic)
        used_at = self.used_topics_memory.get(topic_key)

        if not used_at:
            return False

        try:
            used_at_float = float(used_at)
        except Exception:
            return False

        return time.time() - used_at_float <= self.topic_cooldown_seconds

    def _mark_topic_as_used(self, country_code: str, topic: str):
        """
        Marca tópico como usado depois que o vídeo foi realmente criado.
        """
        topic_key = self._normalize_topic_key(country_code, topic)
        self.used_topics_memory[topic_key] = time.time()
        self._save_used_topics_memory()

    # =====================================================================
    # VALIDAÇÃO DE ROTEIRO E TENDÊNCIAS
    # =====================================================================

    def _is_valid_script(self, script: str) -> bool:
        """
        Evita mandar para vídeo um roteiro com erro, simulação ou vazio.
        """
        if not script:
            return False

        # ATENÇÃO: usar apenas frases específicas de FALHA real.
        # Palavras soltas como "erro"/"error" reprovavam roteiros válidos
        # (ex.: tema "Biggest Mistake" gera texto com "erro"/"error";
        # "terror" contém "error", "ferro"/"enterro" contêm "erro").
        bad_markers = [
            "[simulação",
            "[simulacao",
            "erro ao gerar roteiro",
            "error generating script",
            "traceback (most recent call",
            "não foi possível gerar",
            "nao foi possivel gerar",
        ]

        script_lower = script.lower()

        for marker in bad_markers:
            if marker in script_lower:
                return False

        # Evita roteiros curtos demais.
        if len(script.strip()) < 120:
            return False

        return True

    # Estúdios/distribuidoras cujo conteúdo (trailers oficiais, cenas de
    # filmes) costuma disparar Content ID / copyright strike no YouTube.
    _COPYRIGHT_STUDIO_KEYWORDS = (
        "marvel", "disney", "pixar", "warner", "sony pictures", "universal",
        "paramount", "netflix", "hbo", "dc studios", "lucasfilm",
        "20th century", "a24", "dreamworks", "illumination",
        "columbia pictures", "mgm", "lionsgate", "sony picture",
    )

    _COPYRIGHT_TRAILER_HINTS = (
        "trailer oficial", "official trailer", "trailer dublado",
        "trailer legendado", "teaser trailer", "final trailer",
        "trailer final",
    )

    _COPYRIGHT_MOVIE_SOURCE_HINTS = ("filme", "movie", "animação", "animacao", "animation")

    def _is_copyright_risky_topic(self, topic: str, source: str = "") -> bool:
        """
        Detecta trends com alto risco de bloqueio por direitos autorais
        (ex.: trailers oficiais de filmes/estúdios), ANTES de gastar tempo
        criando o vídeo. Se der positivo, o motor pula esse assunto e usa
        outro no lugar (ver _select_best_unique_trends).
        """
        if not topic:
            return False

        topic_norm = topic.lower()
        source_norm = (source or "").lower()

        # 1) Nome de estúdio/distribuidora aparece no topico ou na fonte.
        for kw in self._COPYRIGHT_STUDIO_KEYWORDS:
            if kw in topic_norm or kw in source_norm:
                return True

        # 2) "trailer" + termo de trailer oficial/dublado/teaser/final.
        if "trailer" in topic_norm:
            for hint in self._COPYRIGHT_TRAILER_HINTS:
                if hint in topic_norm:
                    return True

        # 3) Fonte indica categoria de filmes/animação E o tópico fala de trailer.
        if "trailer" in topic_norm and any(h in source_norm for h in self._COPYRIGHT_MOVIE_SOURCE_HINTS):
            return True

        return False

    def _select_best_unique_trends(
        self,
        trends: list,
        target_videos: int,
        country_code: str
    ):
        """
        Seleciona as melhores trends sem repetição.
        Também remove tópicos com score baixo e pula assuntos usados recentemente.
        """
        valid_trends = []
        seen_topics = set()

        if not trends:
            return valid_trends

        for t in trends:
            topic = str(t.get("topic", "")).strip()

            if not topic:
                continue

            topic_key = topic.lower()

            if topic_key in seen_topics:
                continue

            score = float(t.get("score", 0))

            # Mantém apenas assuntos fortes.
            if score < self.min_trend_score:
                continue

            # Evita repetir assunto dentro do cooldown.
            if self._was_topic_used_recently(country_code, topic):
                print(f"⏭️ [ATLAS ENGINE] Assunto já usado recentemente em {country_code}: {topic}")
                continue

            # Evita assuntos com alto risco de direitos autorais (trailers
            # oficiais de estúdio) — pula e deixa outro assunto preencher a vaga.
            if self._is_copyright_risky_topic(topic, str(t.get("source", ""))):
                print(f"🚫 [ATLAS ENGINE] Assunto com risco de direitos autorais, pulando: {topic}")
                continue

            seen_topics.add(topic_key)
            valid_trends.append(t)

            if len(valid_trends) >= target_videos:
                break

        # Fallback de idioma/produção:
        # Se NENHUMA trend passou no corte de score para este canal
        # (ex.: as trends do Brasil vieram com score abaixo do mínimo),
        # ainda assim garante pelo menos 1 vídeo por canal usando a melhor
        # trend disponível que não tenha sido usada recentemente.
        # Isso evita que o canal BR fique sem produzir e o resultado saia
        # só em inglês.
        if not valid_trends:
            fallback_pool = []
            for t in trends:
                topic = str(t.get("topic", "")).strip()
                if not topic:
                    continue
                if self._was_topic_used_recently(country_code, topic):
                    continue
                if self._is_copyright_risky_topic(topic, str(t.get("source", ""))):
                    continue
                fallback_pool.append(t)

            fallback_pool.sort(
                key=lambda x: float(x.get("score", 0)),
                reverse=True,
            )

            for t in fallback_pool[:max(1, target_videos)]:
                print(
                    f"🩹 [ATLAS ENGINE] Nenhuma trend acima do corte para "
                    f"{country_code}; usando a melhor trend disponível: "
                    f"{t.get('topic')}"
                )
                valid_trends.append(t)

        return valid_trends

    def _get_target_videos_for_channel(self, channel: dict) -> int:
        """
        Define quantos vídeos serão gerados por canal neste ciclo.
        Por padrão usa ATLAS_VIDEOS_PER_CHANNEL_PER_CYCLE=1.
        """
        if self.videos_per_channel_per_cycle_override > 0:
            return self.videos_per_channel_per_cycle_override

        return random.randint(
            int(channel.get("videos_min", 1)),
            int(channel.get("videos_max", 1))
        )

    # =====================================================================
    # LOG DE METADATA
    # =====================================================================

    def _print_metadata_preview(self, metadata: dict):
        """
        Mostra no log o pacote de metadata que será usado no futuro upload.
        """
        if not metadata:
            return

        print("")
        print("🏷️ [METADATA PACKAGE]")
        print(f"   Título YouTube: {metadata.get('youtube_title')}")
        print(f"   Tags YouTube: {', '.join(metadata.get('youtube_tags', []))}")
        print(f"   Hashtags: {' '.join(metadata.get('hashtags', []))}")
        print(f"   TikTok Caption: {metadata.get('tiktok_caption')}")
        print(f"   Instagram Caption: {metadata.get('instagram_caption')}")
        print(f"   Facebook Caption: {metadata.get('facebook_caption')}")
        print("")

    # =====================================================================
    # CICLO PRINCIPAL
    # =====================================================================

    def run_cycle(self, progress_callback=None):
        db = SessionLocal()
        videos_produced = 0

        # ------------------------------------------------------------
        # Planejamento para calcular a PORCENTAGEM de progresso.
        # Calculamos quantos videos serao feitos por canal ANTES do loop
        # (para nao chamar random duas vezes) e somamos o total planejado.
        # ------------------------------------------------------------
        planned_per_channel = [
            self._get_target_videos_for_channel(channel)
            for channel in CHANNELS_CONFIG
        ]
        total_planned = max(1, sum(planned_per_channel))
        done_videos = 0

        def _report(stage_fraction: float, title: str, stage: str):
            """Envia a porcentagem + titulo do video atual para o painel."""
            if not progress_callback:
                return
            try:
                pct = ((done_videos + stage_fraction) / total_planned) * 100.0
                pct = int(max(0, min(99, pct)))
                progress_callback(pct, title, stage)
            except Exception:
                pass

        try:
            print("")
            print("=======================================================")
            print("🚀 [ATLAS OS] Iniciando Produção Global Multi-Canal...")
            print("=======================================================")
            print("")

            self._cleanup_used_topics_memory()

            for channel_idx, channel in enumerate(CHANNELS_CONFIG):
                target_videos = planned_per_channel[channel_idx]

                print("")
                print("-------------------------------------------------------")
                print(f"🌐 [DIRETRIZ] Canal: {channel['channel_name']}")
                print(f"🌎 [REGIÃO] {channel['country_code']}")
                print(f"🗣️ [IDIOMA] {channel['language']}")
                print(f"🎙️ [VOZ] {channel['tts_voice']}")
                print(f"🎯 [META] {target_videos} vídeo(s) neste ciclo")
                print("-------------------------------------------------------")
                print("")

                # 1. Busca tendências reais por país.
                _report(0.02, channel["channel_name"], "Buscando as tendências do momento…")
                trends = self.trend_service.fetch_trends(
                    geo=channel["country_code"]
                )

                selected_trends = self._select_best_unique_trends(
                    trends=trends,
                    target_videos=target_videos,
                    country_code=channel["country_code"]
                )

                if not selected_trends:
                    print(
                        f"⚠️ [ATLAS ENGINE] Nenhuma trend nova qualificada encontrada para "
                        f"{channel['country_code']} neste ciclo."
                    )
                    continue

                for index, trend in enumerate(selected_trends, start=1):
                    topic = trend["topic"]
                    score = trend.get("score", 0)
                    source = trend.get("source", "Unknown")
                    hashtags = trend.get("hashtags", [])

                    print("")
                    print(f"⚙️ [PRODUÇÃO] Vídeo {index}/{len(selected_trends)} para {channel['country_code']}")
                    print(f"🎯 [ASSUNTO] {topic}")
                    print(f"📊 [SCORE] {score}")
                    print(f"📡 [FONTE] {source}")
                    print(f"🏷️ [HASHTAGS BASE] {' '.join(hashtags)}")
                    print("")

                    # 2. Gera roteiro no idioma correto.
                    _report(0.05, topic, "Escrevendo o roteiro com IA…")
                    script = self.content_service.generate_script(
                        topic=topic,
                        language=channel["language"]
                    )

                    if not self._is_valid_script(script):
                        print(f"⚠️ [CONTENT ENGINE] Roteiro inválido para '{topic}'. Pulando vídeo.")
                        continue
                    
                    # --- NOVO: 2.1 Gera o Hook por IA ---
                    _report(0.18, topic, "Criando o gancho (hook) do vídeo…")
                    hook_text = self.content_service.generate_hook(
                        topic=topic,
                        language=channel["language"],
                        script=script,
                        trend_source=source
                    )

                    
                    # 3. Gera pacote de metadata para upload futuro.
                    _report(0.28, topic, "Preparando título, legenda e hashtags…")
                    metadata = self.metadata_service.build_metadata(
                        topic=topic,
                        script=script,
                        geo=channel["country_code"],
                        base_hashtags=hashtags,
                        trend_source=source

                    )

                    self._print_metadata_preview(metadata)

                    # 4. Salva no banco.
                    new_content = Content(
                        topic=topic,
                        language=channel["language_code"],
                        script=script,
                        performance_score=score
                    )

                    db.add(new_content)
                    db.commit()
                    db.refresh(new_content)

                    print(f"💾 [DATABASE] Conteúdo salvo com ID {new_content.id}")

                    # 5. Gera vídeo com voz e idioma corretos.
                    _report(0.40, topic, "Gerando narração e renderizando o vídeo… (parte mais longa)")

                    # Conecta a % REAL de renderização (10%, 20%…) na barra
                    # do painel. A renderização ocupa de 40% a 100% da fatia
                    # deste vídeo, ficando suave em vez de pular direto.
                    _clear_render_cb = None
                    try:
                        from app.services.media_service import (
                            set_render_progress_callback,
                            clear_render_progress_callback,
                        )

                        def _on_render(render_percent, _topic=topic):
                            frac = 0.40 + (max(0, min(100, render_percent)) / 100.0) * 0.55
                            _report(frac, _topic, f"Renderizando o vídeo… {int(render_percent)}%")

                        set_render_progress_callback(_on_render)
                        _clear_render_cb = clear_render_progress_callback
                    except Exception:
                        _clear_render_cb = None

                    try:
                        video_path = self.media_service.create_tiktok_video(
                            topic=topic,
                            script=script,
                            hook_text=hook_text,
                            content_id=new_content.id,
                            voice_name=channel["tts_voice"],
                            language=channel["language_code"],
                            hashtags=metadata.get("hashtags", hashtags),
                            source=source
                        )
                    finally:
                        if _clear_render_cb:
                            _clear_render_cb()

                    # 6. Salva metadata JSON junto ao vídeo.
                    if video_path and os.path.exists(video_path):
                        self.metadata_storage_service.save_metadata(
                            content_id=new_content.id,
                            topic=topic,
                            language=channel["language_code"],
                            country_code=channel["country_code"],
                            performance_score=score,
                            source=source,
                            video_path=video_path,
                            metadata=metadata
                        )

                        # Marca o assunto como usado somente depois do vídeo existir.
                        self._mark_topic_as_used(
                            country_code=channel["country_code"],
                            topic=topic
                        )

                        videos_produced += 1
                        done_videos += 1
                        _report(0.0, topic, "Vídeo finalizado ✅")

                        print(
                            f"🧠 [ATLAS ENGINE] Assunto marcado como usado em "
                            f"{channel['country_code']}: {topic}"
                        )

                    else:
                        done_videos += 1
                        print(f"⚠️ [METADATA STORAGE] Vídeo não encontrado, metadata não salva: {video_path}")
                        print(f"⚠️ [ATLAS ENGINE] Assunto não será marcado como usado porque o vídeo falhou: {topic}")

                    print(f"✅ [ATLAS ENGINE] Vídeo {index} para {channel['country_code']} finalizado.")
                    print("")

                    # Pausa pequena para não bater APIs/CPU sem intervalo.
                    if self.pause_between_videos_seconds > 0:
                        time.sleep(self.pause_between_videos_seconds)

            print("")
            print("🎉 [ATLAS ENGINE] Ciclo Global Finalizado.")
            print("")

            if progress_callback:
                try:
                    progress_callback(100, "", "Ciclo concluído 🎉")
                except Exception:
                    pass

        except Exception as e:
            print(f"❌ [ATLAS ENGINE] Erro crítico no ciclo: {e}")
            # Propaga o erro para quem chamou (ex.: o job do painel) poder
            # mostrar a falha de verdade, em vez de dizer "sucesso" sem video.
            raise

        finally:
            db.close()

        return videos_produced

    # =====================================================================
    # LOOP CONTÍNUO
    # =====================================================================

    def start(self):
        print("🤖 [ATLAS ENGINE] Ligando os reatores da Fábrica...")

        while True:
            cycle_started_at = time.time()

            self.run_cycle()

            elapsed_seconds = time.time() - cycle_started_at
            sleep_seconds = max(0, self.cycle_interval_seconds - elapsed_seconds)

            elapsed_minutes = elapsed_seconds / 60

            if sleep_seconds > 0:
                sleep_minutes = sleep_seconds / 60

                print(
                    f"😴 [ATLAS ENGINE] Ciclo concluído em {elapsed_minutes:.1f} min. "
                    f"Descansando {sleep_minutes:.1f} min até a próxima rodada."
                )

                time.sleep(sleep_seconds)

            else:
                print(
                    f"⚡ [ATLAS ENGINE] Ciclo demorou {elapsed_minutes:.1f} min, "
                    f"maior ou igual ao intervalo configurado. "
                    f"Iniciando próxima rodada imediatamente."
                )


if __name__ == "__main__":
    Engine().start()
