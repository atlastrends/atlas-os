# ============================================================
# ATLAS OS - scripts/setup_avatar_g15.ps1
#
# Prepara o LIP-SYNC de verdade (boca mexendo) no Dell G15 (placa NVIDIA
# GeForce RTX 50). Instala o Wav2Lip num ambiente separado, baixa os pesos
# e deixa tudo pronto para a live usar o motor "wav2lip".
#
# COMO USAR (no G15, no PowerShell, dentro da pasta do projeto):
#     .\scripts\setup_avatar_g15.ps1
#
# Depois, para rodar a live COM lip-sync, use o atalho que este script cria:
#     .\start-live-g15.ps1
#
# OBS.: a placa RTX 50 e' nova (arquitetura Blackwell). Por isso instalamos o
# PyTorch com CUDA 12.8 (cu128) - versoes antigas dao erro "no kernel image".
#
# HONESTIDADE: o Wav2Lip e' um projeto antigo e as vezes exige ajuste fino de
# dependencias. Se algo falhar, me chame que a gente resolve o passo especifico.
# ============================================================

param(
    # Python 3.10 e' o mais tranquilo para o Wav2Lip. Se voce tiver o "py"
    # launcher, deixamos ele escolher a 3.10 automaticamente.
    [string]$PythonExe = "",
    # Fork do Wav2Lip com correcoes para ambientes novos (Windows/Colab).
    [string]$Wav2LipRepo = "https://github.com/justinjohn0306/Wav2Lip.git"
)

$ErrorActionPreference = "Stop"

# Raiz do projeto = pasta acima de \scripts
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "[AVATAR] Projeto: $Root" -ForegroundColor Cyan

# Pastas de trabalho (tudo fora do Git; ver .gitignore)
$AvatarDir = Join-Path $Root "avatar"
$RepoDir = Join-Path $AvatarDir "Wav2Lip"
$VenvDir = Join-Path $Root ".venv-avatar"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $AvatarDir | Out-Null

# ------------------------------------------------------------
# 1) Escolher o Python para criar a venv
# ------------------------------------------------------------
function Resolve-Python {
    param([string]$Preferred)
    if ($Preferred -and (Test-Path $Preferred)) { return $Preferred }
    # Tenta o launcher "py -3.10" (recomendado para Wav2Lip)
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $v = & py -3.10 -c "import sys;print(sys.version.split()[0])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) { Write-Host "[AVATAR] Usando Python $v (py -3.10)"; return "py|-3.10" }
        }
        catch {}
        try {
            $v = & py -c "import sys;print(sys.version.split()[0])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) { Write-Host "[AVATAR] Usando Python $v (py)"; return "py|" }
        }
        catch {}
    }
    if (Get-Command python -ErrorAction SilentlyContinue) { return "python|" }
    throw "Nao encontrei o Python. Instale o Python 3.10 (marque 'Add to PATH') e rode de novo."
}

# ------------------------------------------------------------
# 2) Criar a venv dedicada do avatar (.venv-avatar)
# ------------------------------------------------------------
if (-not (Test-Path $VenvPy)) {
    $pick = Resolve-Python -Preferred $PythonExe
    $parts = $pick.Split("|")
    $exe = $parts[0]
    $arg = $parts[1]
    Write-Host "[AVATAR] Criando ambiente virtual .venv-avatar ..." -ForegroundColor Cyan
    if ($arg) { & $exe $arg -m venv $VenvDir } else { & $exe -m venv $VenvDir }
    if (-not (Test-Path $VenvPy)) { throw "Falha ao criar a venv em $VenvDir" }
}
else {
    Write-Host "[AVATAR] Ambiente .venv-avatar ja existe." -ForegroundColor DarkGray
}

Write-Host "[AVATAR] Atualizando pip ..." -ForegroundColor Cyan
& $VenvPy -m pip install --upgrade pip wheel setuptools

# ------------------------------------------------------------
# 3) PyTorch com CUDA 12.8 (obrigatorio para a RTX 50 / Blackwell)
# ------------------------------------------------------------
Write-Host "[AVATAR] Instalando PyTorch CUDA 12.8 (cu128) - pode demorar ..." -ForegroundColor Cyan
& $VenvPy -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# ------------------------------------------------------------
# 4) Baixar (clonar) o Wav2Lip
# ------------------------------------------------------------
if (-not (Test-Path (Join-Path $RepoDir "inference.py"))) {
    Write-Host "[AVATAR] Baixando o Wav2Lip ..." -ForegroundColor Cyan
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git nao encontrado. Instale o Git (https://git-scm.com) e rode de novo."
    }
    git clone --depth 1 $Wav2LipRepo $RepoDir
}
else {
    Write-Host "[AVATAR] Wav2Lip ja baixado." -ForegroundColor DarkGray
}

# ------------------------------------------------------------
# 5) Dependencias do Wav2Lip (versoes que costumam funcionar)
#    Obs.: NAO usamos o requirements.txt do repo porque ele fixa versoes
#    muito antigas que quebram no Python novo. Estas costumam rodar bem.
# ------------------------------------------------------------
Write-Host "[AVATAR] Instalando dependencias do Wav2Lip ..." -ForegroundColor Cyan
& $VenvPy -m pip install "numpy==1.26.4" "librosa==0.9.2" "opencv-python" "scipy" "tqdm" "numba"

# ------------------------------------------------------------
# 6) Baixar os pesos (modelos treinados)
#    - wav2lip_gan.pth  -> gera a boca sincronizada (melhor qualidade)
#    - s3fd.pth         -> detecta o rosto na foto
# ------------------------------------------------------------
$CkptDir = Join-Path $RepoDir "checkpoints"
$FaceDir = Join-Path $RepoDir "face_detection\detection\sfd"
New-Item -ItemType Directory -Force -Path $CkptDir | Out-Null
New-Item -ItemType Directory -Force -Path $FaceDir | Out-Null

$CkptPath = Join-Path $CkptDir "wav2lip_gan.pth"
$S3fdPath = Join-Path $FaceDir "s3fd.pth"

function Get-Model {
    param([string]$Url, [string]$Dest, [int]$MinBytes)
    if ((Test-Path $Dest) -and ((Get-Item $Dest).Length -ge $MinBytes)) {
        Write-Host "[AVATAR]   ja existe: $(Split-Path $Dest -Leaf)" -ForegroundColor DarkGray
        return $true
    }
    try {
        Write-Host "[AVATAR]   baixando: $(Split-Path $Dest -Leaf) ..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
        if ((Get-Item $Dest).Length -ge $MinBytes) { return $true }
        Write-Host "[AVATAR]   AVISO: arquivo baixado parece pequeno demais." -ForegroundColor Yellow
        return $false
    }
    catch {
        Write-Host "[AVATAR]   FALHOU o download automatico: $_" -ForegroundColor Yellow
        return $false
    }
}

# Pesos hospedados nos "releases" do fork justinjohn0306 (tag: models).
$okCkpt = Get-Model -Url "https://github.com/justinjohn0306/Wav2Lip/releases/download/models/wav2lip_gan.pth" -Dest $CkptPath -MinBytes 200000000
$okS3fd = Get-Model -Url "https://github.com/justinjohn0306/Wav2Lip/releases/download/models/s3fd.pth" -Dest $S3fdPath -MinBytes 80000000

if (-not $okCkpt -or -not $okS3fd) {
    Write-Host ""
    Write-Host "[AVATAR] Nao consegui baixar todos os pesos automaticamente." -ForegroundColor Yellow
    Write-Host "         Baixe manualmente e coloque nestes caminhos:" -ForegroundColor Yellow
    Write-Host "           wav2lip_gan.pth -> $CkptPath" -ForegroundColor Yellow
    Write-Host "           s3fd.pth        -> $S3fdPath" -ForegroundColor Yellow
    Write-Host "         Links (releases do fork justinjohn0306/Wav2Lip, tag 'models')." -ForegroundColor Yellow
}

# ------------------------------------------------------------
# 7) Conferir se a placa (CUDA) foi reconhecida
# ------------------------------------------------------------
Write-Host "[AVATAR] Verificando a placa de video (CUDA) ..." -ForegroundColor Cyan
& $VenvPy -c "import torch; print('CUDA disponivel:', torch.cuda.is_available()); print('Placa:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NENHUMA')"

# ------------------------------------------------------------
# 8) Criar o atalho start-live-g15.ps1 (liga o motor wav2lip e sobe o painel)
# ------------------------------------------------------------
$launcher = Join-Path $Root "start-live-g15.ps1"
$launcherBody = @"
# ============================================================
# ATLAS OS - start-live-g15.ps1  (GERADO por setup_avatar_g15.ps1)
# Sobe o painel com o LIP-SYNC ligado (motor Wav2Lip) no G15.
# ============================================================
Set-Location -Path `$PSScriptRoot
`$env:ATLAS_AVATAR_ENGINE = "wav2lip"
`$env:ATLAS_WAV2LIP_DIR   = "$RepoDir"
`$env:ATLAS_WAV2LIP_PY    = "$VenvPy"
`$env:ATLAS_WAV2LIP_CKPT  = "$CkptPath"
Write-Host "[AVATAR] Motor: wav2lip (lip-sync ligado)" -ForegroundColor Green
.\start-dashboard-local.ps1
"@
Set-Content -LiteralPath $launcher -Value $launcherBody -Encoding utf8
Write-Host "[AVATAR] Atalho criado: $launcher" -ForegroundColor Green

# ------------------------------------------------------------
# 9) Auto-teste (opcional): usa a foto do apresentador ja enviada no painel.
# ------------------------------------------------------------
$presenter = Get-ChildItem (Join-Path $Root "storage\live\presenter") -Filter "presenter.*" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($presenter -and $okCkpt -and $okS3fd) {
    Write-Host "[AVATAR] Rodando um teste rapido com a foto do apresentador ..." -ForegroundColor Cyan
    $ff = & (Join-Path $Root ".venv-dash\Scripts\python.exe") -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())" 2>$null
    $testAudio = Join-Path $AvatarDir "_test.wav"
    $testOut = Join-Path $AvatarDir "_test_out.mp4"
    if ($ff) { cmd /c "`"$ff`" -y -f lavfi -i sine=frequency=220:duration=2 `"$testAudio`"" 2>$null | Out-Null }
    if (Test-Path $testAudio) {
        Push-Location $RepoDir
        & $VenvPy "inference.py" --checkpoint_path $CkptPath --face $presenter.FullName --audio $testAudio --outfile $testOut --nosmooth
        Pop-Location
        if (Test-Path $testOut) {
            Write-Host "[AVATAR] SUCESSO! Video de teste: $testOut" -ForegroundColor Green
        }
        else {
            Write-Host "[AVATAR] O teste nao gerou video. Me chame que ajusto as dependencias." -ForegroundColor Yellow
        }
    }
}
else {
    Write-Host "[AVATAR] Pulei o auto-teste (envie uma FOTO de rosto no painel para testar)." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host " PRONTO! Para rodar a live com lip-sync no G15, use:" -ForegroundColor Green
Write-Host "     .\start-live-g15.ps1" -ForegroundColor Green
Write-Host " No painel: envie uma FOTO DE ROSTO (pessoa realista) e" -ForegroundColor Green
Write-Host " ligue 'Video do apresentador (avatar)'." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
