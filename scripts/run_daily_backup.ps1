$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv-dash\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "py"
}

$arguments = @(
    (Join-Path $PSScriptRoot "atlas_daily_backup.py"),
    "create",
    "--repo-root", $repo,
    "--private-root", (Join-Path $repo "backups\daily")
)

if ($env:ATLAS_BACKUP_MIRROR) {
    $arguments += @("--mirror-root", $env:ATLAS_BACKUP_MIRROR)
}

& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Atlas daily backup failed with exit code $LASTEXITCODE"
}
