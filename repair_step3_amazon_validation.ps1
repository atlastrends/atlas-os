$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Set-Location "C:\atlas-os"

Remove-Item `
    Env:\ATLAS_WORKER_RUN_ENABLED `
    -ErrorAction SilentlyContinue

$projectRoot = (Get-Location).Path

$validatorPath = Join-Path `
    $projectRoot `
    "app\services\amazon_link_validation.py"

$repositoryPath = Join-Path `
    $projectRoot `
    "app\repositories\affiliate.py"

$validationTestPath = Join-Path `
    $projectRoot `
    "validate_step2_amazon.py"

if (-not (Test-Path -LiteralPath $repositoryPath -PathType Leaf)) {
    throw "Repositorio affiliate.py nao encontrado."
}

if (-not (Test-Path -LiteralPath $validationTestPath -PathType Leaf)) {
    throw "Teste validate_step2_amazon.py nao encontrado."
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
Write-Host "CORRECAO DA VALIDACAO DE LINKS AMAZON"
Write-Host "======================================================="
Write-Host "Worker autorizado: $(Test-Path Env:\ATLAS_WORKER_RUN_ENABLED)"
Write-Host ""

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$repositoryBackup = (
    $repositoryPath +
    ".before_amazon_validation_" +
    $timestamp +
    ".bak"
)

Copy-Item `
    -LiteralPath $repositoryPath `
    -Destination $repositoryBackup `
    -Force

if (Test-Path -LiteralPath $validatorPath -PathType Leaf) {
    $validatorBackup = (
        $validatorPath +
        ".before_amazon_validation_" +
        $timestamp +
        ".bak"
    )

    Copy-Item `
        -LiteralPath $validatorPath `
        -Destination $validatorBackup `
        -Force
}

Write-Host "Backups criados."
Write-Host ""

$validatorCode = @"
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse


ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")

ASIN_PATH_PATTERNS = (
    re.compile(
        r"/dp/([A-Z0-9]{10})(?:[/?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"/gp/product/([A-Z0-9]{10})(?:[/?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"/gp/aw/d/([A-Z0-9]{10})(?:[/?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"/product/([A-Z0-9]{10})(?:[/?]|$)",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class AmazonMarketplaceRule:
    marketplace: str
    label: str
    expected_tag: str
    currency: str
    amazon_domain: str


@dataclass(frozen=True)
class ValidatedAmazonLinks:
    marketplace: str
    asin: str
    original_url: str
    affiliate_url: str
    associate_tag: str
    currency: str
    is_short_affiliate_url: bool


def _environment_value(
    primary_name: str,
    secondary_name: str,
    default: str,
) -> str:
    value = os.getenv(
        primary_name,
        os.getenv(secondary_name, default),
    )

    return str(value or default).strip()


def marketplace_rules() -> dict[str, AmazonMarketplaceRule]:
    return {
        "amazon_br": AmazonMarketplaceRule(
            marketplace="amazon_br",
            label="Amazon Brasil",
            expected_tag=_environment_value(
                "AMAZON_BR_ASSOCIATE_TAG",
                "AMAZON_BR_TAG",
                "achadosatlasb-20",
            ),
            currency="BRL",
            amazon_domain="amazon.com.br",
        ),
        "amazon_us": AmazonMarketplaceRule(
            marketplace="amazon_us",
            label="Amazon USA",
            expected_tag=_environment_value(
                "AMAZON_US_ASSOCIATE_TAG",
                "AMAZON_US_TAG",
                "atlasfindsus-20",
            ),
            currency="USD",
            amazon_domain="amazon.com",
        ),
    }


def normalize_marketplace(marketplace: Any) -> str:
    raw_value = getattr(marketplace, "value", marketplace)
    normalized = str(raw_value or "").strip().lower()

    if normalized not in marketplace_rules():
        raise ValueError(
            "Marketplace invalido. Use amazon_br ou amazon_us."
        )

    return normalized


def normalize_asin(asin: Any) -> str:
    normalized = str(asin or "").strip().upper()

    if not ASIN_PATTERN.fullmatch(normalized):
        raise ValueError(
            "ASIN invalido. Informe exatamente 10 caracteres "
            "alfanumericos."
        )

    return normalized


def normalize_required_text(
    value: Any,
    field_name: str,
) -> str:
    normalized = str(value or "").strip()

    if not normalized:
        raise ValueError(f"{field_name} e obrigatorio.")

    return normalized


def normalize_currency(
    marketplace: Any,
    currency: Any,
) -> str:
    normalized_marketplace = normalize_marketplace(marketplace)
    rule = marketplace_rules()[normalized_marketplace]

    normalized_currency = str(currency or "").strip().upper()

    if not normalized_currency:
        return rule.currency

    if normalized_currency != rule.currency:
        raise ValueError(
            f"currency invalida para {rule.label}. "
            f"Esperado: {rule.currency}."
        )

    return normalized_currency


def _normalize_host(parsed_url) -> str:
    host = str(parsed_url.hostname or "").strip().lower()
    return host.rstrip(".")


def _is_amazon_host(
    host: str,
    expected_domain: str,
) -> bool:
    return (
        host == expected_domain
        or host.endswith("." + expected_domain)
    )


def _is_short_amazon_host(host: str) -> bool:
    return host in {
        "amzn.to",
        "www.amzn.to",
    }


def _extract_url_asin(path: str) -> str | None:
    for pattern in ASIN_PATH_PATTERNS:
        match = pattern.search(path or "")

        if match:
            return match.group(1).upper()

    return None


def _extract_tag_values(parsed_url) -> list[str]:
    query = parse_qs(
        parsed_url.query,
        keep_blank_values=True,
    )

    values = query.get("tag", [])

    return [
        str(value or "").strip()
        for value in values
    ]


def validate_amazon_url(
    *,
    url: Any,
    marketplace: Any,
    asin: Any,
    associate_tag: Any,
    field_name: str,
    require_tag_for_direct_url: bool,
) -> tuple[str, bool]:
    normalized_url = normalize_required_text(
        url,
        field_name,
    )

    normalized_marketplace = normalize_marketplace(
        marketplace
    )

    normalized_asin = normalize_asin(asin)

    normalized_tag = normalize_required_text(
        associate_tag,
        "associate_tag",
    )

    rule = marketplace_rules()[normalized_marketplace]

    try:
        parsed = urlparse(normalized_url)
    except Exception as error:
        raise ValueError(
            f"{field_name} invalida."
        ) from error

    if parsed.scheme.lower() != "https":
        raise ValueError(
            f"{field_name} deve usar HTTPS."
        )

    if parsed.username or parsed.password:
        raise ValueError(
            f"{field_name} nao pode conter usuario ou senha."
        )

    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(
            f"{field_name} possui porta invalida."
        ) from error

    if port not in {None, 443}:
        raise ValueError(
            f"{field_name} possui porta nao permitida."
        )

    host = _normalize_host(parsed)

    if not host:
        raise ValueError(
            f"{field_name} nao possui dominio valido."
        )

    is_short_url = _is_short_amazon_host(host)

    if not is_short_url and not _is_amazon_host(
        host,
        rule.amazon_domain,
    ):
        raise ValueError(
            f"{field_name} deve usar um dominio oficial da "
            f"{rule.label}."
        )

    if not is_short_url:
        url_asin = _extract_url_asin(parsed.path)

        if url_asin and url_asin != normalized_asin:
            raise ValueError(
                f"O ASIN presente em {field_name} nao corresponde "
                f"ao ASIN informado."
            )

    tag_values = _extract_tag_values(parsed)

    if any(not value for value in tag_values):
        raise ValueError(
            f"{field_name} possui tracking tag vazia."
        )

    if tag_values:
        unique_tags = set(tag_values)

        if len(unique_tags) != 1:
            raise ValueError(
                f"{field_name} possui tracking tags conflitantes."
            )

        url_tag = tag_values[0]

        if url_tag != normalized_tag:
            raise ValueError(
                f"A tracking tag presente em {field_name} nao "
                f"corresponde a associate_tag."
            )

        if url_tag != rule.expected_tag:
            raise ValueError(
                f"Tracking tag invalida para {rule.label}. "
                f"Esperado: {rule.expected_tag}."
            )

    elif require_tag_for_direct_url and not is_short_url:
        raise ValueError(
            f"{field_name} deve conter a tracking tag oficial "
            f"no parametro tag."
        )

    return normalized_url, is_short_url


def validate_amazon_product_links(
    *,
    marketplace: Any,
    asin: Any,
    original_url: Any,
    affiliate_url: Any,
    associate_tag: Any,
    currency: Any = None,
) -> ValidatedAmazonLinks:
    normalized_marketplace = normalize_marketplace(
        marketplace
    )

    normalized_asin = normalize_asin(asin)

    normalized_tag = normalize_required_text(
        associate_tag,
        "associate_tag",
    )

    rule = marketplace_rules()[normalized_marketplace]

    if normalized_tag != rule.expected_tag:
        raise ValueError(
            f"associate_tag invalido para {rule.label}. "
            f"Esperado: {rule.expected_tag}."
        )

    normalized_currency = normalize_currency(
        normalized_marketplace,
        currency,
    )

    validated_original_url, _ = validate_amazon_url(
        url=original_url,
        marketplace=normalized_marketplace,
        asin=normalized_asin,
        associate_tag=normalized_tag,
        field_name="original_url",
        require_tag_for_direct_url=False,
    )

    (
        validated_affiliate_url,
        is_short_affiliate_url,
    ) = validate_amazon_url(
        url=affiliate_url,
        marketplace=normalized_marketplace,
        asin=normalized_asin,
        associate_tag=normalized_tag,
        field_name="affiliate_url",
        require_tag_for_direct_url=True,
    )

    return ValidatedAmazonLinks(
        marketplace=normalized_marketplace,
        asin=normalized_asin,
        original_url=validated_original_url,
        affiliate_url=validated_affiliate_url,
        associate_tag=normalized_tag,
        currency=normalized_currency,
        is_short_affiliate_url=is_short_affiliate_url,
    )
"@

[System.IO.File]::WriteAllText(
    $validatorPath,
    $validatorCode,
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host "Validador central Amazon gravado."

$repositoryText = [System.IO.File]::ReadAllText(
    $repositoryPath,
    [System.Text.Encoding]::UTF8
)

$importStatement = @"
from app.services.amazon_link_validation import (
    validate_amazon_product_links,
)
"@

if (
    $repositoryText -notmatch
    'from app\.services\.amazon_link_validation import'
) {
    $importAnchor = "from app.schemas.affiliate import ProductCreate"

    if (-not $repositoryText.Contains($importAnchor)) {
        throw (
            "Ponto de importacao nao encontrado em " +
            "app/repositories/affiliate.py."
        )
    }

    $repositoryText = $repositoryText.Replace(
        $importAnchor,
        $importAnchor + "`r`n" + $importStatement.TrimEnd()
    )

    Write-Host "Importacao do validador adicionada ao repository."
}
else {
    Write-Host "Importacao do validador ja estava presente."
}

$oldAssignmentBlockPattern = (
    '(?ms)' +
    '^\s{8}product\.marketplace\s*=\s*normalized_marketplace\s*\r?\n' +
    '\s{8}product\.asin\s*=\s*normalized_asin\s*\r?\n' +
    '\s{8}product\.title\s*=\s*product_in\.title\s*\r?\n' +
    '\s{8}product\.category\s*=\s*product_in\.category\s*\r?\n' +
    '\s{8}product\.original_url\s*=\s*product_in\.original_url\s*\r?\n' +
    '\s{8}product\.affiliate_url\s*=\s*product_in\.affiliate_url\s*\r?\n' +
    '\s{8}product\.associate_tag\s*=\s*product_in\.associate_tag\s*\r?\n' +
    '\s{8}product\.price_text\s*=\s*product_in\.price_text\s*\r?\n' +
    '\s{8}product\.currency\s*=\s*normalized_currency\s*'
)

$newAssignmentBlock = @"
        validated_links = validate_amazon_product_links(
            marketplace=normalized_marketplace,
            asin=normalized_asin,
            original_url=product_in.original_url,
            affiliate_url=product_in.affiliate_url,
            associate_tag=product_in.associate_tag,
            currency=normalized_currency,
        )

        product.marketplace = normalized_marketplace
        product.asin = validated_links.asin
        product.title = product_in.title
        product.category = product_in.category
        product.original_url = validated_links.original_url
        product.affiliate_url = validated_links.affiliate_url
        product.associate_tag = validated_links.associate_tag
        product.price_text = product_in.price_text
        product.currency = validated_links.currency

        if hasattr(product, "product_url"):
            product.product_url = validated_links.original_url

        if hasattr(product, "is_short_affiliate_url"):
            product.is_short_affiliate_url = (
                validated_links.is_short_affiliate_url
            )
"@

if (
    $repositoryText -match
    'validated_links\s*=\s*validate_amazon_product_links'
) {
    Write-Host "Repository ja utiliza o validador central."
}
else {
    $repositoryRegex = New-Object `
        System.Text.RegularExpressions.Regex(
            $oldAssignmentBlockPattern
        )

    if (-not $repositoryRegex.IsMatch($repositoryText)) {
        throw (
            "Bloco de persistencia esperado nao foi localizado. " +
            "O arquivo original foi preservado no backup."
        )
    }

    $repositoryText = $repositoryRegex.Replace(
        $repositoryText,
        $newAssignmentBlock.TrimEnd(),
        1
    )

    Write-Host "Persistencia protegida pelo validador central."
}

[System.IO.File]::WriteAllText(
    $repositoryPath,
    $repositoryText,
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host ""
Write-Host "Validando sintaxe Python..."

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "exec",
        "-T",
        "api",
        "python",
        "-m",
        "py_compile",
        "/atlas/app/services/amazon_link_validation.py",
        "/atlas/app/repositories/affiliate.py",
        "/atlas/validate_step2_amazon.py"
    ) `
    -FailureMessage "Erro de sintaxe nos arquivos corrigidos." |
Out-Null

Write-Host "Sintaxe Python validada."
Write-Host ""
Write-Host "Reiniciando somente a API..."

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "restart",
        "api"
    ) `
    -FailureMessage "Nao foi possivel reiniciar a API." |
Out-Null

Write-Host ""
Write-Host "Aguardando a API responder..."

$apiOnline = $false

for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod `
            -Uri "http://localhost:8000/" `
            -Method Get `
            -TimeoutSec 5

        if ($health.status -eq "online") {
            $apiOnline = $true
            break
        }
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
        -FailureMessage "Nao foi possivel consultar os logs." |
    Out-Null

    throw "A API nao respondeu apos a correcao."
}

Write-Host "API online."
Write-Host ""
Write-Host "Executando novamente a validacao funcional completa..."
Write-Host ""

Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "exec",
        "-T",
        "api",
        "python",
        "/atlas/validate_step2_amazon.py"
    ) `
    -FailureMessage "A validacao funcional ainda encontrou erro." |
Out-Null

Write-Host ""
Write-Host "Confirmando que nao sobraram produtos temporarios..."

$cleanupQuery = @"
SELECT COUNT(*)
FROM affiliate_products
WHERE notes IN (
    'Teste temporario ATLAS',
    'Teste temporário ATLAS',
    'Importacao temporaria',
    'Importação temporária'
)
OR title LIKE 'Produto CSV temporario ATLAS%'
OR title LIKE 'Produto CSV temporário ATLAS%'
OR title LIKE 'Organizador temporario ATLAS%'
OR title LIKE 'Organizador temporário ATLAS%'
OR title IN (
    'Teste de URL invalida',
    'Teste de URL inválida',
    'Teste de tracking tag invalida',
    'Teste de tracking tag inválida'
);
"@

$cleanupCommand = (
    'psql -U "$POSTGRES_USER" ' +
    '-d "$POSTGRES_DB" ' +
    '-tAc "' +
    ($cleanupQuery -replace '"', '\"' -replace '\r?\n', ' ') +
    '"'
)

$cleanupOutput = Invoke-DockerChecked `
    -Arguments @(
        "compose",
        "exec",
        "-T",
        "postgres",
        "sh",
        "-lc",
        $cleanupCommand
    ) `
    -FailureMessage "Nao foi possivel verificar a limpeza final."

$cleanupText = (
    $cleanupOutput |
    Where-Object {
        $_ -match '^\s*\d+\s*$'
    } |
    Select-Object -Last 1
)

if ([string]::IsNullOrWhiteSpace($cleanupText)) {
    throw "Nao foi possivel interpretar a verificacao de limpeza."
}

$remainingTemporaryProducts = [int] $cleanupText.Trim()

if ($remainingTemporaryProducts -ne 0) {
    throw (
        "Ainda existem " +
        $remainingTemporaryProducts +
        " produtos temporarios no banco."
    )
}

Write-Host "Produtos temporarios restantes: 0"
Write-Host ""
Write-Host "======================================================="
Write-Host "CORRECAO E VALIDACAO CONCLUIDAS"
Write-Host "======================================================="
Write-Host "URL externa rejeitada: True"
Write-Host "Tracking tag incorreta rejeitada: True"
Write-Host "Produtos temporarios restantes: 0"
Write-Host "Video gerado: False"
Write-Host "Publicacao executada: False"
Write-Host "Worker autorizado: $(Test-Path Env:\ATLAS_WORKER_RUN_ENABLED)"
Write-Host ""