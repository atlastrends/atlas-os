import os


_TRUE_VALUES = {
    "1",
    "true",
    "yes",
    "on",
    "sim",
}


def is_worker_run_enabled() -> bool:
    value = os.getenv(
        "ATLAS_WORKER_RUN_ENABLED",
        "",
    )

    return value.strip().lower() in _TRUE_VALUES


def main() -> int:
    if not is_worker_run_enabled():
        print(
            "[ATLAS WORKER] Inicializacao bloqueada. "
            "Defina ATLAS_WORKER_RUN_ENABLED=true "
            "explicitamente para executar o motor."
        )
        return 0

    print(
        "[ATLAS WORKER] Autorizacao explicita confirmada. "
        "Iniciando motor."
    )

    from app.workers.loop_worker import Engine

    Engine().start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())