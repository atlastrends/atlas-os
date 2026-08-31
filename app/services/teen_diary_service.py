"""
ATLAS - Servico do "Diario da Bela" (serie continua, 3D cartoon).

Diario emocional de Isabela ("Bela"), 13 anos, e sua irma caçula Maria, 6
anos. Diferente de Terror/Policial (historias independentes), aqui os
episodios sao uma SEQUENCIA continua: cada episodio novo lembra o que ja
aconteceu (bible/memoria persistente) e nunca repete um assunto ja usado.

- 2 episodios por "dia" da serie (parte 1 e parte 2), cada um com 60-90s.
- Bilingue: EN (Isabela/Bela) + PT (Bela). Vozes DEDICADAS por idade real dos
  personagens (adolescente para a Bela, crianca para a Maria) - nunca voz de
  adulto fingindo ser crianca.
- Estilo visual FIXO (3D estilizado cinematografico) com a APARENCIA dos
  personagens travada no codigo, para ficarem visualmente consistentes em
  todo episodio (o publico reconhece a Bela e a Maria sempre do mesmo jeito).
- Memoria continua (bible): personagens, fatos estabelecidos (familia,
  escola, amigos, paixoes...), resumos recentes e a lista de topicos ja
  usados - tudo persistido em disco e ATUALIZADO a cada episodio novo.
- Publica nas MESMAS contas de trending (BR/US) usadas por Terror/Policial
  por enquanto (kind="trend"); reaproveita o registro/publicacao ja pronto
  em routers/stories.py (_run_post), so muda o slug/pasta do episodio.
- Cada episodio vira uma pasta em stories/ (mesmo nivel de horror/crime),
  com um story.json no MESMO formato generico usado pela pagina /stories -
  assim aparece de graca nos endpoints /stories/api/list, /post, /file,
  /delete ja existentes (nao precisa duplicar essa parte).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from typing import Any, Callable, Optional

import numpy as np
import requests
from PIL import Image

try:
    import imageio_ffmpeg
    os.environ.setdefault("IMAGEIO_FFMPEG_EXE", imageio_ffmpeg.get_ffmpeg_exe())
except Exception:
    pass

from app.services.ebook_service import ImageGenerator, _fill, _upscale, _font
from app.services.story_service import STORY_ROOT, _extract_json, _hash, _slug

W, H = 1080, 1920  # vertical 9:16

BIBLE_PATH = os.path.join(STORY_ROOT, "_diario_bible.json")

BRAND_EN = "Bela's Diary"
BRAND_PT = "Diário da Bela"
HASHTAGS = "#teendiary #dailyvlog #siblings #diariodabela #cartoon3d #storytime"

MIN_DURATION = float(os.getenv("ATLAS_DIARY_MIN_DURATION", "60"))
MAX_DURATION = float(os.getenv("ATLAS_DIARY_MAX_DURATION", "90"))
TARGET_DURATION = float(os.getenv("ATLAS_DIARY_TARGET_DURATION", "75"))
MIN_SCENES = int(os.getenv("ATLAS_DIARY_MIN_SCENES", "10"))
MAX_SCENES = int(os.getenv("ATLAS_DIARY_MAX_SCENES", "16"))

DIARY_LOCATIONS = {
    "bedroom", "kitchen", "living_room", "bathroom", "classroom",
    "school_hallway", "playground", "backyard", "street", "school_bus",
}
DIARY_ACTIONS = {
    "wake_stretch", "talk_idle", "look_around", "walk", "run", "sit",
    "stand", "point", "pick_up", "hold_object", "put_down", "eat",
    "laugh", "giggle", "sigh", "eye_roll", "cross_arms", "shrug",
    "wave", "hug", "look_at_phone", "open_door", "close_door",
    "draw", "write_notes", "show_product", "pack_backpack",
    "wear_backpack", "put_on_headphones", "listen_music", "read_book",
    "hold_book", "play_with_toy", "hold_toy", "drink_water",
    "hold_bottle",
}
DIARY_EMOTIONS = {
    "neutral", "happy", "sad", "angry", "annoyed", "worried",
    "surprised", "embarrassed", "mischievous", "tired", "excited",
}
DIARY_CAMERAS = {
    "close_static", "medium_static", "wide_static", "close_push_in",
    "medium_pan", "wide_tracking",
}

# ----------------------------------------------------------------
# Renderizacao acelerada: GPU (NVENC) quando disponivel + todos os
# nucleos de CPU. Nesta maquina (sem GPU dedicada) cai automaticamente
# para CPU/libx264; no Dell G15 (com NVIDIA), detecta e usa h264_nvenc,
# que e MUITO mais rapido que codificar so por CPU. Controlavel via
# ATLAS_VIDEO_ENCODER=auto|nvenc|cpu (auto = detecta sozinho).
# ----------------------------------------------------------------
_encoder_cache: dict[str, Any] = {}


def _detect_video_encoder() -> dict[str, Any]:
    """Descobre o melhor par (ffmpeg, codec) disponivel nesta maquina.

    auto: procura um ffmpeg do SISTEMA (PATH) com suporte a h264_nvenc (o
    binario embutido do imageio-ffmpeg normalmente NAO vem com NVENC
    habilitado). Se achar, usa GPU; senao usa o ffmpeg embutido com
    libx264 (CPU), que sempre funciona em qualquer maquina."""
    if _encoder_cache:
        return _encoder_cache

    mode = (os.getenv("ATLAS_VIDEO_ENCODER", "auto") or "auto").strip().lower()
    import shutil
    import subprocess

    result = {
        "ffmpeg": os.environ.get("IMAGEIO_FFMPEG_EXE", "ffmpeg"),
        "codec": "libx264",
        "preset": os.getenv("ATLAS_VIDEO_PRESET_CPU", "medium"),
        "gpu": False,
    }

    if mode == "cpu":
        _encoder_cache.update(result)
        return result

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        try:
            probe = subprocess.run(
                [system_ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=15,
            )
            has_nvenc = "h264_nvenc" in (probe.stdout or "")
        except Exception:
            has_nvenc = False
        if has_nvenc and mode in ("auto", "nvenc"):
            result = {
                "ffmpeg": system_ffmpeg,
                "codec": "h264_nvenc",
                "preset": os.getenv("ATLAS_VIDEO_PRESET_GPU", "p5"),
                "gpu": True,
            }
        elif mode == "nvenc":
            # usuario forcou nvenc mas nao ha suporte: avisa via log do chamador
            result["gpu_forced_unavailable"] = True

    _encoder_cache.update(result)
    return result


def _cpu_thread_count() -> int:
    """Usa TODOS os nucleos disponiveis para a renderizacao (o encode por
    CPU do moviepy/ffmpeg escala bem com mais threads). Pode ser limitado
    via ATLAS_VIDEO_THREADS se a maquina for compartilhada com outras
    tarefas pesadas."""
    override = os.getenv("ATLAS_VIDEO_THREADS", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    return max(1, os.cpu_count() or 4)


# Estilo visual FIXO (3D cartoon consistente) + aparencia TRAVADA dos
# personagens - injetados em TODO image_prompt para o publico sempre
# reconhecer a Bela e a Maria do mesmo jeito, episodio apos episodio.
VISUAL_STYLE = (
    "high-end stylized 3D animated feature quality, cinematic physically "
    "based rendering, stable detailed geometry, natural skin subsurface "
    "scattering, individual fabric fibers and seams, realistic hair strands, "
    "layered set decoration, atmospheric depth, global illumination, "
    "motivated practical lighting, polished cinematic color grading, "
    "believable real-world physics, vertical 9:16 composition"
)
PROMPT_SCHEMA_VERSION = "v10_automated_quality_gate"
EXTREME_STYLE_BIBLE = (
    "PREMIUM STYLE BIBLE: polished stylized 3D animated feature, never live "
    "action, anime, mobile-game, plastic-toy or generic AI-video aesthetics. "
    "Use physically based materials, realistic contact shadows, art-directed "
    "lighting, filmic highlight roll-off, warm interiors, neutral skin and "
    "restrained saturation. PERFORMANCE: emotionally believable and restrained; "
    "expressions develop through eyes, brows, breathing, shoulders and posture. "
    "No rubber-face acting, theatrical gestures, sudden mood changes, lip sync, "
    "talking or open-mouth smiles unless explicitly required. CAMERA: obey shot "
    "size, camera side, eye line, lens and composition; no jitter, focus pumping, "
    "rolling-shutter wobble, reframing or lens changes. TEMPORAL CONSISTENCY: "
    "stable characters, props, materials, lighting, architecture and wardrobe; "
    "no morphing, boiling textures, disappearing accessories, substitutions or "
    "geometry drift. HANDS: five anatomically correct fingers, plausible pressure, "
    "joints, grip and contact shadows; no fusion, inversion or penetration. "
    "PHONE: exactly one rigid model; glass and rear casing never swap; screen "
    "content is deterministic tracked compositing. TEXT: all readable Portuguese "
    "copy, buttons, icons and disclosures are deterministic composites with exact "
    "accents and punctuation. PHYSICS: realistic gravity, inertia, collision, "
    "cloth settling and rigid props. HAIR/CLOTH: no wind; strongly damped hair "
    "cannot cross eyes, glasses or face; cloth has low-amplitude folds without "
    "texture crawling."
)
ISABELA_APPEARANCE = (
    "the exact approved canonical Isabela ('Bela'), age 13, taller teenage "
    "proportions, identical face, naturally small ears, warm brown eyes, "
    "thin round gold eyeglasses always visible and tied dark side ponytail"
)
MARIA_APPEARANCE = (
    "the exact approved canonical Maria, age 6, shorter child proportions, "
    "identical face, naturally small ears, two dark pigtails and small natural "
    "teeth"
)

RICH_SCENE_FIELDS = (
    "literal_action",
    "action_timeline",
    "environment_details",
    "material_details",
    "lighting_details",
    "composition_details",
    "camera_direction",
    "object_continuity",
)

OBJECT_ACTIONS = {
    "pick_up", "hold_object", "put_down", "draw", "write_notes",
    "show_product", "look_at_phone", "hold_book", "hold_toy",
    "hold_bottle", "drink_water",
}
NARRATED_OBJECT_ALIASES = {
    "drawing": ("drawing", "desenho"),
    "notebook": ("notebook", "caderno"),
    "phone": ("phone", "telefone", "celular"),
    "pencil": ("pencil", "lapis", "lápis"),
    "bottle": ("bottle", "garrafa"),
}
ACTION_OBJECT_ALIASES = {
    "stationery": ("stationery", "notebook", "caderno"),
}

DAILY_WARDROBE_CATALOG = (
    {
        "isabela": (
            "teal hoodie, denim shorts over black leggings, dark sneakers, "
            "purple hair tie, thin round gold eyeglasses"
        ),
        "maria": (
            "coral cardigan, lavender flower dress, dark leggings, yellow "
            "sneakers, pink hair ties"
        ),
    },
    {
        "isabela": (
            "soft lavender zip hoodie, dark denim shorts over black leggings, "
            "gray sneakers, rose hair tie, thin round gold eyeglasses"
        ),
        "maria": (
            "mint cardigan, warm yellow flower dress, navy leggings, coral "
            "sneakers, mint hair ties"
        ),
    },
    {
        "isabela": (
            "deep coral sweatshirt, blue denim shorts over charcoal leggings, "
            "navy sneakers, teal hair tie, thin round gold eyeglasses"
        ),
        "maria": (
            "sky-blue cardigan, soft pink flower dress, plum leggings, cream "
            "sneakers, blue hair ties"
        ),
    },
)

TOPIC_TAGS = (
    "escola", "casa", "amizades", "paixao", "aventura", "irma", "familia",
    "emocional",
)

# Vozes Fish DEDICADAS por personagem/idioma - escolhidas pelo usuario apos
# ouvir amostras (storage/fish_voice_test/). NUNCA usar voz de adulto para
# a Maria - o codigo so aceita vozes classificadas como infantis aqui.
_VOICE_ENV = {
    ("isabela", "pt"): "FISH_VOICE_DIARY_ISABELA_BR",
    ("isabela", "en"): "FISH_VOICE_DIARY_ISABELA_US",
    ("maria", "pt"): "FISH_VOICE_DIARY_MARIA_BR",
    ("maria", "en"): "FISH_VOICE_DIARY_MARIA_US",
}
_VOICE_DEFAULTS = {
    ("isabela", "pt"): "2f6fb2d1b6454539945ee4255715d77c",  # Jovem Narradora Intensa
    ("isabela", "en"): "15d36df387164392b74d0988c8e4dd7f",  # Teen Girl
    ("maria", "pt"): "3af4e46874994a899d9bd0e659a5f60d",    # menina de 7 a 9 anos
    ("maria", "en"): "9a422fe397324ef796df540dededed52",    # Little girl 5yo
}


def _voice_id(speaker: str, lang: str) -> str:
    env_name = _VOICE_ENV.get((speaker, lang))
    override = (os.getenv(env_name, "") if env_name else "").strip()
    return override or _VOICE_DEFAULTS.get((speaker, lang), "")


# ----------------------------------------------------------------
# Bible (memoria continua persistida)
# ----------------------------------------------------------------
def _empty_bible() -> dict:
    return {
        "characters": {
            "isabela": {"name": "Isabela", "nickname": "Bela", "age": 13, "role": "protagonista e narradora"},
            "maria": {"name": "Maria", "age": 6, "role": "irma caçula"},
        },
        "established_facts": [],
        "recent_summaries": [],
        "used_topics": [],
        "episodes": [],
        "next_day": 1,
        "next_part": 1,
        "measured_wpm": {},
        "daily_wardrobe": {},
        "daily_wardrobe_references": {},
    }


def load_bible() -> dict:
    try:
        with open(BIBLE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        base = _empty_bible()
        base.update(data)
        return base
    except Exception:
        return _empty_bible()


def save_bible(bible: dict) -> None:
    os.makedirs(STORY_ROOT, exist_ok=True)
    with open(BIBLE_PATH, "w", encoding="utf-8") as fh:
        json.dump(bible, fh, ensure_ascii=False, indent=2)


def _wardrobe_for_day(bible: dict, day: int) -> dict[str, str]:
    daily = bible.setdefault("daily_wardrobe", {})
    key = str(day)
    existing = daily.get(key)
    if isinstance(existing, dict) and all(
        str(existing.get(character, "")).strip()
        for character in ("isabela", "maria")
    ):
        return {
            "isabela": str(existing["isabela"]),
            "maria": str(existing["maria"]),
        }
    selected = DAILY_WARDROBE_CATALOG[(max(1, day) - 1) % len(DAILY_WARDROBE_CATALOG)]
    wardrobe = {
        "isabela": selected["isabela"],
        "maria": selected["maria"],
    }
    daily[key] = wardrobe
    return wardrobe


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        key = it.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(it.strip())
    return out


class TeenDiaryService:
    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self.log = log or (lambda m: print(m))
        self.img = ImageGenerator(self.log)
        self._fish_note = ""

        self._video_mode = os.getenv(
            "ATLAS_DIARY_VIDEO_MODE", "blender"
        ).strip().lower()
        self._blender_backend = None
        self._video_backends: list = []
        if self._video_mode == "blender":
            try:
                from app.services.blender_diary_backend import \
                    BlenderDiaryBackend

                self._blender_backend = BlenderDiaryBackend(log=self.log)
                if not self._blender_backend.available():
                    self._blender_backend = None
            except Exception as exc:  # noqa: BLE001
                self.log(
                    "[DIARY] Backend Blender indisponivel "
                    f"({exc.__class__.__name__})."
                )
        else:
            # Modo generativo mantido somente para experimentos explícitos;
            # não é mais o padrão de produção da série.
            try:
                from app.services.hf_spaces_video_backend import \
                    HFSpacesVideoBackend

                hf_backend = HFSpacesVideoBackend(log=self.log)
                if hf_backend.available():
                    self._video_backends.append(hf_backend)
            except Exception as exc:  # noqa: BLE001
                self.log(
                    "[DIARY] Backend de video HF Spaces indisponivel "
                    f"({exc.__class__.__name__})."
                )
            try:
                from app.services.local_video_backend import ComfyUIVideoBackend

                comfy_backend = ComfyUIVideoBackend(log=self.log)
                if comfy_backend.available():
                    self._video_backends.append(comfy_backend)
            except Exception as exc:  # noqa: BLE001
                self.log(
                    "[DIARY] Backend de video local (ComfyUI) indisponivel "
                    f"({exc.__class__.__name__})."
                )

        # Backend de CONSISTENCIA DE PERSONAGEM (mesmo rosto/identidade de
        # Bela e Maria em toda cena e episodio, so roupas/pose mudam) via
        # HF Spaces (InstantX/InstantID, GPU compartilhada gratuita).
        self._consistency_backend = None
        if self._video_mode != "blender":
            try:
                from app.services.character_consistency_backend import \
                    CharacterConsistencyBackend

                cb = CharacterConsistencyBackend(log=self.log)
                if cb.available():
                    self._consistency_backend = cb
            except Exception as exc:  # noqa: BLE001
                self.log(
                    "[DIARY] Backend de consistencia de personagem "
                    f"indisponivel ({exc.__class__.__name__})."
                )

    # ---------- roteiro (IA, com continuidade injetada) ----------
    def _build_continuity_prompt(
        self,
        bible: dict,
        day: int,
        part: int,
        target_words: dict[str, int],
        product_pair: Optional[dict] = None,
    ) -> str:
        from app.services.teen_diary_product_service import \
            TeenDiaryProductService

        facts = bible.get("established_facts") or []
        facts_txt = "; ".join(facts[-60:]) if facts else "Nenhum ainda - este e o PRIMEIRO episodio da serie."

        recent = bible.get("recent_summaries") or []
        recent_txt = "\n".join(
            f"- Dia {r.get('day')} parte {r.get('part')}: {r.get('summary_en', '')}"
            for r in recent[-6:]
        ) or "Nenhum episodio anterior."

        used_topics = bible.get("used_topics") or []
        recent_topics = ", ".join(t.get("tag", "") for t in used_topics[-4:]) or "nenhum"
        wardrobe = _wardrobe_for_day(bible, day)

        part_hint = (
            "This is PART 1 of the day (morning): open the day, introduce today's "
            "situation/conflict."
            if part == 1
            else
            "This is PART 2 of the day (evening): resolve or develop further what "
            "happened in part 1 of THIS SAME day, then close with a cliffhanger for "
            "tomorrow."
        )

        return (
            "You are writing episode " + str(day) + " (part " + str(part) + ") of "
            "an ONGOING, SEQUENTIAL teen video-diary series called 'Bela's Diary' / "
            "'Diário da Bela', in BOTH English and Brazilian Portuguese. This is a "
            "CONTINUATION series (like a real ongoing vlog) - people follow it daily, "
            "so EVERY episode must feel like a real next chapter, NEVER a repeat of a "
            "past topic/scenario.\n\n"
            "YOUR #1 GOAL IS RETENTION: this is a short vertical video competing "
            "against thousands of others on a teen's For You Page. If the first line "
            "is not gripping, they scroll away in under 2 seconds. Write like the "
            "best viral teen storytime/vlog creators, NOT like a generic children's "
            "book.\n\n"
            "FIXED CHARACTERS (do not change their basic identity):\n"
            "- Isabela ('Bela'), 13 years old, the narrator. She speaks DIRECTLY to "
            "the camera/diary, first person, very emotional and relatable for a "
            "13-year-old: sometimes impatient with adults, dramatic about small "
            "things, loving but annoyed by her little sister, worried about school, "
            "friendships, crushes ('paixonites'), and fitting in.\n"
            "- Maria, 6 years old, Isabela's little sister. Occasionally Maria gets "
            "her OWN short line(s), delivered in HER OWN voice (mark those scenes "
            "with \"speaker\":\"maria\"), while Isabela narrates the rest "
            "(\"speaker\":\"isabela\").\n\n"
            "IMMUTABLE PHYSICAL IDENTITY:\n"
            "- Faces, skull shape, facial proportions, eyes, nose, mouth, teeth, "
            "ears, skin, height relationship, body proportions and age NEVER "
            "change. Hair remains in the approved tied style. Only clothes and "
            "accessories may vary between different days.\n"
            "TODAY'S WARDROBE IS LOCKED FOR THE ENTIRE DAY, INCLUDING PARTS 1 AND 2 "
            "AND EVERY SCENE:\n"
            f"- Isabela: {wardrobe['isabela']}.\n"
            f"- Maria: {wardrobe['maria']}.\n"
            "Never change, remove, recolor or add wardrobe pieces or accessories "
            "inside this day. Do not describe alternative outfits in scene prompts. "
            "After the first chapter is visually approved, its rendered frame becomes "
            "the wardrobe source of truth for that story day. Every later render must "
            "be compared with that approved frame before acceptance. If text and the "
            "approved frame disagree, the approved frame wins and the mismatched render "
            "must be rejected.\n\n"
            "ESTABLISHED FACTS SO FAR (canon - do not contradict; you MAY add new "
            "ones this episode via 'new_facts'): " + facts_txt + "\n\n"
            "STORY SO FAR (most recent episodes, for continuity):\n" + recent_txt + "\n\n"
            "Topics used in the last few episodes (AVOID repeating the same topic_tag "
            "again now): " + recent_topics + "\n\n"
            + part_hint + "\n\n"
            "HARD RULES FOR WRITING QUALITY (all of these are mandatory):\n"
            "1. HOOK RULE: scene 1's narration MUST be the single most dramatic, "
            "surprising or emotionally charged line of the whole episode - said "
            "IMMEDIATELY, with ZERO preamble ('so today...', 'okay so...', 'dear "
            "diary, today was...' are BANNED as opening lines). Start mid-emotion, "
            "like: a confession, a shocking realization, a question that creates "
            "suspense, or a strong reaction already in progress. The viewer must "
            "NOT be able to guess what happens next from this line alone.\n"
            "2. HYPER-SPECIFIC, NEVER GENERIC: ban vague phrases like 'it was a hard "
            "day' or 'so many things happened'. Every scene must reference a "
            "CONCRETE, nameable detail (a specific object, a specific thing someone "
            "said, a specific place) that a real 13-year-old would mention. Made-up "
            "specificity beats vague emotion every time.\n"
            "3. NATURAL TEEN VOICE: Isabela talks like a real young teenager texting "
            "a friend, not like an adult narrating a children's book. Contractions, "
            "small interruptions, rhetorical questions to the viewer ('you know that "
            "feeling when...?'), mild sarcasm. Avoid moralizing or 'the lesson I "
            "learned was...' endings - real teens don't wrap things up so neatly.\n"
            "4. EMOTIONAL CONTRAST: mix at least one heavy/frustrating moment with "
            "one genuinely sweet or funny moment (often via Maria) in the SAME "
            "episode - pure single-note sadness or pure comedy both retain worse "
            "than contrast.\n"
            "5. CLIFFHANGER RULE (part 2 only): the cliffhanger must create a "
            "SPECIFIC, answerable question the viewer wants resolved tomorrow (not "
            "a vague 'more drama tomorrow' - give them something concrete to "
            "wonder about).\n"
            "6. SHOT VARIETY: assign each scene a \"shot_type\": \"close\" for "
            "emotional/reaction beats (used for a tighter framing on the face) or "
            "\"wide\" for action/setting beats (full scene framing) - alternate "
            "them, don't use the same shot_type more than twice in a row.\n"
            "7. LOCATION MUST MATCH THE NARRATION: every scene's \"image_prompt\" "
            "MUST explicitly name the real physical place that scene's narration is "
            "actually happening in right now (her bedroom, the school hallway, the "
            "classroom, the kitchen, the playground/park, the living room, the "
            "backyard, the school bus, etc.) - never a vague or generic background, "
            "and never a place that contradicts what is being said. Consecutive "
            "scenes in the SAME location should look like the same continuous room "
            "(same furniture/time of day), and when the story moves to a new "
            "location that MUST be because the narration is now describing being "
            "somewhere else.\n\n"
            "8. ANIMATION PLAN: each scene MUST select executable IDs from these "
            "fixed production libraries (do not invent IDs):\n"
            f"- location_id: {', '.join(sorted(DIARY_LOCATIONS))}\n"
            f"- action_id: {', '.join(sorted(DIARY_ACTIONS))}\n"
            f"- emotion_id: {', '.join(sorted(DIARY_EMOTIONS))}\n"
            f"- camera_id: {', '.join(sorted(DIARY_CAMERAS))}\n"
            "Use prop_id as a short snake_case object name (or empty string). "
            "The action, prop and location MUST describe what visibly happens in "
            "the narration; never show the missing object in the character's hands. "
            "Prefer one clear physical action per shot.\n"
            "9. VISUAL RICHNESS IS MANDATORY: every scene must feel like a frame "
            "from a premium 3D animated feature, never an empty room or generic "
            "character portrait. Describe layered foreground, midground and "
            "background details; architecture and furniture; meaningful small "
            "objects; surface materials, texture, wear and reflections; time of "
            "day; motivated practical and ambient lighting; color palette; depth "
            "of field; and atmospheric details. Details must support the story "
            "rather than becoming random clutter.\n"
            "10. LITERAL VISUAL-AUDIO MATCH: every physical action stated in the "
            "narration must be visible. If a notebook is picked up, show the same "
            "notebook being picked up. If a phone is used, the same phone remains "
            "a phone. If pencils fall, show them on the floor under gravity. Never "
            "replace a narrated action with a generic emotional pose.\n"
            "For each scene, required_visible_objects must list every concrete object "
            "named by narration and required_character_count must equal the exact "
            "number of people allowed in frame, including partial people at an edge. "
            "wardrobe_reference_id must be identical across the entire story day and "
            "must identify the first visually approved chapter for that day.\n"
            "11. OBJECT PERMANENCE: explicitly state where every important prop "
            "starts, how it is held or moved, and where it ends. Props cannot "
            "appear, disappear, duplicate, change color, change design, float, "
            "teleport or transform. Pages and screens that require readable text "
            "must reserve a stable clean area for deterministic compositing.\n"
            "12. DIRECT THE FULL SHOT: action_timeline must describe the visible "
            "beginning, middle and end with second ranges; camera_direction must "
            "define framing, lens feeling, camera height and one controlled move; "
            "composition_details must define foreground/midground/background and "
            "the subject's screen position. Do not combine several unrelated "
            "actions in one shot.\n"
            "13. NEW CHAPTER, NEW PROMPTS: write a completely new story-specific "
            "prompt plan for this episode part. Never copy image_prompt, "
            "motion_prompt, literal_action, action_timeline, camera or staging "
            "from a previous chapter. Reuse only the permanent style bible, "
            "approved identities, established locations/facts and today's locked "
            "wardrobe. Part 2 gets new action prompts but keeps Part 1 wardrobe, "
            "room architecture and persistent props.\n"
            f"14. PROMPT SCHEMA VERSION: return prompt_schema_version exactly "
            f"'{PROMPT_SCHEMA_VERSION}'. Older or missing schemas are rejected.\n\n"
            "15. NATURAL PRODUCT STORYTELLING: the product has already been selected "
            "before this script is written. Build a believable story where it is "
            "used naturally before the final disclosure, then show the exact real "
            "product clearly at the end. Never interrupt the story with a sales card.\n"
            "16. NO SUBTITLES OR LARGE TEXT CARDS: the final diary video has narration "
            "but no burned subtitles. Never design full-screen text, giant labels or "
            "UI cards. If phone/notebook text is essential, reserve a small realistic "
            "surface inside the physical object for deterministic compositing.\n\n"
            + TeenDiaryProductService.prompt_block(product_pair)
            + "\n\n"
            "Write for a target of about " + str(target_words["en"]) + " English words "
            "and " + str(target_words["pt"]) + " Portuguese words of NARRATION total "
            "(across all scenes combined) - this controls the video length (60-90 "
            "seconds), so respect it closely.\n\n"
            "Return STRICT JSON only, no markdown: "
            '{"prompt_schema_version":"' + PROMPT_SCHEMA_VERSION + '",'
            '"title_en":"short evocative subtitle","title_pt":"...",'
            '"topic_tag":"one of: escola, casa, amizades, paixao, aventura, irma, '
            'familia, emocional",'
            '"new_facts":["any NEW persistent facts established this episode - '
            'names, places, events - empty list if none"],'
            '"summary_en":"1-2 sentence recap of what happened, for future '
            'continuity","summary_pt":"...",'
            '"cliffhanger_en":"a short hook teasing what happens next (only needed '
            'for part 2; empty string for part 1)","cliffhanger_pt":"...",'
            '"scenes":[{"speaker":"isabela or maria","shot_type":"close or wide",'
            '"location":"short name of the real physical place this scene happens '
            'in, e.g. \'her bedroom\', \'school hallway\', \'the playground\' - MUST '
            'match what the narration is describing",'
            '"location_id":"one fixed location ID above",'
            '"action_id":"one fixed action ID above",'
            '"emotion_id":"one fixed emotion ID above",'
            '"camera_id":"one fixed camera ID above",'
            '"prop_id":"snake_case prop name or empty string",'
            '"required_visible_objects":["canonical snake_case name of every concrete '
            'object named in narration; empty only when narration names no object"],'
            '"required_character_count":"integer 1 or 2; exact people allowed in frame",'
            f'"wardrobe_reference_id":"day-{day}-first-approved",'
            '"product_placement":"boolean; true only in the final disclosed product shot",'
            '"literal_action":"one precise sentence stating the exact visible '
            'physical action that matches narration",'
            '"action_timeline":"detailed beginning, middle and end using second '
            'ranges such as 0-3s, 3-7s and 7-10s",'
            '"environment_details":"rich English description of architecture, '
            'furniture, layered set dressing and meaningful background activity",'
            '"material_details":"rich English description of fabric, wood, metal, '
            'glass, paper, skin and hair surface qualities visible in this shot",'
            '"lighting_details":"time of day, motivated light sources, direction, '
            'softness, bounce light, rim light and color temperature",'
            '"composition_details":"foreground, midground, background, subject '
            'placement, depth layers and visual focal point",'
            '"camera_direction":"shot size, camera height, lens feeling, focus and '
            'one controlled camera movement",'
            '"object_continuity":"starting position, physical movement and final '
            'position/state of every important prop; say no prop if none",'
            '"image_prompt":"visual scene description in English, NO character '
            'appearance details (those are added automatically), just the '
            'SITUATION/ACTION/SETTING grounded in the location above; minimum 30 '
            'English words and packed with story-relevant visual specificity",'
            '"motion_prompt":"detailed English physical performance direction; '
            'minimum 20 words, natural motion, exact contact with props and no '
            'generic idle acting",'
            '"narration_en":"1-3 natural spoken sentences","narration_pt":"...",'
            '"caption_en":"short on-screen caption","caption_pt":"..."}, ... 10 to 16 '
            "scenes]}. Self-contained, original, no copyrighted characters."
        )

    def _build_rich_image_prompt(self, scene: dict, speaker: str) -> str:
        appearance = (
            ISABELA_APPEARANCE
            if speaker == "isabela"
            else MARIA_APPEARANCE
        )
        other = (
            MARIA_APPEARANCE
            if speaker == "isabela"
            else ISABELA_APPEARANCE
        )
        scene_desc = str(scene.get("image_prompt") or "").strip()
        has_both = (
            "sister" in scene_desc.lower()
            or "irma" in scene_desc.lower()
            or "both girls" in scene_desc.lower()
        )
        visible_characters = (
            f"{appearance} and {other}" if has_both else appearance
        )
        prop = str(scene.get("prop_id") or "").strip() or "no important prop"
        wardrobe = scene.get("wardrobe")
        if not isinstance(wardrobe, dict):
            wardrobe = DAILY_WARDROBE_CATALOG[0]
        wardrobe_text = (
            f"Isabela wears {wardrobe['isabela']}; Maria wears {wardrobe['maria']}"
            if has_both
            else f"{speaker.title()} wears {wardrobe[speaker]}"
        )
        return (
            f"LOCATION: {scene.get('location', '')}. "
            f"LITERAL STORY ACTION: {scene.get('literal_action', '')}. "
            f"SHOT SITUATION: {scene_desc}. "
            f"ENVIRONMENT AND SET DRESSING: "
            f"{scene.get('environment_details', '')}. "
            f"VISIBLE MATERIALS AND SURFACE DETAIL: "
            f"{scene.get('material_details', '')}. "
            f"LIGHTING: {scene.get('lighting_details', '')}. "
            f"COMPOSITION: {scene.get('composition_details', '')}. "
            f"CAMERA: {scene.get('camera_direction', '')}. "
            f"PROP: {prop}. OBJECT PERMANENCE: "
            f"{scene.get('object_continuity', '')}. "
            f"CHARACTERS VISIBLE: {visible_characters}. "
            f"LOCKED WARDROBE FOR THIS DAY: {wardrobe_text}. "
            f"RENDERING STANDARD: {VISUAL_STYLE}. {EXTREME_STYLE_BIBLE} "
            "Preserve the approved identity, age, ears, face, glasses, hair, "
            "clothes and body proportions exactly. Every object must be physically "
            "plausible, correctly oriented and ready to perform the narrated action. "
            "Never alter any clothing or accessory during this shot or elsewhere in "
            "the same day. Match the first approved rendered wardrobe reference for "
            "this story day exactly; reject the shot if any garment, color, layer, "
            "shoe, hair tie or accessory differs."
        )

    def _build_rich_motion_prompt(self, scene: dict) -> str:
        return (
            f"EXACT VISIBLE ACTION: {scene.get('literal_action', '')}. "
            f"SECOND-BY-SECOND PERFORMANCE: {scene.get('action_timeline', '')}. "
            f"CHARACTER MOTION: {scene.get('motion_prompt', '')}. "
            f"CAMERA EXECUTION: {scene.get('camera_direction', '')}. "
            f"OBJECT CONTINUITY: {scene.get('object_continuity', '')}. "
            f"EMOTION: {scene.get('emotion_id', '')}. {EXTREME_STYLE_BIBLE} "
            "Maintain continuous premium 3D feature-quality animation. Use natural "
            "weight, inertia, contact, grip and gravity. The narrated action must "
            "happen visibly. Do not add unplanned actions. Do not let any object "
            "appear, disappear, duplicate, teleport, rotate incorrectly or transform."
            " Faces, body proportions, hair, wardrobe and accessories remain identical "
            "from the first frame to the last frame."
        )

    def _validate_diary_script(
        self,
        data: dict,
        product_pair: Optional[dict] = None,
    ) -> tuple[bool, str]:
        """Hard quality gate before spending image/video GPU quota."""
        if not data.get("title_en"):
            return False, "titulo ausente"
        if data.get("prompt_schema_version") != PROMPT_SCHEMA_VERSION:
            return False, "schema de prompt antigo ou ausente"
        scenes = data.get("scenes")
        if not isinstance(scenes, list):
            return False, "scenes nao e uma lista"
        if not MIN_SCENES <= len(scenes) <= MAX_SCENES:
            return False, (
                f"quantidade de cenas fora da faixa "
                f"{MIN_SCENES}-{MAX_SCENES}: {len(scenes)}"
            )
        required = (
            "speaker", "shot_type", "location", "image_prompt",
            "motion_prompt", "narration_en", "narration_pt",
            "caption_en", "caption_pt", "location_id", "action_id",
            "emotion_id", "camera_id", *RICH_SCENE_FIELDS,
            "required_character_count", "wardrobe_reference_id",
        )
        wardrobe_reference_ids: set[str] = set()
        for index, scene in enumerate(scenes, 1):
            if not isinstance(scene, dict):
                return False, f"cena {index} nao e objeto"
            missing = [key for key in required if not str(scene.get(key, "")).strip()]
            if missing:
                return False, f"cena {index} sem campos: {', '.join(missing)}"
            if scene["speaker"] not in ("isabela", "maria"):
                return False, f"cena {index} com speaker invalido"
            if scene["shot_type"] not in ("close", "wide"):
                return False, f"cena {index} com shot_type invalido"
            if scene["location_id"] not in DIARY_LOCATIONS:
                return False, f"cena {index} com location_id invalido"
            if scene["action_id"] not in DIARY_ACTIONS:
                return False, f"cena {index} com action_id invalido"
            if scene["emotion_id"] not in DIARY_EMOTIONS:
                return False, f"cena {index} com emotion_id invalido"
            if scene["camera_id"] not in DIARY_CAMERAS:
                return False, f"cena {index} com camera_id invalido"
            required_objects = scene.get("required_visible_objects")
            if not isinstance(required_objects, list) or any(
                not isinstance(item, str) or not item.strip()
                for item in required_objects
            ):
                return False, (
                    f"cena {index} sem required_visible_objects valido"
                )
            normalized_objects = {
                str(item).strip().lower() for item in required_objects
            }
            character_count = scene.get("required_character_count")
            if character_count not in (1, 2):
                return False, (
                    f"cena {index} com required_character_count invalido"
                )
            wardrobe_reference_ids.add(
                str(scene["wardrobe_reference_id"]).strip()
            )
            prop_id = str(scene.get("prop_id", "")).strip().lower()
            if scene["action_id"] in OBJECT_ACTIONS and not prop_id:
                return False, (
                    f"cena {index} executa {scene['action_id']} sem prop_id"
                )
            if prop_id and prop_id not in normalized_objects:
                return False, (
                    f"cena {index}: prop_id {prop_id} nao esta em "
                    "required_visible_objects"
                )
            narration = " ".join(
                str(scene.get(f"narration_{lang}", "")).lower()
                for lang in ("en", "pt")
            )
            for canonical, aliases in NARRATED_OBJECT_ALIASES.items():
                if any(alias in narration for alias in aliases):
                    if canonical not in normalized_objects:
                        return False, (
                            f"cena {index}: narracao cita {canonical}, mas o "
                            "objeto nao e visualmente obrigatorio"
                        )
            action_text = " ".join((
                str(scene.get("literal_action", "")).lower(),
                str(scene.get("action_timeline", "")).lower(),
                str(scene.get("object_continuity", "")).lower(),
            ))
            for required_object in normalized_objects:
                action_aliases = ACTION_OBJECT_ALIASES.get(
                    required_object, (required_object,)
                )
                if not any(alias in action_text for alias in action_aliases):
                    return False, (
                        f"cena {index}: objeto obrigatorio {required_object} "
                        "nao aparece na acao/continuidade"
                    )
            richness_minimums = {
                "image_prompt": 30,
                "motion_prompt": 20,
                "environment_details": 24,
                "material_details": 16,
                "lighting_details": 16,
                "composition_details": 16,
                "camera_direction": 16,
                "object_continuity": 14,
                "literal_action": 10,
                "action_timeline": 18,
            }
            for field_name, minimum_words in richness_minimums.items():
                word_count = len(str(scene.get(field_name, "")).split())
                if word_count < minimum_words:
                    return False, (
                        f"cena {index} com {field_name} pobre em detalhes: "
                        f"{word_count}/{minimum_words} palavras"
                    )
            if not re.search(r"\b\d+\s*-\s*\d+\s*s\b", scene["action_timeline"]):
                return False, f"cena {index} sem cronograma em segundos"
        if len(wardrobe_reference_ids) != 1:
            return False, (
                "cenas do mesmo dia usam referencias de roupa diferentes"
            )
        if product_pair:
            from app.services.teen_diary_product_service import PROP_ACTIONS

            last = scenes[-1]
            expected_prop = product_pair["br"]["prop_type"]
            product_scenes = [
                (index, scene)
                for index, scene in enumerate(scenes)
                if str(scene.get("prop_id", "")).strip() == expected_prop
                and scene.get("action_id") in PROP_ACTIONS[expected_prop]
            ]
            if len(product_scenes) < 2 or not any(
                index < len(scenes) - 1 for index, _ in product_scenes
            ):
                return False, (
                    "produto precisa ser usado naturalmente antes do pitch "
                    "e mostrado novamente na cena final"
                )
            if last.get("speaker") != "isabela":
                return False, "ultima cena de produto deve ser da Isabela"
            if last.get("product_placement") is not True:
                return False, "ultima cena sem product_placement=true"
            if str(last.get("prop_id", "")).strip() != expected_prop:
                return False, (
                    f"prop final deve ser {expected_prop}, "
                    f"veio {last.get('prop_id')!r}"
                )
            pt_final = str(last.get("narration_pt", "")).lower()
            en_final = str(last.get("narration_en", "")).lower()
            if "afiliad" not in pt_final or "adulto" not in pt_final:
                return False, "disclosure/CTA responsável ausente em PT"
            if "affiliate" not in en_final or not (
                "parent" in en_final or "guardian" in en_final
            ):
                return False, "disclosure/CTA responsável ausente em EN"
        for lang in ("en", "pt"):
            words = sum(
                len(str(scene.get(f"narration_{lang}", "")).split())
                for scene in scenes
            )
            target = max(1, int(
                TARGET_DURATION
                * float((data.get("measured_wpm") or {}).get(lang, 165.0))
                / 60.0
            ))
            if words < int(target * 0.65) or words > int(target * 1.35):
                return False, (
                    f"narracao {lang} fora da faixa: {words} palavras; "
                    f"alvo aproximado {target}"
                )
        return True, ""

    def _ai_diary_script(
        self,
        bible: dict,
        day: int,
        part: int,
        target_words: dict[str, int],
        product_pair: Optional[dict] = None,
    ) -> Optional[dict]:
        from openai import OpenAI

        from app.services.ai_providers import build_extra_providers

        want_json = os.getenv("ATLAS_STORY_JSON_FORMAT", "0").strip().lower() in ("1", "true", "yes", "on", "sim")
        providers: list = []
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
            for p in build_extra_providers("DIARY"):
                if p["models"]:
                    providers.append((p["label"].lower(), p["models"][0], p["client"], False))
        except Exception:  # noqa: BLE001
            pass
        if not providers:
            return None

        prompt = self._build_continuity_prompt(
            bible, day, part, target_words, product_pair
        )
        for label, model, client, use_json in providers:
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.95,
                    "max_tokens": 8000,
                }
                if use_json:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = client.chat.completions.create(**kwargs)
                data = _extract_json(resp.choices[0].message.content or "")
                valid, reason = self._validate_diary_script(data, product_pair)
                if valid:
                    self.log(f"[DIARY] roteiro por {label} ({model})")
                    return data
                self.log(
                    f"[DIARY] {label} devolveu roteiro invalido "
                    f"({reason}); proximo."
                )
            except Exception as exc:  # noqa: BLE001
                self.log(f"[DIARY] IA roteiro {label} falhou ({exc.__class__.__name__}); proximo.")
        return None

    def _ai_repair_length(self, script: dict, lang: str, target_words: int) -> Optional[dict]:
        """Reescreve SOMENTE a narracao/legenda de UM idioma (mantendo cenas,
        image_prompt, topic_tag, new_facts, summary e cliffhanger intactos),
        para ajustar a duracao sem gerar deriva de conteudo entre EN/PT."""
        from openai import OpenAI

        from app.services.ai_providers import build_extra_providers

        providers: list = []
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
            for p in build_extra_providers("DIARY"):
                if p["models"]:
                    providers.append((p["label"].lower(), p["models"][0], p["client"], False))
        except Exception:  # noqa: BLE001
            pass
        if not providers:
            return None

        lang_name = "English" if lang == "en" else "Brazilian Portuguese"
        key_narr = f"narration_{lang}"
        key_cap = f"caption_{lang}"
        current = [
            {"speaker": sc.get("speaker", "isabela"), key_narr: sc.get(key_narr, ""), key_cap: sc.get(key_cap, "")}
            for sc in script.get("scenes", [])
        ]
        prompt = (
            f"Rewrite ONLY the {lang_name} narration/caption of this diary episode's "
            f"scenes so the TOTAL narration is close to {target_words} words in "
            f"{lang_name}, keeping the SAME number of scenes, SAME speakers, SAME "
            "events/order, and the SAME emotional teen-diary tone. Return STRICT "
            'JSON only: {"scenes":[{"' + key_narr + '":"...","' + key_cap + '":"..."}'
            ", ...]} in the SAME order as given below.\n\n"
            f"CURRENT SCENES: {json.dumps(current, ensure_ascii=False)}"
        )
        for label, model, client, use_json in providers:
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 4000,
                }
                if use_json:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = client.chat.completions.create(**kwargs)
                data = _extract_json(resp.choices[0].message.content or "")
                fixed = data.get("scenes")
                if fixed and len(fixed) == len(script.get("scenes", [])):
                    self.log(f"[DIARY] reparo de duracao ({lang}) por {label}")
                    return fixed
            except Exception as exc:  # noqa: BLE001
                self.log(f"[DIARY] reparo de duracao ({lang}) falhou em {label}: {exc.__class__.__name__}")
        return None

    # ---------- voz: SOMENTE Fish (sem fallback para outro provedor) ----------
    def _fish_tts(self, text: str, voice_id: str, path: str, tries: int = 3) -> bool:
        key = os.getenv("FISH_API_KEY")
        if not key or not voice_id:
            return False
        model = os.getenv("ATLAS_FISH_MODEL", "s2.1-pro-free")
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
                time.sleep(1.5 * attempt)
        return False

    def _validate_video_file(self, path: str, timeout: float = 20.0) -> bool:
        """Valida um arquivo de video DECODIFICANDO de verdade o primeiro
        frame via ffmpeg (a mesma operacao que o MoviePy faz internamente
        ao abrir um VideoFileClip) - em vez de so confiar no tamanho em
        bytes. Este e' o padrao recomendado pela propria comunidade para
        este erro exato ("failed to read the first frame"): projetos como
        o MoneyPrinterTurbo (github.com/harry0703/MoneyPrinterTurbo,
        issue #456) identificaram que videos baixados de fontes externas
        (como uma API gratuita de terceiros) podem ocasionalmente ficar
        invalidos/parcialmente corrompidos, e a correcao e' VALIDAR antes
        de confiar no arquivo, descartando e regenerando quando invalido -
        nunca manter um arquivo quebrado em cache "achando" que esta bom
        so' pelo tamanho."""
        if not os.path.isfile(path) or os.path.getsize(path) < 1000:
            return False
        try:
            import subprocess

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            result = subprocess.run(
                [ffmpeg, "-v", "error", "-i", path, "-frames:v", "1", "-f", "null", "-"],
                capture_output=True, timeout=timeout,
            )
            if result.returncode != 0 or result.stderr.strip():
                self.log(
                    f"[DIARY]   validacao de '{os.path.basename(path)}' falhou "
                    f"(ffmpeg: {result.stderr.decode('utf-8', 'ignore')[:200]})."
                )
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            self.log(f"[DIARY]   validacao de '{os.path.basename(path)}' falhou ({exc.__class__.__name__}).")
            return False

    def _ffmpeg_prepare_boomerang(self, raw_video_path: str, scene_idx: int) -> str:
        """Cria o trecho ida+volta inteiramente no FFmpeg.

        Esta funcao substitui definitivamente o antigo caminho MoviePy
        (VideoFileClip -> time_mirror -> concatenate_videoclips), que era o
        unico leitor MoviePy de video ainda presente quando o erro recorria.
        O filtro nativo split/reverse/concat foi validado diretamente contra
        o proprio scene2_raw.mp4 que falhava no MoviePy.
        """
        import subprocess

        folder = os.path.dirname(raw_video_path)
        out_path = os.path.join(folder, f"scene{scene_idx}_boomerang.mp4")
        if os.path.isfile(out_path):
            if self._validate_video_file(out_path):
                return out_path
            try:
                os.remove(out_path)
            except OSError:
                pass

        part_path = out_path + ".part.mp4"
        try:
            os.remove(part_path)
        except OSError:
            pass

        encoder = _detect_video_encoder()
        filter_graph = (
            "[0:v]split=2[f][r];"
            "[r]reverse[rev];"
            f"[f][rev]concat=n=2:v=1:a=0,fps=24,"
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,format=yuv420p[v]"
        )
        command = [
            encoder["ffmpeg"], "-y", "-v", "error", "-i", raw_video_path,
            "-filter_complex", filter_graph, "-map", "[v]", "-an",
            "-c:v", encoder["codec"], "-preset", encoder["preset"],
        ]
        if encoder.get("gpu"):
            command += ["-rc", "vbr", "-cq", "19"]
        else:
            command += ["-threads", str(_cpu_thread_count())]
        command += ["-movflags", "+faststart", part_path]

        result = subprocess.run(command, capture_output=True, timeout=240)
        if result.returncode != 0 or not self._validate_video_file(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
            raise RuntimeError(
                "ffmpeg nao conseguiu criar o bumerangue da cena "
                f"{scene_idx}: {result.stderr.decode('utf-8', 'ignore')[:300]}"
            )
        os.replace(part_path, out_path)
        return out_path

    def _generate_scene_motion_video(
        self,
        image_path: str,
        motion_prompt: str,
        shot_type: str,
        scene_idx: int,
        target_duration: float,
    ) -> Optional[str]:
        """Gera o clipe de MOVIMENTO REAL de uma cena, UMA UNICA VEZ por
        episodio (independente de idioma - o video de uma cena e o mesmo em
        EN e PT, so a narracao muda). Tenta cada backend disponivel em
        ordem (HF Spaces gratis primeiro, ComfyUI local depois), com
        VARIAS tentativas por backend antes de desistir. NAO HA FALLBACK de
        imagem parada: se tudo falhar, retorna None e quem chamou deve
        ABORTAR a geracao do episodio (decisao explicita do produto - todo
        video publicado precisa ter movimento real, personagens e cenario
        apropriado, nunca uma imagem estatica com zoom)."""
        if not self._video_backends:
            self.log(f"[DIARY]   cena {scene_idx}: nenhum backend de video real configurado; sem fallback disponivel.")
            return None
        out_path = os.path.join(os.path.dirname(image_path), f"scene{scene_idx}_raw.mp4")
        if os.path.isfile(out_path):
            # rascunho retomado: este video ja tinha sido gerado numa
            # tentativa anterior - MAS so' reaproveita se ele realmente
            # passar na validacao (decodificar o 1o frame de verdade), nao
            # so' pelo tamanho em bytes. Um arquivo baixado de uma API
            # gratuita externa pode ocasionalmente ficar invalido/
            # incompleto (padrao ja documentado pela comunidade para este
            # exato erro) - nesse caso, descarta e regenera do zero, em vez
            # de ficar preso reusando um arquivo quebrado para sempre.
            if self._validate_video_file(out_path):
                self.log(f"[DIARY]   cena {scene_idx}: video real ja existia (reaproveitando do rascunho).")
                return out_path
            self.log(f"[DIARY]   cena {scene_idx}: video em cache estava invalido; descartando e gerando de novo.")
            try:
                os.remove(out_path)
            except OSError:
                pass
        shot_hint = (
            "close-up shot, subtle natural motion, "
            if shot_type == "close"
            else "wide shot, gentle natural motion, "
        )
        full_prompt = shot_hint + (motion_prompt or "gentle idle motion")
        # duracao pedida ao gerador: no maximo o que o modelo aceita (~8.5s
        # no HF Spaces); cenas mais longas ganham continuidade via
        # ping-pong depois, em vez de pedir uma geracao unica gigante
        # (que estouraria a cota de GPU gratuita).
        gen_duration = max(1.0, min(8.0, target_duration))
        retries = max(1, int(os.getenv("ATLAS_DIARY_VIDEO_RETRIES", "2")))
        for backend in self._video_backends:
            backend_name = backend.__class__.__name__
            for attempt in range(1, retries + 1):
                try:
                    video_path = backend.generate(
                        image_path=image_path,
                        motion_prompt=full_prompt,
                        out_path=out_path,
                        duration=gen_duration,
                    )
                    if video_path:
                        # VALIDA de verdade (decodifica o 1o frame via
                        # ffmpeg) antes de aceitar - um download de API
                        # externa pode ocasionalmente vir invalido/
                        # incompleto; nesse caso descarta e tenta de novo
                        # em vez de propagar um arquivo quebrado adiante.
                        if self._validate_video_file(video_path):
                            self.log(f"[DIARY]   cena {scene_idx}: video real gerado ({backend_name}, tentativa {attempt}).")
                            return video_path
                        self.log(
                            f"[DIARY]   {backend_name} devolveu um video invalido/incompleto na cena "
                            f"{scene_idx} (tentativa {attempt}/{retries}); descartando e tentando de novo."
                        )
                        try:
                            os.remove(video_path)
                        except OSError:
                            pass
                except Exception as exc:  # noqa: BLE001
                    self.log(
                        f"[DIARY]   {backend_name} falhou na cena {scene_idx} "
                        f"(tentativa {attempt}/{retries}, {exc.__class__.__name__})."
                    )
                if getattr(backend, "quota_reached", False):
                    # cota de GPU gratuita esgotada: tentar de novo em
                    # segundos nao resolve (so reseta depois de um tempo) -
                    # para de insistir neste backend AGORA, sem desperdicar
                    # tempo, e passa pro proximo backend (se houver).
                    self.log(
                        f"[DIARY]   {backend_name}: cota de GPU gratuita esgotada "
                        f"({getattr(backend, 'last_error', '')[:150]}); pulando para o proximo backend."
                    )
                    break
                if attempt < retries:
                    time.sleep(2.0)
        self.log(
            f"[DIARY]   cena {scene_idx}: TODOS os backends de video falharam apos tentativas; "
            "sem fallback - episodio sera abortado."
        )
        return None

    def _scene_clip_for_language(
        self,
        raw_video_path: str,
        caption: str,
        duration: float,
        scene_idx: int,
        lang: str,
        folder: str,
        allow_cache: bool = True,
        duration_matched: bool = False,
    ) -> str:
        """Monta o clipe final da cena inteiramente no FFmpeg.

        allow_cache=False e' usado no loop de REPARO de duracao (legenda/
        duracao mudam a cada tentativa) - nesse caso NUNCA reaproveita um
        arquivo antigo do disco, sempre re-renderiza."""
        import subprocess

        out_path = os.path.join(folder, f"scene{scene_idx}_{lang}_final.mp4")
        if allow_cache and os.path.isfile(out_path):
            if self._validate_video_file(out_path):
                # rascunho retomado: esta cena (idioma) ja tinha sido
                # montada e renderizada com sucesso numa tentativa anterior
                # (1a tentativa, antes de qualquer reparo de duracao -
                # legenda/duracao batem).
                self.log(f"[DIARY]   cena {scene_idx} ({lang}): clipe final ja existia (reaproveitando do rascunho).")
                return out_path
            self.log(f"[DIARY]   cena {scene_idx} ({lang}): clipe final em cache estava invalido; regenerando.")
            try:
                os.remove(out_path)
            except OSError:
                pass

        motion_path = (
            raw_video_path
            if duration_matched
            else self._ffmpeg_prepare_boomerang(raw_video_path, scene_idx)
        )
        subtitles_enabled = (
            os.getenv("ATLAS_DIARY_SUBTITLES", "false").strip().lower()
            in {"1", "true", "yes", "on", "sim"}
        )
        caption_path = (
            os.path.join(folder, f"scene{scene_idx}_{lang}_caption.png")
            if subtitles_enabled
            else ""
        )
        part_path = out_path + ".part.mp4"
        if subtitles_enabled:
            Image.fromarray(self._caption_overlay(caption)).save(caption_path)
        try:
            try:
                os.remove(part_path)
            except OSError:
                pass

            encoder = _detect_video_encoder()
            if encoder.get("gpu"):
                self.log(
                    f"[DIARY]   cena {scene_idx} ({lang}): "
                    f"codificando com GPU ({encoder['codec']})."
                )
            command = [
                encoder["ffmpeg"], "-y", "-v", "error",
                "-stream_loop", "-1", "-i", motion_path,
            ]
            if subtitles_enabled:
                command += [
                    "-loop", "1", "-framerate", "24", "-i", caption_path,
                    "-filter_complex",
                    f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                    f"crop={W}:{H},setsar=1[base];"
                    "[base][1:v]overlay=0:0:shortest=1,"
                    "fps=24,setsar=1,format=yuv420p[v]",
                    "-map", "[v]",
                ]
            else:
                command += [
                    "-vf",
                    f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                    f"crop={W}:{H},fps=24,setsar=1,format=yuv420p",
                    "-map", "0:v:0",
                ]
            command += [
                "-t", f"{duration:.3f}", "-an",
                "-c:v", encoder["codec"], "-preset", encoder["preset"],
            ]
            if encoder.get("gpu"):
                command += ["-rc", "vbr", "-cq", "19"]
            else:
                command += ["-threads", str(_cpu_thread_count())]
            command += ["-movflags", "+faststart", part_path]

            result = subprocess.run(command, capture_output=True, timeout=300)
            if result.returncode != 0 or not self._validate_video_file(part_path):
                raise RuntimeError(
                    "ffmpeg nao conseguiu montar o clipe final da cena "
                    f"{scene_idx} ({lang}): "
                    f"{result.stderr.decode('utf-8', 'ignore')[:300]}"
                )
            os.replace(part_path, out_path)
        finally:
            for temp_path in (caption_path, part_path):
                if not temp_path:
                    continue
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        return out_path

    def _ffmpeg_concat_videos(self, video_paths: list[str], out_path: str) -> None:
        """Junta varios .mp4 (video puro, sem audio) em UM SO usando o
        CONCAT DEMUXER do proprio ffmpeg (`-f concat -c copy`), em vez do
        `concatenate_videoclips` do MoviePy.

        Por que isso e' a solucao ROBUSTA (nao um remendo): a montagem
        final via MoviePy precisa reabrir/buscar (seek) dentro de um grafo
        de multiplos leitores ffmpeg (um por cena) simultaneamente - essa
        reinicializacao interna do leitor e' a fonte raiz, ja documentada
        pela comunidade (ex.: MoneyPrinterTurbo, issue #456), do erro
        "failed to read the first frame" no Windows. O concat demuxer do
        ffmpeg, em contraste, e' pensado exatamente para este caso: como
        todas as cenas foram renderizadas AQUI MESMO com o MESMO codec/fps/
        resolucao (ver _scene_clip_for_language), ele apenas COPIA os
        streams (sem decodificar/recodificar nada) - operacao praticamente
        instantanea e sem nenhuma leitura fragil via Python."""
        import subprocess

        list_path = out_path + ".concat_list.txt"
        with open(list_path, "w", encoding="utf-8") as fh:
            for p in video_paths:
                escaped = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
                fh.write(f"file '{escaped}'\n")
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            result = subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path],
                capture_output=True, timeout=120,
            )
            if result.returncode != 0:
                # Fallback (raro): se os segmentos nao forem 100% compativeis
                # para stream-copy (ex.: parametros de codec levemente
                # diferentes entre tentativas), recodifica - mais lento, mas
                # nunca trava.
                self.log(
                    "[DIARY]   concat com stream-copy falhou "
                    f"({result.stderr.decode('utf-8', 'ignore')[:200]}); recodificando."
                )
                result2 = subprocess.run(
                    [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path],
                    capture_output=True, timeout=180,
                )
                if result2.returncode != 0:
                    raise RuntimeError(
                        f"ffmpeg concat (com recodificacao) falhou: {result2.stderr.decode('utf-8', 'ignore')[:300]}"
                    )
        finally:
            try:
                os.remove(list_path)
            except OSError:
                pass

    def _caption_overlay(self, caption: str) -> np.ndarray:
        """Gera uma camada RGBA (so a legenda, resto transparente) para
        sobrepor tanto em video real quanto em imagem com zoom/pan."""
        from PIL import ImageDraw

        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        cf = _font(56, bold=True)
        words = caption.split()
        lines: list[str] = []
        line = ""
        for w in words:
            trial = f"{line} {w}".strip()
            if draw.textlength(trial, font=cf) > W - 120:
                lines.append(line)
                line = w
            else:
                line = trial
        if line:
            lines.append(line)
        total_h = len(lines) * (cf.size + 16)
        yy = H - total_h - 220
        for ln in lines:
            tw = draw.textlength(ln, font=cf)
            x = (W - tw) / 2
            draw.text((x, yy), ln, font=cf, fill=(255, 255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0, 255))
            yy += cf.size + 16
        return np.array(layer)

    def _save_thumbnail(self, base_frame: Image.Image, script: dict, folder: str) -> None:
        """Gera a capa (cover.png) do episodio, otimizada para clique:
        contraste/saturacao realcados (destaca sobre o feed) + texto de
        gancho em destaque (cliffhanger ou titulo), igual ao padrao usado
        pelas paginas de listagem em /stories (arquivo "cover.png")."""
        from PIL import ImageDraw, ImageEnhance

        try:
            frame = base_frame.copy().convert("RGB")
            frame = ImageEnhance.Contrast(frame).enhance(1.15)
            frame = ImageEnhance.Color(frame).enhance(1.25)
            frame = ImageEnhance.Brightness(frame).enhance(1.05)

            hook = (
                script.get("cliffhanger_en")
                or script.get("title_en")
                or "NEW EPISODE"
            )
            hook = hook.strip().upper()
            if len(hook) > 70:
                hook = hook[:67].rsplit(" ", 1)[0] + "..."

            layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)

            cf = _font(72, bold=True)
            words = hook.split()
            lines: list[str] = []
            line = ""
            for w in words:
                trial = f"{line} {w}".strip()
                if draw.textlength(trial, font=cf) > frame.width - 100:
                    lines.append(line)
                    line = w
                else:
                    line = trial
            if line:
                lines.append(line)
            lines = lines[:3]

            line_h = cf.size + 14
            banner_h = 40 * 2 + line_h * len(lines)
            # faixa escura translucida no topo para o texto se destacar em
            # cima de qualquer imagem de fundo (altura dinamica conforme o
            # numero de linhas, para nunca cortar o texto).
            draw.rectangle([(0, 0), (frame.width, banner_h)], fill=(0, 0, 0, 140))

            yy = 40
            for ln in lines:
                tw = draw.textlength(ln, font=cf)
                x = (frame.width - tw) / 2
                draw.text(
                    (x, yy), ln, font=cf, fill=(255, 230, 0, 255),
                    stroke_width=6, stroke_fill=(0, 0, 0, 255),
                )
                yy += line_h

            # selo de marca/serie no rodape, para reforcar reconhecimento.
            bf = _font(40, bold=True)
            brand_txt = BRAND_EN.upper()
            tw = draw.textlength(brand_txt, font=bf)
            draw.text(
                ((frame.width - tw) / 2, frame.height - 110),
                brand_txt, font=bf, fill=(255, 255, 255, 255),
                stroke_width=4, stroke_fill=(0, 0, 0, 255),
            )

            cover = Image.alpha_composite(frame.convert("RGBA"), layer).convert("RGB")
            cover.save(os.path.join(folder, "cover.png"))
        except Exception as exc:  # noqa: BLE001
            self.log(f"[DIARY]   falha ao gerar thumbnail otimizada ({exc.__class__.__name__}); usando frame simples.")
            try:
                base_frame.convert("RGB").save(os.path.join(folder, "cover.png"))
            except Exception:
                pass

    def _save_thumbnail_from_video(
        self,
        video_path: Optional[str],
        script: dict,
        folder: str,
    ) -> None:
        if not video_path or not os.path.isfile(video_path):
            return
        import subprocess

        temp_path = os.path.join(folder, "_cover_source.png")
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [
                ffmpeg, "-y", "-v", "error", "-ss", "1.0",
                "-i", video_path, "-frames:v", "1", temp_path,
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0 or not os.path.isfile(temp_path):
            self.log("[DIARY] falha ao extrair frame para thumbnail.")
            return
        try:
            with Image.open(temp_path) as image:
                self._save_thumbnail(image.convert("RGB"), script, folder)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    # ---------- identidade consistente (mesmo rosto sempre) ----------
    def _reference_image_path(self, character: str) -> str:
        """Caminho PERMANENTE (fora de qualquer pasta de episodio) da foto
        de referencia do personagem - gerada uma unica vez, para sempre, e
        reaproveitada por TODOS os episodios da serie."""
        return os.path.join(STORY_ROOT, f"_diario_{character}_reference.png")

    def _ensure_character_reference(self, character: str) -> Optional[str]:
        """Garante que existe uma foto de referencia PERMANENTE para o
        personagem (gera na primeira vez, nunca mais depois). Retorna o
        caminho, ou None se a geracao falhar (sem fallback - quem chama
        deve abortar, para nao publicar um personagem com cara diferente)."""
        path = self._reference_image_path(character)
        if os.path.isfile(path):
            return path
        os.makedirs(STORY_ROOT, exist_ok=True)
        appearance = ISABELA_APPEARANCE if character == "isabela" else MARIA_APPEARANCE
        prompt = (
            f"{appearance}. Front-facing portrait headshot, neutral friendly "
            "expression, plain light gray background, vertical framing, natural "
            "lighting, this is a REFERENCE PHOTO used only to lock the character's "
            "face/hair/skin tone identity for later renders."
        )
        seed = 770001 if character == "isabela" else 770002
        for attempt in range(1, 4):
            raw = self.img.generate(prompt, width=768, height=1024, seed=seed)
            if raw is not None:
                raw.convert("RGB").save(path)
                self.log(f"[DIARY]   referencia de '{character}' criada em {path} (permanente).")
                return path
            self.log(f"[DIARY]   tentativa {attempt}/3 de criar referencia de '{character}' falhou.")
            time.sleep(2.0)
        return None

    def _consistent_scene_frame(
        self, speaker: str, scene_prompt: str, folder: str, scene_idx: int
    ) -> Optional[Image.Image]:
        """Gera a imagem-chave de uma cena com a IDENTIDADE FACIAL do
        personagem PRESA a foto de referencia (nunca uma pessoa diferente -
        so roupa/pose/cenario mudam conforme o prompt). NAO HA FALLBACK: se
        a consistencia falhar apos tentativas, retorna None e o episodio
        inteiro e' abortado (decisao explicita do produto)."""
        reference_path = self._ensure_character_reference(speaker)
        if reference_path is None:
            self.log(f"[DIARY]   sem foto de referencia para '{speaker}' (sem fallback).")
            return None
        if self._consistency_backend is None:
            self.log("[DIARY]   backend de consistencia de personagem indisponivel (sem fallback).")
            return None

        # arquivo TEMPORARIO dentro da pasta do episodio (nunca solto na
        # raiz de stories/) - apagado logo em seguida, ja que so serve de
        # ponte ate carregarmos a imagem em memoria com PIL.
        temp_out_path = os.path.join(folder, f"scene{scene_idx}_consistency_raw.png")

        retries = max(1, int(os.getenv("ATLAS_DIARY_VIDEO_RETRIES", "2")))
        for attempt in range(1, retries + 1):
            try:
                out_path = self._consistency_backend.generate(
                    reference_image_path=reference_path,
                    scene_prompt=scene_prompt,
                    out_path=temp_out_path,
                )
            except Exception as exc:  # noqa: BLE001
                out_path = None
                self.log(f"[DIARY]   consistencia de personagem falhou (tentativa {attempt}/{retries}, {exc.__class__.__name__}).")
            if out_path:
                try:
                    im = Image.open(out_path)
                    im.load()
                    result = im.convert("RGB")
                    return result
                except Exception as exc:  # noqa: BLE001
                    self.log(f"[DIARY]   imagem consistente invalida ({exc.__class__.__name__}).")
                finally:
                    try:
                        os.remove(out_path)
                    except OSError:
                        pass
            if getattr(self._consistency_backend, "quota_reached", False):
                # cota de GPU gratuita esgotada: nao adianta insistir
                # agora (so libera depois de um tempo) - para de tentar
                # imediatamente, sem desperdicar tempo em retries inuteis.
                self.log(
                    "[DIARY]   cota de GPU gratuita do backend de consistencia esgotada "
                    f"({getattr(self._consistency_backend, 'last_error', '')[:150]}); "
                    "nao ha mais tentativas uteis agora."
                )
                break
            if attempt < retries:
                time.sleep(2.0)
        return None

    # ---------- 1 episodio -> videos (por idioma) ----------
    def _draft_dir(self, day: int, part: int) -> str:
        """Pasta de RASCUNHO fixa por dia/parte (nao depende do titulo, que
        so a IA sabe depois de gerar o roteiro) - usada para RETOMAR um
        episodio que falhou no meio (ex.: cota de GPU gratuita esgotada),
        sem desperdicar o roteiro de IA nem as cenas que ja tinham
        funcionado. So e' renomeada para a pasta final quando o episodio
        fica pronto de verdade (video + audio dos dois idiomas)."""
        return os.path.join(STORY_ROOT, f"_diario_draft_d{day:04d}_p{part:02d}")

    def _build_episode(self, day: int, part: int, bible: dict) -> Optional[dict]:
        wpm = bible.get("measured_wpm") or {}
        default_wpm = {"en": 165.0, "pt": 165.0}
        target_words = {
            lang: int(round(TARGET_DURATION * (wpm.get(lang) or default_wpm[lang]) / 60.0))
            for lang in ("en", "pt")
        }

        folder = self._draft_dir(day, part)
        os.makedirs(folder, exist_ok=True)
        draft_script_path = os.path.join(folder, "_draft_script.json")
        draft_product_path = os.path.join(folder, "_draft_products.json")
        from app.services.teen_diary_product_service import \
            TeenDiaryProductService

        product_service = TeenDiaryProductService()
        if os.path.isfile(draft_product_path):
            with open(draft_product_path, encoding="utf-8") as fh:
                product_pair = json.load(fh)
        else:
            product_pair = product_service.select_pair(
                topic="escola",
                seed=f"diario-{day}-{part}",
            )
            if product_pair:
                with open(draft_product_path, "w", encoding="utf-8") as fh:
                    json.dump(
                        product_pair,
                        fh,
                        ensure_ascii=False,
                        indent=2,
                    )

        script = None
        if os.path.isfile(draft_script_path):
            # RETOMANDO um rascunho anterior que nao completou (ex.: cota de
            # GPU gratuita esgotada no meio) - reaproveita o MESMO roteiro
            # (nao gasta IA de novo) e as imagens/videos de cena que ja
            # tinham sido gerados com sucesso (nao gasta GPU de novo neles).
            with open(draft_script_path, encoding="utf-8") as fh:
                candidate_script = json.load(fh)
            valid_draft, invalid_reason = self._validate_diary_script(
                candidate_script,
                product_pair,
            )
            if valid_draft:
                script = candidate_script
                self.log(
                    f"[DIARY] Retomando rascunho existente do Dia {day} Parte {part} "
                    "(reaproveita roteiro e cenas ja geradas - nao desperdica cota de IA/GPU)."
                )
            else:
                self.log(
                    f"[DIARY] Rascunho antigo do Dia {day} Parte {part} nao atende "
                    f"ao novo padrao visual ({invalid_reason}); regenerando com "
                    "riqueza cinematografica e identidade/roupa travadas."
                )
                try:
                    os.remove(draft_script_path)
                except OSError:
                    pass
                for name in os.listdir(folder):
                    if not name.startswith("scene"):
                        continue
                    path = os.path.join(folder, name)
                    try:
                        if os.path.isdir(path):
                            shutil.rmtree(path)
                        else:
                            os.remove(path)
                    except OSError as error:
                        self.log(
                            f"[DIARY] Nao foi possivel limpar cena antiga "
                            f"'{name}': {error}"
                        )

        if script is None:
            script = self._ai_diary_script(
                bible,
                day,
                part,
                target_words,
                product_pair,
            )
            if not script:
                self.log("[DIARY] Nenhum provedor de IA disponivel; episodio nao gerado.")
                return None
            wardrobe = _wardrobe_for_day(bible, day)
            for scene in script["scenes"]:
                scene["wardrobe"] = wardrobe
            with open(draft_script_path, "w", encoding="utf-8") as fh:
                json.dump(script, fh, ensure_ascii=False, indent=2)

        wardrobe = _wardrobe_for_day(bible, day)
        for scene in script["scenes"]:
            scene["wardrobe"] = wardrobe

        title_en = script.get("title_en", f"Day {day}")
        slug = _slug(f"dia-{day:04d}-parte-{part}-{title_en}")
        self.log(f"[DIARY] Dia {day} parte {part}: '{title_en}' - {len(script['scenes'])} cenas...")

        if self._video_mode == "blender":
            base_frames = []
            base_frame_paths = [None] * len(script["scenes"])
        else:
            # imagens compartilhadas entre idiomas - aparencia dos personagens
        # TRAVADA no codigo (nunca deixada para a IA "lembrar" sozinha) E
        # com IDENTIDADE FACIAL CONSISTENTE (mesmo rosto sempre, so roupa/
        # pose mudam) via referencia + InstantID - ver _ensure_character_reference.
            base_frames = []
            base_frame_paths = []
        for i, sc in (
            [] if self._video_mode == "blender"
            else enumerate(script["scenes"], 1)
        ):
            frame_path = os.path.join(folder, f"scene{i}_keyframe.png")
            frame = None
            if os.path.isfile(frame_path):
                try:
                    cached = Image.open(frame_path)
                    cached.load()
                    frame = cached.convert("RGB")
                    self.log(f"[DIARY]   cena {i}/{len(script['scenes'])}: imagem ja existia (reaproveitando do rascunho).")
                except Exception:
                    frame = None

            if frame is None:
                speaker = sc.get("speaker", "isabela")
                prompt = self._build_rich_image_prompt(sc, speaker)

                raw = self._consistent_scene_frame(speaker, prompt, folder, i)
                if raw is None:
                    # SEM FALLBACK: sem a imagem com identidade consistente
                    # (mesmo rosto de sempre + cenario apropriado) nao ha o
                    # que gerar de video - aborta este episodio (o rascunho
                    # FICA no disco, com o roteiro e as cenas que ja
                    # funcionaram, para o proximo ciclo retomar daqui).
                    self.log(
                        f"[DIARY]   cena {i}: falha ao gerar a imagem-chave consistente (sem "
                        "fallback) -> abortando por agora; rascunho preservado para retomar no proximo ciclo."
                    )
                    return None
                frame = _fill(_upscale(raw.convert("RGB"), H, sharpen=True), (W, H))
                frame.save(frame_path)
                self.log(f"[DIARY]   cena {i}/{len(script['scenes'])} ok")
                if i < len(script["scenes"]):
                    time.sleep(1.2)

            base_frames.append(frame)
            base_frame_paths.append(frame_path)

        results, measured = self._synth_and_mux(
            slug, folder, script, target_words, base_frame_paths
        )
        if not results:
            # rascunho preservado (script + imagens + videos de cena que ja
            # funcionaram) para o proximo ciclo retomar sem desperdicar cota.
            return None

        # Episodio completo de verdade agora - promove o rascunho para a
        # pasta final (nomeada pelo titulo) antes de escrever thumbnail e
        # story.json, para que tudo va parar no lugar certo.
        final_folder = os.path.join(STORY_ROOT, slug)
        if os.path.abspath(folder) != os.path.abspath(final_folder):
            if os.path.isdir(final_folder):
                shutil.rmtree(final_folder, ignore_errors=True)
            # No Windows, um handle de arquivo (video/audio) recem-fechado
            # pode demorar um instante para o SO liberar de verdade - tenta
            # algumas vezes com espera curta antes de desistir.
            for attempt in range(1, 6):
                try:
                    shutil.move(folder, final_folder)
                    break
                except OSError as exc:
                    if attempt >= 5:
                        raise
                    self.log(
                        f"[DIARY]   promover pasta do rascunho falhou (tentativa {attempt}/5, "
                        f"{exc.__class__.__name__}); tentando de novo."
                    )
                    time.sleep(1.0 * attempt)
            folder = final_folder
            self.log(f"[DIARY]   rascunho concluido e promovido para a pasta final: {folder}")

        for lang, wpm_value in measured.items():
            if wpm_value > 0:
                bible.setdefault("measured_wpm", {})[lang] = wpm_value

        if base_frames:
            self._save_thumbnail(base_frames[0], script, folder)
        else:
            self._save_thumbnail_from_video(
                results.get("pt") or results.get("en"),
                script,
                folder,
            )

        new_facts = [str(f).strip() for f in (script.get("new_facts") or []) if str(f).strip()]
        bible["established_facts"] = _dedupe_keep_order(
            (bible.get("established_facts") or []) + new_facts
        )[-200:]
        bible.setdefault("recent_summaries", []).append({
            "day": day, "part": part,
            "summary_en": script.get("summary_en", ""),
            "summary_pt": script.get("summary_pt", ""),
        })
        bible["recent_summaries"] = bible["recent_summaries"][-20:]
        bible.setdefault("used_topics", []).append({"day": day, "part": part, "tag": script.get("topic_tag", "")})
        bible["used_topics"] = bible["used_topics"][-40:]

        h = _hash(f"{day}-{part}-{title_en}")
        meta = {
            "slug": slug,
            "title_en": f"{BRAND_EN} — Day {day} Part {part}: {title_en}",
            "title_pt": f"{BRAND_PT} — Dia {day} Parte {part}: {script.get('title_pt', title_en)}",
            "genre": "teen_diary",
            "series": BRAND_EN,
            "source": "ia",
            "hashtags": HASHTAGS,
            "languages": list(results.keys()),
            "videos": {k: os.path.basename(v) for k, v in results.items()},
            "scenes": len(script["scenes"]),
            "priority": not (
                os.getenv(
                    "ATLAS_DIARY_REQUIRE_VISUAL_APPROVAL", "true"
                ).strip().lower() in ("1", "true", "yes", "on", "sim")
            ),
            "hash": h,
            "created": time.strftime("%Y-%m-%d %H:%M"),
            "day": day,
            "part": part,
            "topic_tag": script.get("topic_tag", ""),
            "cliffhanger_en": script.get("cliffhanger_en", ""),
            "cliffhanger_pt": script.get("cliffhanger_pt", ""),
            "affiliate_products": product_pair or {},
            "affiliate_caption_en": product_service.localized_caption(
                product_pair, "en"
            ),
            "affiliate_caption_pt": product_service.localized_caption(
                product_pair, "pt"
            ),
        }
        requires_visual_approval = not meta["priority"]
        quality_gate = {
            "version": 1,
            "status": (
                "pending_visual_approval"
                if requires_visual_approval
                else "visual_approval_disabled"
            ),
            "publication_allowed": not requires_visual_approval,
            "automatic_checks": {
                "script_schema": "passed",
                "literal_action_plan": "passed",
                "narrated_objects_declared": "passed",
                "single_day_wardrobe_reference": "passed",
            },
            "visual_checks": [
                {
                    "scene": index,
                    "status": "pending",
                    "wardrobe_reference_id": scene["wardrobe_reference_id"],
                    "required_character_count": scene[
                        "required_character_count"
                    ],
                    "required_visible_objects": scene[
                        "required_visible_objects"
                    ],
                    "checks": [
                        "identity",
                        "wardrobe",
                        "literal_action",
                        "object_presence_and_contact",
                        "edge_intrusions",
                        "geometry_stability",
                    ],
                }
                for index, scene in enumerate(script["scenes"], 1)
            ],
        }
        meta["quality_gate_status"] = quality_gate["status"]
        meta["publication_ready"] = quality_gate["publication_allowed"]
        with open(
            os.path.join(folder, "quality_gate.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(quality_gate, fh, ensure_ascii=False, indent=2)
        if requires_visual_approval:
            with open(
                os.path.join(folder, ".pending_visual_approval"),
                "w",
                encoding="ascii",
            ) as fh:
                fh.write("Visual approval is required before publication.\n")
        with open(os.path.join(folder, "story.json"), "w", encoding="utf-8") as fh:
            json.dump({**meta, "script": script}, fh, ensure_ascii=False, indent=2)

        bible.setdefault("episodes", []).append({
            "day": day, "part": part, "slug": slug, "hash": h,
            "title_en": meta["title_en"], "title_pt": meta["title_pt"],
            "topic_tag": script.get("topic_tag", ""), "created": meta["created"],
        })
        return meta

    def _background_music_clip(self, duration: float):
        """Gera uma trilha ambiente suave e SINTETICA (nao usa musica de
        terceiros - zero risco de direitos autorais, zero dependencia de
        internet) para tocar baixinho por baixo da narracao. Retorna None
        se desativado (ATLAS_DIARY_MUSIC=false) ou se a duracao for
        invalida - nesse caso o video sai so com a narracao (como antes)."""
        if os.getenv("ATLAS_DIARY_MUSIC", "true").strip().lower() not in ("1", "true", "yes", "on", "sim"):
            return None
        if duration <= 0:
            return None
        try:
            from moviepy.audio.AudioClip import AudioArrayClip

            volume = float(os.getenv("ATLAS_DIARY_MUSIC_VOLUME", "0.09"))
            fps = 22050
            n = int(duration * fps)
            t = np.linspace(0, duration, n, endpoint=False)

            # progressao de acorde simples e alegre/quente (I - vi - IV - V
            # em Do maior), trocando a cada 4s, com 3 notas leves por acorde
            # (pad suave, sem bateria/percussao - nao compete com a fala).
            chords_hz = [
                (261.63, 329.63, 392.00),  # C maior
                (220.00, 261.63, 329.63),  # A menor
                (174.61, 220.00,261.63),   # F maior
                (196.00, 246.94, 392.00),  # G maior
            ]
            chord_len = 4.0
            wave = np.zeros(n)
            for note_hz in range(3):
                freqs = np.array([chords_hz[int((tt // chord_len) % len(chords_hz))][note_hz] for tt in t])
                wave += np.sin(2 * np.pi * np.cumsum(freqs) / fps)
            wave /= 3.0

            # fade-in/fade-out suave para nao "cortar" abrupto no inicio/fim.
            fade_n = min(n, int(fps * 1.5))
            if fade_n > 0:
                fade = np.linspace(0.0, 1.0, fade_n)
                wave[:fade_n] *= fade
                wave[-fade_n:] *= fade[::-1]

            stereo = np.column_stack([wave, wave]) * volume
            return AudioArrayClip(stereo, fps=fps).set_duration(duration)
        except Exception as exc:  # noqa: BLE001
            self.log(f"[DIARY]   falha ao gerar musica de fundo ({exc.__class__.__name__}); video sai so com narracao.")
            return None

    def _synth_and_mux(
        self,
        slug: str,
        folder: str,
        script: dict,
        target_words: dict[str, int],
        base_frame_paths: list,
    ):
        from moviepy.editor import AudioFileClip, CompositeAudioClip

        results: dict[str, str] = {}
        measured_wpm: dict[str, float] = {}

        # Video de MOVIMENTO REAL de cada cena e gerado SOB DEMANDA (na
        # primeira vez que a cena e' processada, dimensionado para a
        # duracao da narracao daquele idioma) e fica em cache aqui -
        # reaproveitado pelo outro idioma e por novas tentativas de reparo
        # de duracao (motion_prompt/imagem nunca mudam entre elas). NAO HA
        # fallback de imagem parada: se uma cena falhar em gerar video real
        # apos todas as tentativas, o episodio inteiro e' abortado (None).
        raw_videos_by_scene: dict[object, str] = {}
        video_generation_failed = False

        for lang in ("en", "pt"):
            if video_generation_failed:
                break
            attempt = 0
            current_script = script
            while True:
                attempt += 1
                scene_clip_paths, placed_audio, t_cursor = [], [], 0.0
                audio_clips_opened: list = []
                total_words = 0
                ok_all = True
                for i, sc in enumerate(current_script["scenes"], 1):
                    speaker = sc.get("speaker", "isabela")
                    narr = sc.get(f"narration_{lang}") or sc.get("narration_en") or "..."
                    cap = sc.get(f"caption_{lang}") or narr
                    total_words += len(narr.split())
                    apath = os.path.join(folder, f"s{i}_{lang}.mp3")
                    voice = _voice_id(speaker, lang)
                    if attempt == 1 and os.path.isfile(apath) and os.path.getsize(apath) > 2000:
                        # rascunho retomado: este audio (cena/idioma) ja foi
                        # gerado com sucesso numa tentativa anterior, com a
                        # MESMA narracao original (so' na 1a tentativa, antes
                        # de qualquer reparo de duracao) - reaproveita em vez
                        # de chamar o Fish de novo.
                        ok = True
                        self.log(f"[DIARY]   cena {i} ({lang}): audio ja existia (reaproveitando do rascunho).")
                    else:
                        ok = self._fish_tts(narr, voice, apath)
                    if not ok:
                        ok_all = False
                        self.log(f"[DIARY]   Fish falhou cena {i} ({lang}, {speaker}); nota: {self._fish_note}")
                        break
                    aclip = AudioFileClip(apath)
                    audio_clips_opened.append(aclip)
                    d = aclip.duration + 0.3

                    cache_key = (
                        (i, lang)
                        if self._video_mode == "blender"
                        else i
                    )
                    raw_video = raw_videos_by_scene.get(cache_key)
                    if raw_video is None:
                        if self._video_mode == "blender":
                            raw_path = os.path.join(
                                folder,
                                f"scene{i}_{lang}_blender.mp4",
                            )
                            if (
                                attempt == 1
                                and os.path.isfile(raw_path)
                                and self._validate_video_file(raw_path)
                            ):
                                raw_video = raw_path
                                self.log(
                                    f"[DIARY]   cena {i} ({lang}): "
                                    "render Blender reaproveitado."
                                )
                            else:
                                # Individual coverage is intentional for the
                                # proof episode. Two imported CloudRigs in the
                                # same automatic shot expose helper geometry
                                # that destabilizes camera fitting. Dialogue
                                # is covered with alternating singles.
                                visible = [speaker]
                                shot = {
                                    "speaker": speaker,
                                    "visible_characters": visible,
                                    "location_id": sc["location_id"],
                                    "action_id": sc["action_id"],
                                    "emotion_id": sc["emotion_id"],
                                    "camera_id": sc["camera_id"],
                                    "prop_id": sc.get("prop_id", ""),
                                }
                                raw_video = self._blender_backend.render_scene(
                                    shot,
                                    raw_path,
                                    d,
                                )
                        else:
                            image_path = (
                                base_frame_paths[i - 1]
                                if base_frame_paths
                                and i - 1 < len(base_frame_paths)
                                else None
                            )
                            raw_video = self._generate_scene_motion_video(
                                image_path=image_path,
                                motion_prompt=self._build_rich_motion_prompt(sc),
                                shot_type=sc.get("shot_type", "wide"),
                                scene_idx=i,
                                target_duration=d,
                            ) if image_path else None
                        if raw_video is None:
                            self.log(
                                f"[DIARY]   cena {i} sem video real (sem fallback) -> "
                                "abortando geracao deste episodio."
                            )
                            video_generation_failed = True
                            ok_all = False
                            break
                        raw_videos_by_scene[cache_key] = raw_video

                    scene_clip_paths.append(
                        self._scene_clip_for_language(
                            raw_video_path=raw_video,
                            caption=cap,
                            duration=d,
                            scene_idx=i,
                            lang=lang,
                            folder=folder,
                            allow_cache=(attempt == 1),
                            duration_matched=(
                                self._video_mode == "blender"
                            ),
                        )
                    )
                    placed_audio.append(aclip.set_start(t_cursor))
                    t_cursor += d
                try:
                    if video_generation_failed:
                        break
                    if not ok_all:
                        break
                    duration = t_cursor
                    wpm = (total_words / duration) * 60.0 if duration > 0 else 0.0
                    if MIN_DURATION <= duration <= MAX_DURATION or attempt >= 3:
                        if not (MIN_DURATION <= duration <= MAX_DURATION):
                            self.log(
                                f"[DIARY]   {lang.upper()} fora da faixa apos {attempt} tentativas "
                                f"({duration:.1f}s); aceitando mesmo assim (sem bloquear a publicacao)."
                            )
                        measured_wpm[lang] = wpm
                        out = os.path.join(folder, f"{slug}__{lang}.mp4")

                        # 1) Video: cada cena ja foi renderizada como um
                        # .mp4 PLANO e definitivo (mesmo codec/fps - ver
                        # _scene_clip_for_language). Junta tudo via ffmpeg
                        # CONCAT DEMUXER (stream-copy, sem recodificar) -
                        # muito mais rapido e 100% confiavel no Windows do
                        # que o concatenate_videoclips do MoviePy, que
                        # precisa reabrir/religar varios leitores ffmpeg
                        # simultaneamente (fonte do erro "failed to read
                        # the first frame" ja documentado pela comunidade).
                        silent_concat_path = os.path.join(folder, f"{slug}__{lang}_silent.mp4")
                        self._ffmpeg_concat_videos(scene_clip_paths, silent_concat_path)

                        # 2) Audio: mixagem (narracao + trilha de fundo)
                        # continua no MoviePy (nunca foi a origem do bug -
                        # so' precisa ficar isolada num arquivo proprio,
                        # nao "vivo" durante a etapa de video).
                        bg_music = None
                        audio_out_path = os.path.join(folder, f"{slug}__{lang}_audio.wav")
                        try:
                            narration_mix = CompositeAudioClip(placed_audio).set_duration(t_cursor)
                            bg_music = self._background_music_clip(t_cursor)
                            final_audio = (
                                CompositeAudioClip([bg_music, narration_mix]).set_duration(t_cursor)
                                if bg_music is not None
                                else narration_mix
                            )
                            final_audio.write_audiofile(audio_out_path, fps=44100, logger=None)
                        finally:
                            if bg_music is not None:
                                bg_music.close()

                        # 3) Mux final: um UNICO comando ffmpeg junta o
                        # video (ja pronto, so' copia o stream) com o audio
                        # (codificado para AAC agora) - sem nenhuma leitura
                        # de video via MoviePy nesta etapa final.
                        import subprocess

                        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
                        mux = subprocess.run(
                            [
                                ffmpeg, "-y", "-i", silent_concat_path, "-i", audio_out_path,
                                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                                "-c:a", "aac", "-b:a", os.getenv("ATLAS_STORY_AUDIO_BITRATE", "192k"),
                                "-shortest", out,
                            ],
                            capture_output=True, timeout=180,
                        )
                        if mux.returncode != 0:
                            raise RuntimeError(
                                f"ffmpeg mux final falhou: {mux.stderr.decode('utf-8', 'ignore')[:300]}"
                            )
                        for tmp_f in (silent_concat_path, audio_out_path):
                            try:
                                os.remove(tmp_f)
                            except OSError:
                                pass

                        results[lang] = out
                        self.log(f"[DIARY]   {lang.upper()} video: {out} ({duration:.1f}s)")
                        break
                    # duracao fora da faixa: repara SO este idioma (mantendo
                    # o resto do roteiro intacto, sem gerar deriva EN/PT).
                    new_target = int(round(TARGET_DURATION * wpm / 60.0)) if wpm > 0 else target_words[lang]
                    self.log(
                        f"[DIARY]   {lang.upper()} saiu com {duration:.1f}s (fora de "
                        f"{MIN_DURATION:.0f}-{MAX_DURATION:.0f}s); pedindo ajuste para "
                        f"~{new_target} palavras (tentativa {attempt + 1})."
                    )
                    fixed_scenes = self._ai_repair_length(current_script, lang, new_target)
                    if not fixed_scenes:
                        continue
                    merged = json.loads(json.dumps(current_script))  # deep copy
                    for sc, fix in zip(merged["scenes"], fixed_scenes):
                        sc[f"narration_{lang}"] = fix.get(f"narration_{lang}", sc.get(f"narration_{lang}", ""))
                        sc[f"caption_{lang}"] = fix.get(f"caption_{lang}", sc.get(f"caption_{lang}", ""))
                    current_script = merged
                finally:
                    # fecha TODOS os clipes de audio abertos nesta tentativa
                    # (sucesso, reparo ou falha) - handle de arquivo aberto
                    # no Windows impede renomear a pasta do episodio depois.
                    for ac in audio_clips_opened:
                        ac.close()


        if not results:
            return None, {}
        return results, measured_wpm

    # ---------- entrada principal: gera N proximos episodios ----------
    def generate_next(self, count: int = 1) -> list[dict]:
        if self._video_mode == "blender" and self._blender_backend is None:
            self.log(
                "[DIARY] Geracao bloqueada com seguranca: o backend Blender "
                "esta instalado, mas o arquivo mestre 3D de Bela, Maria, "
                "cenarios e animacoes ainda nao passou na validacao. O modo "
                "I2V antigo nao sera usado como fallback porque sua qualidade "
                "foi rejeitada."
            )
            return []
        out: list[dict] = []
        for _ in range(max(1, count)):
            bible = load_bible()
            day = int(bible.get("next_day", 1))
            part = int(bible.get("next_part", 1))
            self.log(f"[DIARY] === Gerando Dia {day} Parte {part} ===")
            meta = self._build_episode(day, part, bible)
            if meta:
                # so' avanca a numeracao dia/parte quando o episodio saiu de
                # verdade (com video real, sem fallback) - se falhar (ex.:
                # HF Spaces fora do ar), a MESMA vaga e' tentada de novo no
                # proximo ciclo, sem criar buracos na sequencia da serie.
                if part >= 2:
                    bible["next_day"] = day + 1
                    bible["next_part"] = 1
                else:
                    bible["next_part"] = 2
                save_bible(bible)
                out.append(meta)
            else:
                self.log(
                    f"[DIARY] Dia {day} Parte {part} nao foi gerado (sem fallback); "
                    "sera tentado novamente no proximo ciclo."
                )
        self.log(f"[DIARY] Lote concluido: {len(out)} episodio(s).")
        return out
