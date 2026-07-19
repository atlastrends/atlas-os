import asyncio
import glob
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

try:
    from proglog import ProgressBarLogger
except ImportError:
    ProgressBarLogger = object

# ============================================================
# LOGGER CUSTOMIZADO PARA VISUALIZAÇÃO NO DOCKER
# ============================================================

# Callback global (opcional) para reportar a % REAL de renderização
# ao painel. O worker define isso antes de renderizar e limpa depois.
_RENDER_PROGRESS_CB = None


def set_render_progress_callback(cb):
    """Define a função que recebe a % real de renderização (0-100)."""
    global _RENDER_PROGRESS_CB
    _RENDER_PROGRESS_CB = cb


def clear_render_progress_callback():
    """Remove o callback de progresso de renderização."""
    global _RENDER_PROGRESS_CB
    _RENDER_PROGRESS_CB = None


class DockerLogger(ProgressBarLogger):
    """
    O Docker engole as barras de progresso padrão (\r).
    Este logger força a impressão de linha a cada 10% para 
    evitar a sensação de que o contêiner 'travou'.
    """
    def __init__(self):
        super().__init__()
        self.last_percent = -1
        self.last_cb_percent = -1

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar == 't':
            total = self.bars[bar].get('total', 0)
            if total > 0:
                percent = int((value / total) * 100)
                if percent % 10 == 0 and percent != self.last_percent:
                    print(f"⏳ [MEDIA ENGINE] Progresso de Renderização: {percent}% concluído...")
                    self.last_percent = percent

                # Reporta a % REAL para o painel (a cada 1% para uma barra suave).
                if percent != self.last_cb_percent and _RENDER_PROGRESS_CB:
                    self.last_cb_percent = percent
                    try:
                        _RENDER_PROGRESS_CB(percent)
                    except Exception:
                        pass

# ============================================================
# TRAVA DE SEGURANÇA: IMAGEMAGICK
# ============================================================
def _neutralize_imagemagick_policy():
    """
    Procura o arquivo policy.xml do ImageMagick em TODOS os caminhos possíveis
    e reescreve com permissões TOTAIS. Roda toda vez que o serviço inicia.
    """
    if platform.system() == "Windows":
        return

    # Define o binário correto (convert)
    for bin_path in ["/usr/bin/convert", "/usr/local/bin/convert"]:
        if os.path.exists(bin_path):
            os.environ["IMAGEMAGICK_BINARY"] = bin_path
            break

    # Conteúdo 100% permissivo
    permissive_policy = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<policymap>\n'
        '  <policy domain="resource" name="memory" value="2GiB"/>\n'
        '  <policy domain="coder" rights="read | write" pattern="*"/>\n'
        '  <policy domain="path" rights="read | write" pattern="@*"/>\n'
        '</policymap>\n'
    )

    # Todos os caminhos onde o Debian/Alpine podem esconder a política
    possible_paths = [
        "/etc/ImageMagick-6/policy.xml",
        "/etc/ImageMagick-7/policy.xml",
        "/etc/ImageMagick/policy.xml",
        "/usr/local/etc/ImageMagick-6/policy.xml",
        "/usr/local/etc/ImageMagick-7/policy.xml",
    ]

    fixed_any = False
    for path in possible_paths:
        folder = os.path.dirname(path)
        try:
            if os.path.isdir(folder):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(permissive_policy)
                fixed_any = True
                print(f"🔓 [MEDIA ENGINE] Política do ImageMagick liberada em: {path}")
        except Exception as e:
            print(f"⚠️ [MEDIA ENGINE] Não consegui liberar {path}: {e}")

    if not fixed_any:
        print("⚠️ [MEDIA ENGINE] Nenhum arquivo de política do ImageMagick encontrado para liberar.")


_neutralize_imagemagick_policy()
# ============================================================
    

import edge_tts
import yt_dlp

# ffmpeg embutido (via imageio-ffmpeg) para que o yt-dlp consiga juntar
# video+audio dos trailers HD mesmo sem ffmpeg instalado no sistema Windows.
try:
    import imageio_ffmpeg

    _BUNDLED_FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:  # noqa: BLE001
    _BUNDLED_FFMPEG_EXE = None


def _get_ytdlp_cookies_from_browser():
    """
    Retorna a especificacao de cookies do navegador para o yt-dlp, permitindo
    baixar videos que o YouTube protege com "confirme que voce nao e um robo".

    Controlado pela variavel de ambiente ATLAS_YTDLP_COOKIES_BROWSER, que aceita
    o nome do navegador logado no YouTube: "edge", "chrome", "firefox", "brave"
    ou "opera". Se nao estiver definida, retorna None (comportamento antigo).
    """
    browser = (os.getenv("ATLAS_YTDLP_COOKIES_BROWSER") or "").strip().lower()
    valid = {"edge", "chrome", "firefox", "brave", "opera", "chromium", "vivaldi"}
    if browser in valid:
        return (browser,)
    return None


def _default_cookies_file():
    """
    Caminho padrao do arquivo de cookies do YouTube. Basta salvar o cookies.txt
    exportado do navegador nesse local que o sistema usa automaticamente (sem
    precisar configurar nada). Mesmo local usado pelo renderizador de afiliados.
    """
    root = (os.getenv("ATLAS_ROOT") or "").strip()
    if not root:
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except Exception:
            root = os.getcwd()
    return os.path.join(root, "storage", "youtube_cookies.txt")


def _apply_ytdlp_cookies(opts: dict) -> dict:
    """Injeta os cookies do navegador nas opcoes do yt-dlp, se configurados."""
    # 1) Arquivo cookies.txt (mais confiavel: funciona com o navegador aberto).
    #    Usa ATLAS_YTDLP_COOKIES_FILE se definido; senao o caminho padrao
    #    storage/youtube_cookies.txt (basta salvar o arquivo la).
    cookie_file = (os.getenv("ATLAS_YTDLP_COOKIES_FILE") or "").strip().strip('"')
    if not cookie_file:
        cookie_file = _default_cookies_file()
    if cookie_file and os.path.isfile(cookie_file):
        opts["cookiefile"] = cookie_file
        return opts

    # 2) Cookies direto do navegador (exige o navegador FECHADO no Windows).
    spec = _get_ytdlp_cookies_from_browser()
    if spec:
        opts["cookiesfrombrowser"] = spec
    return opts


def _apply_ytdlp_bot_bypass(opts: dict) -> dict:
    """
    Faz o yt-dlp se passar por 'clientes alternativos' do YouTube (app de TV,
    celular iOS/Android, Safari) em vez do site normal. Esses clientes quase
    sempre BAIXAM o video SEM pedir 'confirme que voce nao e um robo' e SEM
    precisar de login/cookies.

    100% automatico e portatil: funciona em qualquer computador, sem nenhuma
    configuracao manual. Personalizavel via ATLAS_YTDLP_PLAYER_CLIENTS
    (lista separada por virgula), mas o padrao ja funciona.
    """
    raw = (os.getenv("ATLAS_YTDLP_PLAYER_CLIENTS") or "").strip()
    if raw:
        clients = [c.strip() for c in raw.split(",") if c.strip()]
    else:
        # Ordem escolhida por robustez contra o bot-check do YouTube.
        clients = ["tv", "ios", "android", "web_safari", "mweb"]

    extractor_args = opts.setdefault("extractor_args", {})
    yt_args = extractor_args.setdefault("youtube", {})
    yt_args["player_client"] = clients
    return opts

# O imageio-ffmpeg NAO traz ffprobe. Se existir um ffprobe ao lado do ffmpeg
# (ou no PATH), usamos; caso contrario, a medicao cai para o moviepy.
def _detect_ffprobe():
    import shutil as _shutil

    if _BUNDLED_FFMPEG_EXE:
        _dir = os.path.dirname(_BUNDLED_FFMPEG_EXE)
        for _name in ("ffprobe.exe", "ffprobe"):
            _candidate = os.path.join(_dir, _name)
            if os.path.exists(_candidate):
                return _candidate
    return _shutil.which("ffprobe")


try:
    _BUNDLED_FFPROBE_EXE = _detect_ffprobe()
except Exception:  # noqa: BLE001
    _BUNDLED_FFPROBE_EXE = None

# --- Compatibilidade Pillow 10+ com MoviePy ---
import PIL.Image

if not hasattr(PIL.Image, "ANTIALIAS"):
    try:
        PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS
    except AttributeError:
        PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
# ----------------------------------------------

try:
    import moviepy.editor as mp
except ImportError as e:
    raise ImportError("moviepy.editor não pôde ser importado. Verifique a instalação do MoviePy.") from e

load_dotenv()


class MediaService:
    def __init__(self):
        self.output_dir = os.getenv("ATLAS_OUTPUT_DIR", "output_videos")
        os.makedirs(self.output_dir, exist_ok=True)

        self.video_width = self._env_int("ATLAS_VIDEO_WIDTH", 1080)
        self.video_height = self._env_int("ATLAS_VIDEO_HEIGHT", 1920)
        self.video_fps = self._env_int("ATLAS_VIDEO_FPS", 30)

        self.master_bitrate = os.getenv("ATLAS_MASTER_BITRATE", "9000k")
        self.audio_bitrate = os.getenv("ATLAS_AUDIO_BITRATE", "192k")

        self.min_hd_short_side = self._env_int("ATLAS_MIN_HD_SHORT_SIDE", 720)
        self.min_hd_long_side = self._env_int("ATLAS_MIN_HD_LONG_SIDE", 1280)

        # Limite de bitrate para aceitar o trailer como fundo. Mantido baixo de
        # proposito: a resolucao e a duracao ja sao validadas, e um trailer
        # 1080p real (mesmo ~0.9 Mbps) e muito melhor que um fundo preto.
        self.min_720p_bitrate_mbps = self._env_float("ATLAS_MIN_720P_BITRATE_MBPS", 0.35)
        self.min_1080p_bitrate_mbps = self._env_float("ATLAS_MIN_1080P_BITRATE_MBPS", 0.45)

        self.asset_candidate_limit = self._env_int("ATLAS_ASSET_CANDIDATE_LIMIT", 12)
        self.search_result_limit = self._env_int("ATLAS_YOUTUBE_SEARCH_LIMIT", 18)
        self.max_source_video_seconds = self._env_int("ATLAS_MAX_SOURCE_VIDEO_SECONDS", 900)
        # Duracao MINIMA do video-fonte (b-roll). O compositor repete o clipe em
        # loop para preencher a narracao, entao clipes curtos (ex.: animacoes de
        # trend com ~40-58s) sao aceitos. Antes era 60s fixo, o que descartava a
        # animacao real do assunto e sobrava so spam longo.
        self.min_source_video_seconds = self._env_float("ATLAS_MIN_SOURCE_VIDEO_SECONDS", 20.0)

        self.min_asset_match_score = self._env_float("ATLAS_MIN_ASSET_MATCH_SCORE", 0.34)
        # Piso minimo para o "fallback": abaixo disso preferimos um fundo
        # editorial limpo a usar um video sem relacao com o assunto.
        self.asset_match_floor = self._env_float("ATLAS_ASSET_MATCH_FLOOR", 0.25)
        self.visual_overlay_opacity = self._env_float("ATLAS_VISUAL_OVERLAY_OPACITY", 0.03)

        # Legendas e safe zones
        self.subtitle_shield_enabled = self._env_bool("ATLAS_SUBTITLE_SHIELD", True)
        self.subtitle_enabled = self._env_bool("ATLAS_SUBTITLES_ENABLED", True)

        self.bottom_safe_zone_height = self._env_int("ATLAS_BOTTOM_SAFE_ZONE_HEIGHT", 420)
        self.bottom_safe_zone_opacity = self._env_float("ATLAS_BOTTOM_SAFE_ZONE_OPACITY", 0.18)

        self.subtitle_shield_height = self._env_int("ATLAS_SUBTITLE_SHIELD_HEIGHT", 320)
        self.subtitle_shield_opacity = self._env_float("ATLAS_SUBTITLE_SHIELD_OPACITY", 0.42)
        self.subtitle_shield_bottom_gap = self._env_int("ATLAS_SUBTITLE_SHIELD_BOTTOM_GAP", 180)

        self.subtitle_font_size = self._env_int("ATLAS_SUBTITLE_FONT_SIZE", 56)
        self.subtitle_font_color = os.getenv("ATLAS_SUBTITLE_FONT_COLOR", "white")
        self.subtitle_stroke_color = os.getenv("ATLAS_SUBTITLE_STROKE_COLOR", "black")
        self.subtitle_stroke_width = self._env_int("ATLAS_SUBTITLE_STROKE_WIDTH", 3)
        self.subtitle_bg_opacity = self._env_float("ATLAS_SUBTITLE_BG_OPACITY", 0.0)

        # Hook
        self.enable_hook_text = self._env_bool("ATLAS_ENABLE_HOOK_TEXT", False)
        self.hook_font_size = self._env_int("ATLAS_HOOK_FONT_SIZE", 58)
        self.hook_box_opacity = self._env_float("ATLAS_HOOK_BOX_OPACITY", 0.62)
        self.hook_y = self._env_int("ATLAS_HOOK_Y", 230)

        # Movimento/posição do foreground
        self.foreground_vertical_offset = self._env_int("ATLAS_FOREGROUND_VERTICAL_OFFSET", 100)

        # Duração obrigatória para publicação
        self.min_video_duration_seconds = self._env_float("ATLAS_MIN_VIDEO_DURATION_SECONDS", 60.0)
        self.max_video_duration_seconds = self._env_float("ATLAS_MAX_VIDEO_DURATION_SECONDS", 120.0)

        self.default_voice = os.getenv("ATLAS_DEFAULT_VOICE", "en-US-ChristopherNeural")
        self.visual_risk_reduction = self._env_bool("ATLAS_VISUAL_RISK_REDUCTION", True)

        self._nvenc_available: Optional[bool] = None

    # ============================================================
    # ENV HELPERS
    # ============================================================

    def _env_int(self, name: str, default: int) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return int(value)
        except Exception:
            return default

    def _env_float(self, name: str, default: float) -> float:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return float(value)
        except Exception:
            return default

    def _env_bool(self, name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "sim"}

    # ============================================================
    # TEXT HELPERS E FONTES
    # ============================================================

    def _get_system_font(self) -> str:
        """Busca uma fonte válida no sistema para o TextClip"""
        candidate_fonts = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", # Debian
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",          # Alpine
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        ]
        
        for font_path in candidate_fonts:
            if os.path.exists(font_path):
                return font_path
                
        if platform.system() == "Windows":
            return "Arial-Bold"
            
        print("⚠️ [MEDIA ENGINE] Fonte TTF não encontrada no container. Isso pode causar falha no TextClip.")
        return "Arial-Bold"

    # ------------------------------------------------------------
    # Renderização de texto com Pillow (sem depender do ImageMagick).
    # Funciona no Windows e permite controlar o tamanho do texto,
    # com ajuste automático para nunca estourar a largura do vídeo.
    # ------------------------------------------------------------

    def _get_pil_font_path(self) -> Optional[str]:
        candidates = [
            os.getenv("ATLAS_FONT_PATH", ""),
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None

    def _load_pil_font(self, size: int):
        from PIL import ImageFont

        if not hasattr(self, "_pil_font_cache"):
            self._pil_font_cache = {}

        cache_key = int(size)
        if cache_key in self._pil_font_cache:
            return self._pil_font_cache[cache_key]

        font_path = self._get_pil_font_path()
        try:
            font = ImageFont.truetype(font_path, cache_key) if font_path else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()

        self._pil_font_cache[cache_key] = font
        return font

    def _color_to_rgba(self, color: Any, default=(255, 255, 255)) -> tuple:
        from PIL import ImageColor

        try:
            rgb = ImageColor.getrgb(str(color))
            if len(rgb) == 3:
                return (rgb[0], rgb[1], rgb[2], 255)
            return rgb
        except Exception:
            return (default[0], default[1], default[2], 255)

    def _wrap_text_lines(self, draw, text: str, font, max_width: int, stroke_width: int) -> List[str]:
        words = text.split()
        lines: List[str] = []
        current = ""

        for word in words:
            trial = f"{current} {word}".strip()
            bbox = draw.textbbox((0, 0), trial, font=font, stroke_width=stroke_width)
            width = bbox[2] - bbox[0]
            if width <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = word

        if current:
            lines.append(current)

        return lines

    def _render_text_image(
        self,
        text: str,
        font_size: int,
        max_width: int,
        color=(255, 255, 255, 255),
        stroke_width: int = 0,
        stroke_color=(0, 0, 0, 255),
        align: str = "center",
        max_lines: int = 2,
        min_font_size: int = 30,
        line_spacing: float = 1.12,
        padding: int = 18,
    ):
        """
        Renderiza `text` em uma imagem RGBA transparente, quebrando em linhas
        para caber em `max_width`. Se o texto não couber em `max_lines`, reduz
        a fonte automaticamente (até `min_font_size`) para não ficar grande demais.
        """
        from PIL import Image, ImageDraw

        measure_img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        measure = ImageDraw.Draw(measure_img)

        size = max(min_font_size, int(font_size))
        font = self._load_pil_font(size)
        lines = self._wrap_text_lines(measure, text, font, max_width, stroke_width)

        while len(lines) > max_lines and size > min_font_size:
            size = max(min_font_size, size - 4)
            font = self._load_pil_font(size)
            lines = self._wrap_text_lines(measure, text, font, max_width, stroke_width)

        if not lines:
            lines = [text]

        ascent, descent = font.getmetrics()
        line_height = ascent + descent
        step = int(line_height * line_spacing)

        max_line_width = 0
        for line in lines:
            bbox = measure.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
            max_line_width = max(max_line_width, bbox[2] - bbox[0])

        img_width = min(max_width, max_line_width) + padding * 2
        img_height = step * len(lines) + padding * 2

        img = Image.new("RGBA", (img_width, img_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        y = padding
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
            line_width = bbox[2] - bbox[0]
            if align == "center":
                x = (img_width - line_width) // 2
            else:
                x = padding
            draw.text(
                (x - bbox[0], y),
                line,
                font=font,
                fill=color,
                stroke_width=stroke_width,
                stroke_fill=stroke_color,
            )
            y += step

        return img

    def _clean_text(self, text: Any) -> str:
        if not text:
            return ""
        text = str(text).strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def _normalize_text(self, text: Any) -> str:
        if not text:
            return ""
        text = str(text).lower()
        text = re.sub(r"[^\w\sÀ-ÿ]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _build_search_query(self, topic: str) -> str:
        if not topic:
            return ""

        text = self._clean_text(topic)
        text = re.sub(r"[^\w\sÀ-ÿ]", " ", text)

        noise_terms = [
            "live", "ao vivo", "aovivo", "en vivo",
            "don t blink", "dont blink", "don blink",
            "secret mod activated", "activated",
            "breaking news", "shorts", "viral",
        ]

        lowered = f" {text.lower()} "
        for term in noise_terms:
            lowered = re.sub(rf"\b{re.escape(term)}\b", " ", lowered)

        lowered = re.sub(r"\s+", " ", lowered).strip()

        words = lowered.split()
        if len(words) > 8:
            words = words[:8]

        cleaned = " ".join(words).strip()
        return cleaned or self._clean_text(topic)

    def _extract_first_sentence(self, script: str) -> str:
        script = self._clean_text(script)
        if not script:
            return ""

        script = re.sub(
            r"(?im)^\s*(hook|body|intro|title|caption|voiceover|call to action|cta|breaking news|script|roteiro|narração)\s*:\s*",
            "",
            script,
        )

        parts = re.split(r"(?<=[.!?])\s+", script)
        if parts:
            return parts[0].strip()

        return script[:120].strip()

    def _make_short_hook(self, topic: str, script: str) -> str:
        first = self._extract_first_sentence(script)
        if first and len(first) <= 58:
            return first

        topic_clean = self._clean_text(topic)
        if topic_clean:
            if len(topic_clean) <= 42:
                return f"Why is {topic_clean} trending?"
            return topic_clean[:55].rstrip()

        if first:
            return first[:55].rstrip()

        return "This is trending now"

    # Palavras muito comuns que NAO indicam o assunto (PT + EN). Sao ignoradas
    # no calculo de correspondencia para nao dar match falso (ex.: "novo",
    # "para", "the", "and"). Assim o placar foca no assunto de verdade.
    _STOPWORDS = frozenset({
        # Portugues
        "a", "o", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da",
        "dos", "das", "no", "na", "nos", "nas", "em", "por", "para", "pra",
        "pro", "com", "sem", "sob", "que", "qual", "quais", "quem", "onde",
        "quando", "como", "porque", "porem", "porém", "e", "ou", "mas", "se",
        "ja", "já", "nao", "não", "sim", "muito", "mais", "menos", "seu",
        "sua", "seus", "suas", "meu", "minha", "este", "esta", "isso",
        "aquele", "novo", "nova", "video", "vídeo", "canal", "hoje", "agora",
        "tudo", "todos", "toda", "todas", "ao", "vivo", "aovivo",
        # Ingles
        "the", "an", "of", "to", "in", "on", "for", "and", "or", "but", "if",
        "is", "are", "was", "were", "be", "been", "with", "without", "this",
        "that", "these", "those", "new", "channel", "today", "now", "all",
        "how", "why", "what", "when", "where", "who", "live", "official",
        "full", "best", "top", "vs", "you", "your", "official",
    })

    def _meaningful_words(self, text: str) -> List[str]:
        """Retorna apenas as palavras que realmente identificam o assunto
        (>= 3 letras e que nao sejam palavras comuns/stopwords)."""
        norm = self._normalize_text(text)
        words = [w for w in norm.split() if len(w) >= 3 and w not in self._STOPWORDS]
        if words:
            return words
        # Se sobrou nada (assunto so com palavras comuns), usa o criterio antigo.
        return [w for w in norm.split() if len(w) >= 3]

    def _core_terms(self, topic: str) -> set:
        """Identifica os termos PRINCIPAIS do assunto (o nome do jogo/produto/
        pessoa). Sao eles que o video de fundo PRECISA conter para ser do tema.

        Heuristica: a 1a palavra significativa (assuntos de tendencia costumam
        comecar pelo nome do tema) + nomes proprios (palavras em Maiuscula no
        texto original, ex.: 'Roblox', 'KATSEYE')."""
        cores = set()
        meaningful = self._meaningful_words(topic)
        if meaningful:
            cores.add(meaningful[0])

        original = self._clean_text(topic)
        for raw in re.findall(r"\b[\wÀ-ÿ]+\b", original):
            if len(raw) >= 3 and (raw[0].isupper() or raw.isupper()):
                norm = self._normalize_text(raw)
                if norm and norm not in self._STOPWORDS:
                    cores.add(norm)
        return cores

    def _keyword_match_score(self, topic: str, candidate_text: str) -> float:
        topic_words = self._meaningful_words(topic)
        candidate_norm = self._normalize_text(candidate_text)

        if not topic_words or not candidate_norm:
            return 0.0

        hits = sum(1 for word in topic_words if word in candidate_norm)
        score = hits / len(topic_words)

        # O video PRECISA conter pelo menos um termo principal do assunto
        # (ex.: "roblox"). Se nenhum aparecer, quase certamente NAO e do tema.
        cores = self._core_terms(topic)
        core_present = any(c in candidate_norm for c in cores) if cores else True
        if not core_present:
            score *= 0.30

        # Assunto inteiro presente no titulo/descricao => match perfeito.
        if self._normalize_text(topic) in candidate_norm:
            score = 1.0

        return min(score, 1.0)

    def _split_script_for_subtitles(self, script: str, max_words_per_chunk: int = 6) -> List[str]:
        script = self._clean_text(script)
        if not script:
            return []

        words = script.split()
        if len(words) <= max_words_per_chunk:
            return [script]

        chunks = []
        for i in range(0, len(words), max_words_per_chunk):
            chunks.append(" ".join(words[i:i + max_words_per_chunk]))
        return chunks

    # ============================================================
    # FILE HELPERS
    # ============================================================

    def _safe_remove(self, file_path: str):
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

    def _safe_close_clip(self, clip):
        try:
            if clip:
                clip.close()
        except Exception:
            pass

    def _find_downloaded_background(self, temp_dir: str):
        candidates = []
        for pattern in [
            "temp_background.mp4",
            "temp_background.mkv",
            "temp_background.webm",
            "temp_background.mov",
            "temp_background.*",
        ]:
            candidates.extend(glob.glob(os.path.join(temp_dir, pattern)))

        candidates = [
            p for p in candidates
            if os.path.isfile(p) and not p.endswith(".part")
        ]

        if not candidates:
            return None

        candidates.sort(key=lambda p: os.path.getsize(p), reverse=True)
        return candidates[0]

    # ============================================================
    # FFMPEG / FFPROBE
    # ============================================================

    def _run_command(self, command):
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _has_nvenc(self) -> bool:
        if self._nvenc_available is not None:
            return self._nvenc_available

        if self._env_bool("ATLAS_DISABLE_NVENC", False):
            self._nvenc_available = False
            return False

        try:
            result = self._run_command(["ffmpeg", "-hide_banner", "-encoders"])
            self._nvenc_available = result.returncode == 0 and "h264_nvenc" in result.stdout
        except Exception:
            self._nvenc_available = False

        return self._nvenc_available

    def _probe_video_file(self, file_path: str):
        try:
            command = [
                _BUNDLED_FFPROBE_EXE or "ffprobe",
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path,
            ]

            result = self._run_command(command)
            if result.returncode != 0:
                print(f"❌ [MEDIA ENGINE] ffprobe falhou: {result.stderr}")
                return self._probe_video_file_moviepy(file_path)

            data = json.loads(result.stdout)

            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break

            if not video_stream:
                return self._probe_video_file_moviepy(file_path)

            width = int(video_stream.get("width") or 0)
            height = int(video_stream.get("height") or 0)

            duration = 0.0
            if video_stream.get("duration"):
                duration = float(video_stream.get("duration") or 0)
            elif data.get("format", {}).get("duration"):
                duration = float(data.get("format", {}).get("duration") or 0)

            bitrate = 0
            if data.get("format", {}).get("bit_rate"):
                bitrate = int(float(data.get("format", {}).get("bit_rate") or 0))
            elif video_stream.get("bit_rate"):
                bitrate = int(float(video_stream.get("bit_rate") or 0))

            if not bitrate and duration > 0:
                try:
                    file_size = os.path.getsize(file_path)
                    bitrate = int((file_size * 8) / duration)
                except Exception:
                    bitrate = 0

            short_side = min(width, height)
            long_side = max(width, height)

            return {
                "width": width,
                "height": height,
                "short_side": short_side,
                "long_side": long_side,
                "duration": duration,
                "bitrate": bitrate,
            }

        except FileNotFoundError:
            # ffprobe nao existe no sistema (comum no Windows). Usa o moviepy,
            # que le a resolucao pelo ffmpeg embutido (imageio-ffmpeg).
            return self._probe_video_file_moviepy(file_path)
        except Exception as e:
            print(f"❌ [MEDIA ENGINE] Erro ao medir asset (ffprobe): {e}. Tentando via moviepy...")
            return self._probe_video_file_moviepy(file_path)

    def _probe_video_file_moviepy(self, file_path: str):
        """Mede resolucao/duracao usando moviepy (ffmpeg embutido, sem ffprobe)."""
        clip = None
        try:
            clip = mp.VideoFileClip(file_path)
            width = int(clip.w or 0)
            height = int(clip.h or 0)
            duration = float(clip.duration or 0)

            bitrate = 0
            if duration > 0:
                try:
                    file_size = os.path.getsize(file_path)
                    bitrate = int((file_size * 8) / duration)
                except Exception:
                    bitrate = 0

            short_side = min(width, height)
            long_side = max(width, height)

            return {
                "width": width,
                "height": height,
                "short_side": short_side,
                "long_side": long_side,
                "duration": duration,
                "bitrate": bitrate,
            }
        except Exception as e:
            print(f"❌ [MEDIA ENGINE] Erro ao medir asset (moviepy): {e}")
            return None
        finally:
            self._safe_close_clip(clip)

    def _is_hd_video_file(self, file_path: str) -> bool:
        probe = self._probe_video_file(file_path)
        if not probe:
            print("❌ [MEDIA ENGINE] Asset rejeitado: não foi possível medir resolução.")
            return False

        width = probe["width"]
        height = probe["height"]
        short_side = probe["short_side"]
        long_side = probe["long_side"]
        duration = probe["duration"]
        bitrate = probe["bitrate"]

        bitrate_mbps = bitrate / 1_000_000 if bitrate else 0

        print(
            f"📏 [MEDIA ENGINE] Qualidade do asset: "
            f"{width}x{height} | duração {duration:.1f}s | bitrate {bitrate_mbps:.2f} Mbps"
        )

        if short_side < self.min_hd_short_side or long_side < self.min_hd_long_side:
            print(
                f"❌ [MEDIA ENGINE] Asset rejeitado: não é HD. "
                f"Mínimo exigido: lado menor {self.min_hd_short_side}px e lado maior {self.min_hd_long_side}px."
            )
            return False

        if duration < self.min_source_video_seconds:
            print(f"❌ [MEDIA ENGINE] Asset rejeitado: vídeo muito curto ({duration:.1f}s). Exigido: mínimo de {self.min_source_video_seconds:.0f}s.")
            return False

        if duration > self.max_source_video_seconds:
            print(
                f"❌ [MEDIA ENGINE] Asset rejeitado: duração longa demais "
                f"({duration:.0f}s | máximo {self.max_source_video_seconds}s)."
            )
            return False

        if bitrate_mbps > 0:
            is_1080_or_higher = long_side >= 1920 or short_side >= 1080
            if is_1080_or_higher:
                if bitrate_mbps < self.min_1080p_bitrate_mbps:
                    print(
                        f"❌ [MEDIA ENGINE] Asset rejeitado: bitrate baixo para 1080p+. "
                        f"Detectado {bitrate_mbps:.2f} Mbps | mínimo {self.min_1080p_bitrate_mbps:.2f} Mbps."
                    )
                    return False
            else:
                if bitrate_mbps < self.min_720p_bitrate_mbps:
                    print(
                        f"❌ [MEDIA ENGINE] Asset rejeitado: bitrate baixo para 720p. "
                        f"Detectado {bitrate_mbps:.2f} Mbps | mínimo {self.min_720p_bitrate_mbps:.2f} Mbps."
                    )
                    return False
        else:
            print("⚠️ [MEDIA ENGINE] Bitrate não informado. Aprovando apenas pela resolução/duração.")

        print("✅ [MEDIA ENGINE] Asset HD aprovado com qualidade aceitável.")
        return True

    # ============================================================
    # CANDIDATE FILTER
    # ============================================================

    def _is_bad_background_candidate(self, title: str, entry=None) -> bool:
        title_norm = self._normalize_text(title or "")

        blocked_terms = [
            # Termos de Live/Jogo (já existiam)
            "ao vivo", "aovivo", "en vivo", "live", "livestream", "stream",
            "transmissao", "transmissão", "partido completo", "jogo completo",
            "full match", "watch along", "watchalong", "minuto a minuto",
            "tempo real", "reaccion en vivo", "reacción en vivo", "reaction live",
            "simulacion", "simulación", "simulacao", "simulação",
            "pes 2026", "pes 21", "pes 2021", "efootball", "fifa 26",
            "fifa 2026 gameplay", "narração", "narracao", "relatos",
            "radio en vivo", "rádio ao vivo", "transmision", "transmisión",
            "partido en vivo", "jogo de hoje ao vivo", "assistir agora",
            
            # NOVOS TERMOS DE BLOQUEIO: Podcasts e Comentaristas 🚫
            "podcast", "interview", "entrevista", "reacts", "react", "reaction",
            "reagindo", "commentary", "breakdown", "explained", "explicado",
            "review", "opinion", "opinião", "debate", "talk show", "cortes do",
            "cortes de", "flow", "podpah", "videocast", "episode", "episódio"
        ]

        for term in blocked_terms:
            if term in title_norm:
                print(f"⏭️ [MEDIA ENGINE] Candidato ignorado por conter palavra proibida: '{title}'")
                return True


        if entry:
            live_status = str(entry.get("live_status", "") or "").lower()
            is_live = entry.get("is_live")

            if is_live is True:
                print(f"⏭️ [MEDIA ENGINE] Candidato ignorado por is_live=True: '{title}'")
                return True

            if live_status in {"is_live", "is_upcoming", "was_live", "post_live"}:
                print(f"⏭️ [MEDIA ENGINE] Candidato ignorado por live_status={live_status}: '{title}'")
                return True

            try:
                duration = float(entry.get("duration") or 0)
                if duration and duration < self.min_source_video_seconds:
                    print(f"⏭️ [MEDIA ENGINE] Candidato ignorado por ser curto demais ({duration:.0f}s). Mínimo {self.min_source_video_seconds:.0f}s: '{title}'")
                    return True

                if duration and duration > self.max_source_video_seconds:
                    print(f"⏭️ [MEDIA ENGINE] Candidato ignorado por duração longa demais ({duration:.0f}s): '{title}'")
                    return True
            except Exception:
                pass

        return False

    # ============================================================
    # YOUTUBE SEARCH / DOWNLOAD
    # ============================================================

    def _download_youtube_background(self, topic: str, temp_dir: str):
        safe_topic = self._clean_text(topic)
        if not safe_topic:
            return None

        query_topic = self._build_search_query(topic)
        print(f"🎥 [MEDIA ENGINE] Buscando asset visual HD (>60s) validado sobre: '{query_topic}'...")

        search_query = f"ytsearch{self.search_result_limit}:{query_topic}"

        search_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "noplaylist": True,
            "default_search": f"ytsearch{self.search_result_limit}",
            "socket_timeout": 10,
            "retries": 1,
            "extractor_retries": 1,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
            },
        }
        _apply_ytdlp_cookies(search_opts)
        _apply_ytdlp_bot_bypass(search_opts)

        try:
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                info = ydl.extract_info(search_query, download=False)

            entries = info.get("entries", []) if info else []
            scored_candidates = []

            for entry in entries:
                if not entry:
                    continue

                title = entry.get("title", "") or ""
                description = entry.get("description", "") or ""

                if self._is_bad_background_candidate(title, entry):
                    continue

                candidate_text = f"{title} {description}"
                score = self._keyword_match_score(query_topic, candidate_text)
                print(f"🔎 [MEDIA ENGINE] Candidato: '{title}' | Match: {score:.2f}")

                scored_candidates.append({
                    "entry": entry,
                    "title": title,
                    "score": score,
                })

            scored_candidates.sort(key=lambda item: item["score"], reverse=True)

            candidates_to_try = [
                candidate for candidate in scored_candidates
                if candidate["score"] >= self.min_asset_match_score
            ][:self.asset_candidate_limit]

            if not candidates_to_try:
                # Fallback CONTROLADO: so aceita candidatos que ainda tenham
                # uma relacao minima com o assunto (>= piso). Abaixo disso,
                # e melhor um fundo editorial limpo do que um video ERRADO.
                relaxed = [
                    c for c in scored_candidates
                    if c["score"] >= self.asset_match_floor
                ][:self.asset_candidate_limit]
                if relaxed:
                    print(
                        f"⚠️ [MEDIA ENGINE] Nenhum candidato forte. Usando o melhor "
                        f"parcial (match {relaxed[0]['score']:.2f} ≥ piso {self.asset_match_floor:.2f})."
                    )
                    candidates_to_try = relaxed
                else:
                    best = scored_candidates[0]["score"] if scored_candidates else 0.0
                    print(
                        f"⚠️ [MEDIA ENGINE] Nenhum video combina com o assunto "
                        f"(melhor match {best:.2f} < piso {self.asset_match_floor:.2f}). "
                        f"Usarei um fundo editorial limpo para NAO fugir do tema."
                    )
                    return None

            download_opts = {
                "format": (
                    "bv*[height>=1080][vcodec!*=av01]+ba/"
                    "bv*[height>=1080]+ba/"
                    "bv*[height>=720][vcodec!*=av01]+ba/"
                    "bv*[height>=720]+ba/"
                    "b[height>=720]/"
                    "bv*+ba/"
                    "b"
                ),
                "outtmpl": os.path.join(temp_dir, "temp_background.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "merge_output_format": "mp4",
                "socket_timeout": 12,
                "retries": 1,
                "fragment_retries": 1,
                "extractor_retries": 1,
                "file_access_retries": 1,
                "continuedl": False,
                "overwrites": True,
                "nopart": True,
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
                },
            }

            # Usa o ffmpeg embutido (imageio-ffmpeg) para o yt-dlp poder juntar
            # video+audio; sem isso o download HD falha com "ffmpeg is not installed".
            if _BUNDLED_FFMPEG_EXE:
                download_opts["ffmpeg_location"] = _BUNDLED_FFMPEG_EXE

            # Cookies do navegador logado no YouTube: permitem baixar videos
            # bloqueados por "confirme que voce nao e um robo" (asset 100% fiel).
            _apply_ytdlp_cookies(download_opts)

            # Bypass automatico do bot-check via clientes alternativos do YouTube
            # (TV/celular). Portatil e sem configuracao — funciona sem cookies.
            _apply_ytdlp_bot_bypass(download_opts)

            for candidate in candidates_to_try:
                entry = candidate["entry"]
                approved_title = candidate["title"]
                best_score = candidate["score"]

                if self._is_bad_background_candidate(approved_title, entry):
                    continue

                video_id = entry.get("id")
                url = entry.get("url") or entry.get("webpage_url")
                if video_id and not str(url).startswith("http"):
                    url = f"https://www.youtube.com/watch?v={video_id}"

                if not url:
                    continue

                print(f"✅ [MEDIA ENGINE] Tentando baixar asset HD: '{approved_title}' | Match: {best_score:.2f}")

                for old_file in glob.glob(os.path.join(temp_dir, "temp_background.*")):
                    self._safe_remove(old_file)

                try:
                    with yt_dlp.YoutubeDL(download_opts) as ydl:
                        ydl.download([url])

                    downloaded_file = self._find_downloaded_background(temp_dir)
                    if not downloaded_file:
                        print("⚠️ [MEDIA ENGINE] Download não gerou arquivo válido.")
                        continue

                    if self._is_hd_video_file(downloaded_file):
                        final_path = os.path.join(temp_dir, "temp_background.mp4")
                        if downloaded_file != final_path:
                            try:
                                os.replace(downloaded_file, final_path)
                            except Exception:
                                final_path = downloaded_file

                        print("⬇️ [MEDIA ENGINE] Asset HD baixado com sucesso: temp_background.mp4")
                        return final_path

                    print("🗑️ [MEDIA ENGINE] Removendo asset abaixo de HD: temp_background.mp4")
                    self._safe_remove(downloaded_file)

                except Exception as e:
                    print(f"⚠️ [MEDIA ENGINE] Candidato rejeitado: não possui HD baixável ou falhou download. Erro: {e}")
                    for old_file in glob.glob(os.path.join(temp_dir, "temp_background.*")):
                        self._safe_remove(old_file)
                    continue

            print("⚠️ [MEDIA ENGINE] Nenhum asset HD confiável encontrado.")
            return None

        except Exception as e:
            print(f"⚠️ [MEDIA ENGINE] Falha geral na busca de asset: {e}")
            return None

    # ============================================================
    # STOCK VIDEO (PEXELS / PIXABAY) — funciona quando o YouTube é bloqueado
    # ============================================================

    def _stock_ai_client(self):
        """Cliente Groq (OpenAI-compat) para transformar o assunto em termos visuais."""
        cached = getattr(self, "_stock_ai_client_cached", "unset")
        if cached != "unset":
            return cached

        client = None
        try:
            key = (os.getenv("GROQ_API_KEY") or "").strip()
            if key:
                from openai import OpenAI
                client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
        except Exception as e:
            print(f"⚠️ [STOCK] IA de palavras-chave indisponível: {e}")
            client = None

        self._stock_ai_client_cached = client
        return client

    def _stock_ai_model(self, client):
        """Escolhe um modelo NÃO-raciocínio (llama) para resposta rápida e curta."""
        try:
            models = [m.id for m in client.models.list()]
        except Exception:
            models = []
        for pref in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"):
            if pref in models:
                return pref
        return models[0] if models else "llama-3.3-70b-versatile"

    def _ai_stock_keywords(self, topic: str) -> list:
        """
        Usa IA para converter o ASSUNTO em consultas de vídeo de banco (stock)
        que sejam VISUALMENTE FIÉIS ao tema. Bancos só têm imagens genéricas
        (pessoas, lugares, objetos, esporte, tecnologia), então o segredo é
        traduzir o assunto para o seu "tema visual".
        """
        client = self._stock_ai_client()
        if not client:
            return []

        try:
            prompt = (
                "You choose B-ROLL stock video search queries for a vertical short video.\n"
                f'TOPIC: "{topic}"\n\n'
                "Stock sites (Pexels/Pixabay) only have GENERIC footage: people, places, "
                "activities, objects, nature, technology, sports, abstract. They do NOT have "
                "copyrighted games, movies, TV shows, music videos or specific celebrities.\n"
                "Convert the TOPIC into its VISUAL THEME and return search queries a stock site "
                "would actually match, staying as faithful as possible to the topic's vibe.\n"
                "Examples:\n"
                '- "Brawl Stars animation" -> ["mobile gaming","esports player","game controller closeup","colorful neon arcade"]\n'
                '- "The Batman Part 2 trailer" -> ["dark rainy city night","cinematic detective","movie theater","noir street"]\n'
                '- "iphone 18 pro max" -> ["smartphone closeup","person using phone","modern technology","mobile device"]\n'
                "Return ONLY a JSON array of 4 short English queries (2-3 words each). No prose."
            )

            model = self._stock_ai_model(client)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=200,
            )
            text = (resp.choices[0].message.content or "").strip()

            import json
            match = re.search(r"\[.*\]", text, re.S)
            if match:
                arr = json.loads(match.group(0))
                terms = [str(x).strip() for x in arr if str(x).strip()]
                if terms:
                    print(f"🧠 [STOCK] Palavras-chave visuais da IA: {terms[:5]}")
                return terms[:5]
        except Exception as e:
            print(f"⚠️ [STOCK] Falha ao gerar palavras-chave com IA: {e}")

        return []

    def _stock_search_terms(self, topic: str) -> list:
        """
        Gera termos de busca fiéis ao assunto para bancos de vídeo.
        Ordem: (1) tema visual da IA, (2) palavras literais do assunto.
        NÃO usa mais fundos genéricos aleatórios (technology, city, etc.),
        que traziam vídeos sem relação. Se nada relevante for achado,
        o sistema cai no fundo em gradiente — melhor que um vídeo errado.
        """
        terms = []

        # 1) Tema visual gerado por IA (mais fiel ao assunto).
        terms.extend(self._ai_stock_keywords(topic))

        # 2) Palavras literais do próprio assunto.
        query = self._build_search_query(topic)
        if query:
            words = query.split()
            if len(words) >= 3:
                terms.append(" ".join(words[:3]))
            if len(words) >= 2:
                terms.append(" ".join(words[:2]))
            if words:
                terms.append(words[0])

        seen = set()
        unique = []
        for term in terms:
            term = (term or "").strip()
            if term and term.lower() not in seen:
                seen.add(term.lower())
                unique.append(term)
        return unique

    def _download_stock_background(self, topic: str, temp_dir: str):
        """
        Baixa um vídeo de fundo real de bancos gratuitos (Pexels primeiro,
        Pixabay como reserva). O CDN desses serviços não é bloqueado como o
        YouTube, então funciona mesmo em rede corporativa.
        """
        try:
            import requests
        except Exception:
            print("⚠️ [STOCK] Biblioteca requests indisponível.")
            return None

        pexels_key = (os.getenv("PEXELS_API_KEY") or "").strip()
        pixabay_key = (os.getenv("PIXABAY_API_KEY") or "").strip()

        if not pexels_key and not pixabay_key:
            print("⚠️ [STOCK] Nenhuma chave de banco de vídeos configurada (.env).")
            return None

        for term in self._stock_search_terms(topic):
            print(f"🔎 [STOCK] Procurando vídeo de fundo para '{term}'...")
            path = None
            if pexels_key:
                path = self._pexels_video(term, pexels_key, temp_dir, requests)
            if not path and pixabay_key:
                path = self._pixabay_video(term, pixabay_key, temp_dir, requests)
            if path:
                return path

        print("⚠️ [STOCK] Nenhum vídeo de fundo encontrado nos bancos.")
        return None

    def _pexels_video(self, term: str, api_key: str, temp_dir: str, requests):
        try:
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": api_key},
                params={
                    "query": term,
                    "per_page": 10,
                    "orientation": "portrait",
                    "size": "medium",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"⚠️ [STOCK] Pexels retornou status {resp.status_code} para '{term}'.")
                return None

            videos = resp.json().get("videos", []) or []
            candidates = []
            for video in videos:
                for vfile in video.get("video_files", []) or []:
                    if vfile.get("file_type") != "video/mp4":
                        continue
                    width = int(vfile.get("width") or 0)
                    height = int(vfile.get("height") or 0)
                    link = vfile.get("link")
                    if not link or height < 720 or height < width:
                        continue
                    candidates.append((height, link))

            if not candidates:
                return None

            # Prefere a melhor qualidade até 1920px de altura (evita 4K pesado).
            under = [c for c in candidates if c[0] <= 1920]
            if under:
                _, link = max(under, key=lambda c: c[0])
            else:
                _, link = min(candidates, key=lambda c: c[0])

            return self._download_stock_file(link, temp_dir, requests, source="Pexels", term=term)
        except Exception as e:
            print(f"⚠️ [STOCK] Pexels falhou para '{term}': {e}")
            return None

    def _pixabay_video(self, term: str, api_key: str, temp_dir: str, requests):
        try:
            resp = requests.get(
                "https://pixabay.com/api/videos/",
                params={"key": api_key, "q": term, "per_page": 10, "safesearch": "true"},
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"⚠️ [STOCK] Pixabay retornou status {resp.status_code} para '{term}'.")
                return None

            hits = resp.json().get("hits", []) or []
            for hit in hits:
                streams = hit.get("videos", {}) or {}
                for quality in ("large", "medium", "small"):
                    vfile = streams.get(quality) or {}
                    url = vfile.get("url")
                    if url:
                        path = self._download_stock_file(
                            url, temp_dir, requests, source="Pixabay", term=term
                        )
                        if path:
                            return path
            return None
        except Exception as e:
            print(f"⚠️ [STOCK] Pixabay falhou para '{term}': {e}")
            return None

    def _download_stock_file(self, url: str, temp_dir: str, requests, source: str = "", term: str = ""):
        dest = os.path.join(temp_dir, "temp_background.mp4")
        try:
            with requests.get(url, stream=True, timeout=45) as resp:
                if resp.status_code != 200:
                    print(f"⚠️ [STOCK] Download {source} status {resp.status_code}.")
                    return None
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)

            if os.path.exists(dest) and os.path.getsize(dest) > 100 * 1024:
                print(f"⬇️ [STOCK] Vídeo de fundo baixado de {source} (busca '{term}').")
                return dest

            self._safe_remove(dest)
            return None
        except Exception as e:
            print(f"⚠️ [STOCK] Download falhou ({source}): {e}")
            self._safe_remove(dest)
            return None

    # ============================================================
    # AUDIO / TTS
    # ============================================================

    async def _tts_async(self, script: str, voice_name: str, output_path: str):
        communicate = edge_tts.Communicate(script, voice_name)
        await communicate.save(output_path)

    def _synthesize_voice(self, script: str, voice_name: str, temp_dir: str):
        voice_name = voice_name or self.default_voice
        output_path = os.path.join(temp_dir, "voice.mp3")

        print(f"🎙️ [MEDIA ENGINE] Sintetizando VOZ NEURAL ({voice_name})...")

        try:
            asyncio.run(self._tts_async(script, voice_name, output_path))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._tts_async(script, voice_name, output_path))
            finally:
                loop.close()

        if not os.path.exists(output_path):
            raise RuntimeError("Falha ao sintetizar voz neural.")

        audio_clip = mp.AudioFileClip(output_path)
        duration = float(audio_clip.duration or 0)
        audio_clip.close()

        if duration <= 0:
            raise RuntimeError("Áudio neural gerado com duração inválida.")

        print(f"✅ [MEDIA ENGINE] Voz Neural pronta. Duração usada: {duration:.1f}s")
        return output_path, duration

    # ============================================================
    # VIDEO COMPOSITION HELPERS
    # ============================================================

    def _validate_video_duration(self, duration: float) -> bool:
        if duration < (self.min_video_duration_seconds - 5.0):
            print(
                f"❌ [MEDIA ENGINE] Vídeo rejeitado: áudio da narração muito curto "
                f"({duration:.1f}s | mínimo aceito {self.min_video_duration_seconds - 5.0:.1f}s)."
            )
            return False

        if duration > (self.max_video_duration_seconds + 5.0):
            print(
                f"❌ [MEDIA ENGINE] Vídeo rejeitado: áudio da narração muito longo "
                f"({duration:.1f}s)."
            )
            return False

        print(
            f"✅ [MEDIA ENGINE] Duração da narração aprovada: {duration:.1f}s"
        )
        return True

    def _resize_cover(self, clip, width: int, height: int):
        clip_w, clip_h = clip.size
        scale = max(width / clip_w, height / clip_h)
        new_w = int(math.ceil(clip_w * scale))
        new_h = int(math.ceil(clip_h * scale))
        resized = clip.resize((new_w, new_h))
        x_center = new_w / 2
        y_center = new_h / 2
        return resized.fx(mp.vfx.crop, width=width, height=height, x_center=x_center, y_center=y_center)

    def _resize_contain_width(self, clip, width: int):
        clip_w, clip_h = clip.size
        if clip_w <= 0:
            return clip
        scale = width / clip_w
        new_h = int(clip_h * scale)
        return clip.resize((width, new_h))

    def _apply_visual_risk_reduction(self, clip):
        return clip

    def _make_visual_overlay(self, duration: float):
        try:
            opacity = float(self.visual_overlay_opacity)
            if opacity <= 0:
                return None
            return (
                mp.ColorClip(size=(self.video_width, self.video_height), color=(0, 0, 0))
                .set_duration(duration)
                .set_opacity(opacity)
            )
        except Exception as e:
            print(f"⚠️ [MEDIA ENGINE] Overlay visual não criado: {e}")
            return None

    def _make_bottom_safe_zone(self, duration: float):
        try:
            return (
                mp.ColorClip(
                    size=(self.video_width, self.bottom_safe_zone_height),
                    color=(0, 0, 0),
                )
                .set_duration(duration)
                .set_opacity(self.bottom_safe_zone_opacity)
                .set_position(("center", self.video_height - self.bottom_safe_zone_height))
            )
        except Exception as e:
            print(f"⚠️ [MEDIA ENGINE] Safe zone inferior não criada: {e}")
            return None

    def _make_subtitle_shield(self, duration: float):
        if not self.subtitle_shield_enabled:
            return None

        try:
            return (
                mp.ColorClip(
                    size=(self.video_width, self.subtitle_shield_height),
                    color=(0, 0, 0),
                )
                .set_duration(duration)
                .set_opacity(self.subtitle_shield_opacity)
                .set_position(("center", self.video_height - self.subtitle_shield_height - self.subtitle_shield_bottom_gap))
            )
        except Exception as e:
            print(f"⚠️ [MEDIA ENGINE] Faixa de proteção não criada: {e}")
            return None

    def _make_subtitle_clips(self, text: str, start_time: float, duration: float) -> list:
        """
        Retorna uma lista de clips em vez de um CompositeVideoClip isolado.
        Isso impede o MoviePy de usar múltiplas sub-telas invisíveis e alivia a RAM.
        O texto é renderizado com Pillow (sem ImageMagick), com ajuste automático
        de tamanho para nunca ultrapassar a largura segura do vídeo.
        """
        import numpy as np

        clips = []
        try:
            text = self._clean_text(text)
            if not text:
                return []

            image = self._render_text_image(
                text,
                font_size=self.subtitle_font_size,
                max_width=self.video_width - 180,
                color=self._color_to_rgba(self.subtitle_font_color, (255, 255, 255)),
                stroke_width=self.subtitle_stroke_width,
                stroke_color=self._color_to_rgba(self.subtitle_stroke_color, (0, 0, 0)),
                align="center",
                max_lines=2,
            )

            subtitle = (
                mp.ImageClip(np.array(image))
                .set_start(start_time)
                .set_duration(duration)
                .set_position(
                    ("center", self.video_height - self.bottom_safe_zone_height - 240)
                )
            )

            if self.subtitle_bg_opacity > 0:
                bg = (
                    mp.ColorClip(
                        size=(min(self.video_width - 120, image.width + 40), image.height + 28),
                        color=(0, 0, 0),
                    )
                    .set_start(start_time)
                    .set_duration(duration)
                    .set_opacity(self.subtitle_bg_opacity)
                    .set_position(("center", self.video_height - self.bottom_safe_zone_height - 255))
                )
                clips.append(bg)
            
            clips.append(subtitle)
            return clips

        except Exception as e:
            print(f"⚠️ [MEDIA ENGINE] Falha ao criar subtitle: {e}")
            return []

    def _make_hook_clips(self, hook: str, duration: float) -> list:
        """
        Retorna uma lista de clips em vez de um CompositeVideoClip isolado para não estourar a RAM.
        Texto renderizado com Pillow (sem ImageMagick).
        """
        if not self.enable_hook_text or not hook:
            return []

        import numpy as np

        hook = self._clean_text(hook)

        try:
            image = self._render_text_image(
                hook,
                font_size=self.hook_font_size,
                max_width=self.video_width - 140,
                color=self._color_to_rgba("white", (255, 255, 255)),
                stroke_width=2,
                stroke_color=self._color_to_rgba("black", (0, 0, 0)),
                align="center",
                max_lines=2,
            )

            text_clip = mp.ImageClip(np.array(image)).set_duration(min(duration, 5.0))
            text_w, text_h = image.width, image.height

            box = (
                mp.ColorClip(
                    size=(min(self.video_width - 80, text_w + 80), text_h + 54),
                    color=(0, 0, 0),
                )
                .set_duration(text_clip.duration)
                .set_opacity(self.hook_box_opacity)
            )

            box = box.set_position(("center", self.hook_y))
            text_clip = text_clip.set_position(("center", self.hook_y + 27))

            return [box, text_clip]

        except Exception as e:
            print(f"⚠️ [MEDIA ENGINE] Hook visual desativado por erro na renderização de texto: {e}")
            return []

    def _make_gradient_background_image(self):
        """
        Cria um fundo editorial em GRADIENTE colorido (não mais preto).
        Usado quando o b-roll do YouTube não pôde ser baixado.
        As cores são vibrantes o suficiente para não parecer "tela preta",
        mas permanecem escuras na base para manter a legenda branca legível.
        """
        import numpy as np

        w = self.video_width
        h = self.video_height

        # Paletas atraentes (topo -> base). Uma é sorteada por vídeo para dar
        # variedade sem depender de download externo.
        palettes = [
            ((41, 46, 122), (18, 92, 128), (10, 16, 40)),   # índigo -> azul -> navy
            ((104, 42, 122), (52, 40, 120), (14, 12, 34)),  # roxo -> violeta -> escuro
            ((16, 84, 92), (22, 54, 110), (8, 14, 32)),     # teal -> azul -> navy
            ((122, 58, 46), (86, 40, 92), (18, 12, 28)),    # coral -> vinho -> escuro
        ]
        try:
            top_c, mid_c, bot_c = random.choice(palettes)
        except Exception:
            top_c, mid_c, bot_c = palettes[0]

        top_c = np.array(top_c, dtype=np.float32)
        mid_c = np.array(mid_c, dtype=np.float32)
        bot_c = np.array(bot_c, dtype=np.float32)

        # Interpolação vertical em duas metades (topo->meio, meio->base).
        ys = np.linspace(0.0, 1.0, h, dtype=np.float32)
        col = np.empty((h, 3), dtype=np.float32)
        first = ys < 0.5
        t1 = (ys[first] / 0.5)[:, None]
        col[first] = top_c[None, :] * (1 - t1) + mid_c[None, :] * t1
        t2 = ((ys[~first] - 0.5) / 0.5)[:, None]
        col[~first] = mid_c[None, :] * (1 - t2) + bot_c[None, :] * t2

        grad = np.repeat(col[:, None, :], w, axis=1)

        # Brilho radial suave no terço superior (dá profundidade "editorial").
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = w * 0.5, h * 0.30
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        max_d = np.sqrt(cx ** 2 + cy ** 2)
        glow = np.clip(1.0 - dist / max_d, 0.0, 1.0)[:, :, None] ** 2
        grad = grad + glow * np.array([26, 28, 40], dtype=np.float32)[None, None, :]

        grad = np.clip(grad, 0, 255).astype("uint8")
        return grad

    def _make_fallback_background(self, duration: float):
        print("🎨 [MEDIA ENGINE] Usando fundo editorial em gradiente colorido (b-roll indisponível).")

        try:
            grad = self._make_gradient_background_image()
            return mp.ImageClip(grad).set_duration(duration)
        except Exception as e:
            print(f"⚠️ [MEDIA ENGINE] Gradiente indisponível ({e}); usando cor sólida.")
            return mp.ColorClip(
                size=(self.video_width, self.video_height),
                color=(24, 28, 52),
            ).set_duration(duration)

    def _prepare_source_clip(self, background_path: str, duration: float):
        source = mp.VideoFileClip(background_path)

        if source.duration <= 0:
            raise RuntimeError("Asset visual com duração inválida.")

        usable_duration = min(float(source.duration), max(duration + 1.0, 4.0))

        if source.duration > usable_duration:
            start = 0
            if source.duration > usable_duration + 10:
                start = min(5, max(0, source.duration - usable_duration - 1))
            source = source.subclip(start, start + usable_duration)

        if usable_duration < duration:
            loops_needed = int(math.ceil(duration / usable_duration))
            source = mp.concatenate_videoclips([source] * loops_needed)

        return source.subclip(0, duration)

    def _compose_vertical_video(self, background_path: str, voice_path: str, topic: str, script: str, output_path: str, hook_text: str = ""):
        voice_clip = None
        source = None
        final = None

        try:
            voice_clip = mp.AudioFileClip(voice_path)
            duration = float(voice_clip.duration or 0)

            if duration <= 0:
                raise RuntimeError("Duração do áudio inválida.")

            if not self._validate_video_duration(duration):
                raise RuntimeError(f"Duração fora da faixa permitida: {duration:.1f}s")

            layers = []

            if background_path and os.path.exists(background_path):
                print("🎞️ [MEDIA ENGINE] Compondo vídeo vertical com asset HD validado...")
                source = self._prepare_source_clip(background_path, duration)

                bg = self._resize_cover(source, self.video_width, self.video_height)

                try:
                    bg_strength = self._env_float("ATLAS_BACKGROUND_COLORX", 0.82)
                    bg = bg.fx(mp.vfx.colorx, bg_strength)
                except Exception as color_err:
                    print(f"⚠️ [MEDIA ENGINE] Ajuste leve do fundo indisponível. Erro: {color_err}")

                fg = self._resize_contain_width(source, self.video_width)
                fg = self._apply_visual_risk_reduction(fg)
                fg_y = max(0, int((self.video_height - fg.h) / 2) - self.foreground_vertical_offset)
                fg = fg.set_position(("center", fg_y))

                layers.extend([bg, fg])

                if self.visual_risk_reduction:
                    print("🎞️ [MEDIA ENGINE] Segmentação visual aplicada sem alterar cores do asset.")
                print("🎨 [MEDIA ENGINE] Asset principal mantido com cores naturais.")
            else:
                layers.append(self._make_fallback_background(duration))

            bottom_safe = self._make_bottom_safe_zone(duration)
            if bottom_safe:
                layers.append(bottom_safe)

            shield = self._make_subtitle_shield(duration)
            if shield:
                layers.append(shield)
                print("🛡️ [MEDIA ENGINE] Faixa de proteção contra legenda original aplicada.")

            overlay = self._make_visual_overlay(duration)
            if overlay:
                layers.append(overlay)

            # Inserindo o Hook de forma limpa (direto na lista main)
            hook = hook_text if hook_text else self._make_short_hook(topic, script)
            hook_clips = self._make_hook_clips(hook, duration)
            if hook_clips:
                layers.extend(hook_clips)
                print("📝 [MEDIA ENGINE] Inserindo hook em Safe Zone visual...")
                print(f"✅ [MEDIA ENGINE] Hook inserido: '{hook}'")

            # Inserindo Legendas de forma limpa
            if self.subtitle_enabled:
                chunks = self._split_script_for_subtitles(script, max_words_per_chunk=4)
                if chunks:
                    chunk_duration = max(1.8, duration / max(1, len(chunks)))
                    current_start = 0.0

                    for chunk in chunks:
                        sub_duration = min(chunk_duration, max(0.8, duration - current_start))
                        layers.extend(self._make_subtitle_clips(chunk, current_start, sub_duration))

                        current_start += chunk_duration
                        if current_start >= duration:
                            break

                    print(f"📝 [MEDIA ENGINE] Legendas geradas em {len(chunks)} bloco(s).")
                else:
                    print("⚠️ [MEDIA ENGINE] Nenhuma legenda gerada: script vazio ou inválido.")

            final = mp.CompositeVideoClip(layers, size=(self.video_width, self.video_height)).set_duration(duration)
            final = final.set_audio(voice_clip)

            # Lógica Híbrida: Usa GPU se disponível, senão CPU ultra rápida.
            codec = "libx264"
            preset = "ultrafast"
            if self._has_nvenc():
                codec = "h264_nvenc"
                preset = "p4"
                print("⚡ [MEDIA ENGINE] Renderização ACELERADA POR GPU (NVIDIA/NVENC) ativada!")
            else:
                print("⚙️ [MEDIA ENGINE] Renderização via Processador/CPU (libx264 ultrafast).")

            ffmpeg_params = ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]

            print(f"🎞️ [MEDIA ENGINE] Renderizando MASTER HD vertical {self.video_width}x{self.video_height} com bitrate alto...")

            write_kwargs = {
                "filename": output_path,
                "fps": self.video_fps,
                "codec": codec,
                "audio_codec": "aac",
                "bitrate": self.master_bitrate,
                "audio_bitrate": self.audio_bitrate,
                "ffmpeg_params": ffmpeg_params,
                "preset": preset,
                "threads": self._env_int("ATLAS_RENDER_THREADS", 4),
                "logger": DockerLogger(), # A MÁGICA PARA O DOCKER AQUI
                "temp_audiofile": os.path.join(os.path.dirname(output_path), f"temp_audio_{int(time.time())}.m4a"),
                "remove_temp": True,
            }

            final.write_videofile(**write_kwargs)
            print("✅ [MEDIA ENGINE] Vídeo final renderizado com sucesso.")
            return output_path

        finally:
            self._safe_close_clip(final)
            self._safe_close_clip(source)
            self._safe_close_clip(voice_clip)

    # ============================================================
    # ARG PARSER PARA COMPATIBILIDADE
    # ============================================================

    def _parse_production_args(self, *args, **kwargs):
        def get_from_obj(obj, names, default=None):
            if obj is None:
                return default
            if isinstance(obj, dict):
                for name in names:
                    if name in obj and obj.get(name) is not None:
                        return obj.get(name)
                return default
            for name in names:
                if hasattr(obj, name):
                    value = getattr(obj, name)
                    if value is not None:
                        return value
            return default

        script_fields = [
            "script", "script_text", "voiceover", "voice_over",
            "voiceover_text", "voice_over_text", "text", "narration",
            "narration_text", "roteiro", "caption_script",
        ]

        def looks_like_script(value):
            if not value:
                return False
            text = str(value).strip()
            if len(text) < 25:
                return False
            sentence_marks = text.count(".") + text.count("!") + text.count("?")
            word_count = len(re.findall(r"\b\w+\b", text))
            return word_count >= 8 or sentence_marks >= 1

        def looks_like_topic(value):
            if not value:
                return False
            text = str(value).strip()
            if len(text) > 140:
                return False
            word_count = len(re.findall(r"\b\w+\b", text))
            return 1 <= word_count <= 18

        content = (
            kwargs.get("content")
            or kwargs.get("content_obj")
            or kwargs.get("content_record")
            or kwargs.get("db_content")
            or kwargs.get("item")
        )

        content_id = kwargs.get("content_id") or kwargs.get("id") or kwargs.get("video_id") or kwargs.get("record_id")
        topic = kwargs.get("topic") or kwargs.get("theme") or kwargs.get("subject") or kwargs.get("title") or kwargs.get("trend")
        script = kwargs.get("script")
        
        # ---> RECEBENDO O HOOK TEXT <---
        hook_text = kwargs.get("hook_text") or kwargs.get("hook") or ""

        for field in script_fields:
            if not script and kwargs.get(field):
                script = kwargs.get(field)

        language = kwargs.get("language") or kwargs.get("lang") or kwargs.get("locale") or "en"
        voice_name = kwargs.get("voice_name") or kwargs.get("voice") or kwargs.get("tts_voice") or kwargs.get("voice_id") or kwargs.get("speaker")
        trend_source = kwargs.get("trend_source") or kwargs.get("source") or kwargs.get("fonte") or ""
        base_hashtags = kwargs.get("base_hashtags") or kwargs.get("hashtags") or kwargs.get("tags") or []
        metadata = kwargs.get("metadata") or kwargs.get("metadata_package") or kwargs.get("platform_metadata") or {}

        if isinstance(metadata, dict):
            if not topic:
                topic = metadata.get("topic") or metadata.get("title") or metadata.get("youtube_title")
            if not base_hashtags:
                base_hashtags = metadata.get("hashtags") or []

        if content is not None:
            content_id = content_id or get_from_obj(content, ["id", "content_id", "video_id"])
            topic = topic or get_from_obj(content, ["topic", "theme", "subject", "title", "trend"])
            script = script or get_from_obj(content, script_fields)
            language = language or get_from_obj(content, ["language", "lang", "locale"], "en")

        if args:
            remaining = list(args)
            first = remaining[0]

            if isinstance(first, dict) or hasattr(first, "script") or hasattr(first, "topic"):
                content = first
                content_id = content_id or get_from_obj(content, ["id", "content_id", "video_id"])
                topic = topic or get_from_obj(content, ["topic", "theme", "subject", "title", "trend"])
                script = script or get_from_obj(content, script_fields)
                language = language or get_from_obj(content, ["language", "lang", "locale"], "en")

                remaining = remaining[1:]
                if remaining and not voice_name and isinstance(remaining[0], str) and not looks_like_script(remaining[0]):
                    voice_name = remaining[0]
                    remaining = remaining[1:]
                if remaining and not trend_source and isinstance(remaining[0], str) and not looks_like_script(remaining[0]):
                    trend_source = remaining[0]
                    remaining = remaining[1:]
                if remaining and not base_hashtags and isinstance(remaining[0], list):
                    base_hashtags = remaining[0]
            else:
                if len(remaining) >= 3 and isinstance(remaining[0], int):
                    content_id = content_id or remaining[0]
                    topic = topic or remaining[1]
                    script = script or remaining[2]
                    if len(remaining) >= 4:
                        language = language or remaining[3]
                    if len(remaining) >= 5:
                        voice_name = voice_name or remaining[4]
                    if len(remaining) >= 6:
                        trend_source = trend_source or remaining[5]
                    if len(remaining) >= 7:
                        base_hashtags = base_hashtags or remaining[6]
                elif len(remaining) >= 2:
                    a, b = remaining[0], remaining[1]
                    if looks_like_topic(a) and looks_like_script(b):
                        topic, script = topic or a, script or b
                    elif looks_like_script(a) and looks_like_topic(b):
                        script, topic = script or a, topic or b
                    else:
                        topic, script = topic or a, script or b

                    if len(remaining) >= 3 and not voice_name:
                        voice_name = remaining[2]
                    if len(remaining) >= 4 and not language:
                        language = remaining[3]
                    if len(remaining) >= 5 and not trend_source:
                        trend_source = remaining[4]
                    if len(remaining) >= 6 and not base_hashtags:
                        base_hashtags = remaining[5]
                elif len(remaining) == 1:
                    only = remaining[0]
                    if isinstance(only, int):
                        content_id = content_id or only
                    elif looks_like_script(only):
                        script = script or only
                    elif looks_like_topic(only):
                        topic = topic or only

        if isinstance(metadata, dict):
            script = script or metadata.get("script") or metadata.get("voiceover") or metadata.get("narration")
            topic = topic or metadata.get("topic") or metadata.get("youtube_title") or metadata.get("title")

        if not content_id:
            content_id = time.time_ns()

        topic = self._clean_text(topic or "")
        script = self._clean_text(script or "")

        if not language:
            language = "en"
        if not voice_name:
            voice_name = self.default_voice
        if base_hashtags is None:
            base_hashtags = []

        if not topic or not script:
            print("❌ [MEDIA ENGINE] Argumentos recebidos pelo MediaService não foram reconhecidos.")
            print(f"   args_count: {len(args)}")
            print(f"   kwargs_keys: {list(kwargs.keys())}")
            for idx, arg in enumerate(args):
                try:
                    print(f"   arg[{idx}] type={type(arg)} value_preview={str(arg)[:180]}")
                except Exception:
                    print(f"   arg[{idx}] type={type(arg)} value_preview=<indisponível>")

        if not topic:
            raise RuntimeError("MediaService não recebeu topic.")
        if not script:
            raise RuntimeError("MediaService não recebeu script.")

        return {
            "content": content,
            "content_id": content_id,
            "topic": topic,
            "script": script,
            "hook_text": hook_text,
            "language": language,
            "voice_name": voice_name,
            "trend_source": trend_source,
            "base_hashtags": base_hashtags,
        }

    # ============================================================
    # PRODUÇÃO PRINCIPAL
    # ============================================================

    def produce_video(self, *args, **kwargs):
        data = self._parse_production_args(*args, **kwargs)
        
        content = data["content"]
        content_id = data["content_id"]
        topic = data["topic"]
        script = data["script"]
        hook_text = data["hook_text"]
        language = data["language"]
        voice_name = data["voice_name"]
        trend_source = data["trend_source"]
        base_hashtags = data["base_hashtags"]
        print(f"\n🎬 [MEDIA ENGINE] Iniciando produção do vídeo ID {content_id}")
    
        temp_dir = tempfile.mkdtemp(prefix="atlas_media_")
    
        try:
            max_attempts = 3
    
            for attempt in range(1, max_attempts + 1):
                print(f"🔁 [MEDIA ENGINE] Tentativa {attempt}/{max_attempts} de gerar vídeo")
    
                voice_path, voice_duration = self._synthesize_voice(
                    script=script,
                    voice_name=voice_name,
                    temp_dir=temp_dir,
                )
    
                if voice_duration >= (self.min_video_duration_seconds - 5.0):
                    break
    
                print(
                    f"⚠️ [MEDIA ENGINE] Áudio da narração curto demais ({voice_duration:.1f}s). "
                    f"Precisamos de pelo menos {self.min_video_duration_seconds - 5.0:.1f}s."
                )
    
                if content and hasattr(content, "script_service"):
                    content_service = content.script_service
                else:
                    content_service = None
    
                if not content_service:
                    print("⚠️ [MEDIA ENGINE] Serviço de roteiro não atrelado. Usando áudio como está para avaliação.")
                    break
    
                script = content_service.generate_script(
                    topic=topic,
                    language=language,
                    trend_source=trend_source,
                    research_context=content_service.last_research_context,
                )
    
            background_path = self._download_youtube_background(topic=topic, temp_dir=temp_dir)
    
            if not background_path:
                print("🎬 [MEDIA ENGINE] YouTube sem vídeo utilizável. Buscando fundo em bancos (Pexels/Pixabay)...")
                background_path = self._download_stock_background(topic=topic, temp_dir=temp_dir)

            output_path = os.path.join(self.output_dir, f"video_{content_id}.mp4")

            final_path = self._compose_vertical_video(
                background_path=background_path,
                voice_path=voice_path,
                topic=topic,
                script=script,
                hook_text=hook_text,
                output_path=output_path,
            )
    
            return final_path
    
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ============================================================
    # ALIASES PARA NÃO QUEBRAR O WORKER
    # ============================================================

    def create_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def generate_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def render_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_media(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def build_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def produce_media(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_tiktok_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def generate_tiktok_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def produce_tiktok_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_short_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def generate_short_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def produce_short_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_youtube_short(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_youtube_shorts_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def generate_youtube_short(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def generate_youtube_shorts_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_reels_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_reel_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_instagram_reel(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_instagram_reels_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_facebook_reel(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
    def create_facebook_reels_video(self, *args, **kwargs): return self.produce_video(*args, **kwargs)
