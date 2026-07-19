# ============================================================
# ATLAS OS - atualizar.ps1
# Baixa a versao mais nova do codigo do GitHub (repositorio PUBLICO),
# substitui os arquivos do programa SEM tocar nos seus dados/segredos,
# reinstala dependencias, recompila o painel e reinicia.
#
# Nao precisa de git instalado: baixa um arquivo ZIP por HTTPS.
#
# Uso (normalmente chamado pelo botao "Procurar atualizacoes"):
#   ./atualizar.ps1 -Repo "usuario/atlas-os" -Branch "main"
# ============================================================

param(
    [string]$Repo = $env:ATLAS_UPDATE_REPO,
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Step($msg) { Write-Host "[ATLAS] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[ATLAS] $msg" -ForegroundColor Green }
function Write-Err($msg)  { Write-Host "[ATLAS] $msg" -ForegroundColor Red }

if ([string]::IsNullOrWhiteSpace($Repo)) {
    Write-Err "Repositorio nao informado. Configure ATLAS_UPDATE_REPO no .env."
    Read-Host "Pressione ENTER para fechar"
    exit 1
}
if ([string]::IsNullOrWhiteSpace($Branch)) { $Branch = "main" }

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Yellow
Write-Host "   ATUALIZANDO O ATLAS  ($Repo @ $Branch)" -ForegroundColor Yellow
Write-Host "=====================================================" -ForegroundColor Yellow
Write-Host ""

$root = $PSScriptRoot
$tmp = Join-Path $env:TEMP ("atlas_update_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
$zip = "$tmp.zip"
$zipUrl = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"

try {
    # 1) Descobre o commit mais novo (para gravar no VERSION depois).
    Write-Step "Consultando a versao mais nova no GitHub ..."
    $sha = ""
    try {
        $api = "https://api.github.com/repos/$Repo/commits/$Branch"
        $info = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "atlas-os-updater" } -TimeoutSec 20
        $sha = "$($info.sha)"
    } catch {
        Write-Step "Nao consegui ler o numero da versao (segue mesmo assim)."
    }

    # 2) Baixa o ZIP da versao nova.
    Write-Step "Baixando a versao nova ..."
    Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing -TimeoutSec 300

    # 3) Extrai para uma pasta temporaria.
    Write-Step "Extraindo arquivos ..."
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $extracted = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
    if ($null -eq $extracted) { throw "ZIP invalido: nada foi extraido." }
    $src = $extracted.FullName

    # 4) Para o painel que esta rodando (libera os arquivos).
    Write-Step "Parando o painel atual ..."
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'uvicorn|app.main' } |
        ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }
    Start-Sleep -Seconds 2

    # 5) Copia o codigo novo por cima, PRESERVANDO dados e segredos.
    #    /XD = pastas ignoradas ; /XF = arquivos ignorados.
    Write-Step "Aplicando a atualizacao (preservando seus dados) ..."
    $excludeDirs = @(
        ".git", ".venv-dash", "node_modules", "storage", "data",
        "outputs", "output_videos", "output_metadata", "temp_media",
        "logs", "backups"
    ) | ForEach-Object { Join-Path $root $_ }
    $excludeFiles = @(
        (Join-Path $root ".env"),
        (Join-Path $root "atlas_local.db"),
        (Join-Path $root "dados das contas.txt")
    )
    # Nao sobrescreve o dist antigo do frontend aqui; sera recompilado no passo 7.
    $roboArgs = @(
        $src, $root, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1"
    )
    $roboArgs += "/XD"; $roboArgs += $excludeDirs
    $roboArgs += "/XF"; $roboArgs += $excludeFiles
    & robocopy @roboArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Falha ao copiar arquivos (robocopy $LASTEXITCODE)." }

    # 6) Reinstala dependencias do Python (caso tenham mudado).
    if (Test-Path ".\.venv-dash\Scripts\python.exe") {
        Write-Step "Atualizando dependencias do Python ..."
        .\.venv-dash\Scripts\python.exe -m pip install -r requirements-dashboard.txt --quiet
    }

    # 7) Recompila o painel (frontend).
    if (Test-Path ".\frontend\package.json") {
        Write-Step "Recompilando o painel ..."
        Push-Location ".\frontend"
        try {
            if (-not (Test-Path ".\node_modules")) { npm install } else { npm install --no-audit --no-fund }
            npm run build
        } finally {
            Pop-Location
        }
    }

    # 8) Grava a versao instalada.
    if (-not [string]::IsNullOrWhiteSpace($sha)) {
        Set-Content -Path (Join-Path $root "VERSION") -Value $sha -Encoding ascii
    }

    # 9) Limpa temporarios.
    try { Remove-Item $zip -Force -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue } catch {}

    Write-Ok "Atualizacao concluida! Reiniciando o painel ..."
    Write-Host ""
    # 10) Reinicia o painel nesta mesma janela.
    & (Join-Path $root "start-dashboard-local.ps1")
}
catch {
    Write-Err "Falha na atualizacao: $($_.Exception.Message)"
    Write-Host ""
    Write-Host "Seu ATLAS anterior NAO foi apagado. Voce pode iniciar de novo com:" -ForegroundColor Yellow
    Write-Host "   ./start-dashboard-local.ps1" -ForegroundColor Yellow
    Read-Host "Pressione ENTER para fechar"
    exit 1
}
