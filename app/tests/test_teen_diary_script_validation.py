from app.services.teen_diary_service import (
    PROMPT_SCHEMA_VERSION,
    TeenDiaryService,
    _empty_bible,
    _wardrobe_for_day,
)
from app.services.teen_diary_product_service import TeenDiaryProductService


def _scene(index: int, product: bool = False, final: bool = False) -> dict:
    return {
        "speaker": "isabela",
        "shot_type": "close" if index % 2 else "wide",
        "location": "classroom",
        "location_id": "classroom",
        "action_id": "show_product" if product else "talk_idle",
        "emotion_id": "happy",
        "camera_id": "medium_static",
        "prop_id": "stationery" if product else "",
        "required_visible_objects": ["stationery"] if product else [],
        "required_character_count": 1,
        "wardrobe_reference_id": "day-1-first-approved",
        "product_placement": final,
        "literal_action": (
            "Bela visibly opens the same notebook on her classroom desk and "
            "points to the exact page mentioned in the narration."
        ),
        "action_timeline": (
            "0-3s Bela places one hand on the notebook; 3-7s she opens it "
            "toward herself; 7-10s she points to the stable right-hand page."
        ),
        "environment_details": (
            "A lived-in Brazilian classroom with layered wooden desks, colorful "
            "student projects, a chalkboard calendar, backpacks on hooks, open "
            "windows, distant trees and subtle classmates blurred far behind."
        ),
        "material_details": (
            "Visible cotton hoodie fibers, worn varnished desk grain, matte paper, "
            "rigid notebook discs, brushed metal pen details and soft natural hair."
        ),
        "lighting_details": (
            "Warm late-morning sunlight enters from camera left, softened by thin "
            "curtains, with cool sky fill, gentle desk bounce and subtle hair rim."
        ),
        "composition_details": (
            "Notebook anchors the foreground, Bela occupies the midground left "
            "third, and layered classroom details recede softly into the background."
        ),
        "camera_direction": (
            "Medium eye-level shot with a natural portrait lens, focus locked on "
            "Bela and the notebook, followed by one restrained slow push-in."
        ),
        "object_continuity": (
            "The same notebook starts closed on the desk, opens once toward Bela "
            "and ends open; its color, discs, size and orientation never change."
        ),
        "image_prompt": (
            "Bela sits at her classroom desk with the same notebook directly in "
            "front of her, preparing to open it while the richly decorated room "
            "shows a believable active school day without distracting clutter."
        ),
        "motion_prompt": (
            "Bela leans forward naturally, places her palm on the rigid cover, "
            "opens it once with believable contact, then points calmly while her "
            "sleeves and ponytail settle with subtle secondary motion."
        ),
        "narration_en": (
            "This is an affiliate recommendation. If it seems useful, ask a "
            "parent or guardian to check the link in the caption."
            if final
            else (
                "A detailed school moment that feels natural, specific, emotional, "
                "relatable, and genuinely important to Bela today."
            )
        ),
        "narration_pt": (
            "Esta é uma recomendação de afiliado. Se parecer útil, peça a um "
            "adulto responsável para conferir o link na legenda."
            if final
            else (
                "Um momento escolar detalhado, natural, específico, emocional, "
                "identificável e realmente importante para Bela hoje."
            )
        ),
        "caption_en": "School diary",
        "caption_pt": "Diário da escola",
    }


def test_rejects_too_few_scenes():
    service = object.__new__(TeenDiaryService)
    script = {
        "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        "title_en": "Bad",
        "scenes": [_scene(i) for i in range(3)],
    }

    valid, reason = service._validate_diary_script(script)

    assert not valid
    assert "quantidade de cenas" in reason


def test_accepts_product_use_before_parent_directed_final_disclosure():
    service = object.__new__(TeenDiaryService)
    pair = TeenDiaryProductService().select_pair("escola", "day-1-part-1")
    scenes = [_scene(i) for i in range(10)]
    scenes[4] = _scene(4, product=True)
    scenes[-1] = _scene(9, product=True, final=True)
    script = {
        "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        "title_en": "A School Day",
        "scenes": scenes,
    }

    valid, reason = service._validate_diary_script(script, pair)

    assert valid, reason


def test_rejects_visually_poor_scene():
    service = object.__new__(TeenDiaryService)
    scenes = [_scene(i) for i in range(10)]
    scenes[3]["environment_details"] = "an empty room"

    valid, reason = service._validate_diary_script(
        {
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
            "title_en": "Visually Poor",
            "scenes": scenes,
        }
    )

    assert not valid
    assert "pobre em detalhes" in reason


def test_wardrobe_is_locked_within_day_and_changes_only_between_days():
    bible = _empty_bible()

    day_one_part_one = _wardrobe_for_day(bible, 1)
    day_one_part_two = _wardrobe_for_day(bible, 1)
    day_two = _wardrobe_for_day(bible, 2)

    assert day_one_part_one == day_one_part_two
    assert day_one_part_one != day_two
    assert bible["daily_wardrobe"]["1"] == day_one_part_one


def test_rejects_narrated_object_that_is_not_visually_required():
    service = object.__new__(TeenDiaryService)
    scenes = [_scene(i) for i in range(10)]
    scenes[2]["narration_pt"] = "Maria mostrou o desenho para a Bela."

    valid, reason = service._validate_diary_script(
        {
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
            "title_en": "Missing Drawing",
            "scenes": scenes,
        }
    )

    assert not valid
    assert "narracao cita drawing" in reason


def test_rejects_different_same_day_wardrobe_references():
    service = object.__new__(TeenDiaryService)
    scenes = [_scene(i) for i in range(10)]
    scenes[4]["wardrobe_reference_id"] = "day-2-first-approved"

    valid, reason = service._validate_diary_script(
        {
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
            "title_en": "Wardrobe Drift",
            "scenes": scenes,
        }
    )

    assert not valid
    assert "referencias de roupa diferentes" in reason
