# ============================================================
# ATLAS OS - criar-instalador.ps1
#
# Gera UM UNICO arquivo: ATLAS-Instalador.exe
# Esse .exe e um instalador profissional (assistente com "Avancar,
# Avancar, Concluir") que ja traz TUDO dentro dele:
#   - o programa ATLAS completo
#   - o painel ja compilado (nao precisa de Node no outro PC)
#   - o seu arquivo .env (contas e chaves)   <-- IMPORTANTE
#   - o componente do link publico (cloudflared)
#
# COMO USAR (faca isto UMA vez, NESTE computador):
#   1) De dois cliques neste arquivo (ou rode no PowerShell).
#   2) Espere terminar.
#   3) Pegue o arquivo gerado em:  dist-installer\ATLAS-Instalador.exe
#   4) Leve SO esse .exe para o outro computador e instale como
#      qualquer programa. Nao precisa copiar mais nada.
#
# OBS: como o .env vai DENTRO do instalador, trate o .exe como
# um arquivo confidencial (nao publique na internet).
# ============================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$root = $PSScriptRoot

function Write-Step($m) { Write-Host "[BUILD] $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[BUILD] $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "[BUILD] $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "[BUILD] $m" -ForegroundColor Red }

try {
    # --------------------------------------------------------
    # 1) Compila o painel (frontend) para incluir pronto no pacote.
    #    Assim o outro PC NAO precisa de Node.js instalado.
    # --------------------------------------------------------
    if (Test-Path (Join-Path $root "frontend\package.json")) {
        $npm = Get-Command npm -ErrorAction SilentlyContinue
        if ($npm) {
            Write-Step "Compilando o painel para incluir no instalador ..."
            Push-Location (Join-Path $root "frontend")
            try {
                if (-not (Test-Path ".\node_modules")) { npm install } else { npm install --no-audit --no-fund }
                npm run build
            } finally { Pop-Location }
        } else {
            Write-Warn "Node.js (npm) nao encontrado: vou usar o painel ja compilado, se existir."
        }
    }
    if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
        throw "O painel compilado (frontend\dist) nao existe. Instale o Node.js e rode de novo."
    }

    # --------------------------------------------------------
    # 2) Garante o Inno Setup (o programa que monta o instalador .exe).
    #    Se nao estiver instalado, baixa e instala em modo silencioso.
    # --------------------------------------------------------
    $iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $iscc) {
        Write-Step "Instalando o Inno Setup (uma unica vez) ..."
        $isSetup = Join-Path $env:TEMP "innosetup.exe"
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 300 `
            -Uri "https://jrsoftware.org/download.php/is.exe" -OutFile $isSetup
        Start-Process -FilePath $isSetup -Wait -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
        $iscc = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $iscc) { throw "Nao encontrei o Inno Setup (ISCC.exe) apos a instalacao." }
    Write-Ok "Inno Setup pronto: $iscc"

    # --------------------------------------------------------
    # 3) Monta a pasta com os arquivos que vao DENTRO do instalador.
    #    Copia tudo, menos lixo e coisas especificas deste PC.
    #    (O .env E INCLUIDO de proposito.)
    # --------------------------------------------------------
    $build   = Join-Path $root "build"
    $payload = Join-Path $build "payload"
    if (Test-Path $build) { Remove-Item $build -Recurse -Force }
    New-Item -ItemType Directory -Path $payload -Force | Out-Null

    Write-Step "Preparando os arquivos do programa ..."
    $excludeDirs = @(
        ".git", ".venv-dash", "node_modules", "storage", "data",
        "outputs", "output_videos", "output_metadata", "temp_media",
        "logs", "backups", "build", "dist-installer"
    ) | ForEach-Object { Join-Path $root $_ }

    $excludeFiles = @(
        (Join-Path $root "atlas_local.db")
    )

    $roboArgs = @($root, $payload, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
    $roboArgs += "/XD"; $roboArgs += $excludeDirs
    $roboArgs += "/XF"; $roboArgs += $excludeFiles
    $roboArgs += "*.bak"; $roboArgs += "*.before_*"; $roboArgs += "*.backup"; $roboArgs += "*.backup_*"
    & robocopy @roboArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Falha ao preparar os arquivos (robocopy $LASTEXITCODE)." }

    # Confirma que o .env foi incluido (e o coracao das contas/chaves).
    if (Test-Path (Join-Path $payload ".env")) {
        Write-Ok "Seu .env foi incluido no instalador (contas e chaves)."
    } else {
        Write-Warn "Atencao: nao havia um .env neste PC. O outro PC comecara sem contas configuradas."
    }

    # --------------------------------------------------------
    # 4) Escreve o roteiro do instalador (arquivo .iss do Inno Setup).
    # --------------------------------------------------------
    $distOut = Join-Path $root "dist-installer"
    New-Item -ItemType Directory -Path $distOut -Force | Out-Null

    $iss = @"
; Roteiro gerado automaticamente por criar-instalador.ps1
[Setup]
AppId={{ATLAS-OS-0FE1B7A4-8C2D-4E6A-9B10-ATLAS0000001}}
AppName=ATLAS OS
AppVersion=1.0
AppPublisher=ATLAS Trends
DefaultDirName={autopf}\ATLAS OS
DisableProgramGroupPage=yes
OutputDir=$distOut
OutputBaseFilename=ATLAS-Instalador
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=ATLAS OS

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Area de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "$payload\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\ATLAS OS"; Filename: "{app}\ATLAS.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\ATLAS OS"; Filename: "{app}\ATLAS.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ATLAS.bat"; Description: "Abrir o ATLAS agora"; Flags: postinstall nowait skipifsilent shellexec
"@

    $issPath = Join-Path $build "atlas.iss"
    Set-Content -Path $issPath -Value $iss -Encoding UTF8

    # --------------------------------------------------------
    # 5) Compila o instalador final (.exe).
    # --------------------------------------------------------
    Write-Step "Montando o instalador final (.exe) ..."
    & $iscc $issPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "O Inno Setup retornou erro ($LASTEXITCODE)." }

    $final = Join-Path $distOut "ATLAS-Instalador.exe"
    if (-not (Test-Path $final)) { throw "O instalador nao foi gerado." }

    # Limpa a pasta temporaria de montagem.
    try { Remove-Item $build -Recurse -Force -ErrorAction SilentlyContinue } catch {}

    Write-Host ""
    Write-Ok "PRONTO! Instalador criado com sucesso:"
    Write-Host "   $final" -ForegroundColor Green
    Write-Host ""
    Write-Host "Leve SO esse arquivo para o outro computador e de dois cliques nele." -ForegroundColor Yellow
    Write-Host "Ele instala o ATLAS como um programa, cria o atalho e ja abre o painel." -ForegroundColor Yellow
    Write-Host "Nao precisa copiar mais nenhum arquivo (o .env ja vai dentro)." -ForegroundColor Yellow
    Write-Host ""
    Write-Warn "Guarde esse .exe com cuidado: ele contem suas contas e chaves."
}
catch {
    Write-Err "Falha ao criar o instalador: $($_.Exception.Message)"
    Read-Host "Pressione ENTER para fechar"
    exit 1
}

Read-Host "Pressione ENTER para fechar"
