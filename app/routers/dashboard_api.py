# ============================================================
# ATLAS OS - routers/dashboard_api.py
# API que alimenta o painel web (React/Vite).
#
# Prefixo: /api
# ============================================================

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.dashboard import VideoAsset
from app.publishing.registry import PLATFORMS, platform_status
from app.services import job_service
from app.services.analytics_service import AnalyticsService
from app.services.marketing_service import MarketingService
from app.services.publishing_service import PublishingService
from app.services.shortlink_service import ShortLinkService
from app.services.video_library_service import VideoLibraryService
from app.services import update_service
from app.services import tiktok_oauth_service

router = APIRouter(prefix="/api", tags=["Dashboard"])


# ----------------------------------------------------------------
# Serializacao
# ----------------------------------------------------------------

def _enum(value) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _serialize_asset(asset: VideoAsset, db: Session) -> dict:
    short_url = None
    if asset.short_code:
        short_url = ShortLinkService(db).build_public_url(asset.short_code)

    return {
        "id": asset.id,
        "kind": _enum(asset.kind),
        "external_key": asset.external_key,
        "title": asset.title,
        "topic": asset.topic,
        "language": asset.language,
        "country_code": asset.country_code,
        "video_path": asset.video_path,
        "video_url": (
            f"/media/{asset.video_path}" if asset.video_path else None
        ),
        "thumbnail_path": asset.thumbnail_path,
        "affiliate_url": asset.affiliate_url,
        "short_code": asset.short_code,
        "short_url": short_url,
        "performance_score": asset.performance_score,
        "status": _enum(asset.status),
        "review_notes": asset.review_notes,
        "payload": asset.payload,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "reviewed_at": asset.reviewed_at.isoformat() if asset.reviewed_at else None,
        "published_at": asset.published_at.isoformat() if asset.published_at else None,
        "publications": [
            {
                "platform": p.platform,
                "status": _enum(p.status),
                "external_url": p.external_url,
                "error": p.error,
            }
            for p in (asset.publications or [])
        ],
    }


# ----------------------------------------------------------------
# Requests
# ----------------------------------------------------------------

class ReviewRequest(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=4000)
    platforms: Optional[list[str]] = None


# ----------------------------------------------------------------
# STATUS / OVERVIEW
# ----------------------------------------------------------------

@router.get("/status")
def system_status(db: Session = Depends(get_db)):
    analytics = AnalyticsService(db)
    return {
        "overview": analytics.overview(),
        "platforms": platform_status(),
        "jobs": job_service.get_job_state(),
    }


@router.get("/analytics/overview")
def analytics_overview(db: Session = Depends(get_db)):
    return AnalyticsService(db).overview()


@router.get("/analytics/platforms")
def analytics_platforms(db: Session = Depends(get_db)):
    return AnalyticsService(db).by_platform()


@router.get("/analytics/accounts")
def analytics_accounts(db: Session = Depends(get_db)):
    return AnalyticsService(db).by_account()


@router.get("/analytics/video/{asset_id}")
def analytics_video(asset_id: int, db: Session = Depends(get_db)):
    return AnalyticsService(db).video_metrics(asset_id)


@router.get("/analytics/top-videos")
def analytics_top_videos(
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    return AnalyticsService(db).top_videos(limit=limit)


@router.get("/analytics/platform/{platform}/videos")
def analytics_platform_videos(platform: str, db: Session = Depends(get_db)):
    return AnalyticsService(db).platform_videos(platform)


@router.get("/analytics/account/{key}/videos")
def analytics_account_videos(key: str, db: Session = Depends(get_db)):
    return AnalyticsService(db).account_videos(key)


# ----------------------------------------------------------------
# VIDEOS (reels + afiliados)
# ----------------------------------------------------------------

@router.post("/videos/sync")
def sync_videos(db: Session = Depends(get_db)):
    return VideoLibraryService(db).sync()


@router.post("/videos/clear-reels")
def clear_reels(db: Session = Depends(get_db)):
    """Apaga todos os reels de assuntos em alta (arquivos + banco)."""
    return VideoLibraryService(db).clear_reels()


@router.post("/videos/clear-rejected")
def clear_rejected(
    kind: Optional[str] = Query(default=None, description="reel | affiliate"),
    db: Session = Depends(get_db),
):
    """Apaga os videos rejeitados (arquivos + banco). Opcionalmente por tipo."""
    return VideoLibraryService(db).clear_rejected(kind=kind)


@router.post("/videos/clear-published")
def clear_published(
    kind: Optional[str] = Query(default=None, description="reel | affiliate"),
    db: Session = Depends(get_db),
):
    """Libera espaco: apaga SO o arquivo de video (.mp4) e a miniatura dos
    videos JA PUBLICADOS. Mantem o registro no banco, as ESTATISTICAS e o
    arquivinho .json (para nao gerar o mesmo produto de novo)."""
    return VideoLibraryService(db).delete_published_files(kind=kind)


@router.get("/videos/pending-count")
def videos_pending_count(
    kind: Optional[str] = Query(default=None, description="reel | affiliate"),
    db: Session = Depends(get_db),
):
    """Quantos videos estao aguardando reenvio (bloqueio temporario da
    plataforma, ex.: limite diario do YouTube)."""
    return {"pending": PublishingService(db).count_pending(kind=kind)}


@router.post("/videos/retry-pending")
def retry_pending_videos(
    kind: Optional[str] = Query(default=None, description="reel | affiliate"),
    db: Session = Depends(get_db),
):
    """Reenvia os videos que ficaram AGUARDANDO REENVIO por bloqueio temporario
    da plataforma (ex.: limite diario do YouTube). Use no dia seguinte."""
    return PublishingService(db).retry_pending(kind=kind)



@router.get("/videos")
def list_videos(
    kind: Optional[str] = Query(default=None, description="reel | affiliate"),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=500),
    db: Session = Depends(get_db),
):
    library = VideoLibraryService(db)
    # Sincroniza sob demanda para refletir novos arquivos.
    library.sync()
    assets = library.list_assets(kind=kind, status=status, limit=limit)

    # Esconde da lista os videos JA PUBLICADOS cujo arquivo foi apagado
    # (pela limpeza) ou sumiu do disco. Assim nao aparecem quebrados
    # (player 404). As estatisticas deles seguem no Analytics.
    visible = []
    for a in assets:
        if _enum(a.status) == "published":
            purged = bool((a.payload or {}).get("file_purged"))
            if purged or not library.is_file_present(a):
                continue
        visible.append(a)

    return [_serialize_asset(a, db) for a in visible]


@router.get("/videos/{asset_id}")
def get_video(asset_id: int, db: Session = Depends(get_db)):
    asset = VideoLibraryService(db).get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Video nao encontrado.")
    return _serialize_asset(asset, db)


@router.get("/videos/{asset_id}/caption")
def video_caption(
    asset_id: int,
    platform: str = Query(default="tiktok"),
    db: Session = Depends(get_db),
):
    """Retorna a legenda + hashtags + link que seriam publicados, para o
    usuario COPIAR e COLAR manualmente na rede (ex.: TikTok), depois que o
    video sobe como rascunho."""
    asset = VideoLibraryService(db).get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Video nao encontrado.")
    req = PublishingService(db)._build_request(asset, platform)
    return {
        "platform": platform,
        "title": req.title,
        "caption": req.caption,
        "hashtags": req.hashtags,
    }


@router.post("/videos/{asset_id}/approve")
def approve_video(
    asset_id: int,
    body: ReviewRequest | None = None,
    db: Session = Depends(get_db),
):
    asset = VideoLibraryService(db).get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Video nao encontrado.")

    body = body or ReviewRequest()
    platforms = body.platforms or list(PLATFORMS)
    return PublishingService(db).approve_and_publish(
        asset,
        platforms=platforms,
        notes=body.notes,
    )


@router.post("/videos/{asset_id}/reject")
def reject_video(
    asset_id: int,
    body: ReviewRequest | None = None,
    db: Session = Depends(get_db),
):
    asset = VideoLibraryService(db).get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Video nao encontrado.")

    body = body or ReviewRequest()
    asset = PublishingService(db).reject(asset, notes=body.notes)
    return _serialize_asset(asset, db)


# ----------------------------------------------------------------
# PUBLICACOES
# ----------------------------------------------------------------

@router.get("/publications")
def list_publications(db: Session = Depends(get_db)):
    return PublishingService(db).list_publications()


@router.post("/publications/{publication_id}/retry")
def retry_publication(publication_id: int, db: Session = Depends(get_db)):
    """Reenvia SOMENTE a plataforma que falhou (nao mexe nas outras)."""
    try:
        return PublishingService(db).retry_single_publication(publication_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/publications/{publication_id}")
def delete_publication(publication_id: int, db: Session = Depends(get_db)):
    """Remove um registro de publicacao com erro (aba de reenvio)."""
    try:
        return PublishingService(db).delete_publication(publication_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ----------------------------------------------------------------
# JOBS (botoes do painel)
# ----------------------------------------------------------------

@router.post("/jobs/fetch-amazon-products")
def trigger_fetch_amazon():
    job_service.run_fetch_amazon_products()
    return job_service.get_job_state("fetch_amazon_products")


@router.get("/products/available")
def list_available_products():
    """Produtos buscados (Em Alta) ainda nao transformados em video,
    agrupados por mercado + categoria, para o painel montar a selecao."""
    from app.automation.real_amazon_pipeline import available_products

    return available_products()


class CategorySelection(BaseModel):
    marketplace_code: str
    category: str
    quantity: int = Field(default=1, ge=0, le=50)


class GenerateSelectedRequest(BaseModel):
    selections: list[CategorySelection] = Field(default_factory=list)


@router.post("/jobs/generate-selected")
def trigger_generate_selected(body: GenerateSelectedRequest):
    selection = [s.model_dump() for s in body.selections]
    job_service.run_generate_selected(selection)
    return job_service.get_job_state("generate_selected")


@router.post("/jobs/generate-reels")
def trigger_generate_reels():
    job_service.run_generate_reels()
    return job_service.get_job_state("generate_reels")


class AutoReelsRequest(BaseModel):
    interval_minutes: int = Field(default=30, ge=1, le=720)


@router.post("/jobs/auto-reels/start")
def trigger_auto_reels_start(body: AutoReelsRequest | None = None):
    """Liga a criacao automatica: 1 reel BR + 1 US a cada N minutos,
    ate o usuario parar."""
    minutes = body.interval_minutes if body else 30
    return job_service.start_auto_reels(minutes)


@router.post("/jobs/auto-reels/stop")
def trigger_auto_reels_stop():
    """Desliga a criacao automatica de reels."""
    return job_service.stop_auto_reels()


@router.get("/jobs/auto-reels/status")
def auto_reels_status():
    return job_service.auto_reels_status()


class AutoAffiliateRequest(BaseModel):
    # Padrao: a cada 2 horas (120 minutos).
    interval_minutes: int = Field(default=120, ge=1, le=1440)


@router.post("/jobs/auto-affiliate/start")
def trigger_auto_affiliate_start(body: AutoAffiliateRequest | None = None):
    """Liga o robo de afiliados: busca os mais vendidos, gera video dos
    produtos novos e publica sozinho quando o assunto bate — a cada N
    minutos (padrao 120 = 2 horas), ate o usuario parar."""
    minutes = body.interval_minutes if body else 120
    return job_service.start_auto_affiliate(minutes)


@router.post("/jobs/auto-affiliate/stop")
def trigger_auto_affiliate_stop():
    """Desliga o robo de afiliados automatico."""
    return job_service.stop_auto_affiliate()


@router.get("/jobs/auto-affiliate/status")
def auto_affiliate_status():
    return job_service.auto_affiliate_status()


@router.post("/jobs/collect-metrics")
def trigger_collect_metrics():
    job_service.run_collect_metrics()
    return job_service.get_job_state("collect_metrics")


@router.post("/jobs/auto-approve")
def trigger_auto_approve():
    job_service.run_auto_approval()
    return job_service.get_job_state("auto_approval")


@router.post("/jobs/watch-comments")
def trigger_watch_comments():
    """Dispara agora 1 ciclo do robo de respostas por comentario (polling
    via Graph API -- responde com o link do produto quem comentou nos
    posts do Instagram/Facebook ja publicados)."""
    job_service.run_watch_comments()
    return job_service.get_job_state("watch_comments")


@router.get("/jobs")
def jobs_status():
    return job_service.get_job_state()


# ----------------------------------------------------------------
# ATUALIZACAO DO APLICATIVO (a partir do GitHub publico)
# ----------------------------------------------------------------

@router.get("/update/check")
def update_check():
    return update_service.check()


@router.post("/update/apply")
def update_apply():
    return update_service.apply()


# ----------------------------------------------------------------
# LOGIN DO TIKTOK (OAuth pelo proprio painel)
# ----------------------------------------------------------------

@router.get("/tiktok/status")
def tiktok_status():
    return tiktok_oauth_service.status()


@router.get("/tiktok/connect")
def tiktok_connect(market: str = Query("BR")):
    """Abre o login do TikTok. Redireciona para a pagina de autorizacao."""
    from fastapi.responses import RedirectResponse

    if not (tiktok_oauth_service._client_key() and tiktok_oauth_service._client_secret()):
        raise HTTPException(
            status_code=400,
            detail="Faltam TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET no .env.",
        )
    if not tiktok_oauth_service.redirect_uri():
        raise HTTPException(
            status_code=400,
            detail=(
                "Falta o endereco de retorno (ATLAS_TIKTOK_REDIRECT_URI) no .env. "
                "Use a pagina fixa do GitHub Pages."
            ),
        )
    url = tiktok_oauth_service.build_authorize_url(market)
    return RedirectResponse(url, status_code=302)


@router.get("/tiktok/callback")
def tiktok_callback(code: str = Query(default=""), state: str = Query(default=""), error: str = Query(default="")):
    """Retorno do TikTok apos o login. Troca o code por tokens e salva."""
    from fastapi.responses import HTMLResponse

    def _page(title: str, message: str, ok: bool) -> HTMLResponse:
        color = "#22c55e" if ok else "#f59e0b"
        html = f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ATLAS - TikTok</title></head>
<body style="font-family:system-ui,Segoe UI,Arial;background:#0b1220;color:#e5e7eb;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0">
<div style="max-width:520px;padding:32px;background:#111827;border-radius:16px;
border:1px solid #1f2937;text-align:center">
<div style="font-size:44px;margin-bottom:8px">{'✅' if ok else '⚠️'}</div>
<h2 style="color:{color};margin:0 0 12px">{title}</h2>
<p style="line-height:1.6;color:#cbd5e1">{message}</p>
<p style="margin-top:24px;color:#64748b;font-size:14px">Pode fechar esta aba e voltar ao ATLAS.</p>
</div></body></html>"""
        return HTMLResponse(html)

    if error:
        return _page("Login cancelado", f"O TikTok retornou: {error}", ok=False)
    if not code:
        return _page("Faltou o codigo", "O TikTok nao enviou o codigo de autorizacao.", ok=False)

    market = tiktok_oauth_service.market_from_state(state)
    try:
        data = tiktok_oauth_service.exchange_code(code)
    except Exception as exc:  # noqa: BLE001
        return _page("Erro ao conectar", f"Nao consegui falar com o TikTok: {exc}", ok=False)

    if not (data.get("access_token") or "").strip():
        return _page("Nao autorizado", f"O TikTok nao retornou o token. Resposta: {data}", ok=False)

    tiktok_oauth_service.save_tokens(market, data)
    return _page(
        f"TikTok {market} conectado!",
        f"A conta do TikTok ({market}) foi conectada e sera renovada automaticamente.",
        ok=True,
    )


# ----------------------------------------------------------------
# MARKETING / ANUNCIOS PAGOS
# ----------------------------------------------------------------

class CreateCampaignRequest(BaseModel):
    video_id: int
    budget_amount: float = Field(ge=0)
    budget_period: str = Field(default="weekly")  # weekly | monthly
    publish: bool = False


@router.get("/marketing/status")
def marketing_status(db: Session = Depends(get_db)):
    return MarketingService(db).status()


@router.get("/marketing/best-video")
def marketing_best_video(db: Session = Depends(get_db)):
    return MarketingService(db).best_video()


@router.get("/marketing/roi-ranking")
def marketing_roi_ranking(limit: int = 10, db: Session = Depends(get_db)):
    return {"items": MarketingService(db).roi_ranking(limit=limit)}


@router.get("/marketing/recommendation/{video_id}")
def marketing_recommendation(
    video_id: int, force: bool = False, db: Session = Depends(get_db)
):
    asset = db.query(VideoAsset).filter(VideoAsset.id == video_id).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Video nao encontrado.")
    return MarketingService(db).recommend_for_video(asset, force_ai=force)


@router.get("/marketing/campaigns")
def marketing_campaigns(db: Session = Depends(get_db)):
    return MarketingService(db).list_campaigns()


@router.post("/marketing/campaigns")
def marketing_create_campaign(
    body: CreateCampaignRequest,
    db: Session = Depends(get_db),
):
    try:
        return MarketingService(db).create_campaign(
            video_id=body.video_id,
            budget_amount=body.budget_amount,
            budget_period=body.budget_period,
            publish=body.publish,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/marketing/campaigns/{campaign_id}/launch")
def marketing_launch_campaign(campaign_id: int, db: Session = Depends(get_db)):
    try:
        return MarketingService(db).launch_campaign(campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
