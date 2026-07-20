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

# 2.5) Compila o painel (frontend) se ainda nao existir.
#      A pasta frontend/dist NAO vai para o Git (esta no .gitignore), entao
#      numa maquina nova (ou apos baixar do Git) ela nao existe e o painel
#      aparece velho/sem as paginas novas (ex.: Vendas Amazon). Se o npm
#      estiver instalado, geramos o painel automaticamente aqui.
if (-not (Test-Path ".\frontend\dist\index.html")) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "[ATLAS] Compilando o painel (frontend) pela primeira vez ..." -ForegroundColor Cyan
        try {
            Push-Location ".\frontend"
            npm install
            npm run build
        } catch {
            Write-Host "[ATLAS] AVISO: falha ao compilar o painel: $_" -ForegroundColor Yellow
        } finally {
            Pop-Location -ErrorAction SilentlyContinue
        }
    }
    else {
        Write-Host "[ATLAS] AVISO: 'npm' nao encontrado. Instale o Node.js e rode 'cd frontend; npm install; npm run build' para ver as paginas novas do painel." -ForegroundColor Yellow
    }
}

# 3) Sobe a API + painel em http://127.0.0.1:8000
Write-Host "[ATLAS] Painel em http://127.0.0.1:8000  (Ctrl+C para parar)" -ForegroundColor Green
.\.venv-dash\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
