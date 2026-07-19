# ============================================================
# ATLAS OS - atlas.ps1  (INICIAR COM UM CLIQUE)
#
# Faz TUDO sozinho:
#   1) Instala o que faltar (ambiente Python + painel) na 1a vez.
#   2) Cria um endereco publico https automatico (para o Instagram,
#      Facebook e TikTok conseguirem baixar e publicar os videos).
#   3) Abre o painel no navegador.
#
# O usuario NAO precisa escolher nada: basta abrir o "ATLAS.bat".
# Se nao houver internet aberta para o link publico, o painel ainda
# abre e o YouTube continua publicando normalmente.
# ============================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Info($m) { Write-Host "[ATLAS] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[ATLAS] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "[ATLAS] $m" -ForegroundColor Yellow }

# Descobre o Python (py ou python).
function Get-Python {
    $c = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $c) { $c = Get-Command python -ErrorAction SilentlyContinue }
    return $c
}

# Instala o Python sozinho (sem o usuario precisar fazer nada), se faltar.
function Install-Python {
    Write-Info "Python nao encontrado. Instalando automaticamente (pode demorar) ..."
    # 1) Tenta pela loja de aplicativos do Windows (winget), silencioso.
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        try {
            & winget install --id Python.Python.3.12 --source winget `
                --accept-package-agreements --accept-source-agreements --silent | Out-Null
        } catch {}
    }
    # 2) Se ainda nao houver, baixa o instalador oficial e roda silencioso.
    if ($null -eq (Get-Python)) {
        try {
            $pyExe = Join-Path $env:TEMP "python-setup.exe"
            Invoke-WebRequest -UseBasicParsing -TimeoutSec 300 `
                -Uri "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" `
                -OutFile $pyExe
            Start-Process -FilePath $pyExe -Wait -ArgumentList `
                "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0"
        } catch {}
    }
    # 3) Atualiza o PATH desta sessao para achar o Python recem-instalado.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    return (Get-Python)
}

# ------------------------------------------------------------
# 1) INSTALA O QUE FALTAR (so na primeira vez)
# ------------------------------------------------------------
if (-not (Test-Path ".\.venv-dash\Scripts\python.exe")) {
    Write-Info "Preparando o ambiente pela primeira vez (pode demorar alguns minutos) ..."
    $py = Get-Python
    if ($null -eq $py) { $py = Install-Python }
    if ($null -eq $py) {
        Write-Warn "Nao consegui instalar o Python automaticamente."
        Write-Warn "Instale manualmente em https://www.python.org (marque 'Add Python to PATH') e abra de novo."
        Read-Host "Pressione ENTER para fechar"
        exit 1
    }
    & $py.Source -m venv .venv-dash
    .\.venv-dash\Scripts\python.exe -m pip install --upgrade pip --quiet
    .\.venv-dash\Scripts\python.exe -m pip install -r requirements-dashboard.txt
}

if (-not (Test-Path ".\frontend\dist\index.html")) {
    if (Test-Path ".\frontend\package.json") {
        $npm = Get-Command npm -ErrorAction SilentlyContinue
        if ($null -eq $npm) {
            Write-Warn "Node.js (npm) nao encontrado. Instale em https://nodejs.org (versao LTS) e abra de novo."
            Read-Host "Pressione ENTER para fechar"
            exit 1
        }
        Write-Info "Compilando o painel pela primeira vez ..."
        Push-Location ".\frontend"
        try { npm install; npm run build } finally { Pop-Location }
    }
}

# Cria o .env se ainda nao existir (a partir do exemplo).
if ((-not (Test-Path ".\.env")) -and (Test-Path ".\.env.example")) {
    Copy-Item -Path ".\.env.example" -Destination ".\.env" -Force
    Write-Warn "Arquivo .env criado a partir do exemplo. Preencha suas chaves e contas nele."
}

# ------------------------------------------------------------
# 2) LINK PUBLICO AUTOMATICO (cloudflared)
# ------------------------------------------------------------
$cloudflared = Join-Path $PSScriptRoot "cloudflared.exe"
if (-not (Test-Path $cloudflared)) {
    Write-Info "Baixando o componente do link publico (uma unica vez) ..."
    try {
        Invoke-WebRequest `
            -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
            -OutFile $cloudflared -UseBasicParsing -TimeoutSec 120
    } catch {
        Write-Warn "Nao consegui baixar o link publico agora. O painel abre mesmo assim (YouTube funciona)."
    }
}

$publicUrl = $null
$tunnel = $null
if (Test-Path $cloudflared) {
    Write-Info "Abrindo o link publico (aguarde alguns segundos) ..."
    $logFile = Join-Path $env:TEMP "atlas_cloudflared.log"
    if (Test-Path $logFile)       { Remove-Item $logFile -Force -ErrorAction SilentlyContinue }
    if (Test-Path "$logFile.err") { Remove-Item "$logFile.err" -Force -ErrorAction SilentlyContinue }

    $tunnel = Start-Process -FilePath $cloudflared `
        -ArgumentList "tunnel --url http://localhost:8000 --no-autoupdate" `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError "$logFile.err" `
        -WindowStyle Hidden -PassThru

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        $content = ""
        if (Test-Path $logFile)       { $content += Get-Content $logFile -Raw -ErrorAction SilentlyContinue }
        if (Test-Path "$logFile.err") { $content += Get-Content "$logFile.err" -Raw -ErrorAction SilentlyContinue }
        if ($content -match "failed to request quick Tunnel" -or $content -match "tls: handshake failure") {
            break
        }
        foreach ($m in [regex]::Matches($content, "https://[a-z0-9-]+\.trycloudflare\.com")) {
            if ($m.Value -notlike "*api.trycloudflare.com*") { $publicUrl = $m.Value; break }
        }
        if ($publicUrl) { break }
    }
}

# ------------------------------------------------------------
# 3) VARIAVEIS DE AMBIENTE
# ------------------------------------------------------------
$env:PYTHONIOENCODING   = "utf-8"
$env:PYTHONUTF8         = "1"
$env:DATABASE_URL       = "sqlite:///./atlas_local.db"
$env:ATLAS_ROOT         = (Get-Location).Path

if ($publicUrl) {
    $env:ATLAS_PUBLIC_BASE_URL = $publicUrl
    Write-Host ""
    Write-Ok "Tudo pronto! Instagram, Facebook e TikTok liberados para publicar."
    Write-Host "        Link publico ativo: $publicUrl" -ForegroundColor DarkGray
    Write-Host ""
} else {
    $env:ATLAS_PUBLIC_BASE_URL = "http://localhost:8000"
    Write-Host ""
    Write-Warn "Sem link publico agora (internet fechada ou bloqueada)."
    Write-Warn "O painel abre e o YouTube publica. Instagram/Facebook/TikTok voltam"
    Write-Warn "a publicar sozinhos assim que houver uma internet pessoal (casa/celular)."
    Write-Host ""
}

# ------------------------------------------------------------
# 4) ABRE O NAVEGADOR SOZINHO (quando o painel estiver no ar)
# ------------------------------------------------------------
Start-Job -ScriptBlock {
    for ($i = 0; $i -lt 40; $i++) {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/status" -TimeoutSec 2 | Out-Null
            break
        } catch { Start-Sleep -Milliseconds 1000 }
    }
    Start-Process "http://127.0.0.1:8000"
} | Out-Null

# ------------------------------------------------------------
# 5) SOBE O PAINEL. Ao fechar, derruba o link publico junto.
# ------------------------------------------------------------
try {
    Write-Ok "Painel iniciado. Mantenha esta janela aberta enquanto usa o ATLAS."
    .\.venv-dash\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
finally {
    if ($tunnel -and -not $tunnel.HasExited) {
        Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
    }
}
