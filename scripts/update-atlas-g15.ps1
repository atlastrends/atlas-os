# ============================================================
# ATLAS OS - scripts/update-atlas-g15.ps1
#
# ATUALIZA o Atlas AUTOMATICAMENTE a partir do GitHub (git pull) e deixa
# tudo pronto para rodar: instala dependencias novas (se mudaram) e
# reconstroi o painel (frontend). Feito para o Dell G15.
#
# COMO USAR (sozinho):
#     .\scripts\update-atlas-g15.ps1
#
# Normalmente voce NAO precisa rodar isso na mao: o atalho da live
# (start-live-g15.ps1) ja chama este updater ANTES de subir o painel.
#
# OPCOES:
#     -NoBuild     nao reconstruir o frontend (mais rapido)
#     -NoInstall   nao instalar dependencias Python
#     -Quiet       menos mensagens
#
# SEGURANCA: usa 'git pull --ff-only'. Se o historico tiver divergido,
# ele AVISA e PARA (nao apaga nada a forca). Arquivos que o proprio Atlas
# escreve sozinho (docs/produtos.json, docs/_img_cache.json) sao restaurados
# antes do pull para nao travar a atualizacao.
# ============================================================

param(
    [switch]$NoBuild,
    [switch]$NoInstall,
    [switch]$Quiet
)

# Nao usar "Stop" global: queremos tratar erros na mao e nunca derrubar
# o atalho da live so' porque a atualizacao falhou.
$ErrorActionPreference = "Continue"

function Say {
    param([string]$Msg, [string]$Color = "Cyan")
    if (-not $Quiet) { Write-Host "[UPDATE] $Msg" -ForegroundColor $Color }
}

# Reconstroi o painel (frontend). O frontend/dist e' ignorado pelo Git,
# entao precisa ser gerado localmente sempre que o codigo do painel muda.
function Build-Frontend {
    $fe = Join-Path $Root "frontend"
    if (-not (Test-Path (Join-Path $fe "package.json"))) { return }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Say "npm nao encontrado; pulei a reconstrucao do painel (instale o Node.js)." "Yellow"
        return
    }
    Say "Reconstruindo o painel (frontend) ..."
    Push-Location $fe
    if (-not (Test-Path (Join-Path $fe "node_modules"))) { npm install }
    npm run build
    Pop-Location
    Say "Painel reconstruido." "Green"
}

# Raiz do projeto = pasta acima de \scripts
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# --- Git instalado? ---
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Say "Git nao encontrado. Pulei a atualizacao (instale o Git para atualizar sozinho)." "Yellow"
    return $false
}

# --- E' um repositorio git? ---
git rev-parse --is-inside-work-tree 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Say "Esta pasta nao e' um repositorio Git. Pulei a atualizacao." "Yellow"
    return $false
}

# --- Restaura arquivos que o Atlas escreve sozinho (evita travar o pull) ---
$runtimeFiles = @("docs/produtos.json", "docs/_img_cache.json")
foreach ($f in $runtimeFiles) {
    git ls-files --error-unmatch $f 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { git checkout -- $f 2>$null | Out-Null }
}

# --- Descobrir versao atual e buscar novidades ---
$before = (git rev-parse HEAD 2>$null)
Say "Procurando atualizacoes no GitHub ..."
git fetch --quiet 2>$null

$branch = (git rev-parse --abbrev-ref HEAD 2>$null)
if (-not $branch -or $branch -eq "HEAD") { $branch = "main" }

$behind = 0
$countTxt = (git rev-list --count "HEAD..origin/$branch" 2>$null)
if ($LASTEXITCODE -eq 0 -and $countTxt) { $behind = [int]$countTxt }

if ($behind -le 0) {
    Say "Ja esta na versao mais recente. Nada para baixar." "Green"
    # Mesmo sem update, garante que o painel exista (frontend/dist e' ignorado
    # pelo Git, entao pode faltar num PC recem-clonado).
    $needBuild = (-not $NoBuild) -and (-not (Test-Path (Join-Path $Root "frontend\dist\index.html")))
    if ($needBuild) { Build-Frontend } else { return $true }
    return $true
}

Say "Encontrei $behind atualizacao(oes). Baixando ..." "Green"
git pull --ff-only origin $branch
if ($LASTEXITCODE -ne 0) {
    Say "Nao consegui atualizar com 'ff-only' (o historico local divergiu)." "Yellow"
    Say "Rode manualmente:  git status   e me chame para resolver sem perder nada." "Yellow"
    return $false
}

$after = (git rev-parse HEAD 2>$null)

# --- O que mudou? (para decidir instalar deps / rebuildar) ---
$changed = @()
if ($before -and $after) {
    $changed = (git diff --name-only $before $after 2>$null)
}

# --- Dependencias Python mudaram? ---
$reqChanged = $changed | Where-Object { $_ -match "requirements-dashboard\.txt$" }
if ($reqChanged -and -not $NoInstall) {
    $venvPy = Join-Path $Root ".venv-dash\Scripts\python.exe"
    if (Test-Path $venvPy) {
        Say "As dependencias mudaram. Instalando (pode demorar) ..."
        & $venvPy -m pip install -r (Join-Path $Root "requirements-dashboard.txt")
    }
    else {
        Say "Aviso: .venv-dash nao encontrado; pulei a instalacao de dependencias." "Yellow"
    }
}

# --- Frontend mudou? (ou dist ausente) -> reconstruir ---
$feChanged = $changed | Where-Object { $_ -match "^frontend/" }
$distMissing = -not (Test-Path (Join-Path $Root "frontend\dist\index.html"))
if ((-not $NoBuild) -and ($feChanged -or $distMissing)) {
    Build-Frontend
}

Say ("Atualizado! {0} -> {1}" -f $before.Substring(0, 7), $after.Substring(0, 7)) "Green"
return $true
