# ============================================================
# ATLAS OS - scheduler_service.py
# Agendador em background (APScheduler) que executa tarefas
# automaticas do painel:
#   - coleta de metricas (views, likes, seguidores) a cada N horas
#   - (opcional) scraper de produtos da Amazon a cada N horas
#
# Controle por variaveis de ambiente:
#   ATLAS_SCHEDULER_ENABLED       (default: true)
#   ATLAS_METRICS_INTERVAL_HOURS  (default: 1)  -> 0 desativa
#   ATLAS_SCRAPER_INTERVAL_HOURS  (default: 0)  -> 0 desativa
# ============================================================

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

_scheduler = None


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _collect_metrics_job():
    from app.services import job_service

    job_service.run_collect_metrics()


def _fetch_products_job():
    from app.services import job_service

    job_service.run_fetch_amazon_products()


def _auto_approval_job():
    from app.services import job_service

    job_service.run_auto_approval()


def start_scheduler() -> bool:
    """Inicia o agendador. Retorna True se ficou ativo."""
    global _scheduler

    if not _env_bool("ATLAS_SCHEDULER_ENABLED", True):
        print("[ATLAS SCHEDULER] Desativado (ATLAS_SCHEDULER_ENABLED=false).")
        return False

    if _scheduler is not None:
        return True

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        print("[ATLAS SCHEDULER] APScheduler nao instalado; agendamento inativo.")
        return False

    metrics_hours = _env_int("ATLAS_METRICS_INTERVAL_HOURS", 1)
    scraper_hours = _env_int("ATLAS_SCRAPER_INTERVAL_HOURS", 0)

    scheduler = BackgroundScheduler(timezone="UTC")

    if metrics_hours > 0:
        scheduler.add_job(
            _collect_metrics_job,
            trigger="interval",
            hours=metrics_hours,
            id="collect_metrics",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            # Primeira coleta logo apos o boot (nao espera o intervalo inteiro).
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20),
        )
        print(f"[ATLAS SCHEDULER] Coleta de metricas a cada {metrics_hours}h.")

    if scraper_hours > 0:
        scheduler.add_job(
            _fetch_products_job,
            trigger="interval",
            hours=scraper_hours,
            id="fetch_amazon_products",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        print(f"[ATLAS SCHEDULER] Scraper de produtos a cada {scraper_hours}h.")

    # Aprovacao automatica por qualidade (opcional).
    if _env_bool("ATLAS_AUTO_APPROVE_ENABLED", False):
        approve_hours = _env_int("ATLAS_AUTO_APPROVE_INTERVAL_HOURS", 1)
        if approve_hours > 0:
            scheduler.add_job(
                _auto_approval_job,
                trigger="interval",
                hours=approve_hours,
                id="auto_approval",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
            )
            print(
                f"[ATLAS SCHEDULER] Aprovacao automatica por qualidade a cada {approve_hours}h."
            )

    if not scheduler.get_jobs():
        print("[ATLAS SCHEDULER] Nenhuma tarefa agendada (intervalos = 0).")
        return False

    scheduler.start()
    _scheduler = scheduler
    return True


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        _scheduler = None
