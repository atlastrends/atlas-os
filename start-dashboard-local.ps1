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

# 2.7) Tunel publico automatico (Cloudflare) para o Instagram/Facebook
#      BAIXAREM os videos. O IG/FB nao conseguem baixar de "localhost"; por isso
#      abrimos um endereco https publico apontando para este painel (porta 8000)
#      e colocamos esse endereco em ATLAS_PUBLIC_BASE_URL automaticamente.
#      O tunel so fica de pe enquanto o painel esta aberto.
#
#      DESLIGADO por padrao: usamos o armazenamento na nuvem (Supabase), que
#      passa por firewall corporativo. Para usar o tunel (ex.: no PC de casa,
#      sem configurar a nuvem), rode antes:  $env:ATLAS_USE_TUNNEL = "1"
$cloudflared = Join-Path $PSScriptRoot "bin\cloudflared.exe"
$tunnelProc = $null
if (($env:ATLAS_USE_TUNNEL -eq "1") -and (Test-Path $cloudflared)) {
    $tunnelErr = Join-Path $PSScriptRoot "bin\cloudflared.err.log"
    $tunnelOut = Join-Path $PSScriptRoot "bin\cloudflared.out.log"
    Remove-Item $tunnelErr, $tunnelOut -Force -ErrorAction SilentlyContinue
    Write-Host "[ATLAS] Abrindo tunel publico (cloudflared) ..." -ForegroundColor Cyan
    $tunnelProc = Start-Process -FilePath $cloudflared `
        -ArgumentList @("tunnel", "--no-autoupdate", "--url", "http://localhost:8000") `
        -RedirectStandardError $tunnelErr -RedirectStandardOutput $tunnelOut `
        -WindowStyle Hidden -PassThru

    # Espera o endereco publico aparecer no log (ate ~30s).
    $tunnelUrl = $null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        foreach ($f in @($tunnelErr, $tunnelOut)) {
            if (Test-Path $f) {
                $hit = Select-String -Path $f -Pattern "https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($hit) { $tunnelUrl = $hit.Matches[0].Value; break }
            }
        }
        if ($tunnelUrl) { break }
    }

    if ($tunnelUrl) {
        $env:ATLAS_PUBLIC_BASE_URL = $tunnelUrl
        Write-Host "[ATLAS] Tunel publico ATIVO: $tunnelUrl" -ForegroundColor Green
        Write-Host "[ATLAS] Instagram/Facebook vao baixar os videos por esse endereco." -ForegroundColor Green
    }
    else {
        Write-Host "[ATLAS] AVISO: nao consegui abrir o tunel a tempo. A publicacao em" -ForegroundColor Yellow
        Write-Host "        Instagram/Facebook pode falhar (segue em localhost)." -ForegroundColor Yellow
    }
}
else {
    Write-Host "[ATLAS] Tunel desligado (usando armazenamento na nuvem). Para ligar o" -ForegroundColor DarkGray
    Write-Host '        tunel, rode antes:  $env:ATLAS_USE_TUNNEL = "1"' -ForegroundColor DarkGray
}

# 3) Sobe a API + painel em http://127.0.0.1:8000
Write-Host "[ATLAS] Painel em http://127.0.0.1:8000  (Ctrl+C para parar)" -ForegroundColor Green
try {
    .\.venv-dash\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
finally {
    # Ao fechar o painel (Ctrl+C), derruba o tunel junto.
    if ($tunnelProc -and -not $tunnelProc.HasExited) {
        Write-Host "[ATLAS] Fechando o tunel publico ..." -ForegroundColor Cyan
        Stop-Process -Id $tunnelProc.Id -Force -ErrorAction SilentlyContinue
    }
}
