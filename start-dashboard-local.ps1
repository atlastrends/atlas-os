# ============================================================
# ATLAS OS - Iniciar o painel localmente (Windows / PowerShell)
# Uso: botao direito > "Executar com PowerShell"  OU  no terminal:
#   ./start-dashboard-local.ps1
# ============================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# 1) Cria o ambiente virtual na primeira vez e instala as dependencias.
if (-not (Test-Path ".\.venv-dash\Scripts\python.exe")) {
    Write-Host "[ATLAS] Criando ambiente virtual .venv-dash ..." -ForegroundColor Cyan
    py -m venv .venv-dash
    .\.venv-dash\Scripts\python.exe -m pip install --upgrade pip
    .\.venv-dash\Scripts\python.exe -m pip install -r requirements-dashboard.txt
}

# 2) Variaveis de ambiente para rodar com SQLite (sem Docker/Postgres).
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:DATABASE_URL = "sqlite:///./atlas_local.db"
$env:ATLAS_ROOT = (Get-Location).Path
$env:ATLAS_PUBLIC_BASE_URL = "http://localhost:8000"

# 3) Sobe a API + painel em http://127.0.0.1:8000
Write-Host "[ATLAS] Painel em http://127.0.0.1:8000  (Ctrl+C para parar)" -ForegroundColor Green
.\.venv-dash\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
