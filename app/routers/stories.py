"""
Aba "Historias" do painel ATLAS.

Pagina propria em /stories: botao "Criar 3 historias" (terror ou policial),
mesmo estilo visual sempre, sem repetir (indice), video vertical 9:16 em HD.
Geracao roda em thread de fundo; a pagina acompanha por polling e lista os
videos gerados (marcados como prioridade para subir primeiro nos canais).
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

router = APIRouter(tags=["Stories"])

STORY_ROOT = os.getenv("ATLAS_STORY_OUTPUT", r"C:\atlas-os\stories")

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _run_job(job_id: str, genre: str, count: int, languages: list[str], scenes: int) -> None:
    job = _JOBS[job_id]

    def log(msg: str) -> None:
        job["log"].append(str(msg))
        if len(job["log"]) > 600:
            job["log"] = job["log"][-600:]

    try:
        from app.services.story_service import StoryService

        svc = StoryService(log=log)
        res = svc.generate_batch(count=count, genre=genre, languages=tuple(languages) or ("en", "pt"), scenes=scenes)
        job["result"] = res
        job["status"] = "done"
        log("[STORY] CONCLUIDO.")
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        log(f"[STORY] ERRO: {exc.__class__.__name__}: {exc}")
    finally:
        with _LOCK:
            _JOBS["_running"] = None


def publish_story_folder(slug: str, log: "Any" = None) -> dict:
    """Publica UMA historia/episodio (pasta em STORY_ROOT) nas contas de
    TREND (kind='trend'), nunca nas de afiliado. Funcao PURA (sem depender
    do dicionario _JOBS), para poder ser chamada tanto pelo botao manual
    "Postar" quanto pelo agendador automatico do Diario da Bela."""
    import json as _json

    log = log or (lambda *_: None)

    from app.publishing.base import PublishRequest
    from app.publishing.registry import PLATFORMS, get_publisher

    folder = os.path.join(STORY_ROOT, slug)
    with open(os.path.join(folder, "story.json"), encoding="utf-8") as fh:
        meta = _json.load(fh)
    hashtags_str = meta.get("hashtags", "")
    tags = [t.lstrip("#") for t in hashtags_str.split() if t.strip()]
    posted = meta.get("posted", {})
    assets_info: dict[str, dict] = {}
    results: dict[str, dict] = {}
    for lang, filename in (meta.get("videos", {}) or {}).items():
        country = "BR" if lang == "pt" else "US"
        title = meta.get(f"title_{lang}") or meta.get("title_en") or slug
        affiliate_caption = meta.get(f"affiliate_caption_{lang}", "")
        full = "\n\n".join(
            part
            for part in (title, affiliate_caption, hashtags_str)
            if str(part).strip()
        ).strip()
        rel_path = f"stories/{slug}/{filename}"  # servido em /media/stories/...
        req = PublishRequest(
            video_path=rel_path, title=title, description=full, caption=full,
            hashtags=tags, kind="trend", language=lang, country_code=country,
        )
        assets_info[lang] = {
            "title": title, "rel_path": rel_path, "country": country,
            "hashtags": tags, "caption": full,
            "genre": meta.get("genre"), "series": meta.get("series"),
        }
        log(f"[POST] {lang.upper()} '{title}' -> contas TREND {country}")
        for platform in PLATFORMS:
            pub = get_publisher(platform)
            if pub is None:
                continue
            if not pub.is_configured():
                log(f"[POST]   {platform}: credenciais ausentes ({', '.join(pub.missing_credentials())})")
                continue
            try:
                res = pub.publish(req)
                posted.setdefault(lang, {})[platform] = res.status
                results.setdefault(lang, {})[platform] = res
                url = getattr(res, "external_url", None) or ""
                extra = (f" -> {url}" if url else "") + (f" ({res.error})" if res.error and res.status != "published" else "")
                log(f"[POST]   {platform}: {res.status}{extra}")
            except Exception as exc:  # noqa: BLE001
                log(f"[POST]   {platform}: erro {exc.__class__.__name__}: {exc}")
    meta["posted"] = posted
    with open(os.path.join(folder, "story.json"), "w", encoding="utf-8") as fh:
        _json.dump(meta, fh, ensure_ascii=False, indent=2)
    _register_publications(slug, assets_info, results, log)
    return posted


def _run_post(job_id: str, slug: str) -> None:
    """Publica a historia SOMENTE nas contas de TREND (kind='trend'),
    nunca nas de afiliado (Achados/Finds)."""
    job = _JOBS[job_id]

    def log(msg: str) -> None:
        job["log"].append(str(msg))
        if len(job["log"]) > 400:
            job["log"] = job["log"][-400:]

    try:
        job["result"] = publish_story_folder(slug, log)
        job["status"] = "done"
        log("[POST] CONCLUIDO.")
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        log(f"[POST] ERRO: {exc.__class__.__name__}: {exc}")
    finally:
        with _LOCK:
            _JOBS["_running"] = None


def _register_publications(slug: str, assets_info: dict, results: dict, log=lambda *_: None) -> None:
    """Espelha a publicacao da historia no banco (VideoAsset REEL + Publication
    por plataforma) para aparecer na pagina de Publicacoes, igual reels/afiliados.
    'results' mapeia lang -> plataforma -> PublishResult (ou string de status no
    backfill de historias ja postadas). Nunca reenvia video: so registra."""
    try:
        from datetime import datetime, timezone

        from app.core.database import SessionLocal
        from app.models.dashboard import (
            Publication,
            PublicationStatusEnum,
            VideoAsset,
            VideoKindEnum,
            VideoStatusEnum,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"[POST]   (registro no painel indisponivel: {exc})")
        return

    status_map = {
        "published": PublicationStatusEnum.PUBLISHED,
        "failed": PublicationStatusEnum.FAILED,
        "credentials_missing": PublicationStatusEnum.CREDENTIALS_MISSING,
        "rate_limited": PublicationStatusEnum.RATE_LIMITED,
        "skipped": PublicationStatusEnum.SKIPPED,
        "queued": PublicationStatusEnum.QUEUED,
        "uploading": PublicationStatusEnum.UPLOADING,
    }
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for lang, info in assets_info.items():
            ext_key = f"story:{slug}:{lang}"
            asset = (
                db.query(VideoAsset)
                .filter(
                    VideoAsset.kind == VideoKindEnum.REEL,
                    VideoAsset.external_key == ext_key,
                )
                .first()
            )
            if asset is None:
                asset = VideoAsset(
                    kind=VideoKindEnum.REEL,
                    external_key=ext_key,
                    status=VideoStatusEnum.CREATED,
                )
                db.add(asset)
            asset.title = info.get("title")
            asset.topic = info.get("title")
            asset.language = lang
            asset.country_code = info.get("country")
            asset.video_path = info.get("rel_path")
            asset.payload = {
                "source": "stories",
                "slug": slug,
                "genre": info.get("genre"),
                "series": info.get("series"),
                "hashtags": info.get("hashtags", []),
                "caption": info.get("caption", ""),
            }
            db.commit()
            db.refresh(asset)

            any_published = False
            for platform, res in (results.get(lang, {}) or {}).items():
                status_str = res.status if hasattr(res, "status") else str(res)
                pub = (
                    db.query(Publication)
                    .filter(
                        Publication.video_asset_id == asset.id,
                        Publication.platform == platform,
                    )
                    .first()
                )
                if pub is None:
                    pub = Publication(
                        video_asset_id=asset.id,
                        platform=platform,
                        status=PublicationStatusEnum.QUEUED,
                    )
                    db.add(pub)
                pub.status = status_map.get(status_str, PublicationStatusEnum.FAILED)
                pub.external_id = getattr(res, "external_id", None)
                pub.external_url = getattr(res, "external_url", None)
                pub.error = getattr(res, "error", None)
                if pub.status == PublicationStatusEnum.PUBLISHED:
                    any_published = True
                    pub.published_at = now
                db.commit()

            if any_published:
                asset.status = VideoStatusEnum.PUBLISHED
                asset.published_at = now
                db.commit()
        log("[POST]   registrado na pagina de Publicacoes.")
    except Exception as exc:  # noqa: BLE001
        log(f"[POST]   (falha ao registrar no painel: {exc.__class__.__name__}: {exc})")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def _run_diario_job(job_id: str, count: int) -> None:
    job = _JOBS[job_id]

    def log(msg: str) -> None:
        job["log"].append(str(msg))
        if len(job["log"]) > 600:
            job["log"] = job["log"][-600:]

    try:
        from app.services.teen_diary_service import TeenDiaryService

        svc = TeenDiaryService(log=log)
        res = svc.generate_next(count=count)
        job["result"] = res
        job["status"] = "done"
        log("[DIARY] CONCLUIDO.")
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        log(f"[DIARY] ERRO: {exc.__class__.__name__}: {exc}")
    finally:
        with _LOCK:
            _JOBS["_running"] = None


def _safe(rel: str):
    root = os.path.abspath(STORY_ROOT)
    full = os.path.abspath(os.path.join(root, rel))
    return full if full.startswith(root) and os.path.isfile(full) else None


@router.post("/stories/api/generate")
def api_generate(payload: dict = Body(...)) -> JSONResponse:
    genre = payload.get("genre", "horror")
    if genre not in ("horror", "crime"):
        return JSONResponse({"error": "genero invalido"}, status_code=400)
    count = max(1, min(5, int(payload.get("count", 3))))
    scenes = max(3, min(20, int(payload.get("scenes", 6))))
    languages = [l for l in payload.get("languages", ["en", "pt"]) if l in ("en", "pt")] or ["en", "pt"]
    with _LOCK:
        if _JOBS.get("_running"):
            return JSONResponse({"error": "Ja existe uma geracao em andamento."}, status_code=409)
        job_id = uuid.uuid4().hex[:12]
        _JOBS[job_id] = {"status": "running", "log": [], "result": None, "kind": "generate"}
        _JOBS["_running"] = job_id
    threading.Thread(target=_run_job, args=(job_id, genre, count, languages, scenes), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@router.post("/stories/api/diario/generate")
def api_diario_generate(payload: dict = Body(...)) -> JSONResponse:
    """Gera o(s) proximo(s) episodio(s) do Diario da Bela, continuando de
    onde a bible (memoria persistente) parou. count=2 gera o dia inteiro
    (parte 1 + parte 2) de uma vez; count=1 gera so a proxima parte."""
    count = max(1, min(4, int(payload.get("count", 1))))
    with _LOCK:
        if _JOBS.get("_running"):
            return JSONResponse({"error": "Ja existe uma geracao em andamento."}, status_code=409)
        job_id = uuid.uuid4().hex[:12]
        _JOBS[job_id] = {"status": "running", "log": [], "result": None, "kind": "diario_generate"}
        _JOBS["_running"] = job_id
    threading.Thread(target=_run_diario_job, args=(job_id, count), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@router.get("/stories/api/diario/timeline")
def api_diario_timeline() -> JSONResponse:
    """Memoria continua (bible) + lista de episodios, para a aba mostrar a
    linha do tempo da historia (o que ja aconteceu, personagens, etc.)."""
    from app.services.teen_diary_service import load_bible

    bible = load_bible()
    return JSONResponse({
        "characters": bible.get("characters", {}),
        "established_facts": bible.get("established_facts", []),
        "recent_summaries": list(reversed(bible.get("recent_summaries", [])))[:10],
        "episodes": list(reversed(bible.get("episodes", []))),
        "next_day": bible.get("next_day", 1),
        "next_part": bible.get("next_part", 1),
    })


@router.get("/stories/api/jobs/{job_id}")
def api_job(job_id: str) -> JSONResponse:
    job = _JOBS.get(job_id)
    if not job:
        return JSONResponse({"error": "job nao encontrado"}, status_code=404)
    return JSONResponse({"status": job["status"], "log": job["log"][-80:], "result": job.get("result")})


@router.get("/stories/api/current")
def api_current() -> JSONResponse:
    """Job em andamento (para a pagina reconectar ao voltar de outra aba)."""
    with _LOCK:
        jid = _JOBS.get("_running")
    job = _JOBS.get(jid) if jid else None
    if not job or job.get("status") != "running":
        return JSONResponse({"running": False})
    return JSONResponse({
        "running": True, "job_id": jid, "status": job.get("status"),
        "kind": job.get("kind", "generate"), "log": job.get("log", [])[-80:],
    })


@router.get("/stories/api/list")
def api_list() -> JSONResponse:
    import json as _json

    items = []
    if os.path.isdir(STORY_ROOT):
        for name in sorted(os.listdir(STORY_ROOT), reverse=True):
            folder = os.path.join(STORY_ROOT, name)
            meta_path = os.path.join(folder, "story.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    meta = _json.load(fh)
            except Exception:
                continue
            items.append({
                "slug": name,
                "title": meta.get("title_en") or name,
                "title_pt": meta.get("title_pt", ""),
                "genre": meta.get("genre", ""),
                "series": meta.get("series", ""),
                "hashtags": meta.get("hashtags", ""),
                "posted": meta.get("posted", {}),
                "created": meta.get("created", ""),
                "cover": f"{name}/cover.png" if os.path.isfile(os.path.join(folder, "cover.png")) else None,
                "videos": {k: f"{name}/{v}" for k, v in meta.get("videos", {}).items()},
            })
    return JSONResponse({"count": len(items), "items": items})


@router.get("/stories/api/file")
def api_file(path: str = Query(...)) -> Any:
    full = _safe(path)
    if not full:
        return JSONResponse({"error": "arquivo nao encontrado"}, status_code=404)
    return FileResponse(full)


@router.post("/stories/api/post")
def api_post(payload: dict = Body(...)) -> JSONResponse:
    slug = str(payload.get("slug", "")).strip()
    root = os.path.abspath(STORY_ROOT)
    folder = os.path.abspath(os.path.join(root, slug))
    if not slug or not folder.startswith(root + os.sep) or not os.path.isfile(os.path.join(folder, "story.json")):
        return JSONResponse({"error": "historia invalida"}, status_code=400)
    with _LOCK:
        if _JOBS.get("_running"):
            return JSONResponse({"error": "Ja existe uma operacao em andamento."}, status_code=409)
        job_id = uuid.uuid4().hex[:12]
        _JOBS[job_id] = {"status": "running", "log": [], "result": None, "kind": "post"}
        _JOBS["_running"] = job_id
    threading.Thread(target=_run_post, args=(job_id, slug), daemon=True).start()
    return JSONResponse({"job_id": job_id})


@router.post("/stories/api/delete")
def api_delete(payload: dict = Body(...)) -> JSONResponse:
    import shutil
    slug = str(payload.get("slug", "")).strip()
    root = os.path.abspath(STORY_ROOT)
    folder = os.path.abspath(os.path.join(root, slug))
    # Apaga so a pasta da historia; o _index.json (historico p/ nao repetir) fica.
    if not slug or slug.startswith("_") or not folder.startswith(root + os.sep) or not os.path.isdir(folder):
        return JSONResponse({"error": "historia invalida"}, status_code=400)
    shutil.rmtree(folder, ignore_errors=True)
    return JSONResponse({"ok": True})


@router.get("/stories", response_class=HTMLResponse)
def stories_page() -> HTMLResponse:
    return HTMLResponse(_PAGE)


_PAGE = """<!doctype html>
<html lang="pt-br"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ATLAS - Historias</title>
<style>
  :root{--bg:#0b0d16;--panel:#151a2b;--ink:#e8edf6;--mut:#93a1bd;--acc:#7c3aed;--line:#26304a}
  *{box-sizing:border-box}
  body{margin:0;padding-left:72px;background:radial-gradient(1200px 600px at 70% -10%,#1b1030,#0b0d16);color:var(--ink);font:15px/1.5 Segoe UI,system-ui,sans-serif}
  #atlas-rail{position:fixed;left:0;top:0;width:72px;height:100vh;background:#0a0d18;border-right:1px solid #26304a;z-index:99999;display:flex;flex-direction:column;align-items:center;padding-top:16px;gap:8px}
  #atlas-rail .brand{color:#5b6b8c;font-size:10px;letter-spacing:.12em;margin-bottom:10px;font-weight:700}
  #atlas-rail a{display:flex;flex-direction:column;align-items:center;gap:4px;width:62px;padding:9px 0;border-radius:12px;color:#c7d2e6;text-decoration:none;font-size:11px;font-weight:600}
  #atlas-rail a:hover,#atlas-rail a.active{background:#182238;color:#fff}
  #atlas-rail .ico{font-size:22px;line-height:1}
  header{padding:22px 28px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  header h1{font-size:20px;margin:0}
  header .tag{font-size:12px;color:var(--mut);border:1px solid var(--line);padding:3px 8px;border-radius:20px}
  .wrap{max-width:1100px;margin:0 auto;padding:24px 28px}
  h2{font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:24px 0 12px}
  .row{display:flex;flex-wrap:wrap;gap:16px;align-items:end;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px}
  label{display:block;font-size:12px;color:var(--mut);margin-bottom:6px}
  select,input[type=number]{background:#0e1424;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:10px 12px;font-size:14px}
  .chk{display:inline-flex;align-items:center;gap:6px;margin-right:12px}
  button.go{background:linear-gradient(90deg,#7c3aed,#db2777);color:#fff;border:0;border-radius:10px;padding:13px 26px;font-size:16px;font-weight:700;cursor:pointer}
  button.go:disabled{opacity:.5;cursor:not-allowed}
  .note{color:var(--mut);font-size:13px;margin-top:10px}
  #log{background:#070a12;border:1px solid var(--line);border-radius:10px;padding:12px;height:200px;overflow:auto;font:12px/1.5 Consolas,monospace;color:#c4b5fd;white-space:pre-wrap;margin-top:14px;display:none}
  .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
  .card video{width:100%;height:360px;object-fit:cover;background:#000;display:block}
  .card .b{padding:12px 14px}
  .card b{font-size:14px}
  .card .m{color:var(--mut);font-size:12px;margin:4px 0 9px}
  .badge{display:inline-block;background:#3b1d6e;color:#d6bcfa;border-radius:6px;padding:2px 8px;font-size:11px;margin-left:6px}
  .card a{display:inline-block;background:#0e1424;border:1px solid var(--line);color:var(--ink);text-decoration:none;border-radius:7px;padding:6px 11px;font-size:12px;margin:0 6px 6px 0}
  .card a:hover{border-color:var(--acc)}
  .tabs{display:flex;gap:8px;padding:0 28px;margin-top:14px}
  .tabs button{background:#0e1424;border:1px solid var(--line);color:var(--mut);border-radius:10px 10px 0 0;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer}
  .tabs button.on{background:var(--panel);color:#fff;border-color:var(--acc);border-bottom-color:var(--panel)}
  .tabsec{display:none}
  .tabsec.on{display:block}
  .bible-box{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px}
  .bible-box h3{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}
  .bible-box .facts{font-size:13px;line-height:1.6;color:#d6bcfa}
  .bible-box .sumline{font-size:13px;color:var(--ink);border-left:2px solid var(--acc);padding-left:10px;margin:6px 0}
  .placeholder-warn{background:#3a1f0a;border:1px solid #7c4a12;color:#fde68a;border-radius:10px;padding:10px 14px;font-size:12px;margin-bottom:14px}
</style></head>
<body>
<nav id="atlas-rail"><div class="brand">ATLAS</div>
<a href="/" title="Painel"><span class="ico">🏠</span>Painel</a>
<a href="/stories" class="active" title="Historias"><span class="ico">🎬</span>Histórias</a>
<a href="/ebooks" title="Ebooks"><span class="ico">📚</span>Ebooks</a>
</nav>
<header><h1>ATLAS · Histórias Diárias</h1><span class="tag">terror · policial · diário</span><span class="tag">9:16 HD · EN+PT</span><span class="tag">sem repetir</span></header>
<div class="tabs">
  <button id="tab-btn-classic" class="on" onclick="showTab('classic')">🌙 Terror &amp; Policial</button>
  <button id="tab-btn-diario" onclick="showTab('diario')">📔 Diário da Bela</button>
</div>
<div class="wrap">
  <div id="tab-classic" class="tabsec on">
  <div class="row">
    <div><label>Gênero / Série</label>
      <select id="genre">
        <option value="horror">🌙 Terror — Midnight Tales</option>
        <option value="crime">🕵️ Policial — Case Files</option>
      </select></div>
    <div><label>Histórias</label><input type="number" id="count" value="3" min="1" max="5" style="width:80px"></div>
    <div><label>Cenas por história</label><input type="number" id="scenes" value="6" min="3" max="20" style="width:90px"></div>
    <div><label>Idiomas</label>
      <span class="chk"><input type="checkbox" id="en" checked> EN</span>
      <span class="chk"><input type="checkbox" id="pt" checked> PT</span>
    </div>
    <button class="go" id="go">🎬 Criar histórias</button>
  </div>
  <div class="note">Mesmo estilo visual sempre (o público volta pelo estilo). Cada história é original e checada contra o índice pra <b>não repetir</b>. Vídeos marcados como <b>prioridade</b> — suba-os primeiro nos canais de trending. A geração leva alguns minutos. <b>Pode trocar de aba à vontade</b> — a criação continua no servidor e o progresso reaparece ao voltar aqui.</div>
  <div id="log"></div>

  <h2>Histórias geradas <span id="cnt" class="badge"></span></h2>
  <div class="cards" id="cards"></div>
  </div>

  <div id="tab-diario" class="tabsec">
  <div class="row">
    <div style="max-width:640px"><label>Diário contínuo de Isabela (Bela, 13) e Maria (6)</label>
      <div class="note" style="margin-top:0">Cada clique gera o(s) próximo(s) episódio(s), lembrando tudo que já aconteceu (memória contínua) — nunca repete um assunto já usado.</div>
    </div>
    <button class="go" id="go-diario-part">📖 Gerar próxima parte</button>
    <button class="go" id="go-diario-day" style="background:linear-gradient(90deg,#db2777,#f59e0b)">📖📖 Gerar o dia inteiro (2 partes)</button>
  </div>
  <div id="diario-log"></div>

  <div class="row" style="margin-top:14px">
    <div style="max-width:640px"><label>Publicação automática (2x/dia)</label>
      <div class="note" style="margin-top:0" id="diario-auto-status">Verificando...</div>
    </div>
    <button class="go" id="diario-auto-toggle" style="background:#1f2937">—</button>
  </div>

  <div class="bible-box">
    <h3>Próximo episódio</h3>
    <div id="diario-next" class="note" style="margin:0">—</div>
    <h3 style="margin-top:14px">Fatos estabelecidos (canôn da série)</h3>
    <div id="diario-facts" class="facts">Nenhum ainda — o primeiro episódio vai começar a história.</div>
    <h3 style="margin-top:14px">Últimos resumos (continuidade)</h3>
    <div id="diario-summaries"></div>
  </div>

  <h2>Episódios do Diário <span id="diario-cnt" class="badge"></span></h2>
  <div class="cards" id="diario-cards"></div>
  </div>
</div>
<script>
function showTab(name){
  document.getElementById('tab-classic').classList.toggle('on', name==='classic');
  document.getElementById('tab-diario').classList.toggle('on', name==='diario');
  document.getElementById('tab-btn-classic').classList.toggle('on', name==='classic');
  document.getElementById('tab-btn-diario').classList.toggle('on', name==='diario');
  if(name==='diario'){refreshDiario();refreshDiarioAutoStatus();}
}
async function refresh(){
  const r=await fetch('/stories/api/list');const j=await r.json();
  const items=(j.items||[]).filter(it=>it.genre!=='teen_diary');
  document.getElementById('cnt').textContent=items.length+' no índice';
  const c=document.getElementById('cards');c.innerHTML='';
  if(!items.length){c.innerHTML='<div class="note">Nenhuma história ainda. Clique em Criar.</div>';return;}
  items.forEach(it=>{
    const el=document.createElement('div');el.className='card';
    const first=Object.values(it.videos||{})[0];
    const vid=first?`<video src="/stories/api/file?path=${encodeURIComponent(first)}" controls preload="metadata"></video>`:'';
    let links='';for(const[k,v]of Object.entries(it.videos||{})){links+=`<a href="/stories/api/file?path=${encodeURIComponent(v)}" target="_blank">▶ ${k.toUpperCase()}</a>`;}
    const posted=Object.keys(it.posted||{}).length?'<span class="badge" style="background:#14532d;color:#bbf7d0">postado</span>':'';
    const actions=`<div style="margin-top:8px"><a href="#" onclick="postStory('${it.slug}');return false;" style="background:#1d4ed8;border-color:#1d4ed8;color:#fff">🚀 Postar (trend)</a><a href="#" onclick="delStory('${it.slug}');return false;" style="background:#3a1220;border-color:#5a1a2a">🗑 Apagar</a></div>`;
    el.innerHTML=vid+`<div class="b"><b>${it.title}</b><span class="badge">${it.series}</span>${posted}<div class="m">${it.genre} · ${it.created}</div><div class="m" style="color:#8b7bb8">${it.hashtags||''}</div>${links}${actions}</div>`;
    c.appendChild(el);
  });
}
async function refreshDiario(){
  const [rList,rTl]=await Promise.all([fetch('/stories/api/list'),fetch('/stories/api/diario/timeline')]);
  const j=await rList.json();const tl=await rTl.json();
  const items=(j.items||[]).filter(it=>it.genre==='teen_diary');
  document.getElementById('diario-cnt').textContent=items.length+' episódio(s)';
  document.getElementById('diario-next').innerHTML=`Dia <b>${tl.next_day}</b> · Parte <b>${tl.next_part}</b> (próximo a ser gerado)`;
  const facts=tl.established_facts||[];
  document.getElementById('diario-facts').textContent=facts.length?facts.join(' · '):'Nenhum ainda — o primeiro episódio vai começar a história.';
  const sumEl=document.getElementById('diario-summaries');sumEl.innerHTML='';
  (tl.recent_summaries||[]).forEach(s=>{
    const d=document.createElement('div');d.className='sumline';
    d.textContent=`Dia ${s.day} parte ${s.part}: ${s.summary_pt||s.summary_en||''}`;
    sumEl.appendChild(d);
  });
  const c=document.getElementById('diario-cards');c.innerHTML='';
  if(!items.length){c.innerHTML='<div class="note">Nenhum episódio ainda. Clique em "Gerar próxima parte".</div>';return;}
  items.forEach(it=>{
    const el=document.createElement('div');el.className='card';
    const first=Object.values(it.videos||{})[0];
    const vid=first?`<video src="/stories/api/file?path=${encodeURIComponent(first)}" controls preload="metadata"></video>`:'';
    let links='';for(const[k,v]of Object.entries(it.videos||{})){links+=`<a href="/stories/api/file?path=${encodeURIComponent(v)}" target="_blank">▶ ${k.toUpperCase()}</a>`;}
    const posted=Object.keys(it.posted||{}).length?'<span class="badge" style="background:#14532d;color:#bbf7d0">postado</span>':'';
    const actions=`<div style="margin-top:8px"><a href="#" onclick="postStory('${it.slug}');return false;" style="background:#1d4ed8;border-color:#1d4ed8;color:#fff">🚀 Postar (trend)</a><a href="#" onclick="delStory('${it.slug}');return false;" style="background:#3a1220;border-color:#5a1a2a">🗑 Apagar</a></div>`;
    el.innerHTML=vid+`<div class="b"><b>${it.title}</b><span class="badge">${it.series}</span>${posted}<div class="m">${it.created}</div>${links}${actions}</div>`;
    c.appendChild(el);
  });
}
async function refreshDiarioAutoStatus(){
  try{
    const r=await fetch('/api/jobs/teen-diary-auto/status');const j=await r.json();
    const statusEl=document.getElementById('diario-auto-status');
    const btn=document.getElementById('diario-auto-toggle');
    if(j.active){
      statusEl.innerHTML=`🟢 Ligado — horários: <b>${(j.times||[]).join(', ')}</b> (América/São Paulo)`;
      btn.textContent='⏹ Desligar';btn.style.background='#3a1220';
    }else{
      statusEl.innerHTML=`⚪ Desligado — quando ligar, publica sozinho nos horários: <b>${(j.times||[]).join(', ')}</b>`;
      btn.textContent='▶ Ligar automático';btn.style.background='linear-gradient(90deg,#7c3aed,#db2777)';
    }
  }catch(e){}
}
document.getElementById('diario-auto-toggle').onclick=async()=>{
  const btn=document.getElementById('diario-auto-toggle');
  btn.disabled=true;
  try{
    const r=await fetch('/api/jobs/teen-diary-auto/status');const j=await r.json();
    const endpoint=j.active?'/api/jobs/teen-diary-auto/stop':'/api/jobs/teen-diary-auto/start';
    await fetch(endpoint,{method:'POST'});
  }finally{btn.disabled=false;refreshDiarioAutoStatus();}
};
let _poll=null;
function pollJob(jobId,btn,idleLabel,logId,onDone){
  logId=logId||'log';
  const log=document.getElementById(logId);log.style.display='block';
  if(btn){btn.disabled=true;btn.dataset._label=btn.textContent;btn.textContent='Gerando...';}
  if(_poll)clearInterval(_poll);
  _poll=setInterval(async()=>{
    let jj;try{const rr=await fetch('/stories/api/jobs/'+jobId);jj=await rr.json();}catch(e){return;}
    if(jj.error){clearInterval(_poll);_poll=null;if(btn){btn.disabled=false;btn.textContent=idleLabel||btn.dataset._label;}return;}
    log.textContent=(jj.log||[]).join('\\n');log.scrollTop=log.scrollHeight;
    if(jj.status==='done'||jj.status==='error'){clearInterval(_poll);_poll=null;if(btn){btn.disabled=false;btn.textContent=idleLabel||btn.dataset._label;}if(onDone)onDone();}
  },2000);
}
document.getElementById('go').onclick=async()=>{
  const langs=[];if(document.getElementById('en').checked)langs.push('en');if(document.getElementById('pt').checked)langs.push('pt');
  const body={genre:document.getElementById('genre').value,count:+document.getElementById('count').value,scenes:+document.getElementById('scenes').value,languages:langs};
  const go=document.getElementById('go');
  const log=document.getElementById('log');log.style.display='block';log.textContent='Iniciando...';
  const r=await fetch('/stories/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json();
  if(j.error){log.textContent='ERRO: '+j.error;return;}
  pollJob(j.job_id,go,'🎬 Criar histórias','log',refresh);
};
async function generateDiario(count){
  const btn=count>=2?document.getElementById('go-diario-day'):document.getElementById('go-diario-part');
  const label=btn.textContent;
  const log=document.getElementById('diario-log');log.style.display='block';log.textContent='Iniciando...';
  const r=await fetch('/stories/api/diario/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({count})});
  const j=await r.json();
  if(j.error){log.textContent='ERRO: '+j.error;return;}
  pollJob(j.job_id,btn,label,'diario-log',refreshDiario);
}
document.getElementById('go-diario-part').onclick=()=>generateDiario(1);
document.getElementById('go-diario-day').onclick=()=>generateDiario(2);
async function postStory(slug){
  if(!confirm('Postar esta historia nos canais de TREND (YouTube/TikTok/Instagram/Facebook)? NAO vai para afiliados (Achados/Finds).'))return;
  const log=document.getElementById('log').style.display!=='none'&&document.getElementById('tab-classic').classList.contains('on')?document.getElementById('log'):document.getElementById('diario-log');
  log.style.display='block';log.textContent='Postando...';
  const r=await fetch('/stories/api/post',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug})});
  const j=await r.json();
  if(j.error){log.textContent='ERRO: '+j.error;return;}
  pollJob(j.job_id,null,null,document.getElementById('tab-diario').classList.contains('on')?'diario-log':'log',document.getElementById('tab-diario').classList.contains('on')?refreshDiario:refresh);
}
async function delStory(slug){
  if(!confirm('Apagar os videos desta historia? O historico e mantido para NAO repetir.'))return;
  const r=await fetch('/stories/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slug})});
  const j=await r.json();
  if(j.error){alert('Erro: '+j.error);return;}
  refresh();refreshDiario();
}
async function resumeIfRunning(){
  try{const r=await fetch('/stories/api/current');const j=await r.json();
    if(j.running&&j.job_id){
      const isDiario=j.kind==='diario_generate';
      const logId=isDiario?'diario-log':'log';
      const log=document.getElementById(logId);log.style.display='block';log.textContent=(j.log||['Retomando...']).join('\\n');
      const btn=isDiario?null:(j.kind==='post'?null:document.getElementById('go'));
      pollJob(j.job_id,btn,null,logId,isDiario?refreshDiario:refresh);
    }
  }catch(e){}
}
refresh();resumeIfRunning();
</script>
</body></html>"""
