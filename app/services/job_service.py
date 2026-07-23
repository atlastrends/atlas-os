# ============================================================
# ATLAS OS - job_service.py
# Gatilhos manuais (a partir do painel) executados em background:
#  - fetch_amazon_products : roda o scraper de best sellers (10/categoria BR+US)
#  - generate_reels        : dispara 1 ciclo do motor de reels (1 PT + 1 EN)
#
# Mantem um registro simples em memoria do ultimo status de cada job,
# para o painel exibir o progresso.
# ============================================================

from __future__ import annotations

import threading
import traceback
from datetime import datetime, timedelta, timezone

# Estado dos jobs em memoria (por tipo).
_JOB_STATE: dict[str, dict] = {}
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_job_state(job: str | None = None):
    with _LOCK:
        if job:
            return dict(_JOB_STATE.get(job, {"status": "idle"}))
        return {k: dict(v) for k, v in _JOB_STATE.items()}


def _set_state(job: str, **kwargs):
    with _LOCK:
        state = _JOB_STATE.get(job, {})
        state.update(kwargs)
        _JOB_STATE[job] = state


def is_running(job: str) -> bool:
    with _LOCK:
        return _JOB_STATE.get(job, {}).get("status") == "running"


# ----------------------------------------------------------------
# JOB: buscar produtos na Amazon (scraper)
# ----------------------------------------------------------------

def run_fetch_amazon_products():
    job = "fetch_amazon_products"
    if is_running(job):
        return
    _set_state(job, status="running", started_at=_now_iso(), error=None, result=None)

    def _worker():
        try:
            from app.automation import run_scraper

            # Busca os produtos EM ALTA na Amazon (BR + US).
            # NAO gera videos aqui: o usuario escolhe no painel quais
            # categorias e a quantidade, e depois dispara a geracao.
            _set_state(job, step="scraping")
            run_scraper.main()

            _set_state(
                job,
                status="done",
                step="done",
                finished_at=_now_iso(),
                result={"scraper": "ok"},
            )
        except Exception as exc:  # noqa: BLE001
            _set_state(
                job,
                status="error",
                finished_at=_now_iso(),
                error=f"{exc}",
                traceback=traceback.format_exc()[-2000:],
            )

    threading.Thread(target=_worker, daemon=True, name="atlas-fetch-amazon").start()


def run_generate_selected(selection: list[dict] | None = None):
    """Gera os videos de afiliado APENAS para as categorias/quantidades
    escolhidas no painel. selection = [{marketplace_code, category, quantity}]."""
    job = "generate_selected"
    if is_running(job):
        return
    _set_state(
        job,
        status="running",
        started_at=_now_iso(),
        error=None,
        result=None,
        progress=0,
        current_title="",
        stage="Iniciando…",
    )

    def _worker():
        try:
            selected = selection or []
            total = 0
            for item in selected:
                try:
                    total += max(0, int(item.get("quantity") or 0))
                except Exception:
                    pass

            if total <= 0:
                _set_state(
                    job,
                    status="error",
                    finished_at=_now_iso(),
                    error="Nenhuma categoria/quantidade foi selecionada.",
                )
                return

            _set_state(job, step="generating_reels")
            from app.automation.real_amazon_pipeline import run_pipeline

            def _on_progress(percent, title, stage):
                # Atualiza o painel com a % e o titulo do video sendo criado.
                _set_state(
                    job,
                    progress=int(percent),
                    current_title=title or "",
                    stage=stage or "",
                )

            def _on_video_ready(record):
                # Chamado assim que CADA video fica pronto: ja tenta publicar
                # SO ESTE video, passando pelo controle de qualidade (nota +
                # conferencia de assunto). O que nao passar fica para revisao.
                from app.core.database import SessionLocal
                from app.services.auto_approval_service import AutoApprovalService

                title = (record or {}).get("title") or ""
                _set_state(job, stage=f"Publicando (se aprovado): {title}"[:120])
                db_one = SessionLocal()
                try:
                    AutoApprovalService(db_one).run()
                except Exception as exc:  # noqa: BLE001
                    print(f"[GENERATE] Falha ao publicar '{title}': {exc}")
                finally:
                    db_one.close()

            pipeline_state = run_pipeline(
                maximum_videos=total,
                selection=selected,
                progress_callback=_on_progress,
                on_video_ready=_on_video_ready,
            )
            summary = {"pipeline": pipeline_state}

            # Indexa os videos novos e aprova automaticamente.
            _set_state(
                job,
                step="auto_approving",
                progress=100,
                current_title="",
                stage="Aprovando e publicando…",
            )
            from app.core.database import SessionLocal
            from app.services.auto_approval_service import AutoApprovalService

            db = SessionLocal()
            try:
                summary["auto_approval"] = AutoApprovalService(db).run()
            finally:
                db.close()

            _set_state(
                job,
                status="done",
                step="done",
                finished_at=_now_iso(),
                result=summary,
            )
        except Exception as exc:  # noqa: BLE001
            _set_state(
                job,
                status="error",
                finished_at=_now_iso(),
                error=f"{exc}",
                traceback=traceback.format_exc()[-2000:],
            )

    threading.Thread(target=_worker, daemon=True, name="atlas-generate-selected").start()


def run_generate_reels():
    job = "generate_reels"
    if is_running(job):
        return
    _set_state(
        job,
        status="running",
        started_at=_now_iso(),
        error=None,
        result=None,
        progress=0,
        current_title="",
        stage="Iniciando…",
    )

    def _worker():
        try:
            from app.workers.loop_worker import Engine

            def _on_progress(percent, title, stage):
                # Atualiza o painel com a % e o titulo do video sendo criado.
                _set_state(
                    job,
                    progress=int(percent),
                    current_title=title or "",
                    stage=stage or "",
                )

            produced = Engine().run_cycle(progress_callback=_on_progress)

            if not produced:
                _set_state(
                    job,
                    status="error",
                    finished_at=_now_iso(),
                    error=(
                        "O ciclo terminou sem gerar nenhum reel. "
                        "Nenhuma tendencia nova qualificou ou a producao falhou. "
                        "Veja o terminal para detalhes."
                    ),
                )
                return

            _set_state(
                job,
                status="done",
                finished_at=_now_iso(),
                result=f"Ciclo de reels concluido. {produced} video(s) gerado(s).",
            )
        except Exception as exc:  # noqa: BLE001
            _set_state(
                job,
                status="error",
                finished_at=_now_iso(),
                error=f"{exc}",
                traceback=traceback.format_exc()[-2000:],
            )

    threading.Thread(target=_worker, daemon=True, name="atlas-generate-reels").start()


# ----------------------------------------------------------------
# CRIACAO AUTOMATICA DE REELS (a cada N minutos, ate o usuario parar)
# ----------------------------------------------------------------
# Enquanto ativo, a cada intervalo o sistema verifica os assuntos
# mais falados no Brasil e nos EUA e cria 1 reel para cada (sem repetir
# assunto, gracas a memoria persistente do motor). Fica rodando ate o
# usuario clicar em "Parar" no painel (ou o programa ser fechado).

_auto_reels_scheduler = None
_auto_reels_interval_minutes = 30
_AUTO_REELS_JOB_ID = "auto_reels_cycle"


def auto_reels_status() -> dict:
    """Diz se a criacao automatica esta ligada e quando roda de novo."""
    global _auto_reels_scheduler
    active = _auto_reels_scheduler is not None and getattr(
        _auto_reels_scheduler, "running", False
    )
    next_run = None
    if active:
        try:
            job = _auto_reels_scheduler.get_job(_AUTO_REELS_JOB_ID)
            if job is not None and job.next_run_time is not None:
                next_run = job.next_run_time.astimezone(timezone.utc).isoformat()
        except Exception:  # noqa: BLE001
            next_run = None
    return {
        "active": active,
        "interval_minutes": _auto_reels_interval_minutes,
        "next_run_at": next_run,
    }


def start_auto_reels(interval_minutes: int = 30) -> dict:
    """Liga a criacao automatica: roda 1 ciclo agora e depois a cada
    `interval_minutes` minutos, ate o usuario parar."""
    global _auto_reels_scheduler, _auto_reels_interval_minutes

    try:
        _auto_reels_interval_minutes = max(1, int(interval_minutes or 30))
    except (TypeError, ValueError):
        _auto_reels_interval_minutes = 30

    # Ja esta ligado: nao cria outro agendador.
    if _auto_reels_scheduler is not None and getattr(
        _auto_reels_scheduler, "running", False
    ):
        return auto_reels_status()

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        _set_state(
            "auto_reels",
            status="error",
            error="APScheduler nao instalado; nao da para agendar a criacao automatica.",
        )
        return auto_reels_status()

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_generate_reels,
        trigger="interval",
        minutes=_auto_reels_interval_minutes,
        id=_AUTO_REELS_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        # Primeiro ciclo comeca em alguns segundos (nao espera o intervalo).
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
    )
    scheduler.start()
    _auto_reels_scheduler = scheduler

    _set_state(
        "auto_reels",
        status="active",
        started_at=_now_iso(),
        error=None,
        interval_minutes=_auto_reels_interval_minutes,
    )
    return auto_reels_status()


def stop_auto_reels() -> dict:
    """Desliga a criacao automatica de reels."""
    global _auto_reels_scheduler
    if _auto_reels_scheduler is not None:
        try:
            _auto_reels_scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        _auto_reels_scheduler = None

    _set_state("auto_reels", status="stopped", finished_at=_now_iso())
    return auto_reels_status()


# ----------------------------------------------------------------
# ROBO DE AFILIADOS AUTOMATICO (a cada N horas, ate o usuario parar)
# ----------------------------------------------------------------
# Enquanto ligado, a cada intervalo o sistema:
#   1) busca os produtos MAIS VENDIDOS por categoria na Amazon (BR + US);
#   2) gera video para cada PRODUTO NOVO (que ainda nao virou video);
#   3) confere se o ASSUNTO bate com o video e, quando ha CERTEZA, publica
#      sozinho; o que ficar em duvida vai para aprovacao manual.
# Fica rodando ate o usuario clicar em "Parar" (ou o programa ser fechado).

_auto_affiliate_scheduler = None
_auto_affiliate_interval_minutes = 120
_AUTO_AFFILIATE_JOB_ID = "auto_affiliate_cycle"


def run_affiliate_cycle():
    """Um ciclo do robo de afiliados. Roda dentro do agendador."""
    job = "affiliate_cycle"
    if is_running(job):
        return
    _set_state(job, status="running", started_at=_now_iso(), error=None, result=None)

    try:
        # 1) Atualiza a lista de produtos (todas as categorias, 10 por categoria).
        _set_state(job, step="scraping", stage="Buscando os mais vendidos…")
        try:
            from app.automation import run_scraper

            run_scraper.main()
        except Exception as exc:  # noqa: BLE001
            # Se a rede bloquear a Amazon agora, seguimos com o que ja temos
            # (o scraper preserva os produtos das categorias que falharam).
            print(f"[AFFILIATE CYCLE] Busca falhou, seguindo com dados atuais: {exc}")

        # 2) Descobre os produtos NOVOS (ainda nao viraram video).
        from app.automation.real_amazon_pipeline import available_products

        groups = available_products()
        selection = [
            {
                "marketplace_code": g.get("marketplace_code"),
                "category": g.get("category"),
                "quantity": int(g.get("count") or 0),
            }
            for g in groups
            if int(g.get("count") or 0) > 0
        ]
        total = sum(s["quantity"] for s in selection)

        if total <= 0:
            _set_state(
                job,
                status="done",
                step="done",
                finished_at=_now_iso(),
                result="Nenhum produto novo neste ciclo.",
            )
            return

        # 3) Gera os videos dos produtos novos. Ao terminar, o proprio
        #    run_generate_selected chama a auto-aprovacao, que so publica
        #    sozinho os videos cujo assunto bate (certeza alta).
        _set_state(job, step="generating", stage="Gerando videos dos produtos novos…")
        run_generate_selected(selection)

        _set_state(
            job,
            status="done",
            step="done",
            finished_at=_now_iso(),
            result=f"Ciclo de afiliados: {total} produto(s) novo(s) em producao.",
        )
    except Exception as exc:  # noqa: BLE001
        _set_state(
            job,
            status="error",
            finished_at=_now_iso(),
            error=f"{exc}",
            traceback=traceback.format_exc()[-2000:],
        )


def auto_affiliate_status() -> dict:
    """Diz se o robo de afiliados esta ligado e quando roda de novo."""
    global _auto_affiliate_scheduler
    active = _auto_affiliate_scheduler is not None and getattr(
        _auto_affiliate_scheduler, "running", False
    )
    next_run = None
    if active:
        try:
            job = _auto_affiliate_scheduler.get_job(_AUTO_AFFILIATE_JOB_ID)
            if job is not None and job.next_run_time is not None:
                next_run = job.next_run_time.astimezone(timezone.utc).isoformat()
        except Exception:  # noqa: BLE001
            next_run = None
    return {
        "active": active,
        "interval_minutes": _auto_affiliate_interval_minutes,
        "next_run_at": next_run,
    }


def start_auto_affiliate(interval_minutes: int = 120) -> dict:
    """Liga o robo de afiliados: roda 1 ciclo agora e depois a cada
    `interval_minutes` minutos (padrao 120 = 2 horas), ate o usuario parar."""
    global _auto_affiliate_scheduler, _auto_affiliate_interval_minutes

    try:
        _auto_affiliate_interval_minutes = max(1, int(interval_minutes or 120))
    except (TypeError, ValueError):
        _auto_affiliate_interval_minutes = 120

    # Ja esta ligado: nao cria outro agendador.
    if _auto_affiliate_scheduler is not None and getattr(
        _auto_affiliate_scheduler, "running", False
    ):
        return auto_affiliate_status()

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        _set_state(
            "affiliate_cycle",
            status="error",
            error="APScheduler nao instalado; nao da para agendar o robo de afiliados.",
        )
        return auto_affiliate_status()

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_affiliate_cycle,
        trigger="interval",
        minutes=_auto_affiliate_interval_minutes,
        id=_AUTO_AFFILIATE_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        # Primeiro ciclo comeca em alguns segundos (nao espera o intervalo).
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
    )
    scheduler.start()
    _auto_affiliate_scheduler = scheduler

    _set_state(
        "affiliate_cycle",
        status="active",
        started_at=_now_iso(),
        error=None,
        interval_minutes=_auto_affiliate_interval_minutes,
    )
    return auto_affiliate_status()


def stop_auto_affiliate() -> dict:
    """Desliga o robo de afiliados automatico."""
    global _auto_affiliate_scheduler
    if _auto_affiliate_scheduler is not None:
        try:
            _auto_affiliate_scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        _auto_affiliate_scheduler = None

    _set_state("affiliate_cycle", status="stopped", finished_at=_now_iso())
    return auto_affiliate_status()


def run_collect_metrics():
    job = "collect_metrics"
    if is_running(job):
        return
    _set_state(job, status="running", started_at=_now_iso(), error=None, result=None)

    def _worker():
        try:
            from app.core.database import SessionLocal
            from app.services.metrics_service import MetricsService

            db = SessionLocal()
            try:
                summary = MetricsService(db).collect_all()
            finally:
                db.close()

            _set_state(
                job,
                status="done",
                finished_at=_now_iso(),
                result=summary,
            )
        except Exception as exc:  # noqa: BLE001
            _set_state(
                job,
                status="error",
                finished_at=_now_iso(),
                error=f"{exc}",
                traceback=traceback.format_exc()[-2000:],
            )

    threading.Thread(target=_worker, daemon=True, name="atlas-collect-metrics").start()


# ----------------------------------------------------------------
# JOB: aprovacao automatica por qualidade
# ----------------------------------------------------------------

def run_auto_approval():
    job = "auto_approval"
    if is_running(job):
        return
    _set_state(job, status="running", started_at=_now_iso(), error=None, result=None)

    def _worker():
        try:
            from app.core.database import SessionLocal
            from app.services.auto_approval_service import AutoApprovalService

            db = SessionLocal()
            try:
                summary = AutoApprovalService(db).run()
            finally:
                db.close()

            _set_state(
                job,
                status="done",
                finished_at=_now_iso(),
                result=summary,
            )
        except Exception as exc:  # noqa: BLE001
            _set_state(
                job,
                status="error",
                finished_at=_now_iso(),
                error=f"{exc}",
                traceback=traceback.format_exc()[-2000:],
            )

    threading.Thread(target=_worker, daemon=True, name="atlas-auto-approval").start()


# ----------------------------------------------------------------
# JOB: robo de respostas por comentario (polling, sem webhook)
# ----------------------------------------------------------------

def run_watch_comments():
    job = "watch_comments"
    if is_running(job):
        return
    _set_state(job, status="running", started_at=_now_iso(), error=None, result=None)

    def _worker():
        try:
            from app.core.database import SessionLocal
            from app.services.comment_watcher_service import CommentWatcherService

            db = SessionLocal()
            try:
                summary = CommentWatcherService(db).run()
            finally:
                db.close()

            _set_state(
                job,
                status="done",
                finished_at=_now_iso(),
                result=summary,
            )
        except Exception as exc:  # noqa: BLE001
            _set_state(
                job,
                status="error",
                finished_at=_now_iso(),
                error=f"{exc}",
                traceback=traceback.format_exc()[-2000:],
            )

    threading.Thread(target=_worker, daemon=True, name="atlas-watch-comments").start()
