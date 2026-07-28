# ============================================================
# ATLAS OS - tools/gerar_video_ambiente.py
#
# Gera videos de SONS DA NATUREZA (tela preta, audio continuo) para os
# 2 canais do YouTube (PT e EN), no estilo dos canais de ambiencia/sono
# (ex.: "Closer To Nature - Ambience").
#
# Diferenca para o gerar_video_chuva.py: aqui o som e uma GRAVACAO REAL
# (baixada de fontes com licenca livre por baixar_sons_naturais.py), e
# NAO um som sintetizado. Varios clipes reais sao costurados num LEITO
# longo, embaralhado e sem emenda -> soa natural e nao "parece loop".
#
# Categorias: chuva, tempestade, oceano, floresta, riacho, fogueira,
#             vento, grilos.
#
# Uso (rode com o Python da venv do projeto):
#   # baixa sons de chuva e gera 1 HORA de teste (PT e EN):
#   .\.venv-dash\Scripts\python.exe tools\gerar_video_ambiente.py --categoria chuva --minutos 60
#
#   # preview rapido (90s) so PT:
#   .\.venv-dash\Scripts\python.exe tools\gerar_video_ambiente.py --categoria oceano --segundos 90 --idioma pt
#
#   # todos os 8 tipos, 1h cada, PT e EN:
#   .\.venv-dash\Scripts\python.exe tools\gerar_video_ambiente.py --categoria todas --minutos 60
#
# Saidas (storage/ambiente/), por categoria CAT e idioma XX:
#   CAT_XX.mp4        -> intro falada (1x) + som. Pronto para subir.
#   CAT_loop_XX.mp4   -> SO o som, emenda perfeita (para live/loop 24/7).
#   CAT_XX.txt        -> titulo + descricao + hashtags (+ creditos).
# ============================================================

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import wave
from pathlib import Path

import numpy as np

# Reaproveita o motor ja pronto do gerador de chuva (loop, video, voz...).
from gerar_video_chuva import (
    SR,
    VOICES,
    _cauda_encode,      # noqa: F401  (mantido para simetria/uso futuro)
    _duracao_audio,     # noqa: F401
    _horas_label,
    _loop_sem_emenda,
    _rodar_ffmpeg,
    _tts_async,
    render_com_intro,
    render_loop,
    salvar_wav,
)
from baixar_sons_naturais import CATEGORIAS, baixar_categoria

EXTS_AUDIO = (".ogg", ".oga", ".mp3", ".wav", ".flac", ".opus", ".m4a")

# ------------------------------------------------------------
# Textos por categoria (intro falada, titulo, descricao, hashtags)
# ------------------------------------------------------------
CATS: dict[str, dict] = {
    "chuva": {
        "emoji": "🌧️", "nome_pt": "Chuva Suave", "nome_en": "Gentle Rain",
        "elem_pt": "pelo som suave da chuva caindo",
        "elem_en": "by the gentle sound of falling rain",
        "hash_pt": "#chuva #chuvaparadormir #somdechuva #relaxar #sono #sonoprofundo #paradormir #ruidobranco #sonsdanatureza #relaxamento",
        "hash_en": "#rain #rainsounds #rainforsleeping #relaxing #sleep #deepsleep #whitenoise #naturesounds #relax #insomnia",
    },
    "tempestade": {
        "emoji": "⛈️", "nome_pt": "Chuva e Trovao", "nome_en": "Rain and Thunder",
        "elem_pt": "pelo som da chuva e de trovoes distantes",
        "elem_en": "by the sound of rain and distant thunder",
        "hash_pt": "#chuvaetrovao #trovao #tempestade #chuvaparadormir #somdechuva #relaxar #sono #sonoprofundo #paradormir #sonsdanatureza",
        "hash_en": "#thunderstorm #thunder #rainandthunder #rainsounds #relaxing #sleep #deepsleep #whitenoise #naturesounds #insomnia",
    },
    "oceano": {
        "emoji": "🌊", "nome_pt": "Ondas do Mar", "nome_en": "Ocean Waves",
        "elem_pt": "pelo vaivem calmo das ondas do mar",
        "elem_en": "by the calm rolling of ocean waves",
        "hash_pt": "#ondas #mar #somdomar #oceano #ondasdomar #relaxar #sono #paradormir #sonsdanatureza #relaxamento",
        "hash_en": "#oceanwaves #ocean #seasounds #waves #beach #relaxing #sleep #deepsleep #naturesounds #whitenoise",
    },
    "floresta": {
        "emoji": "🌲", "nome_pt": "Floresta e Passaros", "nome_en": "Forest and Birds",
        "elem_pt": "pelos sons da floresta e pelo canto dos passaros",
        "elem_en": "by the sounds of the forest and birdsong",
        "hash_pt": "#floresta #passaros #cantodospassaros #natureza #somdafloresta #relaxar #meditar #sono #sonsdanatureza #relaxamento",
        "hash_en": "#forest #birdsong #birds #nature #forestsounds #relaxing #meditation #sleep #naturesounds #calm",
    },
    "riacho": {
        "emoji": "🏞️", "nome_pt": "Riacho Correndo", "nome_en": "Flowing Stream",
        "elem_pt": "pelo som de um riacho correndo entre as pedras",
        "elem_en": "by the sound of a stream flowing over the stones",
        "hash_pt": "#riacho #agua #somdeagua #rio #cachoeira #relaxar #sono #paradormir #sonsdanatureza #relaxamento",
        "hash_en": "#stream #water #riversounds #creek #flowingwater #relaxing #sleep #naturesounds #whitenoise #calm",
    },
    "fogueira": {
        "emoji": "🔥", "nome_pt": "Fogueira Crepitando", "nome_en": "Crackling Campfire",
        "elem_pt": "pelo crepitar suave de uma fogueira",
        "elem_en": "by the soft crackling of a campfire",
        "hash_pt": "#fogueira #lareira #somdefogo #crepitar #relaxar #sono #paradormir #aconchego #sonsrelaxantes #relaxamento",
        "hash_en": "#campfire #fireplace #firesounds #crackling #relaxing #sleep #cozy #asmr #whitenoise #calm",
    },
    "vento": {
        "emoji": "🍃", "nome_pt": "Vento nas Arvores", "nome_en": "Wind in the Trees",
        "elem_pt": "pelo som do vento passando entre as arvores",
        "elem_en": "by the sound of wind moving through the trees",
        "hash_pt": "#vento #somdovento #natureza #relaxar #sono #paradormir #ruidobranco #sonsdanatureza #relaxamento #meditar",
        "hash_en": "#wind #windsounds #nature #relaxing #sleep #whitenoise #naturesounds #calm #meditation #ambient",
    },
    "grilos": {
        "emoji": "🦗", "nome_pt": "Noite no Campo", "nome_en": "Night in the Countryside",
        "elem_pt": "pelo som dos grilos numa noite tranquila no campo",
        "elem_en": "by the sound of crickets on a peaceful country night",
        "hash_pt": "#grilos #noite #somdanoite #natureza #campo #relaxar #sono #paradormir #sonsdanatureza #relaxamento",
        "hash_en": "#crickets #nightsounds #night #nature #relaxing #sleep #naturesounds #whitenoise #calm #ambient",
    },
}


def _intro_texto(cat: str, idioma: str) -> str:
    c = CATS[cat]
    if idioma == "en":
        return (
            "Hello, and welcome to our channel. "
            "If you enjoy these sounds, please leave a like, subscribe, and turn on "
            "notifications so you don't miss the next relaxing sounds. "
            "Now relax, close your eyes, and take a slow, deep breath. "
            "In the next few seconds you'll drift into a deep, peaceful sleep, "
            f"carried {c['elem_en']}. Sweet dreams."
        )
    return (
        "Ola, e seja muito bem-vindo ao nosso canal. "
        "Se voce gosta destes sons, deixe o seu like, se inscreva e ative o sininho "
        "para nao perder os proximos sons relaxantes. "
        "Agora relaxe, feche os olhos e respire fundo. "
        "Nos proximos segundos voce vai mergulhar num sono profundo e tranquilo, "
        f"embalado {c['elem_pt']}. Tenha bons sonhos."
    )


# ================================================================
# 1) DECODIFICA cada gravacao real para float32 estereo (via ffmpeg)
# ================================================================
def _decodificar(entrada: str, pasta_tmp: Path, max_seg: float = 240.0) -> np.ndarray | None:
    """Decodifica ate 'max_seg' segundos do clipe (evita ler arquivos enormes
    inteiros na memoria; 4 min ja da variedade de sobra para o leito)."""
    tmp = str(pasta_tmp / (Path(entrada).stem + ".dec.wav"))
    ok, err = _rodar_ffmpeg(["-i", entrada, "-t", f"{max_seg:.1f}",
                             "-vn", "-ac", "2", "-ar", str(SR), tmp])
    if not ok or not Path(tmp).is_file():
        print(f"   ! nao decodificou {Path(entrada).name}: {err[:120]}")
        return None
    try:
        with wave.open(tmp, "rb") as w:
            nch, sw, nf = w.getnchannels(), w.getsampwidth(), w.getnframes()
            raw = w.readframes(nf)
    except Exception as exc:
        print(f"   ! erro lendo {Path(tmp).name}: {exc}")
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if sw != 2:
        return None
    arr = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    arr = arr.reshape(-1, 2) if nch == 2 else np.stack([arr, arr], axis=1)
    return arr


def _normaliza_rms(x: np.ndarray, alvo: float = 0.12) -> np.ndarray:
    rms = float(np.sqrt(np.mean(x ** 2))) + 1e-9
    return np.clip(x * (alvo / rms), -1.0, 1.0).astype(np.float32)


def _apara_bordas(x: np.ndarray, ms: float = 40.0) -> np.ndarray:
    """Micro fade-in/out nas pontas de cada clipe (evita 'clique')."""
    k = int(SR * ms / 1000.0)
    if len(x) > 2 * k and k > 1:
        ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None]
        x[:k] *= ramp
        x[-k:] *= ramp[::-1]
    return x


def _crossfade_append(a: np.ndarray | None, b: np.ndarray, xf: int) -> np.ndarray:
    """Concatena b em a com crossfade de potencia igual (sem emenda)."""
    if a is None:
        return b
    if len(a) < xf or len(b) < xf:
        return np.concatenate([a, b], axis=0)
    t = np.linspace(0.0, 1.0, xf, dtype=np.float32)
    fo = np.cos(t * np.pi / 2.0)[:, None]
    fi = np.sin(t * np.pi / 2.0)[:, None]
    meio = a[-xf:] * fo + b[:xf] * fi
    return np.concatenate([a[:-xf], meio, b[xf:]], axis=0)


def montar_leito(clipes: list[str], base_seg: float, seed: int, pasta_tmp: Path) -> np.ndarray | None:
    """Costura varios clipes REAIS num leito estereo longo, embaralhado,
    normalizado e com LOOP sem emenda. Retorna float32 (n,2) a ~-6 dBFS."""
    rng = np.random.default_rng(seed)
    decs: list[np.ndarray] = []
    for c in clipes:
        d = _decodificar(c, pasta_tmp)
        if d is None or len(d) < SR * 3:  # ignora falhas e clipes < 3s
            continue
        decs.append(_apara_bordas(_normaliza_rms(d)))
    if not decs:
        return None

    alvo = int(base_seg * SR)
    xf = int(1.5 * SR)
    leito: np.ndarray | None = None
    guarda = 0
    while (leito is None or len(leito) < alvo) and guarda < 5000:
        guarda += 1
        ordem = list(range(len(decs)))
        rng.shuffle(ordem)
        for idx in ordem:
            leito = _crossfade_append(leito, decs[idx], xf)
            if len(leito) >= alvo:
                break
    leito = leito[:alvo]

    esq = _loop_sem_emenda(leito[:, 0].copy(), 6.0)
    dir_ = _loop_sem_emenda(leito[:, 1].copy(), 6.0)
    m = min(len(esq), len(dir_))
    leito = np.stack([esq[:m], dir_[:m]], axis=1)

    pico = float(np.max(np.abs(leito))) + 1e-9
    leito *= (10 ** (-6.0 / 20.0)) / pico
    return leito.astype(np.float32)


# ================================================================
# 2) VOZ da introducao (por categoria/idioma)
# ================================================================
def gerar_voz(cat: str, idioma: str, caminho: str) -> None:
    voz = VOICES.get(idioma, VOICES["pt"])
    texto = _intro_texto(cat, idioma)
    try:
        asyncio.run(_tts_async(texto, voz, caminho))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_tts_async(texto, voz, caminho))
        finally:
            loop.close()


# ================================================================
# 3) METADADOS (titulo, descricao, hashtags, creditos) por idioma
# ================================================================
def _bloco_creditos(pasta_fontes: Path, idioma: str) -> str:
    j = pasta_fontes / "creditos.json"
    if not j.is_file():
        return ""
    try:
        import json
        itens = json.loads(j.read_text(encoding="utf-8"))
    except Exception:
        return ""
    # so precisa creditar quem NAO for CC0/dominio publico
    linhas = []
    for it in itens:
        code = (it.get("licenca_code") or "").lower()
        if code in ("cc0", "cc-zero", "pd") or code.startswith("pd"):
            continue
        autor = it.get("autor") or ("Unknown author" if idioma == "en" else "Autor desconhecido")
        linhas.append(f"• \"{it.get('titulo','')}\" — {autor} ({it.get('licenca','')}) {it.get('pagina','')}")
    if not linhas:
        return ""
    cab = "Sound credits (Creative Commons):" if idioma == "en" else "Creditos dos sons (Creative Commons):"
    return cab + "\n" + "\n".join(linhas)


def escrever_metadados(cat: str, idioma: str, minutos: float,
                       pasta_saida: Path, pasta_fontes: Path) -> Path:
    c = CATS[cat]
    dur = _horas_label(minutos)
    creditos = _bloco_creditos(pasta_fontes, idioma)
    if idioma == "en":
        titulo = f"{c['nome_en']} for SLEEPING {c['emoji']} | {dur} of Relaxing Sound | Black Screen, NO Mid-roll Ads"
        desc = (
            f"Close your eyes, take a deep breath and fall into a deep sleep, carried {c['elem_en']}. "
            "Continuous audio, no interruptions, and a black screen to save battery and rest your eyes.\n\n"
            "� If it helps you sleep, leave a LIKE so it reaches more people.\n"
            "�🔔 Subscribe and turn on notifications so you don't miss the next relaxing sounds.\n"
            "💤 Perfect for sleeping, relaxing, meditation, studying, reading, or soothing a baby.\n"
            "⏱️ Set it to LOOP and let it play all night long.\n\n"
            "No music, no talking in the middle, just nature. Sweet dreams.\n\n"
            f"{c['hash_en']}"
        )
    else:
        titulo = f"{c['nome_pt']} para DORMIR {c['emoji']} | {dur} de Som Relaxante | Tela Preta, SEM Anuncios no Meio"
        desc = (
            f"Feche os olhos, respire fundo e durma profundamente, embalado {c['elem_pt']}. "
            "Audio continuo, sem interrupcoes e com tela preta para economizar bateria e nao incomodar os olhos.\n\n"
            "� Se ajudar voce a dormir, deixe seu LIKE para o video alcancar mais pessoas.\n"
            "�🔔 Se inscreva e ative o sininho para nao perder os proximos sons relaxantes.\n"
            "💤 Ideal para dormir, relaxar, meditar, estudar, ler ou acalmar o bebe.\n"
            "⏱️ Coloque para tocar em LOOP e deixe rolar a noite toda.\n\n"
            "Sem musica, sem falas no meio, so a natureza. Bons sonhos.\n\n"
            f"{c['hash_pt']}"
        )
    if creditos:
        desc += "\n\n" + creditos
    txt = f"TITULO:\n{titulo}\n\nDESCRICAO:\n{desc}\n"
    destino = pasta_saida / f"{cat}_{idioma}.txt"
    destino.write_text(txt, encoding="utf-8")
    return destino


# ================================================================
# PRINCIPAL
# ================================================================
def _clipes_da_pasta(pasta: Path) -> list[str]:
    if not pasta.is_dir():
        return []
    return sorted(str(p) for p in pasta.iterdir()
                  if p.suffix.lower() in EXTS_AUDIO and not p.name.startswith("_"))


def processar_categoria(cat: str, args, raiz: Path, pasta_saida: Path,
                        pasta_tmp: Path) -> int:
    preview = args.segundos > 0
    dur_total = float(args.segundos) if preview else float(args.minutos) * 60.0
    dur_total = max(dur_total, 30.0)
    base_seg = min(args.base_seg, dur_total) if preview else args.base_seg
    base_seg = max(base_seg, 30.0)
    seed = args.seed if args.seed else int.from_bytes(os.urandom(4), "little")
    idiomas = ["pt", "en"] if args.idioma == "ambos" else [args.idioma]

    fontes = raiz / "storage" / "ambiente" / "fontes" / cat
    clipes = _clipes_da_pasta(fontes)
    if args.rebaixar or not clipes:
        print(f"[ambiente] baixando sons reais de '{cat}'...")
        baixar_categoria(cat, args.qtd, fontes, sem_sa=args.sem_sa)
        clipes = _clipes_da_pasta(fontes)
    if not clipes:
        print(f"[ambiente] ERRO: sem clipes para '{cat}'. Pulei.")
        return 1

    print(f"[ambiente] '{cat}': {len(clipes)} clipe(s) reais -> montando leito ({base_seg:.0f}s)...")
    leito = montar_leito(clipes, base_seg, seed, pasta_tmp)
    if leito is None:
        print(f"[ambiente] ERRO: falha ao montar o leito de '{cat}'.")
        return 1
    fonte = str(pasta_saida / f"_base_{cat}.wav")
    salvar_wav(leito, fonte)
    print(f"[ambiente] base: {fonte} ({Path(fonte).stat().st_size/1e6:.1f} MB)")

    falhas = 0
    for idi in idiomas:
        sufixo = f"preview_{idi}" if preview else idi
        print(f"\n[ambiente] === {cat} / {idi} ===")
        voz_mp3 = str(pasta_saida / f"_intro_{cat}_{idi}.mp3")
        gerar_voz(cat, idi, voz_mp3)
        if not Path(voz_mp3).is_file():
            print("[ambiente] ERRO: falha na voz da introducao.")
            falhas += 1
            continue

        saida_main = str(pasta_saida / f"{cat}_{sufixo}.mp4")
        ok, err = render_com_intro(fonte, voz_mp3, dur_total, saida_main)
        print(f"[ambiente] {'OK' if ok else 'ERRO'} -> {saida_main}"
              + ("" if ok else f"  ({err[:200]})"))
        falhas += 0 if ok else 1

        saida_loop = str(pasta_saida / f"{cat}_loop_{sufixo}.mp4")
        ok2, err2 = render_loop(fonte, base_seg, saida_loop)
        print(f"[ambiente] {'OK' if ok2 else 'ERRO'} -> {saida_loop}"
              + ("" if ok2 else f"  ({err2[:200]})"))
        falhas += 0 if ok2 else 1

        if not preview:
            meta = escrever_metadados(cat, idi, args.minutos, pasta_saida, fontes)
            print(f"[ambiente] metadados -> {meta}")
    return 1 if falhas else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Gera videos de sons da natureza (tela preta, loop) com audio REAL licenciado.")
    ap.add_argument("--categoria", required=True,
                    help="chuva | tempestade | oceano | floresta | riacho | fogueira | vento | grilos | todas")
    ap.add_argument("--minutos", type=float, default=60.0, help="Duracao do video final (min). Padrao 60.")
    ap.add_argument("--segundos", type=int, default=0, help="MODO PREVIEW: duracao total em s (ignora --minutos).")
    ap.add_argument("--idioma", choices=["pt", "en", "ambos"], default="ambos")
    ap.add_argument("--qtd", type=int, default=8, help="Clipes reais a baixar por categoria (padrao 8).")
    ap.add_argument("--base-seg", type=float, default=600.0, help="Tamanho do leito/loop em s (padrao 600 = 10 min).")
    ap.add_argument("--seed", type=int, default=0, help="Semente (0 = aleatoria).")
    ap.add_argument("--rebaixar", action="store_true", help="Baixar de novo mesmo se ja houver clipes.")
    ap.add_argument("--sem-sa", action="store_true", help="Excluir licencas Share-Alike (CC-BY-SA).")
    ap.add_argument("--saida", default="", help="Pasta de saida (padrao storage/ambiente).")
    args = ap.parse_args()

    raiz = Path(os.getenv("ATLAS_ROOT", os.getcwd()))
    pasta_saida = Path(args.saida) if args.saida else (raiz / "storage" / "ambiente")
    pasta_saida.mkdir(parents=True, exist_ok=True)
    pasta_tmp = pasta_saida / "_tmp"
    pasta_tmp.mkdir(parents=True, exist_ok=True)

    if args.categoria == "todas":
        cats = list(CATS.keys())
    elif args.categoria in CATS:
        cats = [args.categoria]
    else:
        print(f"ERRO: categoria invalida '{args.categoria}'. Opcoes: {', '.join(CATS)} ou 'todas'.")
        return 2

    print(f"[ambiente] saida: {pasta_saida}")
    falhas = 0
    for cat in cats:
        falhas += processar_categoria(cat, args, raiz, pasta_saida, pasta_tmp)

    # limpa temporarios
    try:
        for p in pasta_tmp.glob("*"):
            p.unlink()
        pasta_tmp.rmdir()
    except OSError:
        pass

    print("\n[ambiente] concluido." if not falhas else f"\n[ambiente] concluido com {falhas} falha(s).")
    return 0 if not falhas else 1


if __name__ == "__main__":
    sys.exit(main())
