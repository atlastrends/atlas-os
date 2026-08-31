"""
Aba "Ebooks" do painel ATLAS.

Serve uma pagina propria em /ebooks (independente do SPA React) com botoes para
gerar cada tipo de livro (colorir kids/adulto, labirintos, gratidao, meal
planner, receitas air fryer) em EN e PT. A geracao roda numa thread de fundo
para nao travar o painel; a pagina acompanha o progresso por polling.

Nao toca no pipeline de video.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

router = APIRouter(tags=["Ebooks"])

OUTPUT_ROOT = os.getenv("ATLAS_EBOOK_OUTPUT", r"C:\atlas-os\ebooks")

# Jobs de geracao em memoria (id -> estado)
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()

_KIDS_ANIMALS = [
    "a baby elephant", "a fluffy puppy", "a cute kitten", "a baby bunny",
    "a baby panda", "a lion cub", "a baby fox", "a penguin chick", "a koala",
    "a baby owl", "a baby unicorn", "a friendly baby dinosaur", "a baby giraffe",
    "a hedgehog", "a baby seal", "a duckling", "a baby deer", "a baby turtle",
    "a teddy bear", "a baby hippo",
]
_ADULT_MANDALAS = [
    "an intricate floral mandala", "a geometric lotus mandala",
    "an ornate circular mandala with leaves", "a symmetrical star mandala",
    "a detailed rose mandala", "a mandala with feathers and swirls",
    "a sun and moon mandala", "a butterfly mandala", "a peacock feather mandala",
    "an arabesque ornamental mandala", "a mandala of interlaced hearts",
    "a snowflake style mandala",
]


def _now_slug(base: str) -> str:
    return f"{base}-{time.strftime('%m%d-%H%M%S')}"


def _titles(kind: str) -> tuple[dict, dict]:
    data = {
        "coloring_kids": (
            {"en": "Cute Baby Animals", "pt": "Animais Fofos para Colorir"},
            {"en": "A Fun Coloring Book for Kids Ages 4-8",
             "pt": "Um Livro de Colorir Divertido para Criancas de 4 a 8 Anos"},
        ),
        "coloring_adult": (
            {"en": "Mindful Mandalas", "pt": "Mandalas Relaxantes"},
            {"en": "Stress-Relief Coloring Book for Adults",
             "pt": "Livro de Colorir Antiestresse para Adultos"},
        ),
        "mazes": (
            {"en": "Amazing Mazes for Kids", "pt": "Labirintos Incriveis para Criancas"},
            {"en": "Fun Brain-Boosting Puzzles for Ages 6-10",
             "pt": "Desafios Divertidos para a Mente de 6 a 10 Anos"},
        ),
        "gratitude": (
            {"en": "My Daily Gratitude Journal", "pt": "Meu Diario de Gratidao"},
            {"en": "5 Minutes a Day to a Happier, More Positive You",
             "pt": "5 Minutos por Dia para uma Vida Mais Feliz e Positiva"},
        ),
        "meal": (
            {"en": "Weekly Meal Planner", "pt": "Planejador de Refeicoes"},
            {"en": "Plan Your Meals and Shopping with Ease",
             "pt": "Planeje suas Refeicoes e Compras com Facilidade"},
        ),
        "recipes": (
            {"en": "Easy Air Fryer Recipes", "pt": "Receitas Faceis na Air Fryer"},
            {"en": "Quick, Healthy and Delicious Everyday Meals",
             "pt": "Refeicoes Rapidas, Saudaveis e Deliciosas do Dia a Dia"},
        ),
    }
    return data[kind]


def _run_job(job_id: str, kind: str, count: int, languages: list[str], title: Optional[str]) -> None:
    job = _JOBS[job_id]

    def log(msg: str) -> None:
        job["log"].append(str(msg))
        if len(job["log"]) > 500:
            job["log"] = job["log"][-500:]

    try:
        from app.services.ebook_service import EbookService

        svc = EbookService(log=log)
        langs = tuple(languages) or ("en", "pt")
        titles, subtitles = _titles(kind)
        if title:
            titles = {lang: title for lang in langs}

        if kind == "coloring_kids":
            subs = [_KIDS_ANIMALS[i % len(_KIDS_ANIMALS)] for i in range(count)]
            res = svc.build_coloring_book(
                slug=_now_slug("cute-baby-animals"), titles=titles, subtitles=subtitles,
                subjects=subs, style="cute kawaii style with big friendly eyes, adorable for kids",
                detail="kids", languages=langs,
            )
        elif kind == "coloring_adult":
            subs = [_ADULT_MANDALAS[i % len(_ADULT_MANDALAS)] for i in range(count)]
            res = svc.build_coloring_book(
                slug=_now_slug("mindful-mandalas"), titles=titles, subtitles=subtitles,
                subjects=subs, style="symmetrical ornamental, bold clean lines, intricate detail",
                detail="adult", languages=langs,
            )
        elif kind == "mazes":
            res = svc.build_maze_book(
                slug=_now_slug("amazing-mazes"), titles=titles, subtitles=subtitles,
                count=count, languages=langs,
            )
        elif kind == "gratitude":
            res = svc.build_gratitude_journal(
                slug=_now_slug("gratitude-journal"), titles=titles, subtitles=subtitles,
                days=count, languages=langs,
            )
        elif kind == "meal":
            res = svc.build_meal_planner(
                slug=_now_slug("meal-planner"), titles=titles, subtitles=subtitles,
                weeks=count, languages=langs,
            )
        elif kind == "recipes":
            res = svc.build_recipe_book(
                slug=_now_slug("air-fryer-recipes"), titles=titles, subtitles=subtitles,
                theme="air fryer", count=count, languages=langs,
            )
        else:
            raise ValueError(f"tipo desconhecido: {kind}")

        job["result"] = res
        job["status"] = "done"
        log("[EBOOK] CONCLUIDO.")
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        log(f"[EBOOK] ERRO: {exc.__class__.__name__}: {exc}")
    finally:
        with _LOCK:
            _JOBS["_running"] = None


def _safe_path(rel: str) -> Optional[str]:
    root = os.path.abspath(OUTPUT_ROOT)
    full = os.path.abspath(os.path.join(root, rel))
    if full.startswith(root) and os.path.isfile(full):
        return full
    return None


@router.post("/ebooks/api/generate")
def api_generate(payload: dict = Body(...)) -> JSONResponse:
    kind = str(payload.get("kind", ""))
    if kind not in {"coloring_kids", "coloring_adult", "mazes", "gratitude", "meal", "recipes"}:
        return JSONResponse({"error": "tipo invalido"}, status_code=400)
    count = max(1, min(60, int(payload.get("count", 12))))
    languages = [l for l in payload.get("languages", ["en", "pt"]) if l in ("en", "pt")] or ["en", "pt"]
    title = (payload.get("title") or "").strip() or None

    with _LOCK:
        if _JOBS.get("_running"):
            return JSONResponse({"error": "Ja existe uma geracao em andamento."}, status_code=409)
        job_id = uuid.uuid4().hex[:12]
        _JOBS[job_id] = {"status": "running", "log": [], "result": None, "kind": kind}
        _JOBS["_running"] = job_id

    threading.Thread(target=_run_job, args=(job_id, kind, count, languages, title), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@router.get("/ebooks/api/jobs/{job_id}")
def api_job(job_id: str) -> JSONResponse:
    job = _JOBS.get(job_id)
    if not job:
        return JSONResponse({"error": "job nao encontrado"}, status_code=404)
    return JSONResponse({
        "status": job["status"],
        "log": job["log"][-60:],
        "result": job.get("result"),
    })


@router.get("/ebooks/api/list")
def api_list() -> JSONResponse:
    import json as _json

    items = []
    if os.path.isdir(OUTPUT_ROOT):
        for name in sorted(os.listdir(OUTPUT_ROOT), reverse=True):
            folder = os.path.join(OUTPUT_ROOT, name)
            meta_path = os.path.join(folder, "metadata.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    meta = _json.load(fh)
            except Exception:
                continue
            thumb = None
            for cand in ("preview_page.png", "cover_source.png"):
                if os.path.isfile(os.path.join(folder, cand)):
                    thumb = f"{name}/{cand}"
                    break
            items.append({
                "slug": name,
                "title": meta.get("titles", {}).get("en") or name,
                "kind": meta.get("kind", ""),
                "pages": meta.get("pages", ""),
                "languages": meta.get("languages", []),
                "pdfs": {k: f"{name}/{v}" for k, v in meta.get("pdfs", {}).items()},
                "thumb": thumb,
            })
    return JSONResponse({"items": items})


@router.get("/ebooks/api/file")
def api_file(path: str = Query(...)) -> Any:
    full = _safe_path(path)
    if not full:
        return JSONResponse({"error": "arquivo nao encontrado"}, status_code=404)
    return FileResponse(full)


@router.get("/ebooks", response_class=HTMLResponse)
def ebooks_page() -> HTMLResponse:
    return HTMLResponse(_PAGE_HTML)


_PAGE_HTML = """<!doctype html>
<html lang="pt-br"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ATLAS - Ebooks</title>
<style>
  :root{--bg:#0f1523;--card:#18203400;--panel:#1b2436;--ink:#e8edf6;--mut:#9fb0c9;--acc:#3b82f6;--acc2:#22c55e;--line:#2a3550}
  *{box-sizing:border-box}
  body{margin:0;padding-left:72px;background:linear-gradient(180deg,#0d1220,#0f1523);color:var(--ink);font:15px/1.5 Segoe UI,system-ui,sans-serif}
  #atlas-rail{position:fixed;left:0;top:0;width:72px;height:100vh;background:#0a0d18;border-right:1px solid #26304a;z-index:99999;display:flex;flex-direction:column;align-items:center;padding-top:16px;gap:8px}
  #atlas-rail .brand{color:#5b6b8c;font-size:10px;letter-spacing:.12em;margin-bottom:10px;font-weight:700}
  #atlas-rail a{display:flex;flex-direction:column;align-items:center;gap:4px;width:62px;padding:9px 0;border-radius:12px;color:#c7d2e6;text-decoration:none;font-size:11px;font-weight:600}
  #atlas-rail a:hover,#atlas-rail a.active{background:#182238;color:#fff}
  #atlas-rail .ico{font-size:22px;line-height:1}
  header{padding:22px 28px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px}
  header h1{font-size:20px;margin:0;font-weight:700}
  header .tag{font-size:12px;color:var(--mut);border:1px solid var(--line);padding:3px 8px;border-radius:20px}
  .wrap{max-width:1100px;margin:0 auto;padding:24px 28px}
  h2{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:26px 0 12px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
  .type{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;cursor:pointer;transition:.15s}
  .type:hover{border-color:var(--acc);transform:translateY(-2px)}
  .type.sel{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
  .type .emoji{font-size:26px}
  .type b{display:block;margin:8px 0 3px}
  .type span{color:var(--mut);font-size:13px}
  .controls{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin-top:16px;display:flex;flex-wrap:wrap;gap:18px;align-items:end}
  label{display:block;font-size:12px;color:var(--mut);margin-bottom:6px}
  input[type=number],input[type=text]{background:#0f1626;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:9px 11px;font-size:14px}
  input[type=text]{min-width:260px}
  .chk{display:inline-flex;align-items:center;gap:6px;margin-right:14px;color:var(--ink)}
  button.go{background:var(--acc);color:#fff;border:0;border-radius:9px;padding:11px 22px;font-size:15px;font-weight:600;cursor:pointer}
  button.go:disabled{opacity:.5;cursor:not-allowed}
  #log{background:#0a0f1c;border:1px solid var(--line);border-radius:10px;padding:12px;height:180px;overflow:auto;font:12px/1.5 Consolas,monospace;color:#9fe6b0;white-space:pre-wrap;margin-top:14px;display:none}
  .books{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
  .book{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
  .book img{width:100%;height:200px;object-fit:cover;background:#0a0f1c;display:block}
  .book .b{padding:11px 13px}
  .book b{font-size:14px}
  .book .meta{color:var(--mut);font-size:12px;margin:3px 0 9px}
  .book a{display:inline-block;background:#0f1626;border:1px solid var(--line);color:var(--ink);text-decoration:none;border-radius:7px;padding:5px 10px;font-size:12px;margin:0 5px 5px 0}
  .book a:hover{border-color:var(--acc)}
  .hint{color:var(--mut);font-size:13px;margin-top:6px}
</style></head>
<body>
<nav id="atlas-rail"><div class="brand">ATLAS</div>
<a href="/" title="Painel"><span class="ico">🏠</span>Painel</a>
<a href="/stories" title="Historias"><span class="ico">🎬</span>Histórias</a>
<a href="/ebooks" class="active" title="Ebooks"><span class="ico">📚</span>Ebooks</a>
</nav>
<header><h1>ATLAS · Estudio de Ebooks</h1><span class="tag">colorir · atividades · planners · receitas</span><span class="tag">EN + PT · selo de IA</span></header>
<div class="wrap">
  <h2>1. Escolha o tipo</h2>
  <div class="grid" id="types"></div>
  <div class="controls">
    <div><label>Quantidade de paginas</label><input type="number" id="count" value="12" min="1" max="60"></div>
    <div><label>Idiomas</label>
      <span class="chk"><input type="checkbox" id="en" checked> EN</span>
      <span class="chk"><input type="checkbox" id="pt" checked> PT</span>
    </div>
    <div><label>Titulo (opcional)</label><input type="text" id="title" placeholder="deixe vazio para usar o padrao"></div>
    <button class="go" id="go" disabled>Gerar livro</button>
  </div>
  <div class="hint" id="hint">Selecione um tipo acima. A geracao com imagens (colorir/receitas) leva ~1-2 min.</div>
  <div id="log"></div>

  <h2>Livros gerados</h2>
  <div class="books" id="books"></div>
</div>
<script>
const TYPES=[
 {k:"coloring_kids",e:"🎨",t:"Colorir Kids",d:"Animais fofos (4-8)"},
 {k:"coloring_adult",e:"🌀",t:"Colorir Adulto",d:"Mandalas antiestresse"},
 {k:"mazes",e:"🧩",t:"Labirintos",d:"Atividades (6-10)"},
 {k:"gratitude",e:"📔",t:"Diario de Gratidao",d:"Planner diario"},
 {k:"meal",e:"🥗",t:"Meal Planner",d:"Cardapio + compras"},
 {k:"recipes",e:"🍳",t:"Receitas Air Fryer",d:"IA + fotos"},
];
let sel=null;
const tEl=document.getElementById('types');
TYPES.forEach(x=>{const d=document.createElement('div');d.className='type';d.innerHTML=`<div class="emoji">${x.e}</div><b>${x.t}</b><span>${x.d}</span>`;d.onclick=()=>{document.querySelectorAll('.type').forEach(n=>n.classList.remove('sel'));d.classList.add('sel');sel=x.k;document.getElementById('go').disabled=false;};tEl.appendChild(d);});

async function refresh(){
  const r=await fetch('/ebooks/api/list');const j=await r.json();
  const b=document.getElementById('books');b.innerHTML='';
  if(!j.items.length){b.innerHTML='<div class="hint">Nenhum livro ainda. Gere o primeiro acima.</div>';return;}
  j.items.forEach(it=>{
    const el=document.createElement('div');el.className='book';
    const img=it.thumb?`<img src="/ebooks/api/file?path=${encodeURIComponent(it.thumb)}">`:'<img>';
    let links='';for(const[k,v]of Object.entries(it.pdfs||{})){links+=`<a href="/ebooks/api/file?path=${encodeURIComponent(v)}" target="_blank">PDF ${k.toUpperCase()}</a>`;}
    el.innerHTML=img+`<div class="b"><b>${it.title}</b><div class="meta">${it.kind} · ${it.pages} pág · ${(it.languages||[]).join('/')}</div>${links}</div>`;
    b.appendChild(el);
  });
}

document.getElementById('go').onclick=async()=>{
  if(!sel)return;
  const langs=[];if(document.getElementById('en').checked)langs.push('en');if(document.getElementById('pt').checked)langs.push('pt');
  const body={kind:sel,count:+document.getElementById('count').value,languages:langs,title:document.getElementById('title').value};
  const go=document.getElementById('go');go.disabled=true;go.textContent='Gerando...';
  const log=document.getElementById('log');log.style.display='block';log.textContent='Iniciando...';
  const r=await fetch('/ebooks/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json();
  if(j.error){log.textContent='ERRO: '+j.error;go.disabled=false;go.textContent='Gerar livro';return;}
  const id=j.job_id;
  const poll=setInterval(async()=>{
    const rr=await fetch('/ebooks/api/jobs/'+id);const jj=await rr.json();
    log.textContent=(jj.log||[]).join('\\n');log.scrollTop=log.scrollHeight;
    if(jj.status==='done'||jj.status==='error'){clearInterval(poll);go.disabled=false;go.textContent='Gerar livro';refresh();}
  },1500);
};
refresh();
</script>
</body></html>"""
