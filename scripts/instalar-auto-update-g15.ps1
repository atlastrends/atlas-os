# ============================================================
# ATLAS OS - scripts/instalar-auto-update-g15.ps1
#
# (OPCIONAL) Faz o Atlas se ATUALIZAR SOZINHO no Windows, sem voce precisar
# rodar nada. Ele cria uma "Tarefa Agendada" que roda o updater:
#   - toda vez que voce faz login no Windows;
#   - e uma vez por dia (de manha).
#
# COMO USAR (no G15, dentro da pasta do projeto):
#     .\scripts\instalar-auto-update-g15.ps1
#
# PARA DESINSTALAR (parar de atualizar sozinho):
#     .\scripts\instalar-auto-update-g15.ps1 -Remover
#
# OBS.: a tarefa mantem o CODIGO sempre atualizado. Se o painel ja estiver
# aberto, feche e abra de novo para ver as mudancas do backend. O jeito mais
# garantido continua sendo abrir a live pelo atalho .\start-live-g15.ps1,
# que ja atualiza antes de subir.
# ============================================================

param(
    # Horario da atualizacao diaria (formato 24h, ex.: "08:00").
    [string]$Horario = "08:00",
    # Use -Remover para desinstalar a tarefa.
    [switch]$Remover
)

$ErrorActionPreference = "Stop"
$TaskName = "AtlasOS-AutoUpdate-G15"

$Root = Split-Path -Parent $PSScriptRoot
$updater = Join-Path $Root "scripts\update-atlas-g15.ps1"

# --- Desinstalar ---
if ($Remover) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[AUTO-UPDATE] Tarefa removida. O Atlas nao vai mais se atualizar sozinho." -ForegroundColor Green
    }
    else {
        Write-Host "[AUTO-UPDATE] Nao havia tarefa instalada. Nada a fazer." -ForegroundColor DarkGray
    }
    return
}

if (-not (Test-Path $updater)) {
    throw "Nao encontrei o updater em: $updater"
}

Write-Host "[AUTO-UPDATE] Instalando atualizacao automatica ..." -ForegroundColor Cyan

# Acao: rodar o updater em modo silencioso, sem abrir janela.
$psExe = (Get-Command powershell.exe).Source
$action = New-ScheduledTaskAction -Execute $psExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$updater`" -Quiet" `
    -WorkingDirectory $Root

# Gatilhos: ao fazer login + todo dia no horario escolhido.
$trigLogon = New-ScheduledTaskTrigger -AtLogOn
$trigDaily = New-ScheduledTaskTrigger -Daily -At $Horario

# Roda como o usuario atual, com a maquina na tomada ou na bateria.
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# Substitui se ja existir.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName `
    -Action $action `
    -Trigger @($trigLogon, $trigDaily) `
    -Principal $principal `
    -Settings $settings `
    -Description "Atualiza o Atlas OS automaticamente a partir do GitHub (G15)." | Out-Null

Write-Host "[AUTO-UPDATE] Pronto! O Atlas vai se atualizar sozinho:" -ForegroundColor Green
Write-Host "               - ao ligar/logar no Windows;" -ForegroundColor Green
Write-Host ("               - e todo dia as {0}." -f $Horario) -ForegroundColor Green
Write-Host "[AUTO-UPDATE] Para desligar: .\scripts\instalar-auto-update-g15.ps1 -Remover" -ForegroundColor DarkGray
