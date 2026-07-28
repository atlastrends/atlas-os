# ============================================================
# ATLAS OS - tools/gerar_video_chuva.py
#
# Gera videos de CHUVA + TROVAO para dormir (canal ambiente/sono),
# com TELA PRETA e AUDIO CONTINUO, prontos para os 2 canais do
# YouTube (Brasil/PT e EUA/EN).
#
# Ideias-chave (pedido do usuario):
#   - O clipe NAO precisa ser longo: ele e feito para RODAR EM LOOP
#     sem emenda audivel (a chuva volta ao inicio sem "clique"/corte).
#   - A introducao falada ("se inscreva... relaxe... bom sono") toca
#     UMA UNICA VEZ no comeco. O trecho que se repete no loop e SO a
#     chuva/trovao -> nunca ha interrupcao (se a intro entrasse no
#     loop, ela se repetiria e a pessoa nao salvaria o video).
#
# Copyright: o som de chuva/trovao e SINTETIZADO aqui (ruido colorido
# + trovoes de baixa frequencia). Nao usa gravacao de terceiros ->
# zero risco de Content ID / strike (essencial para monetizar).
# Se preferir usar um audio proprio LICENCIADO, passe --audio arquivo.
#
# Uso (rode com o Python da venv do projeto):
#   .\.venv-dash\Scripts\python.exe tools\gerar_video_chuva.py --segundos 75      # PREVIEW rapido PT+EN
#   .\.venv-dash\Scripts\python.exe tools\gerar_video_chuva.py --minutos 10       # clipe final em loop PT+EN
#   .\.venv-dash\Scripts\python.exe tools\gerar_video_chuva.py --idioma pt        # so PT
#   .\.venv-dash\Scripts\python.exe tools\gerar_video_chuva.py --audio chuva.mp3  # usa audio proprio no lugar do sintetizado
#
# Saidas (em storage/ambiente/ por padrao), por idioma XX (pt/en):
#   chuva_trovao_XX.mp4        -> intro (1x) + chuva. Video pronto p/ subir.
#   chuva_trovao_loop_XX.mp4   -> SO chuva/trovao, emenda perfeita (para
#                                 rodar 24/7 em loop / live).
#   chuva_trovao_XX.txt        -> titulo + descricao + hashtags sugeridos.
# ============================================================

from __future__ import annotations

import argparse
import asyncio
import math
import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100  # taxa de amostragem do audio
VIDEO_W = 1920
VIDEO_H = 1080
VIDEO_FPS = 1  # tela preta estatica -> 1 quadro/s deixa o arquivo minusculo

# Vozes neurais MASCULINAS e SUAVES (Edge TTS, gratis) - ja usadas no projeto.
VOICES = {
    "pt": "pt-BR-AntonioNeural",
    "en": "en-US-ChristopherNeural",
}

# Texto da introducao falada (uma unica vez, no comeco).
INTRO_TEXT = {
    "pt": (
        "Ola, e seja muito bem-vindo ao nosso canal. "
        "Se inscreva e ative o sininho para nao perder os proximos sons relaxantes. "
        "Agora relaxe, feche os olhos e respire fundo. "
        "Nos proximos segundos voce vai mergulhar num sono profundo e tranquilo, "
        "embalado pelo som suave da chuva e de trovoes distantes. Tenha bons sonhos."
    ),
    "en": (
        "Hello, and welcome to our channel. "
        "Please subscribe and turn on notifications so you don't miss the next relaxing sounds. "
        "Now relax, close your eyes, and take a slow, deep breath. "
        "In the next few seconds you'll drift into a deep, peaceful sleep, "
        "carried by the gentle sound of rain and distant thunder. Sweet dreams."
    ),
}


# ----------------------------------------------------------------
# Localizacao do ffmpeg (PATH ou o binario do imageio-ffmpeg)
# ----------------------------------------------------------------
def _resolve_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FFMPEG = _resolve_ffmpeg()


# ================================================================
# 1) SINTESE DO SOM DE CHUVA + TROVAO (numpy, sem dependencia extra)
# ================================================================
def _ruido_colorido(n: int, seed: int, lp_hz: float = 6000.0, hp_hz: float = 200.0) -> np.ndarray:
    """Ruido moldado no espectro para o LEITO suave da chuva (fundo).

    Parte de ruido branco e aplica, no dominio da frequencia:
      - inclinacao rosa (~-3 dB/oitava) = corpo natural;
      - passa-alta ~200 Hz = tira o ronco grave (deixa o trovao aparecer);
      - passa-baixa ~6 kHz = agudos contidos (chuva suave, sem "chiado").
    """
    rng = np.random.default_rng(seed)
    branco = rng.standard_normal(n).astype(np.float32)
    espec = np.fft.rfft(branco)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    f = np.maximum(freqs, 1.0)
    inclina = 1.0 / np.sqrt(f)                       # rosa
    passa_alta = f / np.sqrt(f * f + hp_hz ** 2)     # ~200 Hz
    passa_baixa = 1.0 / np.sqrt(1.0 + (f / lp_hz) ** 2)  # ~6 kHz
    h = (inclina * passa_alta * passa_baixa).astype(np.float32)
    saida = np.fft.irfft(espec * h, n=n).astype(np.float32)
    return saida


def _envelope_rajada(n: int, seed: int, rate_hz: float = 0.08, prof: float = 0.22) -> np.ndarray:
    """Oscilacao LENTA de volume: a chuva 'respira' (mais forte / mais fraca),
    como rajadas reais de vento/chuva. Vetorizado via interpolacao."""
    rng = np.random.default_rng(seed + 3)
    npts = max(4, int(n / SR * rate_hz * 4))
    xs = np.linspace(0, n - 1, npts)
    ys = rng.random(npts).astype(np.float32)
    env = np.interp(np.arange(n), xs, ys).astype(np.float32)
    return (1.0 - prof) + prof * env


def _pingos(n: int, seed: int, densidade: float, faixa: tuple[float, float],
            dec: tuple[float, float], glide: float, ganho: float) -> np.ndarray:
    """Gotas INDIVIDUAIS (transientes) espalhadas no tempo (aleatorio).

    Cada gota = um "tec" curto de ruido + um tom que decai rapido. Com
    'glide' > 0 o tom CAI (efeito de pingo caindo/gotejando na poca).
    'densidade' = numero medio de gotas por segundo. Isso da o som de
    chuva batendo no telhado e pingando no chao da casa.
    """
    rng = np.random.default_rng(seed)
    out = np.zeros(n, dtype=np.float32)
    n_gotas = int(n / SR * densidade)
    if n_gotas <= 0:
        return out
    pos = rng.integers(0, max(1, n - 1), size=n_gotas)
    for p in pos:
        f0 = float(rng.uniform(*faixa))
        d = float(rng.uniform(*dec))
        L = int(d * 4.5 * SR)
        if L < 6:
            continue
        if p + L > n:
            L = n - p
        if L < 6:
            continue
        t = np.arange(L, dtype=np.float32) / SR
        env = np.exp(-t / d).astype(np.float32)
        if glide > 0.0:
            fq = f0 * (1.0 - glide * (t / (t[-1] + 1e-9)))
            fase = (2.0 * np.pi * np.cumsum(fq) / SR).astype(np.float32)
            tom = np.sin(fase).astype(np.float32)
        else:
            tom = np.sin(2.0 * np.pi * f0 * t).astype(np.float32)
        tec = rng.standard_normal(L).astype(np.float32) * np.exp(-t / 0.004).astype(np.float32)
        amp = float(rng.uniform(0.4, 1.0)) * ganho
        out[p:p + L] += (0.6 * tom + 0.5 * tec) * env * amp
    return out


def _trovao(n: int, centro_seg: float, seed: int, ganho: float) -> np.ndarray:
    """Um trovao: estouro de ruido grave (rumble) com ataque rapido e
    cauda longa que decai (rola ao longe). Somado sobre a chuva."""
    out = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(seed)
    dur = float(rng.uniform(5.0, 9.0))
    inicio = int(centro_seg * SR)
    comp = int(dur * SR)
    if inicio < 0:
        inicio = 0
    if inicio + comp > n:
        comp = n - inicio
    if comp <= SR:
        return out
    branco = rng.standard_normal(comp).astype(np.float32)
    espec = np.fft.rfft(branco)
    freqs = np.fft.rfftfreq(comp, 1.0 / SR)
    f = np.maximum(freqs, 1.0)
    passa_baixa = 1.0 / (1.0 + (f / 120.0) ** 2)   # enfatiza < 120 Hz
    passa_alta = f / np.sqrt(f * f + 25.0 ** 2)     # tira subgrave inaudivel
    rumble = np.fft.irfft(espec * passa_baixa * passa_alta, n=comp).astype(np.float32)
    t = np.arange(comp, dtype=np.float32) / SR
    atk = max(1, int(float(rng.uniform(0.2, 0.6)) * SR))
    env = np.ones(comp, dtype=np.float32)
    env[:atk] = np.linspace(0.0, 1.0, atk, dtype=np.float32)
    env *= np.exp(-t / (dur * 0.45)).astype(np.float32)
    seg = rumble * env
    pico = float(np.max(np.abs(seg))) + 1e-9
    out[inicio:inicio + comp] += (seg / pico) * ganho
    return out


def _loop_sem_emenda(x: np.ndarray, xf_seg: float = 6.0) -> np.ndarray:
    """Faz o sinal repetir SEM 'clique': mistura (crossfade de potencia
    igual) o FINAL com o INICIO, para que o fim se conecte ao comeco."""
    xf = int(xf_seg * SR)
    if xf * 2 >= len(x):
        return x
    cabeca = x[:xf].copy()
    cauda = x[-xf:].copy()
    t = np.linspace(0.0, 1.0, xf, dtype=np.float32)
    a = np.cos(t * math.pi / 2.0)
    b = np.sin(t * math.pi / 2.0)
    mistura = cauda * a + cabeca * b
    y = x[:-xf].copy()
    y[:xf] = mistura
    return y


def gerar_base_chuva(dur_seg: float, seed: int) -> np.ndarray:
    """Gera a base ESTEREO de chuva, pronta para LOOP perfeito.

    Chuva SUAVE (nao intensa) com PINGOS audiveis: gotas no telhado
    (agudas e secas) e pingando no chao/poca (mais graves, com gotejar).
    Retorna float32 shape (n, 2), pico ~-6 dBFS.
    """
    n = int(dur_seg * SR)
    xf = 6.0

    # 1) leito suave da chuva (nivel baixo, agudos contidos = menos "chiado")
    esq = _ruido_colorido(n, seed)
    dir_ = _ruido_colorido(n, seed + 101)  # canal decorrelacionado = estereo largo
    raj = _envelope_rajada(n, seed)
    esq *= raj
    dir_ *= raj
    norm = 0.20 / (np.percentile(np.abs(esq), 99.0) + 1e-9)
    esq *= norm
    dir_ *= norm

    # 2) PINGOS: telhado (agudos e secos) + chao/poca (graves com gotejar)
    esq += _pingos(n, seed + 11, densidade=20, faixa=(1800.0, 4200.0), dec=(0.008, 0.03), glide=0.0, ganho=0.5)
    dir_ += _pingos(n, seed + 12, densidade=20, faixa=(1800.0, 4200.0), dec=(0.008, 0.03), glide=0.0, ganho=0.5)
    esq += _pingos(n, seed + 21, densidade=5, faixa=(320.0, 720.0), dec=(0.09, 0.22), glide=0.5, ganho=0.7)
    dir_ += _pingos(n, seed + 22, densidade=5, faixa=(320.0, 720.0), dec=(0.09, 0.22), glide=0.5, ganho=0.7)

    # 3) trovoes distantes e suaves (poucos, baixo ganho)
    trov = np.zeros(n, dtype=np.float32)
    n_ev = max(1, int(dur_seg / 180.0))
    rng = np.random.default_rng(seed + 55)
    lim_i = 8.0
    lim_f = max(lim_i + 1.0, dur_seg - xf - 9.0)
    for i in range(n_ev):
        centro = float(rng.uniform(lim_i, lim_f))
        trov += _trovao(n, centro, seed + 200 + i, ganho=float(rng.uniform(0.35, 0.6)))
    esq += trov * 0.7
    dir_ += trov * 0.7

    # 4) emenda de loop imperceptivel
    esq = _loop_sem_emenda(esq, xf)
    dir_ = _loop_sem_emenda(dir_, xf)

    # 5) normaliza mais baixo (-6 dBFS) = chuva menos intensa
    pico = max(float(np.max(np.abs(esq))), float(np.max(np.abs(dir_)))) + 1e-9
    g = (10 ** (-6.0 / 20.0)) / pico
    esq *= g
    dir_ *= g

    m = min(len(esq), len(dir_))
    return np.stack([esq[:m], dir_[:m]], axis=1).astype(np.float32)


def salvar_wav(estereo: np.ndarray, caminho: str) -> None:
    dados = np.clip(estereo, -1.0, 1.0)
    ints = (dados * 32767.0).astype("<i2")
    with wave.open(caminho, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(ints.tobytes())


# ================================================================
# 2) VOZ DA INTRODUCAO (Edge TTS, gratis, sem GPU)
# ================================================================
async def _tts_async(texto: str, voz: str, caminho: str,
                     rate: str = "-12%", volume: str = "-5%", pitch: str = "-2Hz") -> None:
    import edge_tts

    try:
        com = edge_tts.Communicate(texto, voz, rate=rate, volume=volume, pitch=pitch)
    except TypeError:
        com = edge_tts.Communicate(texto, voz, rate=rate)
    await com.save(caminho)


def gerar_intro_voz(idioma: str, caminho: str) -> None:
    voz = VOICES.get(idioma, VOICES["pt"])
    texto = INTRO_TEXT.get(idioma, INTRO_TEXT["pt"])
    try:
        asyncio.run(_tts_async(texto, voz, caminho))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_tts_async(texto, voz, caminho))
        finally:
            loop.close()


# ================================================================
# 3) MONTAGEM DO VIDEO (ffmpeg): tela preta + audio
# ================================================================
def _rodar_ffmpeg(args: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0, (proc.stderr or "").strip()


def _duracao_audio(caminho: str) -> float | None:
    """Duracao (segundos) de um audio, lendo o stderr do ffmpeg (sem ffprobe)."""
    proc = subprocess.run([FFMPEG, "-hide_banner", "-i", caminho],
                          capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _args_video_preto() -> list[str]:
    return ["-f", "lavfi", "-i",
            f"color=c=black:s={VIDEO_W}x{VIDEO_H}:r={VIDEO_FPS}"]


def _cauda_encode(dur_seg: float, saida: str) -> list[str]:
    return [
        "-map", "0:v", "-map", "[aout]",
        "-t", f"{dur_seg:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
        "-pix_fmt", "yuv420p", "-r", str(VIDEO_FPS), "-g", "2",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", str(SR),
        "-movflags", "+faststart", saida,
    ]


def render_loop(fonte_audio: str, dur_seg: float, saida: str) -> tuple[bool, str]:
    """Clipe SO chuva/trovao (sem voz), emenda perfeita -> ideal p/ loop 24/7."""
    args = [
        *_args_video_preto(),
        "-stream_loop", "-1", "-i", fonte_audio,
        "-filter_complex", "[1:a]aformat=channel_layouts=stereo,asetpts=N/SR/TB[aout]",
        *_cauda_encode(dur_seg, saida),
    ]
    return _rodar_ffmpeg(args)


def render_com_intro(fonte_audio: str, voz_mp3: str, dur_seg: float, saida: str) -> tuple[bool, str]:
    """Video final: a VOZ da introducao toca PRIMEIRO (sozinha). Quando a
    fala termina, a CHUVA entra suavemente (fade-in) e segue ate o fim.
    Assim a chuva 'so entra depois de terminar de falar' (pedido do user)
    e nao ha mais nenhuma interrupcao ate o fim."""
    vdur = _duracao_audio(voz_mp3) or 22.0
    inicio = vdur + 0.5              # a chuva comeca logo apos a fala
    delay_ms = int(inicio * 1000)
    fade = 2.5
    filtro = (
        f"[2:a]aformat=channel_layouts=stereo:sample_rates={SR}[voz];"
        f"[1:a]aformat=channel_layouts=stereo,adelay={delay_ms}|{delay_ms},"
        f"afade=t=in:st={inicio:.2f}:d={fade}[chuva];"
        f"[chuva][voz]amix=inputs=2:duration=first:normalize=0[aout]"
    )
    args = [
        *_args_video_preto(),
        "-stream_loop", "-1", "-i", fonte_audio,
        "-i", voz_mp3,
        "-filter_complex", filtro,
        *_cauda_encode(dur_seg, saida),
    ]
    return _rodar_ffmpeg(args)


# ================================================================
# 4) METADADOS (titulo, descricao, hashtags) por idioma
# ================================================================
def _horas_label(minutos: float) -> str:
    if minutos >= 60 and abs(minutos % 60) < 1e-6:
        h = int(minutos // 60)
        return f"{h} Horas" if h > 1 else "1 Hora"
    if minutos >= 60:
        return f"{minutos/60:.1f} Horas".replace(".0", "")
    return f"{int(round(minutos))} Minutos"


META = {
    "pt": {
        "arquivo": "chuva_trovao_pt.txt",
        "titulo": "Chuva e Trovao para DORMIR 🌧️⛈️ | {dur} de Som Relaxante | Tela Preta, SEM Anuncios no Meio",
        "descricao": (
            "Feche os olhos, respire fundo e durma profundamente com o som suave da chuva "
            "e de trovoes distantes. Audio continuo, sem interrupcoes e com tela preta para "
            "economizar bateria e nao incomodar os olhos.\n\n"
            "🔔 Se inscreva e ative o sininho para nao perder os proximos sons relaxantes.\n"
            "💤 Ideal para dormir, relaxar, meditar, estudar, ler ou acalmar o bebe.\n"
            "⏱️ Coloque para tocar em LOOP e deixe rolar a noite toda.\n\n"
            "Sem musica, sem falas no meio, so a natureza. Bons sonhos.\n\n"
            "#chuva #chuvaparadormir #somdechuva #trovao #chuvaetrovao #relaxar #sono "
            "#sonoprofundo #paradormir #ruidobranco #sonsdanatureza #relaxamento #meditar #insonia"
        ),
    },
    "en": {
        "arquivo": "chuva_trovao_en.txt",
        "titulo": "Rain and Thunder Sounds for SLEEPING 🌧️⛈️ | {dur} of Relaxing Sound | Black Screen, NO Mid-roll Ads",
        "descricao": (
            "Close your eyes, take a deep breath and fall into a deep sleep with the gentle "
            "sound of rain and distant thunder. Continuous audio, no interruptions, and a "
            "black screen to save battery and rest your eyes.\n\n"
            "🔔 Subscribe and turn on notifications so you don't miss the next relaxing sounds.\n"
            "💤 Perfect for sleeping, relaxing, meditation, studying, reading, or soothing a baby.\n"
            "⏱️ Set it to LOOP and let it play all night long.\n\n"
            "No music, no talking in the middle, just nature. Sweet dreams.\n\n"
            "#rain #rainsounds #rainforsleeping #thunder #thunderstorm #relaxing #sleep "
            "#deepsleep #sleepsounds #whitenoise #naturesounds #relax #study #insomnia"
        ),
    },
}


def escrever_metadados(idioma: str, minutos: float, pasta: Path) -> Path:
    m = META[idioma]
    dur = _horas_label(minutos)
    txt = (
        f"TITULO:\n{m['titulo'].format(dur=dur)}\n\n"
        f"DESCRICAO:\n{m['descricao']}\n"
    )
    destino = pasta / m["arquivo"]
    destino.write_text(txt, encoding="utf-8")
    return destino


# ================================================================
# PRINCIPAL
# ================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Gera video de chuva+trovao para dormir (loop, tela preta).")
    ap.add_argument("--minutos", type=float, default=10.0, help="Duracao do video final (min). Padrao 10.")
    ap.add_argument("--segundos", type=int, default=0, help="MODO PREVIEW: duracao total em segundos (ignora --minutos).")
    ap.add_argument("--idioma", choices=["pt", "en", "ambos"], default="ambos")
    ap.add_argument("--audio", default="", help="Audio proprio de chuva (mp3/wav) no lugar do sintetizado.")
    ap.add_argument("--base-seg", type=float, default=480.0, help="Tamanho da base sintetizada / clipe de loop (s).")
    ap.add_argument("--seed", type=int, default=0, help="Semente (0 = aleatoria).")
    ap.add_argument("--saida", default="", help="Pasta de saida (padrao storage/ambiente).")
    args = ap.parse_args()

    raiz = Path(os.getenv("ATLAS_ROOT", os.getcwd()))
    pasta = Path(args.saida) if args.saida else (raiz / "storage" / "ambiente")
    pasta.mkdir(parents=True, exist_ok=True)

    preview = args.segundos > 0
    dur_total = float(args.segundos) if preview else float(args.minutos) * 60.0
    dur_total = max(dur_total, 30.0)  # precisa caber a intro
    base_seg = min(args.base_seg, dur_total) if preview else args.base_seg
    base_seg = max(base_seg, 30.0)
    seed = args.seed if args.seed else int.from_bytes(os.urandom(4), "little")

    idiomas = ["pt", "en"] if args.idioma == "ambos" else [args.idioma]

    print(f"[chuva] ffmpeg: {FFMPEG}")
    print(f"[chuva] saida: {pasta}")
    print(f"[chuva] duracao final: {dur_total:.0f}s | base/loop: {base_seg:.0f}s | seed: {seed}"
          + (" | MODO PREVIEW" if preview else ""))

    # 1) fonte de audio (sintetizada ou arquivo do usuario)
    if args.audio:
        fonte = str(Path(args.audio).resolve())
        if not Path(fonte).is_file():
            print(f"[chuva] ERRO: audio nao encontrado: {fonte}")
            return 2
        print(f"[chuva] usando audio proprio: {fonte}")
    else:
        print("[chuva] sintetizando chuva+trovao (numpy)...")
        base = gerar_base_chuva(base_seg, seed)
        fonte = str(pasta / "_chuva_base.wav")
        salvar_wav(base, fonte)
        print(f"[chuva] base gravada: {fonte} ({Path(fonte).stat().st_size/1e6:.1f} MB)")

    falhas = 0
    for idi in idiomas:
        sufixo = "preview_" + idi if preview else idi
        print(f"\n[chuva] === idioma: {idi} ===")

        # 2) voz da introducao
        voz_mp3 = str(pasta / f"_intro_{idi}.mp3")
        print("[chuva] gerando voz da introducao (edge-tts)...")
        gerar_intro_voz(idi, voz_mp3)
        if not Path(voz_mp3).is_file():
            print("[chuva] ERRO: falha ao gerar a voz da introducao.")
            falhas += 1
            continue

        # 3a) video final = intro (1x) + chuva
        saida_main = str(pasta / f"chuva_trovao_{sufixo}.mp4")
        print("[chuva] renderizando video com introducao...")
        ok, err = render_com_intro(fonte, voz_mp3, dur_total, saida_main)
        if ok:
            print(f"[chuva] OK -> {saida_main} ({Path(saida_main).stat().st_size/1e6:.1f} MB)")
        else:
            print(f"[chuva] ERRO no video com intro: {err[:400]}")
            falhas += 1

        # 3b) clipe SO chuva para loop 24/7 (sem voz)
        saida_loop = str(pasta / f"chuva_trovao_loop_{sufixo}.mp4")
        print("[chuva] renderizando clipe de loop (so chuva)...")
        ok2, err2 = render_loop(fonte, base_seg, saida_loop)
        if ok2:
            print(f"[chuva] OK -> {saida_loop} ({Path(saida_loop).stat().st_size/1e6:.1f} MB)")
        else:
            print(f"[chuva] ERRO no clipe de loop: {err2[:400]}")
            falhas += 1

        # 4) metadados (nao no preview)
        if not preview:
            meta = escrever_metadados(idi, args.minutos, pasta)
            print(f"[chuva] metadados -> {meta}")

    print("\n[chuva] concluido." if falhas == 0 else f"\n[chuva] concluido com {falhas} falha(s).")
    return 0 if falhas == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
