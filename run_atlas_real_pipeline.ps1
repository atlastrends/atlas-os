$ErrorActionPreference = "Stop"

Set-Location "C:\atlas-os"

Remove-Item Env:\ATLAS_WORKER_RUN_ENABLED -ErrorAction SilentlyContinue

$logDirectory = "C:\atlas-os\storage\video_pipeline"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

$logPath = Join-Path $logDirectory "scheduled-run.log"

$timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"

Add-Content -LiteralPath $logPath -Value "[$timestamp] PIPELINE_START"

docker compose exec -T api python -m app.automation.real_amazon_pipeline --max-videos 2 2>&1 |
    Tee-Object -FilePath $logPath -Append

$exitCode = $LASTEXITCODE

$timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"

Add-Content -LiteralPath $logPath -Value "[$timestamp] PIPELINE_EXIT=$exitCode"

exit $exitCode