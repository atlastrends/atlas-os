"""
ATLAS - Servico de geracao de ebooks (livros de colorir, atividades e planners).

Gera livros curtos com muitas imagens (line-art), prontos para publicar como
PDF na Amazon KDP (impressao sob demanda) ou vender como PDF premium
(Hotmart/Kiwify/Gumroad). Suporta EN e PT e inclui pagina de divulgacao de IA
(selo obrigatorio em algumas plataformas).

Independente do pipeline de video: nao importa nada do motor de reels, entao
nao ha risco de afetar a producao de videos.

Imagem: usa Pollinations.ai (gratis, sem chave) por padrao; Gemini (chave do
.env) como opcao quando ATLAS_EBOOK_IMAGE_GEMINI=true e houver cota.
PDF: montado com Pillow (sem dependencia extra).
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import time
import unicodedata
import urllib.parse
import urllib.request

import requests
from typing import Any, Callable, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - fallback sem OpenCV
    cv2 = None
    np = None

try:
    from dotenv import load_dotenv

    load_dotenv()  # carrega GROQ_API_KEY etc. para as receitas por IA
except Exception:  # pragma: no cover
    pass

# ---------------------------------------------------------------------------
# Constantes de impressao (8.5 x 11 in @ 300 DPI = padrao KDP)
# ---------------------------------------------------------------------------
DPI = 300
PAGE_W_IN, PAGE_H_IN = 8.5, 11.0
PAGE_PX = (int(PAGE_W_IN * DPI), int(PAGE_H_IN * DPI))  # (2550, 3300)
MARGIN = int(0.6 * DPI)  # 180 px de margem segura (interior sem sangria)

OUTPUT_ROOT = os.getenv("ATLAS_EBOOK_OUTPUT", r"C:\atlas-os\ebooks")
BRAND = os.getenv("ATLAS_EBOOK_BRAND", "ATLAS Press")

_WIN_FONTS = r"C:\Windows\Fonts"
_FONT_FILES = {
    ("arial", False): "arial.ttf",
    ("arial", True): "arialbd.ttf",
    ("georgia", False): "georgia.ttf",
    ("georgia", True): "georgiab.ttf",
    ("comic", False): "comic.ttf",
    ("comic", True): "comicbd.ttf",
    ("verdana", False): "verdana.ttf",
    ("verdana", True): "verdanab.ttf",
}


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on", "sim")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "ebook"


def _font(size: int, bold: bool = False, family: str = "arial") -> ImageFont.FreeTypeFont:
    path = os.path.join(_WIN_FONTS, _FONT_FILES.get((family, bold), "arial.ttf"))
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype(os.path.join(_WIN_FONTS, "arial.ttf"), size)
        except Exception:
            return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Textos bilingues (selo de IA + rotulos)
# ---------------------------------------------------------------------------
AI_DISCLOSURE = {
    "en": (
        "This book was created with the assistance of artificial "
        "intelligence (AI). The illustrations and content were generated "
        "using AI tools and reviewed for quality by the publisher before "
        "publication."
    ),
    "pt": (
        "Este livro foi criado com o auxilio de inteligencia artificial "
        "(IA). As ilustracoes e o conteudo foram gerados com ferramentas de "
        "IA e revisados quanto a qualidade pela editora antes da publicacao."
    ),
}

_L = {
    "belongs_en": "This book belongs to:",
    "belongs_pt": "Este livro pertence a:",
    "ai_title_en": "About this book",
    "ai_title_pt": "Sobre este livro",
    "grat_title_en": "Gratitude Journal",
    "grat_title_pt": "Diario de Gratidao",
    "date_en": "Date:",
    "date_pt": "Data:",
    "grateful_en": "Today I am grateful for:",
    "grateful_pt": "Hoje eu sou grato(a) por:",
    "affirm_en": "Today's affirmation:",
    "affirm_pt": "Afirmacao de hoje:",
    "smile_en": "One thing that made me smile:",
    "smile_pt": "Algo que me fez sorrir:",
    "mood_en": "Mood:",
    "mood_pt": "Humor:",
    "maze_en": "Maze",
    "maze_pt": "Labirinto",
    "start_en": "START",
    "start_pt": "INICIO",
    "end_en": "END",
    "end_pt": "FIM",
}

_DAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "pt": ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"],
}
_MEALS = {
    "en": ["Breakfast", "Lunch", "Dinner", "Snack"],
    "pt": ["Cafe", "Almoco", "Jantar", "Lanche"],
}
_MP = {
    "title_en": "Weekly Meal Plan", "title_pt": "Cardapio da Semana",
    "week_en": "Week of:", "week_pt": "Semana de:",
    "shop_en": "Shopping List", "shop_pt": "Lista de Compras",
}
_RC = {
    "ingredients_en": "Ingredients", "ingredients_pt": "Ingredientes",
    "steps_en": "Instructions", "steps_pt": "Modo de Preparo",
    "time_en": "Time", "time_pt": "Tempo",
    "serves_en": "Serves", "serves_pt": "Porcoes",
    "calories_en": "Calories", "calories_pt": "Calorias",
}

# Rede de seguranca: receitas curadas e distintas (usadas se a IA falhar).
_FALLBACK_RECIPES = {
    "en": [
        {"title": "Crispy Air Fryer Chicken Wings", "time": "25 min", "serves": "4", "calories": "350 kcal",
         "ingredients": ["1 kg chicken wings", "1 tbsp olive oil", "1 tsp paprika", "1 tsp garlic powder", "Salt and pepper"],
         "steps": ["Pat the wings dry.", "Toss with oil and spices.", "Air fry at 200C for 22 min, flipping halfway.", "Serve hot."]},
        {"title": "Parmesan Zucchini Fries", "time": "18 min", "serves": "4", "calories": "180 kcal",
         "ingredients": ["2 zucchinis", "1/2 cup grated parmesan", "1/2 cup breadcrumbs", "1 egg", "Salt"],
         "steps": ["Cut zucchini into sticks.", "Dip in egg, coat in parmesan and breadcrumbs.", "Air fry at 200C for 12 min.", "Serve with a dip."]},
        {"title": "Air Fryer Salmon", "time": "15 min", "serves": "2", "calories": "300 kcal",
         "ingredients": ["2 salmon fillets", "1 tbsp olive oil", "1 tsp lemon juice", "1 clove garlic", "Salt and pepper"],
         "steps": ["Brush salmon with oil and lemon.", "Season with garlic, salt and pepper.", "Air fry at 200C for 10 min.", "Rest and serve."]},
        {"title": "Sweet Potato Fries", "time": "22 min", "serves": "4", "calories": "210 kcal",
         "ingredients": ["2 sweet potatoes", "1 tbsp olive oil", "1 tsp paprika", "Salt"],
         "steps": ["Cut into fries.", "Toss with oil and paprika.", "Air fry at 200C for 18 min, shaking halfway.", "Salt and serve."]},
        {"title": "Stuffed Mushrooms", "time": "20 min", "serves": "4", "calories": "160 kcal",
         "ingredients": ["12 mushrooms", "1/2 cup cream cheese", "1 clove garlic", "Parsley", "2 tbsp parmesan"],
         "steps": ["Remove the stems.", "Mix the filling.", "Stuff the caps.", "Air fry at 180C for 12 min."]},
        {"title": "Banana Oat Muffins", "time": "20 min", "serves": "6", "calories": "190 kcal",
         "ingredients": ["2 bananas", "1 cup oats", "1 egg", "2 tbsp honey", "1 tsp baking powder"],
         "steps": ["Blend all ingredients.", "Pour into muffin cups.", "Air fry at 160C for 15 min.", "Cool before serving."]},
        {"title": "Crispy Tofu Bites", "time": "20 min", "serves": "3", "calories": "200 kcal",
         "ingredients": ["1 block firm tofu", "2 tbsp soy sauce", "1 tbsp cornstarch", "1 clove garlic", "Sesame seeds"],
         "steps": ["Cube the tofu.", "Toss with soy sauce and cornstarch.", "Air fry at 200C for 15 min.", "Sprinkle sesame and serve."]},
        {"title": "Garlic Parmesan Potatoes", "time": "25 min", "serves": "4", "calories": "230 kcal",
         "ingredients": ["500 g baby potatoes", "2 tbsp olive oil", "2 cloves garlic", "Parmesan", "Parsley"],
         "steps": ["Halve the potatoes.", "Toss with oil and garlic.", "Air fry at 200C for 20 min.", "Top with parmesan and parsley."]},
    ],
    "pt": [
        {"title": "Asas de Frango Crocantes", "time": "25 min", "serves": "4", "calories": "350 kcal",
         "ingredients": ["1 kg de asas de frango", "1 colher de azeite", "1 colher de paprica", "1 colher de alho em po", "Sal e pimenta"],
         "steps": ["Seque bem as asas.", "Misture com azeite e temperos.", "Air fry a 200C por 22 min, virando na metade.", "Sirva quente."]},
        {"title": "Palitos de Abobrinha com Parmesao", "time": "18 min", "serves": "4", "calories": "180 kcal",
         "ingredients": ["2 abobrinhas", "1/2 xicara de parmesao ralado", "1/2 xicara de farinha de rosca", "1 ovo", "Sal"],
         "steps": ["Corte a abobrinha em palitos.", "Passe no ovo e na mistura de parmesao e farinha.", "Air fry a 200C por 12 min.", "Sirva com molho."]},
        {"title": "Salmao na Air Fryer", "time": "15 min", "serves": "2", "calories": "300 kcal",
         "ingredients": ["2 files de salmao", "1 colher de azeite", "1 colher de suco de limao", "1 dente de alho", "Sal e pimenta"],
         "steps": ["Pincele o salmao com azeite e limao.", "Tempere com alho, sal e pimenta.", "Air fry a 200C por 10 min.", "Descanse e sirva."]},
        {"title": "Batata Doce Frita", "time": "22 min", "serves": "4", "calories": "210 kcal",
         "ingredients": ["2 batatas doces", "1 colher de azeite", "1 colher de paprica", "Sal"],
         "steps": ["Corte em palitos.", "Misture com azeite e paprica.", "Air fry a 200C por 18 min, sacudindo na metade.", "Salgue e sirva."]},
        {"title": "Cogumelos Recheados", "time": "20 min", "serves": "4", "calories": "160 kcal",
         "ingredients": ["12 cogumelos", "1/2 xicara de cream cheese", "1 dente de alho", "Salsinha", "2 colheres de parmesao"],
         "steps": ["Retire os talos.", "Misture o recheio.", "Recheie os chapeus.", "Air fry a 180C por 12 min."]},
        {"title": "Muffins de Banana e Aveia", "time": "20 min", "serves": "6", "calories": "190 kcal",
         "ingredients": ["2 bananas", "1 xicara de aveia", "1 ovo", "2 colheres de mel", "1 colher de fermento"],
         "steps": ["Bata todos os ingredientes.", "Coloque nas forminhas.", "Air fry a 160C por 15 min.", "Deixe esfriar antes de servir."]},
        {"title": "Cubos de Tofu Crocante", "time": "20 min", "serves": "3", "calories": "200 kcal",
         "ingredients": ["1 bloco de tofu firme", "2 colheres de shoyu", "1 colher de amido", "1 dente de alho", "Gergelim"],
         "steps": ["Corte o tofu em cubos.", "Misture com shoyu e amido.", "Air fry a 200C por 15 min.", "Salpique gergelim e sirva."]},
        {"title": "Batatas com Alho e Parmesao", "time": "25 min", "serves": "4", "calories": "230 kcal",
         "ingredients": ["500 g de batata bolinha", "2 colheres de azeite", "2 dentes de alho", "Parmesao", "Salsinha"],
         "steps": ["Corte as batatas ao meio.", "Misture com azeite e alho.", "Air fry a 200C por 20 min.", "Finalize com parmesao e salsinha."]},
    ],
}


# ---------------------------------------------------------------------------
# Geracao de imagem (Pollinations gratis -> Gemini opcional)
# ---------------------------------------------------------------------------
class ImageGenerator:
    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self.log = log or (lambda m: print(m))
        self.use_gemini = _env_bool("ATLAS_EBOOK_IMAGE_GEMINI", False)
        self.poll_model = os.getenv("ATLAS_EBOOK_POLL_MODEL", "flux")
        self.tries = _env_int("ATLAS_EBOOK_IMAGE_TRIES", 3)
        self._gemini = None
        if self.use_gemini:
            self._init_gemini()

        # ------------------------------------------------------------
        # Backend LOCAL de imagem (Stable Diffusion via Automatic1111/
        # ComfyUI-compat, endpoint /sdapi/v1/txt2img). OPCIONAL: so entra
        # em acao se ATLAS_LOCAL_SD_URL apontar para um servidor de verdade
        # rodando (ex.: "http://127.0.0.1:7860" numa maquina com GPU
        # dedicada, como o Dell G15). Nesta maquina (sem GPU dedicada) fica
        # inativo e o gerador cai automaticamente no Pollinations (remoto,
        # gratis). Preparado agora para poder ligar so trocando o .env
        # quando rodar num notebook com placa de video.
        self.local_sd_url = (os.getenv("ATLAS_LOCAL_SD_URL") or "").strip().rstrip("/")
        self._local_sd_checked = False
        self._local_sd_ok = False

    def _local_sd_available(self) -> bool:
        """Confere (uma vez por processo) se o servidor local de Stable
        Diffusion esta de pe. Timeout curto para nao travar a geracao
        quando ATLAS_LOCAL_SD_URL nao estiver configurado/acessivel."""
        if not self.local_sd_url:
            return False
        if self._local_sd_checked:
            return self._local_sd_ok
        self._local_sd_checked = True
        try:
            resp = requests.get(f"{self.local_sd_url}/sdapi/v1/sd-models", timeout=3)
            self._local_sd_ok = resp.status_code == 200
        except Exception:
            self._local_sd_ok = False
        if self._local_sd_ok:
            self.log(f"[IMAGE] Stable Diffusion LOCAL detectado em {self.local_sd_url} (usando GPU local).")
        return self._local_sd_ok

    def _local_sd_image(self, prompt: str, width: int, height: int, seed: int) -> Optional[bytes]:
        """Gera a imagem no servidor LOCAL (Automatic1111-compat). Retorna
        None em qualquer falha, para o chamador cair no fallback remoto."""
        if not self._local_sd_available():
            return None
        style_suffix = (os.getenv("ATLAS_LOCAL_SD_STYLE_SUFFIX") or "").strip()
        full_prompt = f"{prompt}, {style_suffix}" if style_suffix else prompt
        body = {
            "prompt": full_prompt,
            "negative_prompt": os.getenv(
                "ATLAS_LOCAL_SD_NEGATIVE_PROMPT",
                "blurry, low quality, deformed, extra limbs, watermark, text, signature",
            ),
            "width": width,
            "height": height,
            "steps": _env_int("ATLAS_LOCAL_SD_STEPS", 28),
            "cfg_scale": _env_int("ATLAS_LOCAL_SD_CFG_SCALE", 7),
            "sampler_name": os.getenv("ATLAS_LOCAL_SD_SAMPLER", "DPM++ 2M Karras"),
            "seed": seed,
        }
        checkpoint = (os.getenv("ATLAS_LOCAL_SD_MODEL") or "").strip()
        if checkpoint:
            body["override_settings"] = {"sd_model_checkpoint": checkpoint}
        try:
            resp = requests.post(
                f"{self.local_sd_url}/sdapi/v1/txt2img",
                json=body,
                timeout=int(os.getenv("ATLAS_LOCAL_SD_TIMEOUT", "180")),
            )
            if resp.status_code != 200:
                self.log(f"[IMAGE] Stable Diffusion local HTTP {resp.status_code}; caindo no fallback remoto.")
                return None
            payload = resp.json()
            images = payload.get("images") or []
            if not images:
                return None
            import base64
            return base64.b64decode(images[0])
        except Exception as exc:  # noqa: BLE001
            self.log(f"[IMAGE] Stable Diffusion local falhou ({exc.__class__.__name__}); caindo no fallback remoto.")
            return None

    def _init_gemini(self) -> None:
        try:
            from google import genai  # type: ignore

            key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if key:
                self._gemini = genai.Client(api_key=key)
        except Exception as exc:  # pragma: no cover - opcional
            self.log(f"[EBOOK] Gemini indisponivel: {exc}")
            self._gemini = None

    def _pollinations(self, prompt: str, width: int, height: int, seed: int) -> bytes:
        base = "https://image.pollinations.ai/prompt/"
        q = urllib.parse.quote(prompt)
        url = (
            f"{base}{q}?width={width}&height={height}&seed={seed}"
            f"&nologo=true&model={self.poll_model}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()

    def _gemini_image(self, prompt: str) -> Optional[bytes]:
        if not self._gemini:
            return None
        try:
            from google.genai import types  # type: ignore

            r = self._gemini.models.generate_content(
                model=os.getenv("ATLAS_EBOOK_GEMINI_MODEL", "gemini-2.5-flash-image"),
                contents=prompt,
                config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
            )
            for c in (r.candidates or []):
                for p in (c.content.parts or []):
                    data = getattr(getattr(p, "inline_data", None), "data", None)
                    if data:
                        return data
        except Exception as exc:
            self.log(f"[EBOOK] Gemini image falhou ({exc.__class__.__name__}), usando Pollinations.")
        return None

    def generate(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1320,
        seed: Optional[int] = None,
    ) -> Optional[Image.Image]:
        seed = seed if seed is not None else random.randint(1, 10_000_000)
        # Ordem: Stable Diffusion LOCAL (GPU dedicada, se configurado e de pe)
        # -> Gemini (se habilitado) -> Pollinations (fallback remoto, sempre
        # disponivel). O local so entra quando ATLAS_LOCAL_SD_URL aponta para
        # um servidor de verdade (ex.: no Dell G15); nesta maquina cai direto
        # no Pollinations, sem qualquer mudanca de comportamento.
        local_data = self._local_sd_image(prompt, width, height, seed)
        if local_data:
            try:
                im = Image.open(io.BytesIO(local_data))
                im.load()
                return im.convert("RGB")
            except Exception:
                pass
        if self.use_gemini:
            data = self._gemini_image(prompt)
            if data:
                try:
                    im = Image.open(io.BytesIO(data))
                    im.load()
                    return im.convert("RGB")
                except Exception:
                    pass
        for attempt in range(1, self.tries + 1):
            try:
                data = self._pollinations(prompt, width, height, seed + attempt - 1)
                im = Image.open(io.BytesIO(data))
                im.load()
                return im.convert("RGB")
            except Exception as exc:
                msg = str(exc)
                is_429 = "429" in msg or "Too Many" in msg
                self.log(f"[EBOOK] Imagem tentativa {attempt}/{self.tries} falhou: {exc}")
                if attempt < self.tries:
                    # 429 = limite temporario do provedor: espera bem mais para a
                    # janela liberar, senao caimos em quadros pretos.
                    time.sleep(min(30.0, 7.0 * attempt) if is_429 else 1.5 * attempt)
        return None


def _to_lineart(img: Image.Image, threshold: int = 165) -> Image.Image:
    """Fallback simples (sem OpenCV): limiar direto para preto-e-branco."""
    g = img.convert("L")
    g = ImageOps.autocontrast(g, cutoff=1)
    bw = g.point(lambda p: 255 if p > threshold else 0)
    return bw.convert("RGB")


def _despeckle(bw: "np.ndarray", min_area: int) -> "np.ndarray":
    """Remove manchinhas pretas isoladas (ruido de canto), preservando tracos."""
    inv = 255 - bw
    n, lab, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=8)
    keep = np.zeros_like(inv)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[lab == i] = 255
    return 255 - keep


def _photo_to_lineart(img: Image.Image, detail: str = "kids") -> Image.Image:
    """Converte um render em line-art de colorir de ALTA DEFINICAO.

    Segredo da qualidade: AMPLIA a fonte para ~2400px ANTES de extrair o traco,
    entao o limiar adaptativo produz linhas suaves e nitidas em alta resolucao
    (em vez de serrilhado ao ampliar depois). 'kids' = traco bold e limpo;
    'adult' = mais detalhe (mandalas/floral).
    """
    if cv2 is None or np is None:
        return _to_lineart(img)
    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]
    target = _env_int("ATLAS_EBOOK_LINEART_PX", 2400)
    scale = target / max(h, w)
    if scale > 1.0:
        arr = cv2.resize(arr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 90, 90)  # achata sombra/textura, preserva bordas
    if detail == "adult":
        block, c, min_area, thicken = 23, 9, 90, 0
    else:
        block, c, min_area, thicken = 41, 11, 140, 1
    edges = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, block, c)
    edges = cv2.medianBlur(edges, 3)
    edges = _despeckle(edges, min_area)
    if thicken:
        black = cv2.dilate(255 - edges, np.ones((3, 3), np.uint8), iterations=1)
        edges = 255 - black
    return Image.fromarray(edges).convert("RGB")


def _upscale(img: Image.Image, target_long: int, sharpen: bool = False) -> Image.Image:
    w, h = img.size
    if max(w, h) < target_long:
        scale = target_long / max(w, h)
        size = (int(w * scale), int(h * scale))
        if cv2 is not None and np is not None:
            arr = cv2.resize(np.array(img.convert("RGB")), size, interpolation=cv2.INTER_CUBIC)
            img = Image.fromarray(arr)
        else:
            img = img.resize(size, Image.LANCZOS)
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=2))
    return img


def _fill(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    tw, th = size
    r = max(tw / img.width, th / img.height)
    im = img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))), Image.LANCZOS)
    x = (im.width - tw) // 2
    y = (im.height - th) // 2
    return im.crop((x, y, x + tw, y + th))


# ---------------------------------------------------------------------------
# Helpers de pagina (Pillow)
# ---------------------------------------------------------------------------
def _new_page(color: str = "white") -> Image.Image:
    return Image.new("RGB", PAGE_PX, color)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_centered_block(
    page: Image.Image,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    y: int,
    fill: str = "black",
    line_gap: int = 18,
) -> int:
    draw = ImageDraw.Draw(page)
    for ln in lines:
        w = draw.textlength(ln, font=font)
        draw.text(((PAGE_PX[0] - w) / 2, y), ln, font=font, fill=fill)
        y += (font.size + line_gap)
    return y


def _paste_fit(page: Image.Image, img: Image.Image, margin: int = MARGIN, top: int = MARGIN) -> None:
    max_w = PAGE_PX[0] - 2 * margin
    max_h = PAGE_PX[1] - top - margin
    ratio = min(max_w / img.width, max_h / img.height)
    new = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))), Image.LANCZOS)
    x = (PAGE_PX[0] - new.width) // 2
    y = top + (max_h - new.height) // 2
    page.paste(new, (x, y))


def _footer(page: Image.Image, text: str, page_no: Optional[int] = None) -> None:
    draw = ImageDraw.Draw(page)
    font = _font(34)
    draw.text((MARGIN, PAGE_PX[1] - int(0.42 * DPI)), text, font=font, fill=(150, 150, 150))
    if page_no is not None:
        s = str(page_no)
        w = draw.textlength(s, font=font)
        draw.text((PAGE_PX[0] - MARGIN - w, PAGE_PX[1] - int(0.42 * DPI)), s, font=font, fill=(150, 150, 150))


# ---------------------------------------------------------------------------
# Paginas padrao (titulo, "pertence a", selo de IA)
# ---------------------------------------------------------------------------
def _title_page(title: str, subtitle: str, author: str) -> Image.Image:
    page = _new_page()
    draw = ImageDraw.Draw(page)
    tfont = _font(120, bold=True, family="georgia")
    lines = _wrap(draw, title, tfont, PAGE_PX[0] - 2 * MARGIN)
    y = _draw_centered_block(page, lines, tfont, int(2.6 * DPI))
    if subtitle:
        sfont = _font(58, family="georgia")
        y = _draw_centered_block(page, _wrap(draw, subtitle, sfont, PAGE_PX[0] - 2 * MARGIN), sfont, y + 40, fill=(90, 90, 90))
    afont = _font(48)
    _draw_centered_block(page, [author], afont, PAGE_PX[1] - int(2.0 * DPI), fill=(120, 120, 120))
    return page


def _belongs_page(lang: str) -> Image.Image:
    page = _new_page()
    draw = ImageDraw.Draw(page)
    font = _font(70, bold=True, family="comic")
    label = _L[f"belongs_{lang}"]
    w = draw.textlength(label, font=font)
    draw.text(((PAGE_PX[0] - w) / 2, int(3.2 * DPI)), label, font=font, fill="black")
    ly = int(4.4 * DPI)
    draw.line([(MARGIN + 200, ly), (PAGE_PX[0] - MARGIN - 200, ly)], fill=(120, 120, 120), width=5)
    return page


def _ai_disclosure_page(lang: str) -> Image.Image:
    page = _new_page()
    draw = ImageDraw.Draw(page)
    tfont = _font(60, bold=True, family="georgia")
    title = _L[f"ai_title_{lang}"]
    w = draw.textlength(title, font=tfont)
    draw.text(((PAGE_PX[0] - w) / 2, int(2.4 * DPI)), title, font=tfont, fill="black")
    bfont = _font(46, family="georgia")
    lines = _wrap(draw, AI_DISCLOSURE[lang], bfont, PAGE_PX[0] - 2 * MARGIN - 200)
    _draw_centered_block(page, lines, bfont, int(3.3 * DPI), fill=(60, 60, 60), line_gap=22)
    _draw_centered_block(page, [f"(c) {BRAND}"], _font(38), PAGE_PX[1] - int(2.0 * DPI), fill=(150, 150, 150))
    return page


# ---------------------------------------------------------------------------
# Capa
# ---------------------------------------------------------------------------
def _cover(title: str, subtitle: str, author: str, illustration: Optional[Image.Image]) -> Image.Image:
    page = _new_page((245, 241, 232))
    if illustration is not None:
        art = _fill(_upscale(illustration.convert("RGB"), PAGE_PX[0], sharpen=True), PAGE_PX)
        page.paste(art, (0, 0))
        overlay = Image.new("RGBA", PAGE_PX, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle([(0, 0), (PAGE_PX[0], int(2.05 * DPI))], fill=(20, 28, 46, 190))
        od.rectangle([(0, int(PAGE_PX[1] - 1.5 * DPI)), (PAGE_PX[0], PAGE_PX[1])], fill=(20, 28, 46, 190))
        page = Image.alpha_composite(page.convert("RGBA"), overlay).convert("RGB")
    else:
        d = ImageDraw.Draw(page)
        d.rectangle([(0, 0), (PAGE_PX[0], int(2.05 * DPI))], fill=(20, 28, 46))
        d.rectangle([(0, int(PAGE_PX[1] - 1.5 * DPI)), (PAGE_PX[0], PAGE_PX[1])], fill=(20, 28, 46))
    draw = ImageDraw.Draw(page)
    tfont = _font(122, bold=True, family="georgia")
    y = int(0.4 * DPI)
    for ln in _wrap(draw, title, tfont, PAGE_PX[0] - 2 * MARGIN)[:3]:
        w = draw.textlength(ln, font=tfont)
        draw.text(((PAGE_PX[0] - w) / 2, y), ln, font=tfont, fill="white")
        y += tfont.size + 10
    if subtitle:
        sfont = _font(52, bold=True, family="georgia")
        sy = int(PAGE_PX[1] - 1.32 * DPI)
        for ln in _wrap(draw, subtitle, sfont, PAGE_PX[0] - 2 * MARGIN)[:2]:
            w = draw.textlength(ln, font=sfont)
            draw.text(((PAGE_PX[0] - w) / 2, sy), ln, font=sfont, fill=(235, 235, 235))
            sy += sfont.size + 8
    afont = _font(46, family="georgia")
    w = draw.textlength(author, font=afont)
    draw.text(((PAGE_PX[0] - w) / 2, int(PAGE_PX[1] - 0.6 * DPI)), author, font=afont, fill=(210, 210, 210))
    return page


# ---------------------------------------------------------------------------
# Gerador de labirintos (atividades) - desenho vetorial, alta qualidade
# ---------------------------------------------------------------------------
def _maze_page(cols: int, rows: int, lang: str, index: int) -> Image.Image:
    page = _new_page()
    draw = ImageDraw.Draw(page)
    tfont = _font(70, bold=True, family="comic")
    label = f"{_L[f'maze_{lang}']} {index}"
    draw.text((MARGIN, int(0.55 * DPI)), label, font=tfont, fill="black")

    # area do labirinto
    top = int(1.7 * DPI)
    size = PAGE_PX[0] - 2 * MARGIN
    cell = size // cols
    grid_h = cell * rows
    ox, oy = MARGIN, top

    # recursive backtracker
    walls_v = [[True] * (cols + 1) for _ in range(rows)]
    walls_h = [[True] * cols for _ in range(rows + 1)]
    visited = [[False] * cols for _ in range(rows)]
    stack = [(0, 0)]
    visited[0][0] = True
    while stack:
        cx, cy = stack[-1]
        nb = []
        if cx > 0 and not visited[cy][cx - 1]:
            nb.append(("L", cx - 1, cy))
        if cx < cols - 1 and not visited[cy][cx + 1]:
            nb.append(("R", cx + 1, cy))
        if cy > 0 and not visited[cy - 1][cx]:
            nb.append(("U", cx, cy - 1))
        if cy < rows - 1 and not visited[cy + 1][cx]:
            nb.append(("D", cx, cy + 1))
        if not nb:
            stack.pop()
            continue
        d, nx, ny = random.choice(nb)
        if d == "L":
            walls_v[cy][cx] = False
        elif d == "R":
            walls_v[cy][cx + 1] = False
        elif d == "U":
            walls_h[cy][cx] = False
        else:
            walls_h[cy + 1][cx] = False
        visited[ny][nx] = True
        stack.append((nx, ny))

    # entrada/saida
    walls_h[0][0] = False
    walls_h[rows][cols - 1] = False
    lw = max(4, cell // 12)
    for y in range(rows):
        for x in range(cols):
            px, py = ox + x * cell, oy + y * cell
            if walls_h[y][x]:
                draw.line([(px, py), (px + cell, py)], fill="black", width=lw)
            if walls_v[y][x]:
                draw.line([(px, py), (px, py + cell)], fill="black", width=lw)
    # borda direita e inferior
    for y in range(rows):
        if walls_v[y][cols]:
            px = ox + cols * cell
            draw.line([(px, oy + y * cell), (px, oy + (y + 1) * cell)], fill="black", width=lw)
    for x in range(cols):
        if walls_h[rows][x]:
            py = oy + rows * cell
            draw.line([(ox + x * cell, py), (ox + (x + 1) * cell, py)], fill="black", width=lw)

    sfont = _font(44, bold=True)
    draw.text((ox, oy - int(0.55 * DPI) + 10), _L[f"start_{lang}"], font=sfont, fill=(0, 140, 0))
    draw.text((ox + (cols - 1) * cell, oy + grid_h + 16), _L[f"end_{lang}"], font=sfont, fill=(200, 0, 0))
    _footer(page, BRAND, index)
    return page


# ---------------------------------------------------------------------------
# Pagina de diario de gratidao (planner) - desenho vetorial
# ---------------------------------------------------------------------------
def _gratitude_page(lang: str, page_no: int) -> Image.Image:
    page = _new_page()
    draw = ImageDraw.Draw(page)
    x0 = MARGIN
    x1 = PAGE_PX[0] - MARGIN
    tfont = _font(64, bold=True, family="georgia")
    draw.text((x0, int(0.5 * DPI)), _L[f"grat_title_{lang}"], font=tfont, fill=(38, 50, 74))
    dfont = _font(46)
    draw.text((x0, int(1.25 * DPI)), _L[f"date_{lang}"], font=dfont, fill="black")
    draw.line([(x0 + 160, int(1.25 * DPI) + 55), (x1, int(1.25 * DPI) + 55)], fill=(150, 150, 150), width=4)

    y = int(2.0 * DPI)
    lfont = _font(50, bold=True, family="georgia")
    draw.text((x0, y), _L[f"grateful_{lang}"], font=lfont, fill=(38, 50, 74))
    y += 90
    for i in range(1, 4):
        draw.text((x0, y), f"{i}.", font=dfont, fill=(120, 120, 120))
        draw.line([(x0 + 70, y + 55), (x1, y + 55)], fill=(180, 180, 180), width=3)
        y += 130

    y += 40
    draw.text((x0, y), _L[f"affirm_{lang}"], font=lfont, fill=(38, 50, 74))
    y += 90
    draw.line([(x0, y + 55), (x1, y + 55)], fill=(180, 180, 180), width=3)
    y += 170

    draw.text((x0, y), _L[f"smile_{lang}"], font=lfont, fill=(38, 50, 74))
    y += 100
    draw.rounded_rectangle([(x0, y), (x1, y + int(1.6 * DPI))], radius=30, outline=(180, 180, 180), width=4)
    y += int(1.6 * DPI) + 60

    draw.text((x0, y), _L[f"mood_{lang}"], font=lfont, fill=(38, 50, 74))
    cx = x0 + 250
    for _ in range(5):
        draw.ellipse([(cx, y - 6), (cx + 80, y + 74)], outline=(150, 150, 150), width=4)
        cx += 130
    _footer(page, BRAND, page_no)
    return page


# ---------------------------------------------------------------------------
# Meal planner + Receitas (novos nichos)
# ---------------------------------------------------------------------------
def _meal_planner_page(lang: str, week_no: int) -> Image.Image:
    page = _new_page()
    draw = ImageDraw.Draw(page)
    x0, x1 = MARGIN, PAGE_PX[0] - MARGIN
    tfont = _font(60, bold=True, family="georgia")
    draw.text((x0, int(0.5 * DPI)), _MP[f"title_{lang}"], font=tfont, fill=(38, 50, 74))
    dfont = _font(40)
    draw.text((x0, int(1.15 * DPI)), _MP[f"week_{lang}"], font=dfont, fill="black")
    draw.line([(x0 + int(2.0 * DPI), int(1.15 * DPI) + 52), (x1, int(1.15 * DPI) + 52)], fill=(150, 150, 150), width=3)
    days, meals = _DAYS[lang], _MEALS[lang]
    top = int(1.7 * DPI)
    label_w = int(1.15 * DPI)
    grid_w = x1 - x0
    col_w = (grid_w - label_w) // len(meals)
    row_h = int(0.7 * DPI)
    head_h = int(0.42 * DPI)
    hfont = _font(30, bold=True)
    cfont = _font(30, bold=True, family="georgia")
    for j, m in enumerate(meals):
        cxp = x0 + label_w + j * col_w
        draw.rectangle([(cxp, top), (cxp + col_w, top + head_h)], fill=(38, 50, 74))
        w = draw.textlength(m, font=hfont)
        draw.text((cxp + (col_w - w) / 2, top + head_h / 2 - 20), m, font=hfont, fill="white")
    for i, day in enumerate(days):
        ry = top + head_h + i * row_h
        draw.rectangle([(x0, ry), (x0 + label_w, ry + row_h)], outline=(120, 130, 150), width=2, fill=(238, 241, 246))
        w = draw.textlength(day, font=cfont)
        draw.text((x0 + (label_w - w) / 2, ry + row_h / 2 - 20), day, font=cfont, fill=(38, 50, 74))
        for j in range(len(meals)):
            cxp = x0 + label_w + j * col_w
            draw.rectangle([(cxp, ry), (cxp + col_w, ry + row_h)], outline=(185, 190, 200), width=2)
    sy = top + head_h + len(days) * row_h + int(0.3 * DPI)
    lfont = _font(46, bold=True, family="georgia")
    draw.text((x0, sy), _MP[f"shop_{lang}"], font=lfont, fill=(38, 50, 74))
    sy += 84
    half = grid_w // 2
    for cxp in (x0, x0 + half + 20):
        yy = sy
        for _ in range(5):
            draw.ellipse([(cxp, yy + 8), (cxp + 22, yy + 30)], outline=(150, 150, 150), width=3)
            draw.line([(cxp + 42, yy + 40), (cxp + half - 40, yy + 40)], fill=(195, 195, 195), width=2)
            yy += int(0.4 * DPI)
    _footer(page, BRAND, week_no)
    return page


def _recipe_page(recipe: dict, photo: Optional[Image.Image], lang: str, page_no: int) -> Image.Image:
    page = _new_page()
    draw = ImageDraw.Draw(page)
    x0, x1 = MARGIN, PAGE_PX[0] - MARGIN
    tfont = _font(64, bold=True, family="georgia")
    ty = int(0.45 * DPI)
    for ln in _wrap(draw, str(recipe.get("title", "")), tfont, x1 - x0)[:2]:
        draw.text((x0, ty), ln, font=tfont, fill=(38, 50, 74))
        ty += tfont.size + 6
    py = ty + 20
    ph_h = int(2.9 * DPI)
    if photo is not None:
        page.paste(_fill(_upscale(photo.convert("RGB"), 1600, sharpen=True), (x1 - x0, ph_h)), (x0, py))
    else:
        draw.rectangle([(x0, py), (x1, py + ph_h)], fill=(235, 235, 235))
    cy = py + ph_h + 22
    chipf = _font(32, bold=True)
    chips = []
    for k in ("time", "serves", "calories"):
        v = recipe.get(k)
        if v:
            chips.append(f"{_RC[k + '_' + lang]}: {v}")
    cx = x0
    for ch in chips:
        w = draw.textlength(ch, font=chipf)
        draw.rounded_rectangle([(cx, cy), (cx + w + 46, cy + 64)], radius=16, fill=(238, 241, 246))
        draw.text((cx + 23, cy + 15), ch, font=chipf, fill=(38, 50, 74))
        cx += w + 74
    yy = cy + 100
    hfont = _font(44, bold=True, family="georgia")
    bfont = _font(33)
    draw.text((x0, yy), _RC[f"ingredients_{lang}"], font=hfont, fill=(38, 50, 74))
    yy += 66
    for ing in list(recipe.get("ingredients", []))[:12]:
        for ln in _wrap(draw, f"- {ing}", bfont, x1 - x0):
            draw.text((x0, yy), ln, font=bfont, fill=(40, 40, 40))
            yy += bfont.size + 10
    yy += 22
    draw.text((x0, yy), _RC[f"steps_{lang}"], font=hfont, fill=(38, 50, 74))
    yy += 66
    for i, st in enumerate(list(recipe.get("steps", []))[:10], 1):
        for ln in _wrap(draw, f"{i}. {st}", bfont, x1 - x0):
            draw.text((x0, yy), ln, font=bfont, fill=(40, 40, 40))
            yy += bfont.size + 8
        yy += 6
        if yy > PAGE_PX[1] - int(0.7 * DPI):
            break
    _footer(page, BRAND, page_no)
    return page


# ---------------------------------------------------------------------------
# Montagem / salvamento
# ---------------------------------------------------------------------------
def _save_pdf(pages: list[Image.Image], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pages[0].save(
        path, "PDF", save_all=True, append_images=pages[1:], resolution=float(DPI)
    )


def _write_metadata(folder: str, meta: dict[str, Any]) -> None:
    with open(os.path.join(folder, "metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)


class EbookService:
    """Fabrica de ebooks (colorir / atividades / planner) em EN e PT."""

    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self.log = log or (lambda m: print(m))
        self.img = ImageGenerator(self.log)

    # ---- Colorir -------------------------------------------------------
    def build_coloring_book(
        self,
        slug: str,
        titles: dict[str, str],
        subtitles: dict[str, str],
        subjects: list[str],
        style: str,
        author: str = BRAND,
        languages: tuple[str, ...] = ("en", "pt"),
        detail: str = "kids",
    ) -> dict[str, Any]:
        self.log(f"[EBOOK] Colorir '{slug}': gerando {len(subjects)} ilustracoes...")
        art_pages: list[Image.Image] = []
        cover_art: Optional[Image.Image] = None
        for i, subj in enumerate(subjects, 1):
            prompt = (
                f"detailed black and white line drawing of {subj}, {style}, children's "
                "coloring book illustration, clear bold black outlines, white background, "
                "medium detail, ink line art, no color, no text"
            )
            im = self.img.generate(prompt)
            page = _new_page()
            if im is not None:
                _paste_fit(page, _photo_to_lineart(im, detail))
                if cover_art is None:
                    cover_art = self.img.generate(
                        f"children's book cover illustration, {subjects[0]}, {style}, "
                        "vibrant, playful, professional, full frame composition, no text, no border",
                    )
            else:
                d = ImageDraw.Draw(page)
                d.rectangle([(MARGIN, MARGIN), (PAGE_PX[0] - MARGIN, PAGE_PX[1] - MARGIN)], outline=(200, 200, 200), width=6)
                _draw_centered_block(page, [subj], _font(70, family="comic"), int(PAGE_PX[1] / 2), fill=(180, 180, 180))
            _footer(page, BRAND, i)
            art_pages.append(page)
            self.log(f"[EBOOK]   pagina {i}/{len(subjects)} ok")
        return self._emit(slug, "coloring", titles, subtitles, author, subjects, art_pages, cover_art, languages, style)

    # ---- Atividades (labirintos) --------------------------------------
    def build_maze_book(
        self,
        slug: str,
        titles: dict[str, str],
        subtitles: dict[str, str],
        count: int = 12,
        author: str = BRAND,
        languages: tuple[str, ...] = ("en", "pt"),
    ) -> dict[str, Any]:
        self.log(f"[EBOOK] Labirintos '{slug}': desenhando {count} paginas...")
        folder_meta = {"kind": "activity-maze", "pages": count}
        results: dict[str, str] = {}
        base_folder = os.path.join(OUTPUT_ROOT, slug)
        cover_art = self.img.generate(
            "fun colorful kids activity book cover, cartoon maze and puzzles, playful, "
            "professional, full frame, no text, no border"
        )
        for lang in languages:
            pages = [
                _cover(titles[lang], subtitles.get(lang, ""), author, cover_art),
                _title_page(titles[lang], subtitles.get(lang, ""), author),
                _ai_disclosure_page(lang),
                _belongs_page(lang),
            ]
            for i in range(1, count + 1):
                diff = 8 + (i // 3) * 2  # dificuldade crescente
                pages.append(_maze_page(diff, int(diff * 1.3), lang, i))
            path = os.path.join(base_folder, f"{slug}__{lang}.pdf")
            _save_pdf(pages, path)
            results[lang] = path
            self.log(f"[EBOOK]   {lang.upper()} salvo: {path}")
        self._finish_meta(base_folder, slug, titles, subtitles, folder_meta, results)
        return {"folder": base_folder, "pdfs": results}

    # ---- Planner (gratidao) -------------------------------------------
    def build_gratitude_journal(
        self,
        slug: str,
        titles: dict[str, str],
        subtitles: dict[str, str],
        days: int = 30,
        author: str = BRAND,
        languages: tuple[str, ...] = ("en", "pt"),
    ) -> dict[str, Any]:
        self.log(f"[EBOOK] Diario de gratidao '{slug}': {days} paginas...")
        base_folder = os.path.join(OUTPUT_ROOT, slug)
        cover_art = self.img.generate(
            "beautiful minimalist gratitude journal cover, soft watercolor flowers, "
            "calm elegant, lots of white space, professional, full frame, no text, no border"
        )
        results: dict[str, str] = {}
        for lang in languages:
            pages = [
                _cover(titles[lang], subtitles.get(lang, ""), author, cover_art),
                _title_page(titles[lang], subtitles.get(lang, ""), author),
                _ai_disclosure_page(lang),
                _belongs_page(lang),
            ]
            for d in range(1, days + 1):
                pages.append(_gratitude_page(lang, d))
            path = os.path.join(base_folder, f"{slug}__{lang}.pdf")
            _save_pdf(pages, path)
            results[lang] = path
            self.log(f"[EBOOK]   {lang.upper()} salvo: {path}")
        self._finish_meta(base_folder, slug, titles, subtitles, {"kind": "planner-gratitude", "pages": days}, results)
        return {"folder": base_folder, "pdfs": results}

    # ---- Meal planner --------------------------------------------------
    def build_meal_planner(
        self,
        slug: str,
        titles: dict[str, str],
        subtitles: dict[str, str],
        weeks: int = 13,
        author: str = BRAND,
        languages: tuple[str, ...] = ("en", "pt"),
    ) -> dict[str, Any]:
        self.log(f"[EBOOK] Meal planner '{slug}': {weeks} semanas...")
        base_folder = os.path.join(OUTPUT_ROOT, slug)
        cover_art = self.img.generate(
            "beautiful meal planner cookbook cover, fresh healthy food flat lay with "
            "vegetables and fruits, clean modern, professional, full frame, no text, no border"
        )
        results: dict[str, str] = {}
        for lang in languages:
            pages = [
                _cover(titles[lang], subtitles.get(lang, ""), author, cover_art),
                _title_page(titles[lang], subtitles.get(lang, ""), author),
                _ai_disclosure_page(lang),
                _belongs_page(lang),
            ]
            for wk in range(1, weeks + 1):
                pages.append(_meal_planner_page(lang, wk))
            path = os.path.join(base_folder, f"{slug}__{lang}.pdf")
            _save_pdf(pages, path)
            results[lang] = path
            self.log(f"[EBOOK]   {lang.upper()} salvo: {path}")
        if cover_art is not None:
            os.makedirs(base_folder, exist_ok=True)
            cover_art.convert("RGB").save(os.path.join(base_folder, "cover_source.png"))
        self._finish_meta(base_folder, slug, titles, subtitles, {"kind": "planner-meal", "pages": weeks}, results)
        return {"folder": base_folder, "pdfs": results}

    # ---- Receitas (texto por IA + fotos) ------------------------------
    def _ai_recipes(self, n: int, theme: str, lang: str) -> list[dict]:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            return []
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
        lang_name = "Brazilian Portuguese" if lang == "pt" else "English"
        prompt = (
            f"Create {n} easy {theme} recipes written in {lang_name}. "
            "Return STRICT JSON only, no markdown: "
            '{"recipes":[{"title":"...","time":"...","serves":"...","calories":"...",'
            '"ingredients":["..."],"steps":["..."]}]}. '
            "Each recipe: 6-10 ingredients and 4-7 short numbered steps. All recipes distinct."
        )
        for attempt in range(1, 4):
            try:
                resp = client.chat.completions.create(
                    model=os.getenv("ATLAS_EBOOK_TEXT_MODEL", "openai/gpt-oss-120b"),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=4000,
                    response_format={"type": "json_object"},
                )
                data = json.loads(resp.choices[0].message.content or "{}")
                out = [r for r in data.get("recipes", []) if r.get("title")]
                if out:
                    self.log(f"[EBOOK] IA gerou {len(out)} receitas ({theme}/{lang}).")
                    return out[:n]
            except Exception as exc:
                self.log(f"[EBOOK] IA receitas tentativa {attempt}/3 falhou ({exc.__class__.__name__}).")
                time.sleep(8 * attempt)
        return []

    def _generate_recipes(self, n: int, theme: str, lang: str) -> list[dict]:
        recipes = self._ai_recipes(n, theme, lang)
        if recipes:
            return recipes
        base = _FALLBACK_RECIPES.get(lang, _FALLBACK_RECIPES["en"])
        self.log(f"[EBOOK] Usando {len(base)} receitas curadas (fallback) para {lang}.")
        return [dict(base[i % len(base)]) for i in range(n)]

    def build_recipe_book(
        self,
        slug: str,
        titles: dict[str, str],
        subtitles: dict[str, str],
        theme: str = "air fryer",
        count: int = 12,
        author: str = BRAND,
        languages: tuple[str, ...] = ("en", "pt"),
    ) -> dict[str, Any]:
        self.log(f"[EBOOK] Receitas '{slug}': {count} receitas ({theme})...")
        base_folder = os.path.join(OUTPUT_ROOT, slug)
        cover_art = self.img.generate(
            f"professional cookbook cover, {theme} dish beautifully plated, fresh ingredients, "
            "modern clean food photography, full frame, no text, no border"
        )
        results: dict[str, str] = {}
        preview_saved = False
        for lang in languages:
            recipes = self._generate_recipes(count, theme, lang)
            pages = [
                _cover(titles[lang], subtitles.get(lang, ""), author, cover_art),
                _title_page(titles[lang], subtitles.get(lang, ""), author),
                _ai_disclosure_page(lang),
                _belongs_page(lang),
            ]
            for i, rc in enumerate(recipes, 1):
                photo = self.img.generate(
                    f"professional food photography of {rc.get('title', 'a dish')}, {theme}, "
                    "top view on a plate, appetizing, natural light, magazine style, high detail"
                )
                pages.append(_recipe_page(rc, photo, lang, i))
                if not preview_saved and photo is not None:
                    os.makedirs(base_folder, exist_ok=True)
                    _recipe_page(rc, photo, lang, i).save(os.path.join(base_folder, "preview_page.png"))
                    preview_saved = True
                self.log(f"[EBOOK]   receita {i}/{count} ({lang}) ok")
            path = os.path.join(base_folder, f"{slug}__{lang}.pdf")
            _save_pdf(pages, path)
            results[lang] = path
            self.log(f"[EBOOK]   {lang.upper()} salvo: {path}")
        if cover_art is not None:
            os.makedirs(base_folder, exist_ok=True)
            cover_art.convert("RGB").save(os.path.join(base_folder, "cover_source.png"))
        self._finish_meta(base_folder, slug, titles, subtitles, {"kind": "cookbook", "pages": count, "theme": theme}, results)
        return {"folder": base_folder, "pdfs": results}

    # ---- interno -------------------------------------------------------
    def _emit(self, slug, kind, titles, subtitles, author, subjects, art_pages, cover_art, languages, style):
        base_folder = os.path.join(OUTPUT_ROOT, slug)
        results: dict[str, str] = {}
        for lang in languages:
            pages = [
                _cover(titles[lang], subtitles.get(lang, ""), author, cover_art),
                _title_page(titles[lang], subtitles.get(lang, ""), author),
                _ai_disclosure_page(lang),
                _belongs_page(lang),
            ]
            pages.extend(p.copy() for p in art_pages)
            path = os.path.join(base_folder, f"{slug}__{lang}.pdf")
            _save_pdf(pages, path)
            results[lang] = path
            self.log(f"[EBOOK]   {lang.upper()} salvo: {path}")
        if art_pages:
            art_pages[0].save(os.path.join(base_folder, "preview_page.png"))
        if cover_art is not None:
            cover_art.convert("RGB").save(os.path.join(base_folder, "cover_source.png"))
        self._finish_meta(
            base_folder, slug, titles, subtitles,
            {"kind": kind, "pages": len(art_pages), "style": style, "subjects": subjects},
            results,
        )
        return {"folder": base_folder, "pdfs": results}

    def _finish_meta(self, folder, slug, titles, subtitles, extra, results):
        os.makedirs(folder, exist_ok=True)
        meta = {
            "slug": slug,
            "brand": BRAND,
            "titles": titles,
            "subtitles": subtitles,
            "languages": list(results.keys()),
            "pdfs": {k: os.path.basename(v) for k, v in results.items()},
            "trim_size": "8.5x11in",
            "dpi": DPI,
            "ai_generated": True,
            "ai_disclosure": AI_DISCLOSURE,
            "kdp_note": (
                "Ao publicar na Amazon KDP responda 'Yes' na pergunta de conteudo "
                "gerado por IA e marque Texto/Imagens conforme aplicavel."
            ),
            "suggested_price_usd": "9.99-14.99",
            "suggested_price_brl": "34.90-59.90",
            **extra,
        }
        _write_metadata(folder, meta)
        self.log(f"[EBOOK] metadata.json salvo em {folder}")
