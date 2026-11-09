"""Cross-cutting API contract regression tests."""

from collections import Counter
import re

import pytest
from fastapi.testclient import TestClient

from app.api.v1.dependencies import get_pagination_params
from app.core.config import settings
from app.main import create_application


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
PUBLIC_API_OPERATIONS = {
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/refresh"),
    ("post", "/api/v1/auth/forgot-password"),
    ("post", "/api/v1/auth/reset-password"),
    ("post", "/api/v1/stock/low-stock-alert/cron"),
    ("get", "/api/v1/stock/low-stock-alert/cron"),
    ("post", "/api/v1/generated-documents/monthly/cron"),
    ("get", "/api/v1/generated-documents/monthly/cron"),
    ("delete", "/api/v1/generated-documents/expired/cron"),
    ("get", "/api/v1/generated-documents/expired/cron"),
    ("get", "/api/v1/branding"),
}


def api_operations(schema):
    for path, path_item in schema["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS:
                yield method.lower(), path, operation


def test_openapi_schema_generates_with_unique_operation_ids():
    schema = create_application().openapi()
    operations = list(api_operations(schema))
    operation_ids = [operation["operationId"] for _, _, operation in operations]

    assert operations
    assert len(operation_ids) == len(set(operation_ids)), {
        operation_id: count
        for operation_id, count in Counter(operation_ids).items()
        if count > 1
    }


def test_api_operations_declare_success_and_validation_responses():
    schema = create_application().openapi()

    for method, path, operation in api_operations(schema):
        responses = operation.get("responses", {})
        assert any(response.startswith("2") for response in responses), (method, path)
        if operation.get("requestBody") or operation.get("parameters"):
            assert "422" in responses, (method, path)


def test_all_non_cron_api_operations_declare_bearer_authentication():
    schema = create_application().openapi()

    for method, path, operation in api_operations(schema):
        key = (method, path)
        if key in PUBLIC_API_OPERATIONS:
            continue
        assert operation.get("security") == [{"HTTPBearer": []}], key


def test_protected_bodyless_operations_reject_missing_credentials(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    app = create_application()
    schema = app.openapi()

    client = TestClient(app, raise_server_exceptions=False)
    for method, path, operation in api_operations(schema):
        key = (method, path)
        if key in PUBLIC_API_OPERATIONS or operation.get("requestBody"):
            continue
        concrete_path = re.sub(r"\{[^}]+\}", "missing-id", path)
        response = client.request(method.upper(), concrete_path)
        assert response.status_code == 401, (method, path, response.status_code)
        payload = response.json()
        assert payload["error"]["code"] == "AUTHENTICATION_ERROR", key


@pytest.mark.parametrize(
    ("page", "page_size", "sort_by", "sort_order", "expected"),
    [
        (1, 20, "name", "asc", (1, 20, "name", "asc", 0)),
        (0, 0, "", "invalid", (1, 1, "name", "asc", 0)),
        (-5, -10, None, "desc", (1, 1, "name", "desc", 0)),
        (3, 500, "created_at", "desc", (3, 100, "created_at", "desc", 200)),
    ],
)
def test_shared_pagination_bounds(
    page,
    page_size,
    sort_by,
    sort_order,
    expected,
):
    params = get_pagination_params(page, page_size, sort_by, sort_order)

    assert (
        params["page"],
        params["page_size"],
        params["sort_by"],
        params["sort_order"],
        params["offset"],
    ) == expected
