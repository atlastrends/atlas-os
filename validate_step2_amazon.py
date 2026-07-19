import csv
import io
import json
import os
import random
import string
import sys
import traceback
from typing import Any
from urllib.parse import urlencode

import requests
from sqlalchemy import inspect, text

from app.core.database import SessionLocal, engine
from app.models.affiliate import AffiliateProduct


BASE_URL = "http://localhost:8000"
TIMEOUT = 30

BR_TAG = os.getenv(
    "AMAZON_BR_ASSOCIATE_TAG",
    os.getenv("AMAZON_BR_TAG", "achadosatlasb-20"),
).strip()

US_TAG = os.getenv(
    "AMAZON_US_ASSOCIATE_TAG",
    os.getenv("AMAZON_US_TAG", "atlasfindsus-20"),
).strip()

created_asins = set()
failures = []
successes = []


def record_success(message: str) -> None:
    successes.append(message)
    print(f"[OK] {message}", flush=True)


def record_failure(message: str) -> None:
    failures.append(message)
    print(f"[ERRO] {message}", flush=True)


def show_response(response: requests.Response) -> str:
    try:
        content = response.json()
        return json.dumps(
            content,
            ensure_ascii=False,
            indent=2,
        )[:4000]
    except Exception:
        return response.text[:4000]


def request_json(
    method: str,
    path: str,
    *,
    expected_statuses: set[int],
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> requests.Response:
    response = requests.request(
        method=method,
        url=f"{BASE_URL}{path}",
        json=payload,
        params=params,
        timeout=TIMEOUT,
    )

    if response.status_code not in expected_statuses:
        raise AssertionError(
            f"{method} {path} retornou HTTP "
            f"{response.status_code}.\n"
            f"{show_response(response)}"
        )

    return response


def random_asin() -> str:
    alphabet = string.ascii_uppercase + string.digits

    return "B0" + "".join(
        random.choice(alphabet)
        for _ in range(8)
    )


def resolve_schema(
    openapi: dict[str, Any],
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    if not schema:
        return {}

    if "$ref" in schema:
        reference = schema["$ref"]
        prefix = "#/components/schemas/"

        if reference.startswith(prefix):
            schema_name = reference[len(prefix):]

            return resolve_schema(
                openapi,
                openapi.get("components", {})
                .get("schemas", {})
                .get(schema_name, {}),
            )

    if "allOf" in schema:
        merged: dict[str, Any] = {
            "properties": {},
            "required": [],
        }

        for item in schema["allOf"]:
            resolved = resolve_schema(openapi, item)

            merged["properties"].update(
                resolved.get("properties", {})
            )

            for required_name in resolved.get("required", []):
                if required_name not in merged["required"]:
                    merged["required"].append(required_name)

        for key, value in schema.items():
            if key != "allOf":
                merged[key] = value

        return merged

    return schema


def find_operation(
    openapi: dict[str, Any],
    *,
    method: str,
    required_fragments: list[str],
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    method = method.lower()

    for path, path_data in openapi.get("paths", {}).items():
        operation = path_data.get(method)

        if not operation:
            continue

        search_text = " ".join(
            [
                path,
                str(operation.get("operationId", "")),
                str(operation.get("summary", "")),
                " ".join(operation.get("tags", [])),
            ]
        ).lower()

        if all(
            fragment.lower() in search_text
            for fragment in required_fragments
        ):
            return path, operation

    return None, None


def find_manual_operation(
    openapi: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    candidates = [
        ["import-manual"],
        ["manual", "product"],
        ["manual", "amazon"],
    ]

    for fragments in candidates:
        path, operation = find_operation(
            openapi,
            method="post",
            required_fragments=fragments,
        )

        if path:
            return path, operation

    raise AssertionError(
        "Endpoint POST de importação manual não encontrado."
    )


def find_csv_operation(
    openapi: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    candidates = [
        ["csv", "product"],
        ["import-csv"],
        ["csv"],
    ]

    for fragments in candidates:
        path, operation = find_operation(
            openapi,
            method="post",
            required_fragments=fragments,
        )

        if path:
            return path, operation

    raise AssertionError(
        "Endpoint POST de importação CSV não encontrado."
    )


def find_list_operation(
    openapi: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    preferred_paths = [
        "/affiliate/catalog/products",
        "/affiliate/manage/products",
        "/affiliate/products",
    ]

    for path in preferred_paths:
        operation = (
            openapi.get("paths", {})
            .get(path, {})
            .get("get")
        )

        if operation:
            return path, operation

    for path, path_data in openapi.get("paths", {}).items():
        if "{" in path:
            continue

        operation = path_data.get("get")

        if (
            operation
            and "affiliate" in path.lower()
            and "product" in path.lower()
        ):
            return path, operation

    raise AssertionError(
        "Endpoint GET de listagem de produtos não encontrado."
    )


def generic_value(
    field_name: str,
    field_schema: dict[str, Any],
) -> Any:
    resolved = field_schema

    if "$ref" in resolved:
        return None

    enum_values = resolved.get("enum")

    if enum_values:
        return enum_values[0]

    field_type = resolved.get("type", "string")
    name = field_name.lower()

    known_values: dict[str, Any] = {
        "marketplace": "amazon_br",
        "asin": random_asin(),
        "title": "Produto temporário de validação ATLAS",
        "category": "Teste controlado",
        "original_url": "https://www.amazon.com.br/dp/B000000000",
        "affiliate_url": (
            "https://www.amazon.com.br/dp/B000000000"
            f"?tag={BR_TAG}"
        ),
        "associate_tag": BR_TAG,
        "tracking_id": BR_TAG,
        "tag": BR_TAG,
        "currency": "BRL",
        "price_text": None,
        "source": "manual",
        "source_type": "manual",
        "status": "active",
        "notes": "Registro temporário de validação",
    }

    if name in known_values:
        return known_values[name]

    if field_type == "boolean":
        return False

    if field_type == "integer":
        return 1

    if field_type == "number":
        return 1.0

    if field_type == "array":
        return []

    if field_type == "object":
        return {}

    return "validation"


def complete_required_fields(
    openapi: dict[str, Any],
    operation: dict[str, Any],
    payload: dict[str, Any],
    content_type: str = "application/json",
) -> dict[str, Any]:
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    media_schema = content.get(content_type, {}).get("schema", {})

    schema = resolve_schema(openapi, media_schema)
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])

    result = dict(payload)

    for field_name in required_fields:
        if field_name in result:
            continue

        field_schema = resolve_schema(
            openapi,
            properties.get(field_name, {}),
        )

        result[field_name] = generic_value(
            field_name,
            field_schema,
        )

    return result


def extract_product(response: requests.Response) -> dict[str, Any]:
    data = response.json()

    if isinstance(data, dict):
        product = data.get("product")

        if isinstance(product, dict):
            return product

        data_section = data.get("data")

        if isinstance(data_section, dict):
            nested_product = data_section.get("product")

            if isinstance(nested_product, dict):
                return nested_product

        if "asin" in data:
            return data

    raise AssertionError(
        "A resposta não contém um produto reconhecível:\n"
        f"{show_response(response)}"
    )


def test_health() -> None:
    response = request_json(
        "GET",
        "/",
        expected_statuses={200},
    )

    data = response.json()

    if data.get("status") != "online":
        raise AssertionError(
            "O health check não informou status online."
        )

    if data.get("atlas_engine_enabled") is not False:
        raise AssertionError(
            "ATLAS_ENGINE_ENABLED não está false."
        )

    record_success(
        "API online e motor automático desativado."
    )


def test_database_structure() -> None:
    inspector = inspect(engine)

    table_names = set(inspector.get_table_names())

    required_tables = {
        "affiliate_products",
        "affiliate_contents",
    }

    missing_tables = required_tables - table_names

    if missing_tables:
        raise AssertionError(
            "Tabelas ausentes: "
            + ", ".join(sorted(missing_tables))
        )

    columns = {
        item["name"]: item
        for item in inspector.get_columns(
            "affiliate_products"
        )
    }

    minimum_columns = {
        "id",
        "marketplace",
        "asin",
        "title",
        "original_url",
        "affiliate_url",
        "associate_tag",
        "currency",
        "created_at",
    }

    missing_columns = minimum_columns - set(columns)

    if missing_columns:
        raise AssertionError(
            "Colunas obrigatórias ausentes: "
            + ", ".join(sorted(missing_columns))
        )

    print("")
    print("Colunas de affiliate_products:")

    for column_name, column_data in columns.items():
        print(
            f"  - {column_name}: "
            f"{column_data['type']} "
            f"nullable={column_data['nullable']}"
        )

    unique_constraints = inspector.get_unique_constraints(
        "affiliate_products"
    )

    has_identity_constraint = any(
        set(item.get("column_names") or [])
        == {"marketplace", "asin"}
        for item in unique_constraints
    )

    if not has_identity_constraint:
        raise AssertionError(
            "Constraint única marketplace + asin não encontrada."
        )

    check_constraints = inspector.get_check_constraints(
        "affiliate_products"
    )

    has_asin_check = any(
        "asin" in str(item.get("sqltext", "")).lower()
        for item in check_constraints
    )

    if not has_asin_check:
        raise AssertionError(
            "Constraint de normalização do ASIN não encontrada."
        )

    record_success(
        "Tabelas, colunas e constraints essenciais confirmadas."
    )


def test_alembic_revision() -> None:
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()

    if revision != "e4b82d7c91aa":
        raise AssertionError(
            f"Revisão inesperada: {revision}"
        )

    record_success(
        "Banco confirmado na revisão e4b82d7c91aa."
    )


def test_openapi() -> dict[str, Any]:
    response = request_json(
        "GET",
        "/openapi.json",
        expected_statuses={200},
    )

    openapi = response.json()

    affiliate_routes = []

    for path, path_data in openapi.get("paths", {}).items():
        if "affiliate" not in path.lower():
            continue

        for method in path_data:
            if method.lower() in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
            }:
                affiliate_routes.append(
                    f"{method.upper()} {path}"
                )

    print("")
    print("Rotas Affiliate carregadas:")

    for route in sorted(affiliate_routes):
        print(f"  - {route}")

    find_manual_operation(openapi)
    find_csv_operation(openapi)
    find_list_operation(openapi)

    record_success(
        "Rotas manual, CSV e listagem localizadas no OpenAPI."
    )

    return openapi


def build_manual_payload(
    asin: str,
    title: str,
) -> dict[str, Any]:
    return {
        "marketplace": "amazon_br",
        "asin": asin,
        "title": title,
        "category": "Organização",
        "original_url": (
            f"https://www.amazon.com.br/dp/{asin}"
        ),
        "affiliate_url": (
            f"https://www.amazon.com.br/dp/{asin}"
            f"?tag={BR_TAG}"
        ),
        "associate_tag": BR_TAG,
        "price_text": None,
        "currency": "BRL",
        "source": "manual",
        "notes": "Teste temporário ATLAS",
    }


def test_manual_import(
    openapi: dict[str, Any],
) -> tuple[str, str]:
    manual_path, operation = find_manual_operation(openapi)

    asin = random_asin()
    created_asins.add(asin)

    payload = build_manual_payload(
        asin=asin,
        title="Organizador temporário ATLAS",
    )

    payload = complete_required_fields(
        openapi,
        operation,
        payload,
    )

    response = request_json(
        "POST",
        manual_path,
        expected_statuses={200, 201},
        payload=payload,
    )

    product = extract_product(response)

    if str(product.get("asin", "")).upper() != asin:
        raise AssertionError(
            "O ASIN retornado não corresponde ao enviado."
        )

    record_success(
        f"Cadastro manual criado pelo endpoint {manual_path}."
    )

    updated_payload = dict(payload)
    updated_payload["title"] = (
        "Organizador temporário ATLAS atualizado"
    )

    update_response = request_json(
        "POST",
        manual_path,
        expected_statuses={200, 201},
        payload=updated_payload,
    )

    updated_product = extract_product(update_response)

    if (
        updated_product.get("title")
        != updated_payload["title"]
    ):
        raise AssertionError(
            "O upsert não atualizou o título."
        )

    record_success(
        "Upsert por marketplace + ASIN confirmado."
    )

    return asin, manual_path


def test_invalid_url_and_tag(
    openapi: dict[str, Any],
    manual_path: str,
) -> None:
    _, operation = find_manual_operation(openapi)

    invalid_url_asin = random_asin()
    invalid_url_payload = build_manual_payload(
        asin=invalid_url_asin,
        title="Teste de URL inválida",
    )

    invalid_url_payload["affiliate_url"] = (
        f"https://example.com/dp/{invalid_url_asin}"
        f"?tag={BR_TAG}"
    )

    invalid_url_payload = complete_required_fields(
        openapi,
        operation,
        invalid_url_payload,
    )

    response = requests.post(
        f"{BASE_URL}{manual_path}",
        json=invalid_url_payload,
        timeout=TIMEOUT,
    )

    if response.status_code not in {400, 422}:
        created_asins.add(invalid_url_asin)

        raise AssertionError(
            "URL externa não foi rejeitada. "
            f"HTTP {response.status_code}\n"
            f"{show_response(response)}"
        )

    record_success(
        "URL fora dos domínios Amazon foi rejeitada."
    )

    invalid_tag_asin = random_asin()
    invalid_tag_payload = build_manual_payload(
        asin=invalid_tag_asin,
        title="Teste de tracking tag inválida",
    )

    invalid_tag_payload["associate_tag"] = "tag-invalida-20"
    invalid_tag_payload["affiliate_url"] = (
        f"https://www.amazon.com.br/dp/{invalid_tag_asin}"
        "?tag=tag-invalida-20"
    )

    invalid_tag_payload = complete_required_fields(
        openapi,
        operation,
        invalid_tag_payload,
    )

    response = requests.post(
        f"{BASE_URL}{manual_path}",
        json=invalid_tag_payload,
        timeout=TIMEOUT,
    )

    if response.status_code not in {400, 422}:
        created_asins.add(invalid_tag_asin)

        raise AssertionError(
            "Tracking tag inválida não foi rejeitada. "
            f"HTTP {response.status_code}\n"
            f"{show_response(response)}"
        )

    record_success(
        "Tracking tag incorreta foi rejeitada."
    )


def build_csv_content(asins: list[str]) -> str:
    output = io.StringIO(newline="")

    fieldnames = [
        "marketplace",
        "asin",
        "title",
        "category",
        "original_url",
        "affiliate_url",
        "associate_tag",
        "price_text",
        "currency",
        "source",
        "notes",
    ]

    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
    )

    writer.writeheader()

    for index, asin in enumerate(asins, start=1):
        writer.writerow(
            {
                "marketplace": "amazon_br",
                "asin": asin,
                "title": (
                    f"Produto CSV temporário ATLAS {index}"
                ),
                "category": "Teste CSV",
                "original_url": (
                    f"https://www.amazon.com.br/dp/{asin}"
                ),
                "affiliate_url": (
                    f"https://www.amazon.com.br/dp/{asin}"
                    f"?tag={BR_TAG}"
                ),
                "associate_tag": BR_TAG,
                "price_text": "",
                "currency": "BRL",
                "source": "csv",
                "notes": "Importação temporária",
            }
        )

    return output.getvalue()


def test_csv_import(
    openapi: dict[str, Any],
) -> list[str]:
    csv_path, operation = find_csv_operation(openapi)

    csv_asins = [
        random_asin(),
        random_asin(),
    ]

    created_asins.update(csv_asins)

    csv_content = build_csv_content(csv_asins)

    request_content = (
        operation.get("requestBody", {})
        .get("content", {})
    )

    if "multipart/form-data" in request_content:
        multipart_schema = resolve_schema(
            openapi,
            request_content["multipart/form-data"]
            .get("schema", {}),
        )

        properties = multipart_schema.get(
            "properties",
            {},
        )

        file_field = None

        for field_name, field_schema in properties.items():
            resolved = resolve_schema(
                openapi,
                field_schema,
            )

            if (
                resolved.get("format") == "binary"
                or field_name.lower() in {
                    "file",
                    "csv_file",
                    "upload",
                }
            ):
                file_field = field_name
                break

        if not file_field:
            file_field = "file"

        files = {
            file_field: (
                "atlas_validation.csv",
                csv_content.encode("utf-8"),
                "text/csv",
            )
        }

        form_data = {}

        for required_name in multipart_schema.get(
            "required",
            [],
        ):
            if required_name == file_field:
                continue

            field_schema = resolve_schema(
                openapi,
                properties.get(required_name, {}),
            )

            value = generic_value(
                required_name,
                field_schema,
            )

            if value is not None:
                form_data[required_name] = str(value)

        response = requests.post(
            f"{BASE_URL}{csv_path}",
            files=files,
            data=form_data,
            timeout=TIMEOUT,
        )

    elif "application/json" in request_content:
        payload = {
            "csv_content": csv_content,
            "content": csv_content,
            "csv_text": csv_content,
            "filename": "atlas_validation.csv",
        }

        payload = complete_required_fields(
            openapi,
            operation,
            payload,
            content_type="application/json",
        )

        response = requests.post(
            f"{BASE_URL}{csv_path}",
            json=payload,
            timeout=TIMEOUT,
        )

    else:
        raise AssertionError(
            "Formato de upload CSV não reconhecido: "
            + ", ".join(request_content.keys())
        )

    if response.status_code not in {200, 201, 207}:
        raise AssertionError(
            f"Importação CSV falhou com HTTP "
            f"{response.status_code}.\n"
            f"{show_response(response)}"
        )

    response_text = show_response(response)

    print("")
    print("Resposta da importação CSV:")
    print(response_text)

    record_success(
        f"Importação CSV aceita pelo endpoint {csv_path}."
    )

    return csv_asins


def test_listing(
    openapi: dict[str, Any],
    expected_asins: set[str],
) -> None:
    list_path, operation = find_list_operation(openapi)

    available_parameters = {
        parameter.get("name")
        for parameter in operation.get("parameters", [])
    }

    params: dict[str, Any] = {}

    if "marketplace" in available_parameters:
        params["marketplace"] = "amazon_br"

    if "limit" in available_parameters:
        params["limit"] = 200

    if "offset" in available_parameters:
        params["offset"] = 0

    if "skip" in available_parameters:
        params["skip"] = 0

    response = request_json(
        "GET",
        list_path,
        expected_statuses={200},
        params=params,
    )

    data = response.json()

    if isinstance(data, list):
        products = data
    elif isinstance(data, dict):
        products = (
            data.get("products")
            or data.get("items")
            or data.get("data")
            or []
        )

        if isinstance(products, dict):
            products = (
                products.get("products")
                or products.get("items")
                or []
            )
    else:
        products = []

    returned_asins = {
        str(product.get("asin", "")).upper()
        for product in products
        if isinstance(product, dict)
    }

    missing = expected_asins - returned_asins

    if missing:
        raise AssertionError(
            "Produtos temporários ausentes na listagem: "
            + ", ".join(sorted(missing))
        )

    record_success(
        f"Listagem e filtros confirmados em {list_path}."
    )


def cleanup() -> None:
    if not created_asins:
        return

    db = SessionLocal()

    try:
        products = (
            db.query(AffiliateProduct)
            .filter(AffiliateProduct.asin.in_(created_asins))
            .all()
        )

        removed = len(products)

        for product in products:
            db.delete(product)

        db.commit()

        remaining = (
            db.query(AffiliateProduct)
            .filter(AffiliateProduct.asin.in_(created_asins))
            .count()
        )

        if remaining:
            record_failure(
                f"A limpeza deixou {remaining} produto(s) temporário(s)."
            )
        else:
            record_success(
                f"Limpeza removeu {removed} produto(s) temporário(s)."
            )

    except Exception as error:
        db.rollback()

        record_failure(
            f"Falha ao limpar produtos temporários: {error}"
        )

    finally:
        db.close()


def main() -> int:
    print("")
    print("=" * 60)
    print("VALIDAÇÃO FUNCIONAL DO NÚCLEO AMAZON")
    print("=" * 60)
    print(f"BR tag configurada: {BR_TAG}")
    print(f"US tag configurada: {US_TAG}")
    print("")

    try:
        test_health()
        test_alembic_revision()
        test_database_structure()

        openapi = test_openapi()

        manual_asin, manual_path = test_manual_import(
            openapi
        )

        test_invalid_url_and_tag(
            openapi,
            manual_path,
        )

        csv_asins = test_csv_import(openapi)

        expected_asins = {
            manual_asin,
            *csv_asins,
        }

        test_listing(
            openapi,
            expected_asins,
        )

    except Exception as error:
        record_failure(str(error))
        print("")
        traceback.print_exc()

    finally:
        cleanup()

    print("")
    print("=" * 60)
    print("RESULTADO DA VALIDAÇÃO")
    print("=" * 60)
    print(f"Sucessos: {len(successes)}")
    print(f"Falhas: {len(failures)}")
    print("Worker autorizado: False")
    print("Vídeo gerado: False")
    print("Publicação executada: False")

    if failures:
        print("")
        print("Falhas encontradas:")

        for failure in failures:
            print(f"  - {failure}")

        return 1

    print("")
    print("PASSO 3 CONCLUÍDO COM SUCESSO")
    return 0


if __name__ == "__main__":
    sys.exit(main())