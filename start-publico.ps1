# ============================================================
# ATLAS OS - Iniciar o painel com LINK PUBLICO (https)
#
# Use este script quando for PUBLICAR de verdade no Instagram e
# Facebook. Ele cria um endereco publico e seguro (https) que aponta
# para o seu painel, para que o Instagram/Facebook consigam baixar o
# video. Usa um tunel gratuito do Cloudflare (sem cadastro).
#
# Uso: clique com o botao direito > "Executar com PowerShell"
#      OU no terminal:  ./start-publico.ps1
#
# Para uso APENAS no seu PC (sem publicar), use start-dashboard-local.ps1
# ============================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# 1) Ambiente virtual (cria na primeira vez).
if (-not (Test-Path ".\.venv-dash\Scripts\python.exe")) {
    Write-Host "[ATLAS] Criando ambiente virtual .venv-dash ..." -ForegroundColor Cyan
    py -m venv .venv-dash
    .\.venv-dash\Scripts\python.exe -m pip install --upgrade pip
    .\.venv-dash\Scripts\python.exe -m pip install -r requirements-dashboard.txt
}

# 2) Garante o cloudflared.exe (baixa o binario oficial se faltar).
$cloudflared = Join-Path $PSScriptRoot "cloudflared.exe"
if (-not (Test-Path $cloudflared)) {
    Write-Host "[ATLAS] Baixando o cloudflared (uma unica vez) ..." -ForegroundColor Cyan
    $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    try {
        Invoke-WebRequest -Uri $url -OutFile $cloudflared -UseBasicParsing
    } catch {
        Write-Host "[ATLAS] Nao consegui baixar o cloudflared automaticamente." -ForegroundColor Red
        Write-Host "        Baixe manualmente em: $url" -ForegroundColor Yellow
        Write-Host "        e salve como cloudflared.exe nesta pasta." -ForegroundColor Yellow
        exit 1
    }
}

# 3) Abre o tunel publico apontando para a porta 8000 e captura a URL.
$logFile = Join-Path $env:TEMP "atlas_cloudflared.log"
if (Test-Path $logFile) { Remove-Item $logFile -Force }
if (Test-Path "$logFile.err") { Remove-Item "$logFile.err" -Force }

Write-Host "[ATLAS] Abrindo o link publico (aguarde alguns segundos) ..." -ForegroundColor Cyan
$tunnel = Start-Process -FilePath $cloudflared `
    -ArgumentList "tunnel --url http://localhost:8000 --no-autoupdate" `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError "$logFile.err" `
    -WindowStyle Hidden -PassThru

# Procura a URL https://<aleatorio>.trycloudflare.com no log (ate ~30s).
# IMPORTANTE: ignora "api.trycloudflare.com" (endpoint interno do cloudflared)
# e detecta falha de rede (comum em rede corporativa com inspecao de TLS).
$publicUrl = $null
$failed = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $content = ""
    if (Test-Path $logFile)      { $content += Get-Content $logFile -Raw -ErrorAction SilentlyContinue }
    if (Test-Path "$logFile.err"){ $content += Get-Content "$logFile.err" -Raw -ErrorAction SilentlyContinue }

    if ($content -match "failed to request quick Tunnel" -or $content -match "tls: handshake failure") {
        $failed = $true
        break
    }
    foreach ($m in [regex]::Matches($content, "https://[a-z0-9-]+\.trycloudflare\.com")) {
        if ($m.Value -notlike "*api.trycloudflare.com*") { $publicUrl = $m.Value; break }
    }
    if ($publicUrl) { break }
}

if ($failed -or -not $publicUrl) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host " NAO FOI POSSIVEL PUBLICAR NO INSTAGRAM E FACEBOOK" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host ""
    if ($failed) {
        Write-Host " O QUE ACONTECEU:" -ForegroundColor Yellow
        Write-Host "   A sua rede atual BLOQUEOU o link publico." -ForegroundColor White
        Write-Host "   (Isso e normal em rede de EMPRESA, como a rede da Ford," -ForegroundColor Gray
        Write-Host "    que tem seguranca/Zscaler e nao deixa criar o tunel.)" -ForegroundColor Gray
        Write-Host ""
        Write-Host " POR QUE ISSO IMPORTA:" -ForegroundColor Yellow
        Write-Host "   O YouTube funciona em qualquer rede (o programa ENVIA o video)." -ForegroundColor White
        Write-Host "   Ja o Instagram e o Facebook precisam BAIXAR o video de um" -ForegroundColor White
        Write-Host "   endereco publico na internet - e esse endereco a rede bloqueou." -ForegroundColor White
        Write-Host ""
        Write-Host " COMO RESOLVER (escolha UMA):" -ForegroundColor Green
        Write-Host "   1) Ligue o roteador do seu CELULAR (hotspot / ponto de acesso)," -ForegroundColor White
        Write-Host "      conecte o computador nele, e rode este script de novo." -ForegroundColor White
        Write-Host "   2) Ou rode este script no Wi-Fi da sua CASA." -ForegroundColor White
        Write-Host ""
        Write-Host "   Dica: nao precisa mudar mais nada. Assim que estiver numa rede" -ForegroundColor Gray
        Write-Host "   pessoal, o link publico sobe sozinho e o Instagram/Facebook" -ForegroundColor Gray
        Write-Host "   voltam a publicar automaticamente." -ForegroundColor Gray
    } else {
        Write-Host " Verifique sua conexao com a internet e tente de novo." -ForegroundColor Yellow
    }
    Write-Host ""
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " LINK PUBLICO ATIVO:" -ForegroundColor Green
Write-Host "   $publicUrl" -ForegroundColor White
Write-Host " (mantenha esta janela aberta enquanto publica)" -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

# 4) Variaveis de ambiente. Banco SQLite local + URL publica do tunel.
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:DATABASE_URL = "sqlite:///./atlas_local.db"
$env:ATLAS_ROOT = (Get-Location).Path
$env:ATLAS_PUBLIC_BASE_URL = $publicUrl

# 5) Sobe a API + painel. Ao fechar (Ctrl+C), derruba o tunel tambem.
try {
    Write-Host "[ATLAS] Painel em http://127.0.0.1:8000  (Ctrl+C para parar)" -ForegroundColor Green
    .\.venv-dash\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
finally {
    if ($tunnel -and -not $tunnel.HasExited) {
        Write-Host "[ATLAS] Encerrando o link publico ..." -ForegroundColor Cyan
        Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
    }
}
