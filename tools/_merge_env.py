"""Consolida o .env local mesclando os segredos que hoje ficam no OneDrive.

Regra (igual ao runtime do env_loader.load_env): o .env COMPARTILHADO
(ATLAS-OS-SECRETS) e a fonte da verdade dos segredos, entao os valores dele
VENCEM em caso de conflito. Chaves que so existem no projeto sao mantidas.

Nao imprime NENHUM valor de segredo -- so nomes de chave e contagens.
Faz backup do .env do projeto antes de sobrescrever.
"""
from __future__ import annotations

import shutil
from pathlib import Path

PROJECT_ENV = Path(r"C:\atlas-os\.env")
SHARED_ENV = Path(r"C:\Users\cpenteri\OneDrive - azureford\ATLAS-OS-SECRETS\.env")


def key_of(line: str) -> str | None:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.lower().startswith("export "):
        s = s[7:]
    if "=" not in s:
        return None
    return s.split("=", 1)[0].strip()


def parse_shared(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        k = key_of(raw)
        if k:
            out[k] = raw.rstrip("\r\n")
    return out


def main() -> None:
    if not PROJECT_ENV.is_file():
        raise SystemExit(f"Nao achei o .env do projeto: {PROJECT_ENV}")
    shared = parse_shared(SHARED_ENV)
    project_lines = PROJECT_ENV.read_text(encoding="utf-8", errors="replace").splitlines()

    project_keys = {key_of(l) for l in project_lines} - {None}

    # backup
    bak = PROJECT_ENV.with_suffix(".env.premerge.bak") if PROJECT_ENV.suffix else PROJECT_ENV.parent / ".env.premerge.bak"
    bak = PROJECT_ENV.parent / ".env.premerge.bak"
    shutil.copy2(PROJECT_ENV, bak)

    out: list[str] = []
    used: set[str] = set()
    overridden = 0
    for raw in project_lines:
        k = key_of(raw)
        if k and k in shared:
            out.append(shared[k])           # segredo vence
            used.add(k)
            overridden += 1
        else:
            out.append(raw)

    appended = [k for k in shared if k not in used]
    if appended:
        out.append("")
        out.append("# --- Consolidado de ATLAS-OS-SECRETS (movido do OneDrive) ---")
        for k in appended:
            out.append(shared[k])

    PROJECT_ENV.write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"chaves no projeto (antes) : {len(project_keys)}")
    print(f"chaves nos segredos       : {len(shared)}")
    print(f"sobrescritas (segredo venceu): {overridden}")
    print(f"acrescentadas (so nos segredos): {len(appended)}")
    print(f"backup do .env do projeto : {bak}")
    print("OK: .env local consolidado (nenhum valor exibido).")


if __name__ == "__main__":
    main()
