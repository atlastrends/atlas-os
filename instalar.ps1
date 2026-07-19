# ============================================================
# ATLAS OS - instalar.ps1
# Instala o ATLAS pela PRIMEIRA VEZ em um computador novo.
# Baixa o codigo do GitHub (repositorio PUBLICO), prepara o ambiente
# Python, instala tudo, compila o painel e cria o arquivo .env.
#
# NAO precisa de git instalado: baixa um ZIP por HTTPS.
#
# Como usar (no computador novo):
#   1) Instale o Python 3 (marque "Add Python to PATH") e o Node.js.
#   2) Salve este arquivo em uma pasta vazia (ex.: C:\atlas-os).
#   3) Botao direito neste arquivo > "Executar com PowerShell".
#      OU no terminal:  ./instalar.ps1 -Repo "usuario/atlas-os"
# ============================================================

param(
    [string]$Repo = "",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Step($m) { Write-Host "[ATLAS] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[ATLAS] $m" -ForegroundColor Green }
function Write-Err($m)  { Write-Host "[ATLAS] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Yellow
Write-Host "        INSTALADOR DO ATLAS OS" -ForegroundColor Yellow
Write-Host "=====================================================" -ForegroundColor Yellow
Write-Host ""

# 0) Pergunta o repositorio se nao foi informado.
if ([string]::IsNullOrWhiteSpace($Repo)) {
    $Repo = Read-Host "Digite o endereco do repositorio no GitHub (ex.: usuario/atlas-os)"
}
if ([string]::IsNullOrWhiteSpace($Repo)) {
    Write-Err "Repositorio nao informado. Encerrando."
    Read-Host "Pressione ENTER para fechar"
    exit 1
}
if ([string]::IsNullOrWhiteSpace($Branch)) { $Branch = "main" }

# 1) Confere Python e Node.
Write-Step "Conferindo Python e Node.js ..."
$py = Get-Command py -ErrorAction SilentlyContinue
if ($null -eq $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if ($null -eq $py) {
    Write-Err "Python nao encontrado. Instale em https://www.python.org (marque 'Add to PATH')."
    Read-Host "Pressione ENTER para fechar"
    exit 1
}
$node = Get-Command npm -ErrorAction SilentlyContinue
if ($null -eq $node) {
    Write-Err "Node.js (npm) nao encontrado. Instale em https://nodejs.org (versao LTS)."
    Read-Host "Pressione ENTER para fechar"
    exit 1
}

$root = $PSScriptRoot
$tmp = Join-Path $env:TEMP ("atlas_install_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
$zip = "$tmp.zip"
$zipUrl = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"

try {
    # 2) Descobre a versao (commit) para gravar no VERSION.
    $sha = ""
    try {
        $info = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/commits/$Branch" -Headers @{ "User-Agent" = "atlas-os-installer" } -TimeoutSec 20
        $sha = "$($info.sha)"
    } catch { }

    # 3) Baixa e extrai o codigo.
    Write-Step "Baixando o ATLAS do GitHub ..."
    Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing -TimeoutSec 300
    Write-Step "Extraindo ..."
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $extracted = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
    if ($null -eq $extracted) { throw "ZIP invalido: nada foi extraido." }

    Write-Step "Copiando os arquivos para esta pasta ..."
    Copy-Item -Path (Join-Path $extracted.FullName "*") -Destination $root -Recurse -Force

    # 4) Grava a versao instalada.
    if (-not [string]::IsNullOrWhiteSpace($sha)) {
        Set-Content -Path (Join-Path $root "VERSION") -Value $sha -Encoding ascii
    }

    # 5) Cria o .env a partir do exemplo (se ainda nao existir).
    $envPath = Join-Path $root ".env"
    if (-not (Test-Path $envPath)) {
        Copy-Item -Path (Join-Path $root ".env.example") -Destination $envPath -Force
        # Ja deixa o repositorio de atualizacao preenchido.
        Add-Content -Path $envPath -Value ""
        Add-Content -Path $envPath -Value "ATLAS_UPDATE_REPO=$Repo"
        Add-Content -Path $envPath -Value "ATLAS_UPDATE_BRANCH=$Branch"
        Write-Ok "Arquivo .env criado. Voce vai precisar preencher suas chaves depois."
    }

    # 6) Cria o ambiente Python e instala as dependencias.
    Write-Step "Criando ambiente Python (.venv-dash) e instalando dependencias ..."
    if (-not (Test-Path (Join-Path $root ".venv-dash\Scripts\python.exe"))) {
        & $py.Source -m venv .venv-dash
    }
    .\.venv-dash\Scripts\python.exe -m pip install --upgrade pip --quiet
    .\.venv-dash\Scripts\python.exe -m pip install -r requirements-dashboard.txt

    # 7) Compila o painel (frontend).
    if (Test-Path (Join-Path $root "frontend\package.json")) {
        Write-Step "Instalando e compilando o painel (pode demorar na 1a vez) ..."
        Push-Location ".\frontend"
        try {
            npm install
            npm run build
        } finally {
            Pop-Location
        }
    }

    # 8) Limpa temporarios.
    try { Remove-Item $zip -Force -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue } catch {}

    Write-Host ""
    Write-Ok "Instalacao concluida! 🎉"
    Write-Host ""
    Write-Host "PROXIMOS PASSOS:" -ForegroundColor Yellow
    Write-Host "  1) Abra o arquivo .env e preencha suas chaves (IA, contas, etc.)." -ForegroundColor Yellow
    Write-Host "  2) Depois, para usar o ATLAS, de dois cliques em:  ATLAS.bat" -ForegroundColor Yellow
    Write-Host "     (ele abre o painel sozinho, ja com o link publico)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Para atualizar no futuro, use o botao 'Procurar atualizacoes' no painel." -ForegroundColor Green
    Write-Host ""

    # Ja abre o ATLAS na hora (um clique), sem precisar de mais nada.
    $atlas = Join-Path $root "atlas.ps1"
    if (Test-Path $atlas) {
        Write-Step "Abrindo o ATLAS ..."
        & $atlas
    } else {
        Read-Host "Pressione ENTER para fechar"
    }
}
catch {
    Write-Err "Falha na instalacao: $($_.Exception.Message)"
    Read-Host "Pressione ENTER para fechar"
    exit 1
}
