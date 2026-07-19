$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Set-Location "C:\atlas-os"

Remove-Item `
    Env:\ATLAS_WORKER_RUN_ENABLED `
    -ErrorAction SilentlyContinue

function Invoke-DockerChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments,

        [Parameter(Mandatory = $true)]
        [string] $FailureMessage
    )

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    try {
        $output = & docker @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    $output | ForEach-Object {
        Write-Host $_
    }

    if ($exitCode -ne 0) {
        throw "$FailureMessage Exit code: $exitCode"
    }

    return @($output)
}

Write-Host ""
Write-Host "======================================================="
Write-Host "CORRECAO DO PASSO 2"
Write-Host "======================================================="

$migrationPath = Join-Path `
    (Get-Location).Path `
    "alembic\versions\e4b82d7c91aa_amazon_catalog_workaround.py"

if (-not (Test-Path -LiteralPath $migrationPath -PathType Leaf)) {
    throw "A migracao e4b82d7c91aa nao existe no projeto."
}

$migrationText = Get-Content `
    -LiteralPath $migrationPath `
    -Raw

if ($migrationText -notmatch 'revision:\s*str\s*=\s*"e4b82d7c91aa"') {
    throw "O identificador da migracao e4b82d7c91aa esta incorreto."
}

if ($migrationText -notmatch 'down_revision:.*"7c91e4d8a2f0"') {
    throw "A migracao nao aponta para a revisao anterior correta."
}

Write-Host ""
Write-Host "Migracao local encontrada e validada."

Write-Host ""
Write-Host "Parando somente a API..."

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "stop",
        "api"
    ) `
    -FailureMessage "Nao foi possivel parar a API."

Write-Host ""
Write-Host "Garantindo PostgreSQL e Redis ativos..."

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "up",
        "-d",
        "postgres",
        "redis"
    ) `
    -FailureMessage "Nao foi possivel iniciar a infraestrutura."

Write-Host ""
Write-Host "Aguardando PostgreSQL ficar saudavel..."

$postgresHealthy = $false

for ($attempt = 1; $attempt -le 30; $attempt++) {
    $health = & docker inspect `
        --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}" `
        atlas_postgres `
        2>$null

    if ($LASTEXITCODE -eq 0 -and $health -eq "healthy") {
        $postgresHealthy = $true
        break
    }

    Start-Sleep -Seconds 2
}

if (-not $postgresHealthy) {
    throw "PostgreSQL nao ficou saudavel dentro do prazo."
}

Write-Host "PostgreSQL saudavel."

Write-Host ""
Write-Host "Verificando se o container enxerga a migracao..."

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "api",
        "python",
        "-c",
        "from pathlib import Path; p=Path('/atlas/alembic/versions/e4b82d7c91aa_amazon_catalog_workaround.py'); assert p.is_file(), 'migration_not_visible'; print('migration_visible:', p)"
    ) `
    -FailureMessage "O container nao enxerga a migracao."

Write-Host ""
Write-Host "Revisoes head reconhecidas pelo Alembic..."

$headsOutput = Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "api",
        "alembic",
        "heads"
    ) `
    -FailureMessage "Falha ao consultar o head do Alembic."

$headsText = $headsOutput -join "`n"

if ($headsText -notmatch "e4b82d7c91aa") {
    throw "O Alembic nao reconheceu e4b82d7c91aa como head."
}

Write-Host ""
Write-Host "Revisao atual antes da migracao..."

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "run",
        "--rm",
        "api",
        "alembic",
        "current"
    ) `
    -FailureMessage "Falha ao consultar a revisao atual."

Write-Host ""
Write-Host "Aplicando migracao e4b82d7c91aa..."

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "run",
        "--rm",
        "api",
        "alembic",
        "upgrade",
        "e4b82d7c91aa"
    ) `
    -FailureMessage "A migracao Amazon falhou."

Write-Host ""
Write-Host "Confirmando revisao final..."

$currentOutput = Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "run",
        "--rm",
        "api",
        "alembic",
        "current"
    ) `
    -FailureMessage "Falha ao confirmar a revisao final."

$currentText = $currentOutput -join "`n"

if ($currentText -notmatch "e4b82d7c91aa") {
    throw "O banco nao terminou na revisao e4b82d7c91aa."
}

Write-Host ""
Write-Host "Verificando colunas criadas no PostgreSQL..."

$columnOutput = Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "exec",
        "-T",
        "postgres",
        "sh",
        "-lc",
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT column_name FROM information_schema.columns WHERE table_schema=''public'' AND table_name=''affiliate_products'' ORDER BY column_name;"'
    ) `
    -FailureMessage "Falha ao consultar as colunas Amazon."

$requiredColumns = @(
    "affiliate_url_verified_at",
    "catalog_status",
    "click_count",
    "data_source",
    "description",
    "features",
    "image_url",
    "is_short_affiliate_url",
    "last_verified_at",
    "notes",
    "price_observed_at",
    "product_url"
)

$columnText = $columnOutput -join "`n"
$missingColumns = @()

foreach ($column in $requiredColumns) {
    if ($columnText -notmatch "(?m)^$([regex]::Escape($column))\s*$") {
        $missingColumns += $column
    }
}

if ($missingColumns.Count -gt 0) {
    throw "Colunas ausentes: $($missingColumns -join ', ')"
}

Write-Host "Todas as colunas Amazon foram confirmadas."

Write-Host ""
Write-Host "Recriando a API com as variaveis atuais..."

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "up",
        "-d",
        "--force-recreate",
        "api"
    ) `
    -FailureMessage "Falha ao recriar a API."

Write-Host ""
Write-Host "Aguardando a API responder..."

$health = $null

for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod `
            -Uri "http://localhost:8000/" `
            -Method Get `
            -TimeoutSec 5

        if ($health.status -eq "online") {
            break
        }
    }
    catch {
        $health = $null
    }

    Start-Sleep -Seconds 2
}

if ($null -eq $health -or $health.status -ne "online") {
    Write-Host ""
    Write-Host "Ultimos logs da API:"

    & docker compose logs `
        --tail 150 `
        api

    throw "A API nao ficou online."
}

if ($health.atlas_engine_enabled -ne $false) {
    throw "O motor automatico foi ativado inesperadamente."
}

Write-Host ""
Write-Host "Testando catalogo Amazon..."

try {
    $catalog = Invoke-RestMethod `
        -Uri "http://localhost:8000/affiliate/amazon/products" `
        -Method Get `
        -TimeoutSec 15
}
catch {
    Write-Host ""
    Write-Host "Ultimos logs da API:"

    & docker compose logs `
        --tail 200 `
        api

    throw "O endpoint do catalogo continua com erro."
}

if ($null -eq $catalog.total) {
    throw "O catalogo respondeu sem o campo total."
}

Write-Host ""
Write-Host "Confirmando que o worker esta parado..."

$runningServices = @(
    & docker compose `
        --profile worker `
        ps `
        --status running `
        --services
)

if ($LASTEXITCODE -ne 0) {
    throw "Falha ao consultar os servicos em execucao."
}

$workerRunning = $runningServices -contains "worker"

if ($workerRunning) {
    throw "O worker esta em execucao inesperadamente."
}

Write-Host ""
Write-Host "======================================================="
Write-Host "PASSO 2 CORRIGIDO E VALIDADO"
Write-Host "======================================================="
Write-Host "API online: $($health.status)"
Write-Host "Motor automatico: $($health.atlas_engine_enabled)"
Write-Host "Catalogo Amazon: $($health.amazon_catalog_enabled)"
Write-Host "Produtos existentes: $($catalog.total)"
Write-Host "Revision atual: e4b82d7c91aa"
Write-Host "Worker em execucao: False"
Write-Host "======================================================="