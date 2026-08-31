"""
ATLAS - Servico de historias diarias (reels de trending).

Gera N historias curtas por lote (botao "Criar"), no MESMO estilo visual (para o
publico voltar), genero terror ou policial, narradas, em video vertical 9:16 com
imagens em ALTA DEFINICAO e legendas. Guarda um indice para NAO repetir historia.

Independente do pipeline de video de reels de afiliado; produz os MP4 em
C:\\atlas-os\\stories\\ marcados como prioridade (devem subir primeiro).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from typing import Any, Callable, Optional

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

# Aponta o moviepy para o ffmpeg embutido (nao depende de PATH).
try:
    import imageio_ffmpeg
    os.environ.setdefault("IMAGEIO_FFMPEG_EXE", imageio_ffmpeg.get_ffmpeg_exe())
except Exception:
    pass

from app.services.ebook_service import ImageGenerator, _fill, _upscale, _font  # reuso

STORY_ROOT = os.getenv("ATLAS_STORY_OUTPUT", r"C:\atlas-os\stories")
INDEX_PATH = os.path.join(STORY_ROOT, "_index.json")
BRAND = os.getenv("ATLAS_STORY_BRAND", "ATLAS")

W, H = 1080, 1920  # vertical 9:16

# Series: mesmo estilo visual sempre (o publico volta pelo estilo).
SERIES = {
    "horror": {
        "brand_en": "Urban Legends", "brand_pt": "Lendas Urbanas",
        "style": ("dark cinematic horror photography, photorealistic, eerie atmospheric, "
                  "moody dramatic lighting, fog, film grain, ominous, highly detailed, 9:16"),
        "hashtags": "#horrorstories #scarystories #terrifyingtales #urbanlegend #creepy #horror",
    },
    "crime": {
        "brand_en": "Case Files", "brand_pt": "Arquivos Secretos",
        "style": ("dark cinematic true-crime photography, photorealistic, noir mood, "
                  "dramatic lighting, rain, moody city night, film grain, highly detailed, 9:16"),
        "hashtags": "#truecrime #mystery #detective #crimestories #unsolved",
    },
}

# Vozes Fish (fish.audio), unica fonte de narracao (sem fallback para outro
# provedor). Override por env: ATLAS_FISH_HORROR_EN/_PT, ATLAS_FISH_CRIME_EN/_PT,
# ou (por ultimo, se nao houver padrao para o genero) FISH_VOICE_US_MALE/BR_MALE.
#
# Terror e Policial usam DE PROPOSITO a MESMA voz (escolha do usuario: um
# narrador unico para as duas series). Os valores abaixo sao so o FALLBACK
# do codigo - o .env normalmente ja define ATLAS_FISH_HORROR_EN/_PT e
# ATLAS_FISH_CRIME_EN/_PT com os MESMOS ids, que tem prioridade sobre isto.
_FISH_DEFAULTS = {
    "horror": {"en": "98544e744e754814a6aa22229f63f475", "pt": "20367c93ce394b22b740449f1f65cc6d"},
    "crime": {"en": "98544e744e754814a6aa22229f63f475", "pt": "20367c93ce394b22b740449f1f65cc6d"},
}


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text or "story")[:60]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def _hash(text: str) -> str:
    return hashlib.sha1(_norm(text).encode()).hexdigest()[:16]


def _extract_json(text: str) -> dict:
    """Extrai o objeto JSON de uma resposta de LLM (tolera markdown e reasoning)."""
    if not text:
        return {}
    t = text.strip()
    if "```" in t:
        t = re.sub(r"```[a-zA-Z]*", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    a, b = t.find("{"), t.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(t[a:b + 1])
        except Exception:
            return {}
    return {}


def load_index() -> list[dict]:
    try:
        with open(INDEX_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


def _save_index(items: list[dict]) -> None:
    os.makedirs(STORY_ROOT, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)


_VIGNETTE = None


def _vignette():
    """Multiplicador de brilho (H,W,1): escurece as bordas (clima de terror)."""
    global _VIGNETTE
    if _VIGNETTE is None:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        _VIGNETTE = (1.0 - np.clip((r - 0.6) * 0.8, 0.0, 0.55))[..., None]
    return _VIGNETTE


class StoryService:
    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self.log = log or (lambda m: print(m))
        self.img = ImageGenerator(self.log)

    # ---------- roteiro (IA, bilingue, sem repetir) ----------
    def _ai_script(self, genre: str, avoid: list[str], scenes: int) -> Optional[dict]:
        from openai import OpenAI

        from app.services.ai_providers import build_extra_providers

        # Rodizio de IA: cada provedor tem cota propria; quando um esgota, cai no
        # proximo -> nunca trava. Basta ter a chave no .env. Ordem: Nemotron
        # (OpenRouter) -> Groq -> Gemini -> demais provedores com chave.
        want_json = os.getenv("ATLAS_STORY_JSON_FORMAT", "0").strip().lower() in ("1", "true", "yes", "on", "sim")
        providers: list = []  # (rotulo, modelo, client, usa_json)
        or_key = os.getenv("OPENROUTER_API_KEY")
        if or_key:
            providers.append((
                "openrouter", os.getenv("ATLAS_STORY_TEXT_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"),
                OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1"), want_json,
            ))
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            providers.append((
                "groq", os.getenv("ATLAS_STORY_TEXT_MODEL_GROQ", "openai/gpt-oss-120b"),
                OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1"), True,
            ))
        gem_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if gem_key:
            providers.append((
                "gemini", os.getenv("ATLAS_STORY_TEXT_MODEL_GEMINI", "gemini-2.0-flash"),
                OpenAI(api_key=gem_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/"), False,
            ))
        try:
            for p in build_extra_providers("STORY"):
                if p["models"]:
                    providers.append((p["label"].lower(), p["models"][0], p["client"], False))
        except Exception:  # noqa: BLE001
            pass
        if not providers:
            return None

        avoid_txt = "; ".join(avoid[-40:]) if avoid else "none"
        if genre == "horror":
            style_note = (
                "Write it like a viral horror-shorts channel that retells URBAN LEGENDS and true "
                "scary stories with ominous documentary narration. Invent an ORIGINAL urban legend "
                "or creepy tale. The title must look like a legend, e.g. 'The Bunny Man | Urban "
                "Legend' or 'The Hollow Man'. Narration: ominous, immersive, building dread; scene 1 "
                "is a chilling hook and the ending leaves the viewer unsettled (a warning or "
                "unresolved dread). Image prompts: dark, photorealistic, cinematic horror scenes "
                "(the location, a shadowy figure, the victim) - absolutely no cartoons."
            )
        else:
            style_note = (
                "Write it like a true-crime / detective mystery shorts channel: ominous narration, a "
                "gripping hook, escalating clues and a twist or unresolved ending. Image prompts: "
                "dark cinematic noir crime scenes, photorealistic."
            )
        prompt = (
            f"Create ONE original short-video story with {scenes} scenes, in BOTH English and "
            "Brazilian Portuguese. " + style_note + " "
            "Return STRICT JSON only, no markdown: "
            '{"title_en":"...","title_pt":"...","scenes":[{"image_prompt":"english visual '
            'description, no text","narration_en":"1-2 punchy sentences","narration_pt":"1-2 '
            'frases de impacto","caption_en":"short on-screen caption","caption_pt":"legenda curta"}]}. '
            f"Make it DISTINCT from these already-used titles: {avoid_txt}. "
            "Self-contained, original, no copyrighted characters or real named people."
        )
        for label, model, client, use_json in providers:
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.9,
                    "max_tokens": 8000,
                }
                if use_json:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = client.chat.completions.create(**kwargs)
                data = _extract_json(resp.choices[0].message.content or "")
                if data.get("title_en") and data.get("scenes"):
                    self.log(f"[STORY] roteiro por {label} ({model})")
                    return data
                self.log(f"[STORY] {label} devolveu roteiro invalido; proximo.")
            except Exception as exc:  # noqa: BLE001
                self.log(f"[STORY] IA roteiro {label} falhou ({exc.__class__.__name__}); proximo.")
        return None

    def _fallback_script(self, genre: str, seed: int, scenes: int) -> dict:
        if genre == "horror":
            titles = [
                ("The Hollow Man | Urban Legend", "O Homem Oco | Lenda Urbana"),
                ("Room {n} | Urban Legend", "Quarto {n} | Lenda Urbana"),
                ("The Night Clerk | Urban Legend", "O Porteiro da Noite | Lenda Urbana"),
            ]
            beats = [
                ("a dark empty hotel corridor at night, flickering light", "It started the night I checked into room {n}.", "Comecou na noite em que entrei no quarto {n}."),
                ("a hotel clerk's shadowed face behind an old front desk", "The clerk warned me: never open the door after midnight.", "O porteiro me avisou: nunca abra a porta depois da meia-noite."),
                ("an old rotary phone glowing faintly in the dark", "At 3 a.m. the phone rang. Only slow breathing answered.", "As tres da manha o telefone tocou. So uma respiracao lenta respondeu."),
                ("a mirror with a tall hollow-eyed figure standing behind", "In the mirror, a tall hollow-eyed man stood behind me.", "No espelho, um homem alto de olhos vazios estava atras de mim."),
                ("a door slowly opening to pure darkness", "I spun around. The room was empty.", "Me virei num salto. O quarto estava vazio."),
                ("a long human shadow stretching across a wall by itself", "But his shadow stayed on the wall, watching me.", "Mas a sombra dele ficou na parede, me observando."),
                ("wet dark footprints leading across a hotel carpet", "Wet footprints led from the mirror to my bed.", "Pegadas molhadas iam do espelho ate a minha cama."),
                ("heavy curtains moving with no wind, window sealed shut", "The curtains moved, though every window was sealed.", "As cortinas se mexiam, mesmo com todas as janelas lacradas."),
                ("an old yellowed hotel guestbook open on a desk", "In the guestbook, my name was already written, dated 1962.", "No livro de hospedes, meu nome ja estava escrito, com data de 1962."),
                ("a dying red EXIT sign flickering in a long hallway", "Every light I passed died the moment I looked away.", "Cada luz que eu passava se apagava assim que eu desviava o olhar."),
                ("an old elevator opening by itself, dim yellow light", "The elevator opened on its own and began going down.", "O elevador abriu sozinho e comecou a descer."),
                ("a cold concrete basement boiler room, one bare bulb", "It took me to a floor that should not exist.", "Ele me levou a um andar que nao deveria existir."),
                ("hundreds of old brass room keys hanging on a wall", "Hundreds of keys hung there, every one for room {n}.", "Centenas de chaves penduradas, todas do quarto {n}."),
                ("a faded portrait of a gaunt hollow-eyed man", "A portrait showed him, the last guest who never left.", "Um retrato o mostrava, o ultimo hospede que nunca foi embora."),
                ("extreme close up of a pale mouth whispering in shadow", "You checked in, he whispered. No one checks out.", "Voce entrou, ele sussurrou. Ninguem sai daqui."),
                ("a person running down an endless identical corridor", "I ran, but every single door was numbered {n}.", "Eu corri, mas cada porta tinha o numero {n}."),
                ("pale hands sliding out from cracks in the walls", "Pale hollow hands slid out from the walls.", "Maos palidas e vazias sairam de dentro das paredes."),
                ("an empty hotel lobby with the front doors bricked shut", "I reached the lobby. The doors were bricked shut.", "Cheguei ao saguao. As portas estavam muradas."),
                ("the night clerk turning to reveal hollow black eyes", "The clerk turned to me. His eyes were hollow too.", "O porteiro se virou para mim. Os olhos dele tambem eram vazios."),
                ("a grand old hotel at night, a single window lit", "Pass that hotel at night and count the windows. If one is lit, room {n} is waiting for you.", "Passe por aquele hotel a noite e conte as janelas. Se uma estiver acesa, o quarto {n} espera por voce."),
            ]
        else:
            titles = [
                ("Case File {n} | Unsolved", "Arquivo {n} | Sem Solucao"),
                ("The Music Box | Case Files", "A Caixa de Musica | Arquivos Secretos"),
                ("The Last Name | Case Files", "O Ultimo Nome | Arquivos Secretos"),
            ]
            beats = [
                ("a rainy city street at night, red and blue police lights", "The call came in at 3 a.m.", "A ligacao chegou as tres da manha."),
                ("a detective staring at a cluttered crime board", "No fingerprints. No witnesses. No body.", "Sem digitais. Sem testemunhas. Sem corpo."),
                ("a dark alley with a child's music box on the wet ground", "Only one thing was left behind: a child's music box.", "So uma coisa foi deixada para tras: uma caixa de musica de crianca."),
                ("a suspect's silhouette under a flickering streetlight", "Everyone had an alibi. One of them was lying.", "Todos tinham alibi. Um deles estava mentindo."),
                ("an old photograph lying on a wooden desk", "One single photograph changed everything.", "Uma unica foto mudou tudo."),
                ("a rain-soaked notebook with a list of five names", "The victim's notebook held five names. Four were already dead.", "O caderno da vitima tinha cinco nomes. Quatro ja estavam mortos."),
                ("a tense interrogation room lit by a single lamp", "The suspect only smiled and said nothing.", "O suspeito so sorriu e nao disse nada."),
                ("a city map covered in red pins forming a shape", "The murders formed a shape on the map, like a key.", "Os assassinatos formavam um desenho no mapa, como uma chave."),
                ("an abandoned warehouse beside a dark river", "The last pin pointed to a warehouse by the river.", "O ultimo alfinete apontava para um galpao perto do rio."),
                ("a flashlight beam cutting through a dusty warehouse", "Inside, the music box was playing all by itself.", "La dentro, a caixa de musica tocava sozinha."),
                ("a wall covered in surveillance photos of a detective", "The wall was covered in photos of the detective himself.", "A parede estava coberta de fotos do proprio detetive."),
                ("an empty chair with rope under a hanging bulb", "Someone had been watching him for years.", "Alguem o vigiava havia anos."),
                ("a hidden basement door behind old shelves", "A door led down where the records said nothing existed.", "Uma porta descia para onde os registros diziam nao haver nada."),
                ("endless rows of dusty unsolved case boxes", "Every unsolved case in the city was hidden down there.", "Todo caso sem solucao da cidade estava escondido la embaixo."),
                ("a tarnished police badge lying in the dust", "One badge lay in the dust: his partner's, missing since 09.", "Um distintivo no chao: o do parceiro dele, sumido desde 2009."),
                ("a figure standing motionless in deep shadow", "A voice said: you finally found me, detective.", "Uma voz disse: ate que enfim me achou, detetive."),
                ("an old tape recorder playing on a metal table", "On the tape was the one man he never suspected: himself.", "Na fita estava o homem que ele nunca suspeitou: ele mesmo."),
                ("two silhouettes facing each other in the dark", "The killer knew every move, because he had trained him.", "O assassino sabia cada passo, porque tinha treinado ele."),
                ("police sirens and headlights flooding a doorway", "Backup arrived. The basement was empty again.", "O reforco chegou. O porao estava vazio de novo."),
                ("a case file folder closing under a desk lamp", "The case was closed as unsolved. But somewhere, at 3 a.m., the music box still plays.", "O caso foi arquivado sem solucao. Mas em algum lugar, as tres da manha, a caixa de musica ainda toca."),
            ]
        t_en, t_pt = titles[seed % len(titles)]
        total = len(beats)
        n = max(1, min(scenes, total))
        # Nunca repete: para N < total usa o inicio + a cena final (sensacao de historia completa).
        chosen = beats if n >= total else beats[: n - 1] + [beats[-1]]
        sc = []
        for vis, en, pt in chosen:
            sc.append({
                "image_prompt": vis,
                "narration_en": en.replace("{n}", str(seed)),
                "narration_pt": pt.replace("{n}", str(seed)),
                "caption_en": en.replace("{n}", str(seed)),
                "caption_pt": pt.replace("{n}", str(seed)),
            })
        return {"title_en": t_en.replace("{n}", str(seed)),
                "title_pt": t_pt.replace("{n}", str(seed)), "scenes": sc}

    # ---------- legenda queimada na imagem (sem ImageMagick) ----------
    def _frame_with_caption(self, base: Image.Image, caption: str, brand: str) -> Image.Image:
        frame = base.copy()
        draw = ImageDraw.Draw(frame)
        # marca da serie no topo
        bf = _font(46, bold=True, family="georgia")
        draw.text((40, 40), brand.upper(), font=bf, fill=(255, 255, 255))
        # Legenda queimada DESLIGADA por padrao (ATLAS_STORY_CAPTIONS=1 religa).
        if os.getenv("ATLAS_STORY_CAPTIONS", "").strip().lower() not in ("1", "true", "yes", "on", "sim"):
            return frame
        # caixa da legenda embaixo
        cf = _font(58, bold=True, family="arial")
        words, lines, cur = caption.split(), [], ""
        for w in words:
            if draw.textlength((cur + " " + w).strip(), font=cf) <= W - 120:
                cur = (cur + " " + w).strip()
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        lines = lines[:4]
        box_h = len(lines) * (cf.size + 16) + 50
        y0 = H - box_h - 120
        overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle([(0, y0 - 20), (W, y0 + box_h)], fill=(0, 0, 0, 150))
        frame = Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(frame)
        yy = y0
        for ln in lines:
            w = draw.textlength(ln, font=cf)
            x = (W - w) / 2
            draw.text((x, yy), ln, font=cf, fill="white", stroke_width=4, stroke_fill=(0, 0, 0))
            yy += cf.size + 16
        return frame

    # ---------- voz: SOMENTE Fish (sem fallback para outro provedor) ----------
    def _fish_voice(self, genre: str, lang: str) -> str:
        # Ordem: override especifico do genero (ATLAS_FISH_<GENERO>_<LANG>) ->
        # voz padrao da SERIE (Case Files/Urban Legends, fixada no codigo) ->
        # so por ultimo a voz generica FISH_VOICE_BR_MALE/US_MALE (usada pelo
        # pipeline de afiliados). A generica precisa vir POR ULTIMO: se ficar
        # antes do padrao da serie, qualquer genero sem override proprio no
        # .env "vaza" e usa a voz dos videos de produto por engano (foi o que
        # aconteceu com "The Midnight Ledger", genero crime, sem
        # ATLAS_FISH_CRIME_PT configurado).
        vid = os.getenv(f"ATLAS_FISH_{genre.upper()}_{lang.upper()}")
        if vid:
            return vid
        default = _FISH_DEFAULTS.get(genre, {}).get(lang, "")
        if default:
            return default
        if lang == "pt":
            return os.getenv("FISH_VOICE_BR_MALE") or ""
        return os.getenv("FISH_VOICE_US_MALE") or ""

    def _fish_tts(self, text: str, voice_id: str, path: str, tries: int = 3) -> bool:
        key = os.getenv("FISH_API_KEY")
        if not key or not voice_id:
            return False
        model = os.getenv("ATLAS_FISH_MODEL", "s2.1-pro-free")  # modelo gratis do Fish
        for attempt in range(1, tries + 1):
            try:
                r = requests.post(
                    "https://api.fish.audio/v1/tts",
                    headers={"Authorization": f"Bearer {key}", "model": model},
                    json={"text": text, "reference_id": voice_id, "format": "mp3"},
                    timeout=90,
                )
                if r.status_code == 200 and len(r.content) > 2000:
                    with open(path, "wb") as fh:
                        fh.write(r.content)
                    return True
                self._fish_note = f"Fish HTTP {r.status_code}"
            except Exception as exc:
                self._fish_note = f"Fish {exc.__class__.__name__}"
            if attempt < tries:
                time.sleep(1.5 * attempt)  # espera crescente antes de tentar de novo (falha transitoria)
        return False

    def _synth_fish(self, text: str, genre: str, lang: str, path: str) -> bool:
        """Gera a narracao usando SOMENTE o Fish Audio (sem fallback para outro
        provedor). _fish_tts ja tenta novamente sozinho (retries internos) em
        falhas transitorias; se mesmo assim falhar, quem chama decide o que
        fazer (aqui: descartar o idioma desta historia)."""
        return self._fish_tts(text, self._fish_voice(genre, lang), path)

    # ---------- movimento cinematografico (nao ficar estatico) ----------
    def _ken_burns(self, frame, d: float, idx: int):
        """Zoom lento alternado (in/out) para a cena ter vida sem IA de video."""
        from moviepy.editor import CompositeVideoClip, ImageClip

        try:
            zoom = float(os.getenv("ATLAS_STORY_ZOOM", "0.12"))
        except ValueError:
            zoom = 0.12
        clip = ImageClip(frame).set_duration(d)
        if idx % 2 == 1:
            clip = clip.resize(lambda t: 1.0 + zoom * (t / d))          # zoom in
        else:
            clip = clip.resize(lambda t: 1.0 + zoom * (1.0 - t / d))    # zoom out
        return CompositeVideoClip([clip.set_position("center")], size=(W, H)).set_duration(d)

    # ---------- atmosfera de terror (nevoa + vinheta + grao + flicker) ----------
    def _fog_clip(self, d: float):
        import cv2
        from moviepy.editor import ImageClip

        fw = int(W * 1.6)
        low = np.random.rand(max(2, H // 12), max(2, fw // 12)).astype(np.float32)
        n = cv2.resize(low, (fw, H), interpolation=cv2.INTER_CUBIC)
        n = cv2.GaussianBlur(n, (0, 0), 28)
        n = (n - n.min()) / (n.max() - n.min() + 1e-6)
        alpha = (np.clip((n - 0.58) * 1.4, 0.0, 1.0) * 0.14).astype(np.float32)
        fog = ImageClip(np.full((H, fw, 3), 205, np.uint8)).set_duration(d)
        fog = fog.set_mask(ImageClip(alpha, ismask=True).set_duration(d))
        dx = fw - W
        return fog.set_position(lambda t: (-int(dx * (t / max(d, 0.1))), 0))

    def _atmosphere(self, video):
        if os.getenv("ATLAS_STORY_FX", "1").strip().lower() in ("0", "false", "no", "off", "nao"):
            return video
        import math
        from moviepy.editor import CompositeVideoClip

        d = video.duration
        base = video
        try:
            base = CompositeVideoClip([video, self._fog_clip(d)], size=(W, H)).set_duration(d)
        except Exception as exc:  # noqa: BLE001
            self.log(f"[STORY] nevoa off ({exc.__class__.__name__})")
        vig = _vignette()

        def fx(gf, t):
            frame = gf(t).astype(np.float32)
            frame *= vig
            frame *= (1.0 + 0.045 * math.sin(t * 9.0))
            frame += np.random.randint(-9, 10, (H, W, 1)).astype(np.float32)
            return np.clip(frame, 0.0, 255.0).astype(np.uint8)

        return base.fl(fx, apply_to=[])

    # ---------- 1 historia -> videos (por idioma) ----------
    def _build_one(self, genre: str, series: dict, languages: tuple[str, ...], scenes: int,
                   avoid: list[str]) -> Optional[dict]:
        script = self._ai_script(genre, avoid, scenes)
        source = "ia"
        if not script:
            script = self._fallback_script(genre, int(time.time()) % 1000, scenes)
            source = "fallback"
        title_en = script.get("title_en", "Untitled")
        h = _hash(title_en)
        if any(it.get("hash") == h for it in load_index()):
            title_en += f" #{int(time.time()) % 97}"
            h = _hash(title_en)
        slug = _slug(title_en)
        folder = os.path.join(STORY_ROOT, slug)
        os.makedirs(folder, exist_ok=True)
        self.log(f"[STORY] '{title_en}' ({source}) - gerando {len(script['scenes'])} cenas...")

        # imagens compartilhadas entre idiomas
        base_frames = []
        for i, sc in enumerate(script["scenes"], 1):
            prompt = f"{sc.get('image_prompt', 'a dramatic scene')}, {series['style']}"
            raw = self.img.generate(prompt, width=768, height=1344)
            if raw is None:
                raw = Image.new("RGB", (W, H), (12, 14, 22))
            frame = _fill(_upscale(raw.convert("RGB"), H, sharpen=True), (W, H))
            base_frames.append(frame)
            self.log(f"[STORY]   cena {i}/{len(script['scenes'])} ok")
            if i < len(script["scenes"]):
                time.sleep(1.2)  # respiro entre imagens: evita 429 do provedor

        from moviepy.editor import (AudioFileClip, CompositeAudioClip, ImageClip,
                                    concatenate_videoclips)

        results = {}
        for lang in languages:
            brand = series[f"brand_{lang}"]
            vclips, placed_audio, t_cursor = [], [], 0.0
            voice_id = self._fish_voice(genre, lang)
            self.log(f"[STORY]   voz {lang.upper()}: fish ({voice_id or 'nao configurada'})")
            lang_failed = False
            for i, sc in enumerate(script["scenes"], 1):
                narr = sc.get(f"narration_{lang}") or sc.get("narration_en") or "..."
                cap = sc.get(f"caption_{lang}") or narr
                apath = os.path.join(folder, f"s{i}_{lang}.mp3")
                ok = False
                try:
                    ok = self._synth_fish(narr, genre, lang, apath)
                except Exception as exc:
                    self.log(f"[STORY]   Fish deu excecao na cena {i} ({lang.upper()}): {exc.__class__.__name__}")
                if not ok:
                    note = getattr(self, "_fish_note", "sem detalhe")
                    self.log(
                        f"[STORY]   Fish falhou na cena {i} ({lang.upper()}) apos as "
                        f"tentativas ({note}); descartando o idioma {lang.upper()} "
                        "desta historia (sem fallback)."
                    )
                    lang_failed = True
                    break
                aclip = AudioFileClip(apath)
                d = aclip.duration + 0.35
                frame = self._frame_with_caption(base_frames[i - 1], cap, brand)
                vclips.append(self._ken_burns(np.array(frame), d, i))
                placed_audio.append(aclip.set_start(t_cursor))
                t_cursor += d
            if lang_failed:
                # limpa os .mp3 parciais deste idioma (nao deixa lixo no disco)
                for i in range(1, len(script["scenes"]) + 1):
                    try:
                        os.remove(os.path.join(folder, f"s{i}_{lang}.mp3"))
                    except OSError:
                        pass
                continue
            video = concatenate_videoclips(vclips, method="chain")
            video = self._atmosphere(video)
            video = video.set_audio(CompositeAudioClip(placed_audio).set_duration(t_cursor))
            out = os.path.join(folder, f"{slug}__{lang}.mp4")
            # bitrate limitado: grao/nevoa inflam muito o arquivo (evita mp4 gigante).
            video.write_videofile(out, fps=24, codec="libx264", audio_codec="aac",
                                  bitrate=os.getenv("ATLAS_STORY_BITRATE", "2500k"),
                                  preset="medium", threads=4, logger=None)
            results[lang] = out
            self.log(f"[STORY]   {lang.upper()} video: {out}")

        if not results:
            # Fish falhou em TODOS os idiomas: nao ha o que publicar desta
            # historia (sem fallback para outro provedor). O chamador
            # (generate_batch) simplesmente descarta esta tentativa.
            self.log(f"[STORY] '{title_en}': Fish falhou em todos os idiomas; historia descartada.")
            return None

        # capa/preview
        base_frames[0].save(os.path.join(folder, "cover.png"))
        meta = {
            "slug": slug, "title_en": title_en, "title_pt": script.get("title_pt", title_en),
            "genre": genre, "series": series[f"brand_en"], "source": source,
            "hashtags": series.get("hashtags", ""),
            "languages": list(results.keys()), "videos": {k: os.path.basename(v) for k, v in results.items()},
            "scenes": len(script["scenes"]), "priority": True, "hash": h,
            "created": time.strftime("%Y-%m-%d %H:%M"),
        }
        with open(os.path.join(folder, "story.json"), "w", encoding="utf-8") as fh:
            json.dump({**meta, "script": script}, fh, ensure_ascii=False, indent=2)

        idx = load_index()
        idx.insert(0, {k: meta[k] for k in ("slug", "title_en", "title_pt", "genre", "hash", "created")})
        _save_index(idx)
        return meta

    def generate_batch(self, count: int = 3, genre: str = "horror",
                       languages: tuple[str, ...] = ("en", "pt"), scenes: int = 6) -> list[dict]:
        series = SERIES.get(genre, SERIES["horror"])
        avoid = [it.get("title_en", "") for it in load_index()]
        out = []
        for n in range(1, count + 1):
            self.log(f"[STORY] === Historia {n}/{count} ({genre}) ===")
            meta = self._build_one(genre, series, languages, scenes, avoid)
            if meta:
                out.append(meta)
                avoid.append(meta["title_en"])
        self.log(f"[STORY] Lote concluido: {len(out)} historia(s).")
        return out
