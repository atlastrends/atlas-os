"""Teste rapido das vozes do Fish Audio (modelo gratis s2.1-pro-free).

Uso (no terminal, com a SUA chave gratis de fish.audio/app/api-keys/):
    $env:FISH_API_KEY = 'sua_chave'
    & 'C:\\atlas-os\\.venv-dash\\Scripts\\python.exe' 'C:\\atlas-os\\tools\\_fish_voice_test.py'

Opcional: testar vozes especificas por id (separadas por virgula):
    $env:FISH_TEST_VOICES = 'id1,id2'

Gera MP3s em storage/fish_voice_test/ e um catalogo voices_catalog.json.
Tambem gera a mesma frase no Edge TTS atual para comparar (A/B).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

API = "https://api.fish.audio"
FREE_MODEL = "s2.1-pro-free"
KEY = (os.getenv("FISH_API_KEY") or "").strip()
SORT = (os.getenv("FISH_SORT") or "score").strip()
OUT = Path(os.getenv("ATLAS_ROOT") or r"C:\atlas-os") / "storage" / "fish_voice_test"

# Texto PT proposital com muitas palavras em ingles (onde o Edge TTS erra).
PT_TEXT = (
    "Esse e o soundcore P40i da Anker: com Bluetooth cinco ponto tres, "
    "cancelamento de ruido e modo wireless, ele entrega um som bem limpo. "
    "O recurso BassUp reforca os graves, e pelo app voce ativa o modo gaming "
    "e o hands-free para as chamadas. Perfeito para streaming de musica, "
    "podcast e a sua playlist no dia a dia."
)
EN_TEXT = (
    "This is the Anker soundcore P40i: with Bluetooth five point three, active "
    "noise cancelling and a true wireless design, it delivers clean, punchy "
    "sound. BassUp boosts the low end, and the app unlocks gaming mode and "
    "hands-free calls for streaming, podcasts and playlists."
)


def die(msg: str, code: int = 1) -> None:
    print(msg)
    sys.exit(code)


if not KEY:
    die(
        "FISH_API_KEY nao definido.\nNo terminal rode:\n"
        "  $env:FISH_API_KEY = 'sua_chave'; "
        "& 'C:\\atlas-os\\.venv-dash\\Scripts\\python.exe' "
        "'C:\\atlas-os\\tools\\_fish_voice_test.py'",
        2,
    )

session = requests.Session()
session.headers["Authorization"] = f"Bearer {KEY}"


def list_voices(lang_candidates: list[str]) -> tuple[str | None, list[dict]]:
    for cand in lang_candidates:
        try:
            resp = session.get(
                f"{API}/model",
                params={"language": cand, "sort_by": SORT, "page_size": 30},
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  erro ao listar ({cand}): {exc}")
            continue
        if resp.status_code == 401:
            die("Chave invalida (401). Gere uma nova em fish.audio/app/api-keys/", 3)
        if resp.status_code != 200:
            print(f"  lista {cand}: HTTP {resp.status_code} {resp.text[:120]}")
            continue
        items = (resp.json() or {}).get("items") or []
        if items:
            return cand, items
    return None, []


def show(items: list[dict], limit: int = 15) -> None:
    for i, m in enumerate(items[:limit]):
        langs = ",".join(m.get("languages") or [])
        tags = ",".join(m.get("tags") or [])
        print(
            f"  #{i:<2} {(m.get('title') or '')[:32]:<32} "
            f"[{langs:<8}] tags={tags[:24]:<24} "
            f"uso={m.get('task_count', 0):<6} id={m.get('_id')}"
        )


def synth(text: str, reference_id: str, out_path: Path, label: str) -> None:
    body = {
        "text": text,
        "reference_id": reference_id,
        "format": "mp3",
        "mp3_bitrate": 128,
        "chunk_length": 300,
        "normalize": True,
        "prosody": {"speed": 1.0},
    }
    t0 = time.time()
    try:
        resp = session.post(
            f"{API}/v1/tts",
            json=body,
            headers={"model": FREE_MODEL, "Content-Type": "application/json"},
            timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [x] {label}: erro {exc}")
        return
    if resp.status_code != 200:
        print(f"  [x] {label}: HTTP {resp.status_code} {resp.text[:160]}")
        return
    out_path.write_bytes(resp.content)
    print(
        f"  [ok] {label}: {out_path.name} "
        f"({len(resp.content) // 1024} KB, {time.time() - t0:.1f}s)"
    )


def edge(text: str, voice: str, out_path: Path) -> None:
    cmd = [
        sys.executable, "-m", "edge_tts",
        "--voice", voice, "--text", text, "--write-media", str(out_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        print(f"  [x] edge {voice}: erro {exc}")
        return
    if proc.returncode == 0 and out_path.exists():
        print(f"  [ok] edge {voice}: {out_path.name} ({out_path.stat().st_size // 1024} KB)")
    else:
        print(f"  [x] edge {voice}: rc={proc.returncode} {proc.stderr[:160]}")


def safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name)[:32] or "voz"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manual = [v.strip() for v in (os.getenv("FISH_TEST_VOICES") or "").split(",") if v.strip()]

    print("== Vozes PT (melhor avaliadas) ==")
    pt_lang, pt_items = list_voices(["pt-BR", "pt", "portuguese", "Portuguese"])
    show(pt_items)
    print(f"  (filtro de idioma usado: {pt_lang})\n")

    print("== Vozes EN (melhor avaliadas) ==")
    _, en_items = list_voices(["en-US", "en", "english", "English"])
    show(en_items)
    print()

    (OUT / "voices_catalog.json").write_text(
        json.dumps({"pt": pt_items[:30], "en": en_items[:30]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    id2title = {m.get("_id"): (m.get("title") or "") for m in pt_items}
    targets = manual or [m.get("_id") for m in pt_items[:3] if m.get("_id")]

    print("== Sintese PT (texto com palavras em ingles) ==")
    for vid in targets:
        title = id2title.get(vid, vid)
        synth(PT_TEXT, vid, OUT / f"fish_pt_{safe(title)}.mp3", f"fish PT {title}")

    print("\n== Sintese EN ==")
    for m in en_items[:2]:
        synth(EN_TEXT, m.get("_id"), OUT / f"fish_en_{safe(m.get('title') or '')}.mp3",
              f"fish EN {m.get('title') or ''}")

    print("\n== Edge TTS atual (comparacao A/B, PT) ==")
    edge(PT_TEXT, "pt-BR-FranciscaNeural", OUT / "edge_pt_Francisca.mp3")
    edge(PT_TEXT, "pt-BR-AntonioNeural", OUT / "edge_pt_Antonio.mp3")

    print(f"\nArquivos em: {OUT}")


if __name__ == "__main__":
    main()
