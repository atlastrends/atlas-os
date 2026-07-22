# ============================================================
# ATLAS OS - scripts/gerar_modelo.ps1
#
# Gera a FOTO da apresentadora (modelo virtual) usando uma IA de imagem
# GRATUITA (Pollinations). A imagem e' gerada por IA (nao e' pessoa real),
# entao pode usar na live sem problema de direitos.
#
# DOIS MODOS:
#   .\scripts\gerar_modelo.ps1
#       -> salva em  assets/presenter_default.jpg  (MODELO PADRAO do projeto).
#          Esse arquivo vai para o GitHub. Depois faca commit/push para
#          sincronizar com todas as maquinas (inclusive o G15).
#
#   .\scripts\gerar_modelo.ps1 -Local
#       -> salva em  storage/live/presenter/presenter.jpg  (MODELO SO' DESTE PC).
#          NAO vai para o GitHub, tem PRIORIDADE sobre o padrao e SOBREVIVE
#          as atualizacoes automaticas. Use no G15 para trocar a modelo sem
#          precisar mexer no GitHub.
#
# Para gerar outro rosto, rode de novo (o -Seed muda sozinho):
#     .\scripts\gerar_modelo.ps1 -Seed 1234
# ============================================================

param(
    # Descricao da apresentadora (loira e bonita, estilo estudio profissional).
    [string]$Prompt = "professional corporate headshot photo of a beautiful young blonde woman, golden blonde straight hair neatly styled, blue eyes, natural glam makeup, bright confident friendly smile, looking directly at camera, elegant white blazer, plain light gray studio background, softbox studio lighting, photorealistic, ultra detailed, sharp focus, shot on DSLR 85mm",
    [int]$Width = 720,
    [int]$Height = 1280,
    [int]$Seed = 0,
    # -Local salva como modelo SO' deste PC (gitignored, tem prioridade).
    [switch]$Local,
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $OutFile) {
    if ($Local) {
        $OutFile = Join-Path $Root "storage\live\presenter\presenter.jpg"
    }
    else {
        $OutFile = Join-Path $Root "assets\presenter_default.jpg"
    }
}
New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null

if ($Seed -le 0) { $Seed = Get-Random -Minimum 1 -Maximum 999999 }

$enc = [uri]::EscapeDataString($Prompt)
$url = "https://image.pollinations.ai/prompt/$enc?width=$Width&height=$Height&seed=$Seed&nologo=true&enhance=true&model=flux"

Write-Host "[MODELO] Gerando a apresentadora com IA (pode levar ate 1 min)..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $url -OutFile $OutFile -TimeoutSec 180

$len = (Get-Item $OutFile).Length
if ($len -lt 15000) {
    throw "A imagem gerada parece invalida (muito pequena: $len bytes). Tente de novo."
}
Write-Host ("[MODELO] Salvo: {0} ({1} KB, seed {2})" -f $OutFile, [math]::Round($len / 1kb), $Seed) -ForegroundColor Green
if ($Local) {
    Write-Host "[MODELO] Pronto! Esta modelo vale so' neste PC (tem prioridade e nao vai para o GitHub)." -ForegroundColor Green
}
else {
    Write-Host "[MODELO] Pronto! Faca commit/push para o GitHub para sincronizar com o G15." -ForegroundColor Green
}
