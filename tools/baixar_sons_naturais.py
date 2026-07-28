# ============================================================
# ATLAS OS - tools/baixar_sons_naturais.py
#
# Baixa GRAVACOES REAIS de sons da natureza (chuva, oceano, floresta,
# riacho, fogueira, vento, grilos, tempestade) de fontes com licenca
# LIVRE para uso comercial/monetizacao:
#
#   - Wikimedia Commons (CC0, Dominio Publico, CC-BY, CC-BY-SA).
#     Nao precisa de chave de API. Sao field recordings REAIS.
#   - (Opcional) Freesound.org, so os sons CC0, se existir a variavel
#     de ambiente FREESOUND_TOKEN. Melhor qualidade / mais longos.
#
# IMPORTANTE (protege o canal do usuario):
#   NAO baixamos audio de canais do YouTube (isso da Content ID/strike).
#   Aqui so entram licencas que PERMITEM uso comercial. Para CC-BY /
#   CC-BY-SA a lei pede CREDITO -> geramos CREDITOS.txt automaticamente.
#
# Uso (rode com o Python da venv do projeto):
#   .\.venv-dash\Scripts\python.exe tools\baixar_sons_naturais.py --categoria chuva --qtd 8
#   .\.venv-dash\Scripts\python.exe tools\baixar_sons_naturais.py --categoria todas --qtd 6
# ============================================================

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "AtlasOS-Ambience/1.0 (https://github.com/atlastrends/atlas-os; ambience sleep sounds)"

# ------------------------------------------------------------
# Configuracao por categoria: termos de busca, palavras a EXCLUIR
# (para nao entrar fala/musica/animal errado) e duracao minima.
# ------------------------------------------------------------
# Cada categoria aponta para CATEGORIAS TEMATICAS reais do Wikimedia Commons
# (a forma mais confiavel de achar gravacoes de campo VERDADEIRAS), mais
# termos de busca de reforco e uma WHITELIST (palavra que PRECISA aparecer
# nas categorias do arquivo -> garante que e o som certo, nao fala/musica).
CATEGORIAS: dict[str, dict] = {
    "chuva": {
        "cats": ["Sounds of rain", "Rain sounds"],
        "termos": ["rain ambience", "rainfall", "rain on roof", "sound of rain"],
        "whitelist": ["rain", "lluvia", "chuva", "regen", "pluie"],
        "excluir": ["thunder", "trueno", "storm", "urban", "street", "city", "traffic", "song",
                    "onweer", "donder", "trovao", "trovoada", "tonnerre", "gewitter",
                    "verkeer", "stemmen"],
        "min_seg": 15.0,
    },
    "tempestade": {
        "cats": ["Sounds of thunder", "Thunder", "Sounds of thunderstorms"],
        "termos": ["thunderstorm", "thunder rumble", "rain and thunder", "distant thunder"],
        "whitelist": ["thunder", "trueno", "storm", "trovao", "trovoada", "gewitter"],
        "excluir": ["traffic", "urban", "street", "song"],
        "min_seg": 12.0,
    },
    "oceano": {
        "cats": ["Sounds of the sea", "Ocean surface waves", "Breaking ocean waves"],
        "termos": ["ocean waves", "sea waves", "waves on shore", "surf beach"],
        "whitelist": ["wave", "ocean", "sea", "surf", "mar", "olas", "beach", "coast"],
        "excluir": ["boat engine", "motor", "ship", "harbor", "sine", "hertz",
                    "signal", "song", "march", "life on the ocean", "ambient noise"],
        "min_seg": 15.0,
    },
    "floresta": {
        "cats": ["Bird sounds", "Sounds of birds", "Forest sounds", "Birdsong"],
        "termos": ["forest ambience", "birdsong", "dawn chorus", "forest birds"],
        "whitelist": ["bird", "forest", "woodland", "jungle", "passaro", "ave", "chorus", "vogel"],
        "excluir": ["traffic", "car", "aircraft", "gunshot", "all nature"],
        "min_seg": 15.0,
    },
    "riacho": {
        "cats": ["Sounds of water", "Sounds of rivers", "Sounds of streams", "Streams"],
        "termos": ["stream water", "river flowing", "babbling brook", "creek water"],
        "whitelist": ["river", "stream", "creek", "brook", "water", "riacho", "rio", "arroyo", "waterfall"],
        "excluir": ["traffic", "tap", "faucet", "shower", "pool", "dishwasher",
                    "appliance", "droning", "humming", "frog", "toad",
                    "advertisement call", "atelopus", "mill", "song",
                    "brunnen", "fountain", "tram", "plaza", "thunder",
                    "horse-trough", "trough", "drainage", "bucket", "basin",
                    "bath", "phalarope", "agonistic", "sink", "kitchen",
                    "draining", "cecropis", "roepe", "freiburg"],
        "min_seg": 15.0,
    },
    "fogueira": {
        "cats": ["Campfires", "Fireplaces", "Bonfires", "Sounds of fire"],
        "termos": ["campfire crackling", "fireplace crackling", "bonfire", "wood fire crackling"],
        "whitelist": ["campfire", "fireplace", "bonfire", "crackling", "hearth",
                      "fogueira", "lareira", "lagerfeuer"],
        "excluir": ["gun", "explosion", "firework", "engine", "friendly fire",
                    "iraq", "gunfire", "wildfire", "military", "song",
                    "bones", "forge", "blacksmith", "iron working", "metal"],
        "min_seg": 10.0,
    },
    "vento": {
        "cats": ["Sounds of wind", "Wind sounds", "Recordings of wind"],
        "termos": ["gentle breeze", "soft wind", "light breeze", "wind ambience",
                   "breeze in trees", "leaves rustling in wind", "calm wind"],
        "whitelist": ["wind", "viento", "vento", "breeze", "rustling"],
        "excluir": ["turbine", "instrument", "traffic", "tornado", "song", "window",
                    "howling", "gale", "blustery", "storm", "gust", "strong wind",
                    "meters per second", "25 mps", "fiche technique", "ficus", "thunder",
                    "automobile", "vehicle engine", "tram", "cobblestone", "baby",
                    "babies", "children", "doppler", "plane", "personality rights",
                    "corner of", "street", "martian", "dust devil", "nasa",
                    "perseverance", "mars sound", "x100", "windy", "rain"],
        "min_seg": 12.0,
    },
    "grilos": {
        "cats": ["Cricket sounds", "Gryllidae", "Orthoptera sounds"],
        "termos": ["night crickets", "crickets", "summer night crickets", "cricket chorus",
                   "night ambience crickets", "crickets chirping", "insects night"],
        "whitelist": ["cricket", "gryllidae", "grillidae", "grillo", "grilo", "katydid", "orthoptera"],
        "excluir": ["traffic", "dog", "car", "cicada", "cicadidae", "song",
                    "ringing", "coil", "stridulation", "subfamily",
                    "odé", "ode collection", "advertisement call"],
        "min_seg": 12.0,
    },
}

# Palavras que NUNCA queremos num som para dormir (fala/pronuncia/musica...).
# 'song' NAO entra aqui de proposito (existe 'bird song' legitimo na floresta).
EXCLUIR_GLOBAL = [
    "pronunciation", "pronunciación", "vocabulary", "speech", "spoken",
    "voice", "voz", "vocal", "anthem", "hino", "interview", "podcast",
    "lecture", "sermon", "audiobook", "chapter", "narration", "narrator",
    "reading", "read by", "poem", "poetry", "address", "inaugural", "testimony",
    "monologue", "dialogue", "conversation", "news", "broadcast", "opera",
    "choir", "symphony", "sonata", "concerto", "hymn", "remix", "album",
    "soundtrack", "music", "guitar", "piano", "drum", "melody", "karaoke",
    "siren", "alarm", "vacuum", "ringtone", "beep", "test tone", "tts",
    "sine wave", "phonograph", "gramophone", "wax cylinder",
    "military", "gunfire", "artillery", "combat", "warfare", "iraq",
    "recording of this text", "fiche technique", "xeno-canto",
    "808", "horror", "skeleton",
]

# Extensoes de audio aceitas (evita baixar GIF/imagem/video como se fosse som).
AUDIO_EXTS = (".ogg", ".oga", ".mp3", ".wav", ".flac", ".opus", ".m4a")


def _sem_html(texto: str) -> str:
    """Remove tags HTML e espacos extras (campo Artist vem com <a>...)."""
    limpo = re.sub(r"<[^>]+>", "", texto or "")
    limpo = re.sub(r"\s+", " ", limpo).strip()
    return limpo


def _licenca_permitida(code: str, sem_sa: bool = False) -> bool:
    """Aceita so licenca que PERMITE uso comercial + derivada.
    OK: cc0, dominio publico (pd*), cc-by*, cc-by-sa* (a menos que --sem-sa).
    REJEITA: qualquer -nc- (nao-comercial) ou -nd- (sem derivadas)."""
    c = (code or "").lower().strip()
    if not c:
        return False
    if "-nc" in c or "-nd" in c or "noncommercial" in c:
        return False
    if sem_sa and "-sa" in c:
        return False
    return c in ("cc0", "cc-zero", "pd") or c.startswith("cc-by") or c.startswith("pd")


def _parse_paginas(dados: dict) -> list[dict]:
    paginas = (dados.get("query", {}) or {}).get("pages", {}) or {}
    saida: list[dict] = []
    for pg in paginas.values():
        info = (pg.get("imageinfo") or [{}])[0]
        ext = info.get("extmetadata", {}) or {}
        code = (ext.get("License", {}) or {}).get("value", "")
        saida.append({
            "titulo": pg.get("title", "").replace("File:", ""),
            "url": info.get("url", ""),
            "pagina": info.get("descriptionurl", ""),
            "mime": info.get("mime", ""),
            "tamanho": int(info.get("size", 0) or 0),
            "duracao": float(info.get("duration", 0.0) or 0.0),
            "licenca_code": code,
            "licenca": (ext.get("LicenseShortName", {}) or {}).get("value", code),
            "autor": _sem_html((ext.get("Artist", {}) or {}).get("value", "")),
            "descricao": _sem_html((ext.get("ImageDescription", {}) or {}).get("value", "")),
            "categorias": (ext.get("Categories", {}) or {}).get("value", ""),
        })
    return saida


def _consulta(params: dict, requests, rotulo: str) -> list[dict]:
    params = {**params, "action": "query", "format": "json",
              "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata"}
    try:
        r = requests.get(COMMONS_API, params=params,
                         headers={"User-Agent": USER_AGENT}, timeout=40)
        r.raise_for_status()
        return _parse_paginas(r.json())
    except Exception as exc:  # rede/JSON
        print(f"   ! falha em {rotulo}: {exc}")
        return []


def _buscar_texto(termo: str, limite: int, requests) -> list[dict]:
    """Busca por TEXTO (reforco). Exige whitelist depois no filtro."""
    return _consulta({
        "generator": "search",
        "gsrsearch": f"{termo} filetype:audio",
        "gsrnamespace": "6",
        "gsrlimit": str(limite),
    }, requests, f"busca '{termo}'")


def _buscar_categoria(cat_title: str, limite: int, requests) -> list[dict]:
    """Lista os ARQUIVOS de uma categoria tematica do Commons (mais confiavel:
    'Sounds of rain', 'Sounds of the sea', etc.)."""
    return _consulta({
        "generator": "categorymembers",
        "gcmtitle": f"Category:{cat_title}",
        "gcmtype": "file",
        "gcmlimit": str(limite),
    }, requests, f"categoria '{cat_title}'")


def _passa_filtro(cand: dict, cfg: dict, sem_sa: bool) -> bool:
    if not cand["url"]:
        return False
    # So AUDIO: rejeita imagem/video (ex.: um GIF de onda que passou por ter
    # "duracao") tanto pelo mime quanto pela extensao do arquivo.
    mime = (cand["mime"] or "").lower()
    if mime.startswith("video") or mime.startswith("image"):
        return False
    if Path(cand["url"]).suffix.lower() not in AUDIO_EXTS:
        return False
    # Duracao tem que ser CONHECIDA e >= minimo. Arquivos com duracao 0
    # (metadado ausente / corrompidos) costumam falhar ao decodificar.
    if cand["duracao"] < cfg["min_seg"]:
        return False
    if not _licenca_permitida(cand["licenca_code"], sem_sa):
        return False
    texto = (cand["titulo"] + " " + cand["descricao"] + " " + cand["categorias"]).lower()
    for palavra in EXCLUIR_GLOBAL + cfg.get("excluir", []):
        if palavra.lower() in texto:
            return False
    # WHITELIST: a palavra do tema tem que aparecer no titulo/categorias/descricao.
    # As EXCLUSOES acima (fala/musica/militar/etc.) ja derrubam o que 'casou'
    # so pela busca textual, entao aqui podemos olhar o texto completo.
    wl = cfg.get("whitelist", [])
    if wl and not any(w.lower() in texto for w in wl):
        return False
    return True


def _nome_arquivo_seguro(titulo: str, url: str, indice: int) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", Path(titulo).stem)[:50].strip("_") or "som"
    ext = Path(url).suffix.lower() or ".ogg"
    if ext not in (".ogg", ".oga", ".mp3", ".wav", ".flac", ".opus", ".m4a"):
        ext = ".ogg"
    return f"{indice:02d}_{base}{ext}"


def baixar_categoria(categoria: str, qtd: int, dest: Path,
                     sem_sa: bool = False) -> list[dict]:
    """Baixa ate 'qtd' gravacoes reais da categoria para 'dest'.
    Retorna a lista de metadados baixados e escreve CREDITOS.txt."""
    import requests

    cfg = CATEGORIAS[categoria]
    dest.mkdir(parents=True, exist_ok=True)

    # 1) coleta candidatos: PRIMEIRO das categorias tematicas do Commons
    #    (mais confiavel), depois reforca com busca textual. Dedup por url.
    vistos: set[str] = set()
    candidatos: list[dict] = []
    for cat_title in cfg.get("cats", []):
        for c in _buscar_categoria(cat_title, limite=50, requests=requests):
            if c["url"] and c["url"] not in vistos and _passa_filtro(c, cfg, sem_sa):
                vistos.add(c["url"])
                candidatos.append(c)
    for termo in cfg["termos"]:
        for c in _buscar_texto(termo, limite=15, requests=requests):
            if c["url"] and c["url"] not in vistos and _passa_filtro(c, cfg, sem_sa):
                vistos.add(c["url"])
                candidatos.append(c)

    # 2) prioriza os mais LONGOS (menos repeticao no leito final)
    candidatos.sort(key=lambda c: c["duracao"], reverse=True)

    if not candidatos:
        print(f"[sons] {categoria}: nenhum candidato passou no filtro de licenca/duracao.")
        return []

    # 3) baixa os melhores
    baixados: list[dict] = []
    for i, c in enumerate(candidatos):
        if len(baixados) >= qtd:
            break
        nome = _nome_arquivo_seguro(c["titulo"], c["url"], len(baixados) + 1)
        caminho = dest / nome
        try:
            with requests.get(c["url"], headers={"User-Agent": USER_AGENT},
                              stream=True, timeout=90) as resp:
                resp.raise_for_status()
                with open(caminho, "wb") as fh:
                    for bloco in resp.iter_content(chunk_size=1 << 16):
                        if bloco:
                            fh.write(bloco)
        except Exception as exc:
            print(f"   ! falha ao baixar {nome}: {exc}")
            continue
        c["arquivo"] = str(caminho)
        baixados.append(c)
        print(f"   + {nome}  ({c['duracao']:.0f}s, {c['licenca']})")

    # 4) creditos (obrigatorio p/ CC-BY / CC-BY-SA)
    if baixados:
        _escrever_creditos(categoria, baixados, dest)
    print(f"[sons] {categoria}: {len(baixados)} arquivo(s) baixado(s) em {dest}")
    return baixados


def _escrever_creditos(categoria: str, itens: list[dict], dest: Path) -> None:
    linhas = [f"CREDITOS / ATTRIBUTION - sons de '{categoria}'",
              "Fonte: Wikimedia Commons. Licencas com uso comercial permitido.",
              "Cole este bloco na descricao do video (exigido para CC-BY / CC-BY-SA).",
              "-" * 60]
    for it in itens:
        autor = it["autor"] or "Autor desconhecido"
        linhas.append(f"- \"{it['titulo']}\" por {autor} | {it['licenca']} | {it['pagina']}")
    (dest / "CREDITOS.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    # tambem em JSON para o gerador montar a descricao automaticamente
    (dest / "creditos.json").write_text(
        json.dumps(itens, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Baixa sons naturais reais (licenca livre) para os videos de ambiente.")
    ap.add_argument("--categoria", required=True,
                    help="chuva | tempestade | oceano | floresta | riacho | fogueira | vento | grilos | todas")
    ap.add_argument("--qtd", type=int, default=8, help="Quantos clipes por categoria (padrao 8).")
    ap.add_argument("--dest", default="", help="Pasta de saida (padrao storage/ambiente/fontes/<categoria>).")
    ap.add_argument("--sem-sa", action="store_true", help="Excluir licencas Share-Alike (CC-BY-SA).")
    args = ap.parse_args()

    raiz = Path(os.getenv("ATLAS_ROOT", os.getcwd()))
    base_dest = Path(args.dest) if args.dest else (raiz / "storage" / "ambiente" / "fontes")

    if args.categoria == "todas":
        cats = list(CATEGORIAS.keys())
    elif args.categoria in CATEGORIAS:
        cats = [args.categoria]
    else:
        print(f"ERRO: categoria invalida '{args.categoria}'. Opcoes: {', '.join(CATEGORIAS)} ou 'todas'.")
        return 2

    total = 0
    for cat in cats:
        dest = base_dest / cat if (args.categoria == "todas" or not args.dest) else Path(args.dest)
        print(f"\n[sons] === {cat} ===")
        total += len(baixar_categoria(cat, args.qtd, dest, sem_sa=args.sem_sa))

    print(f"\n[sons] concluido. {total} arquivo(s) no total.")
    return 0 if total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
