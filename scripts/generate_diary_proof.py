"""Gera um episódio de prova do Diário da Bela fora do servidor web."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)
os.environ["DATABASE_URL"] = "sqlite:///./atlas_local.db"
os.environ["PYTHONUTF8"] = "1"

from app.services.teen_diary_service import TeenDiaryService


LOG_PATH = ROOT / "logs" / "diario_proof.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def main() -> int:
    log("[PROOF] iniciando episodio 3D completo")
    episodes = TeenDiaryService(log=log).generate_next(count=1)
    if not episodes:
        log("[PROOF] falhou: nenhum episodio concluido")
        return 1
    log(f"[PROOF] concluido: {episodes[0]['slug']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
