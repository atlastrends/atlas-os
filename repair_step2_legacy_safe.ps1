$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Remove-Item `
    Env:\ATLAS_WORKER_RUN_ENABLED `
    -ErrorAction SilentlyContinue

$projectRoot = (Get-Location).Path

$migrationPath = Join-Path `
    $projectRoot `
    "alembic\versions\e4b82d7c91aa_amazon_catalog_workaround.py"

if (-not (Test-Path -LiteralPath $migrationPath -PathType Leaf)) {
    throw "A migracao Amazon nao foi encontrada."
}

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
        $output = @(
            & docker @Arguments 2>&1 |
            ForEach-Object {
                $_.ToString()
            }
        )

        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }

    foreach ($line in $output) {
        Write-Host $line
    }

    if ($exitCode -ne 0) {
        throw "$FailureMessage Exit code: $exitCode"
    }

    return $output
}

Write-Host ""
Write-Host "======================================================="
Write-Host "REPARO SEGURO DA MIGRACAO AMAZON"
Write-Host "======================================================="
Write-Host "Worker autorizado: $(Test-Path Env:\ATLAS_WORKER_RUN_ENABLED)"
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
    -FailureMessage "Nao foi possivel iniciar PostgreSQL e Redis." |
Out-Null

Write-Host ""
Write-Host "Aguardando o PostgreSQL ficar saudavel..."

$postgresHealthy = $false

for ($attempt = 1; $attempt -le 30; $attempt++) {
    $containerId = (
        & docker compose ps -q postgres 2>$null
    ).Trim()

    if (-not [string]::IsNullOrWhiteSpace($containerId)) {
        $healthStatus = (
            & docker inspect `
                --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" `
                $containerId `
                2>$null
        ).Trim()

        if (
            $healthStatus -eq "healthy" -or
            $healthStatus -eq "running"
        ) {
            $postgresHealthy = $true
            break
        }
    }

    Start-Sleep -Seconds 2
}

if (-not $postgresHealthy) {
    throw "O PostgreSQL nao ficou saudavel no tempo esperado."
}

Write-Host "PostgreSQL saudavel."
Write-Host ""

Write-Host "Confirmando a revisao atual do banco..."

$currentOutput = Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "run",
        "--rm",
        "api",
        "alembic",
        "current"
    ) `
    -FailureMessage "Nao foi possivel consultar a revisao atual."

$currentText = $currentOutput -join "`n"

$alreadyApplied = $currentText -match "e4b82d7c91aa"
$previousRevision = $currentText -match "7c91e4d8a2f0"

if (-not $alreadyApplied -and -not $previousRevision) {
    throw (
        "O banco esta em uma revisao inesperada. " +
        "Nenhuma migracao foi executada."
    )
}

if ($alreadyApplied) {
    Write-Host ""
    Write-Host "A migracao Amazon ja esta aplicada."
}
else {
    Write-Host ""
    Write-Host "Banco confirmado na revisao anterior."
}

Write-Host ""
Write-Host "Diagnosticando os dados legados..."

$diagnosticCommand = "psql -U `"`$POSTGRES_USER`" -d `"`$POSTGRES_DB`" -tAc `"SELECT 'asin_maior_que_10=' || COUNT(*) FROM affiliate_products WHERE char_length(asin) > 10; SELECT 'titulo_maior_que_500=' || COUNT(*) FROM affiliate_products WHERE char_length(title) > 500; SELECT 'categoria_maior_que_255=' || COUNT(*) FROM affiliate_products WHERE category IS NOT NULL AND char_length(category) > 255;`""

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "exec",
        "-T",
        "postgres",
        "sh",
        "-lc",
        $diagnosticCommand
    ) `
    -FailureMessage "Nao foi possivel diagnosticar os dados legados." |
Out-Null

if (-not $alreadyApplied) {
    Write-Host ""
    Write-Host "Criando backup da migracao..."

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

    $backupPath = (
        $migrationPath +
        ".before_legacy_safe_" +
        $timestamp +
        ".bak"
    )

    Copy-Item `
        -LiteralPath $migrationPath `
        -Destination $backupPath `
        -Force

    Write-Host "Backup criado."

    $lines = [System.IO.File]::ReadAllLines(
        $migrationPath,
        [System.Text.Encoding]::UTF8
    )

    $result = New-Object `
        "System.Collections.Generic.List[string]"

    $protectedColumns = @(
        "asin",
        "title",
        "category"
    )

    $markersFound = @{
        asin = $false
        title = $false
        category = $false
    }

    foreach ($line in $lines) {
        foreach ($column in $protectedColumns) {
            $marker = (
                "LEGACY_SAFE_NO_NARROW_" +
                $column.ToUpperInvariant()
            )

            if ($line.Contains($marker)) {
                $markersFound[$column] = $true
            }
        }
    }

    $insideUpgrade = $false
    $index = 0

    while ($index -lt $lines.Length) {
        $line = $lines[$index]

        if ($line -match '^\s*def\s+upgrade\s*\(') {
            $insideUpgrade = $true
        }
        elseif ($line -match '^\s*def\s+downgrade\s*\(') {
            $insideUpgrade = $false
        }

        if (
            $insideUpgrade -and
            $line -match '^\s*op\.alter_column\s*\('
        ) {
            $block = New-Object `
                "System.Collections.Generic.List[string]"

            $balance = 0

            do {
                $blockLine = $lines[$index]
                $block.Add($blockLine)

                $openCount = (
                    [regex]::Matches(
                        $blockLine,
                        '\('
                    )
                ).Count

                $closeCount = (
                    [regex]::Matches(
                        $blockLine,
                        '\)'
                    )
                ).Count

                $balance += $openCount
                $balance -= $closeCount
                $index++
            }
            while (
                $index -lt $lines.Length -and
                $balance -gt 0
            )

            $blockText = $block -join "`n"

            $isAffiliateProduct = (
                $blockText -match
                '["'']affiliate_products["'']'
            )

            $matchedColumn = $null

            if ($isAffiliateProduct) {
                foreach ($column in $protectedColumns) {
                    $columnPattern = (
                        '["'']' +
                        [regex]::Escape($column) +
                        '["'']'
                    )

                    if ($blockText -match $columnPattern) {
                        $matchedColumn = $column
                        break
                    }
                }
            }

            if ($null -ne $matchedColumn) {
                $marker = (
                    "LEGACY_SAFE_NO_NARROW_" +
                    $matchedColumn.ToUpperInvariant()
                )

                $result.Add(
                    "    # $marker"
                )

                $result.Add(
                    "    # Coluna legada preservada sem reducao de tamanho."
                )

                $result.Add(
                    "    # Novos valores continuam validados pela aplicacao."
                )

                $result.Add("")

                $markersFound[$matchedColumn] = $true

                Write-Host (
                    "Reducao removida com seguranca: " +
                    $matchedColumn
                )

                continue
            }

            foreach ($blockLine in $block) {
                $result.Add($blockLine)
            }

            continue
        }

        $result.Add($line)
        $index++
    }

    foreach ($column in $protectedColumns) {
        if (-not $markersFound[$column]) {
            throw (
                "Nao foi possivel proteger a coluna " +
                $column +
                ". O backup foi preservado."
            )
        }
    }

    $newMigrationText = $result -join "`r`n"

    if (
        $newMigrationText -notmatch
        'e4b82d7c91aa'
    ) {
        throw "O identificador da migracao nao foi encontrado."
    }

    if (
        $newMigrationText -notmatch
        '7c91e4d8a2f0'
    ) {
        throw "A revisao anterior nao foi encontrada."
    }

    [System.IO.File]::WriteAllText(
        $migrationPath,
        $newMigrationText,
        (New-Object System.Text.UTF8Encoding($false))
    )

    Write-Host ""
    Write-Host "Validando a sintaxe Python da migracao..."

    Invoke-DockerChecked `
        -Arguments @(
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "api",
            "python",
            "-m",
            "py_compile",
            "alembic/versions/e4b82d7c91aa_amazon_catalog_workaround.py"
        ) `
        -FailureMessage "A migracao corrigida possui erro de sintaxe." |
    Out-Null

    Write-Host ""
    Write-Host "Confirmando o head reconhecido pelo Alembic..."

    $headsOutput = Invoke-DockerChecked `
        -Arguments @(
            "compose",
            "run",
            "--rm",
            "api",
            "alembic",
            "heads"
        ) `
        -FailureMessage "O Alembic nao reconheceu a migracao."

    $headsText = $headsOutput -join "`n"

    if ($headsText -notmatch "e4b82d7c91aa") {
        throw "A migracao Amazon nao aparece como head."
    }

    Write-Host ""
    Write-Host "Aplicando a migracao corrigida..."

    Invoke-DockerChecked `
        -Arguments @(
            "compose",
            "run",
            "--rm",
            "api",
            "alembic",
            "upgrade",
            "head"
        ) `
        -FailureMessage "A migracao corrigida terminou com erro." |
    Out-Null
}

Write-Host ""
Write-Host "Confirmando a revisao final..."

$finalOutput = Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "run",
        "--rm",
        "api",
        "alembic",
        "current"
    ) `
    -FailureMessage "Nao foi possivel confirmar a revisao final."

$finalText = $finalOutput -join "`n"

if ($finalText -notmatch "e4b82d7c91aa") {
    throw "O banco nao terminou na revisao Amazon esperada."
}

Write-Host ""
Write-Host "Iniciando somente a API..."

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "up",
        "-d",
        "api"
    ) `
    -FailureMessage "Nao foi possivel iniciar a API." |
Out-Null

Write-Host ""
Write-Host "Aguardando a API responder..."

$apiOnline = $false
$healthResult = $null

for ($attempt = 1; $attempt -le 20; $attempt++) {
    try {
        $healthResult = Invoke-RestMethod `
            -Uri "http://localhost:8000/" `
            -Method Get `
            -TimeoutSec 5

        $apiOnline = $true
        break
    }
    catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $apiOnline) {
    Write-Host ""
    Write-Host "Logs recentes da API:"

    Invoke-DockerChecked `
        -Arguments @(
            "compose",
            "logs",
            "--tail",
            "100",
            "api"
        ) `
        -FailureMessage "A API nao respondeu e os logs falharam." |
    Out-Null

    throw "A migracao foi aplicada, mas a API nao respondeu."
}

Write-Host ""
Write-Host "Estado final dos servicos:"

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "ps"
    ) `
    -FailureMessage "Nao foi possivel consultar os servicos." |
Out-Null

Write-Host ""
Write-Host "======================================================="
Write-Host "REPARO CONCLUIDO COM SUCESSO"
Write-Host "======================================================="
Write-Host "Migracao atual: e4b82d7c91aa"
Write-Host "API online: True"
Write-Host "Worker autorizado: $(Test-Path Env:\ATLAS_WORKER_RUN_ENABLED)"
Write-Host ""