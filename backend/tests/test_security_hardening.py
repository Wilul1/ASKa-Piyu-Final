"""Targeted tests for remaining security hardening."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.config import admin_api_key_auth_enabled, is_placeholder_secret, openapi_enabled
from app.services.document_storage import documents_root, persist_uploaded_document, resolve_stored_path
from app.services.ticket_attachments import detect_content_type


def test_resolve_stored_path_rejects_escape(tmp_path, monkeypatch):
    root = tmp_path / "documents"
    root.mkdir()
    monkeypatch.setattr("app.services.document_storage.documents_root", lambda: root)

    safe = persist_uploaded_document(
        b"%PDF-1.4 safe",
        document_id="doc-safe",
        filename="handbook.pdf",
        content_type="application/pdf",
    )
    resolved = resolve_stored_path(safe.stored_file_path)
    assert resolved.is_file()
    assert resolved.is_relative_to(root.resolve())

    with pytest.raises(ValueError, match="escapes"):
        resolve_stored_path("../secrets.txt")

    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        resolve_stored_path(str(outside.resolve()))


def test_detect_content_type_magic_bytes():
    assert detect_content_type(b"%PDF-1.4") == "application/pdf"
    assert detect_content_type(b"\x89PNG\r\n\x1a\nxxxx") == "image/png"
    assert detect_content_type(b"\xff\xd8\xff\xe0xxxx") == "image/jpeg"
    assert detect_content_type(b"GIF89axxxx") == "image/gif"
    assert detect_content_type(b"RIFFxxxxWEBPxxxx") == "image/webp"
    assert detect_content_type(b"not-a-real-file") is None


def test_client_ip_ignores_forwarded_headers_unless_trust_proxy(monkeypatch):
    from unittest.mock import MagicMock

    from app.services.client_ip import client_ip

    request = MagicMock()
    request.client.host = "10.0.0.5"
    request.headers = {"x-forwarded-for": "203.0.113.9, 10.0.0.5"}

    monkeypatch.setattr("app.services.client_ip.settings.trust_proxy", False)
    assert client_ip(request) == "10.0.0.5"

    monkeypatch.setattr("app.services.client_ip.settings.trust_proxy", True)
    assert client_ip(request) == "203.0.113.9"


def test_placeholder_secret_detection():
    assert is_placeholder_secret(None) is True
    assert is_placeholder_secret("") is True
    assert is_placeholder_secret("change-this-admin-key") is True
    assert is_placeholder_secret("aska-piyu-dev-secret") is True
    assert is_placeholder_secret("xK9mP2vQ7nL4wR8sT1uY") is False


def test_admin_api_key_auth_defaults(monkeypatch):
    monkeypatch.setattr("app.config.settings.env", "development")
    monkeypatch.setattr("app.config.settings.allow_admin_api_key", None)
    assert admin_api_key_auth_enabled() is True

    monkeypatch.setattr("app.config.settings.env", "production")
    monkeypatch.setattr("app.config.settings.allow_admin_api_key", None)
    assert admin_api_key_auth_enabled() is False

    monkeypatch.setattr("app.config.settings.allow_admin_api_key", True)
    assert admin_api_key_auth_enabled() is True


def test_openapi_disabled_in_production(monkeypatch):
    monkeypatch.setattr("app.config.settings.env", "production")
    monkeypatch.setattr("app.config.settings.expose_openapi", None)
    assert openapi_enabled() is False

    monkeypatch.setattr("app.config.settings.env", "development")
    assert openapi_enabled() is True


def test_production_startup_rejects_missing_auth_secret(monkeypatch):
    import asyncio

    from app.main import validate_startup_configuration

    monkeypatch.setattr("app.main.settings.env", "production")
    monkeypatch.setattr("app.main.settings.auth_secret_key", None)
    monkeypatch.setattr("app.main.settings.admin_api_key", "strong-unique-admin-key-xyz")
    monkeypatch.setattr("app.main.settings.allow_admin_api_key", False)
    monkeypatch.setattr("app.main.settings.cors_origins", ["https://aska.example"])
    monkeypatch.setattr("app.main.settings.groq_model", "")
    monkeypatch.setattr("app.main.settings.database_url", "postgresql://u:p@localhost/aska")

    with pytest.raises(RuntimeError, match="ASKA_AUTH_SECRET_KEY is required"):
        asyncio.run(validate_startup_configuration())


def test_production_startup_rejects_cors_wildcard(monkeypatch):
    import asyncio

    from app.main import validate_startup_configuration

    monkeypatch.setattr("app.main.settings.env", "production")
    monkeypatch.setattr("app.main.settings.auth_secret_key", "strong-unique-auth-secret-xyz")
    monkeypatch.setattr("app.main.settings.admin_api_key", None)
    monkeypatch.setattr("app.main.settings.allow_admin_api_key", False)
    monkeypatch.setattr("app.main.settings.cors_origins", ["*"])
    monkeypatch.setattr("app.main.settings.groq_model", "")
    monkeypatch.setattr("app.main.settings.database_url", "postgresql://u:p@localhost/aska")
    monkeypatch.setattr("app.main.settings.database_init_on_startup", False)

    with pytest.raises(RuntimeError, match="CORS"):
        asyncio.run(validate_startup_configuration())


def test_production_startup_requires_database_url(monkeypatch):
    import asyncio

    from app.main import validate_startup_configuration

    monkeypatch.setattr("app.main.settings.env", "production")
    monkeypatch.setattr("app.main.settings.auth_secret_key", "strong-unique-auth-secret-xyz")
    monkeypatch.setattr("app.main.settings.admin_api_key", None)
    monkeypatch.setattr("app.main.settings.allow_admin_api_key", False)
    monkeypatch.setattr("app.main.settings.cors_origins", ["https://aska.example"])
    monkeypatch.setattr("app.main.settings.groq_model", "")
    monkeypatch.setattr("app.main.settings.database_url", None)
    monkeypatch.setattr("app.main.settings.database_init_on_startup", False)

    with pytest.raises(RuntimeError, match="ASKA_DATABASE_URL"):
        asyncio.run(validate_startup_configuration())


def test_production_startup_rejects_init_on_startup(monkeypatch):
    import asyncio

    from app.main import validate_startup_configuration

    monkeypatch.setattr("app.main.settings.env", "production")
    monkeypatch.setattr("app.main.settings.auth_secret_key", "strong-unique-auth-secret-xyz")
    monkeypatch.setattr("app.main.settings.admin_api_key", None)
    monkeypatch.setattr("app.main.settings.allow_admin_api_key", False)
    monkeypatch.setattr("app.main.settings.cors_origins", ["https://aska.example"])
    monkeypatch.setattr("app.main.settings.groq_model", "")
    monkeypatch.setattr("app.main.settings.database_url", "postgresql://u:p@localhost/aska")
    monkeypatch.setattr("app.main.settings.database_init_on_startup", True)

    with pytest.raises(RuntimeError, match="ASKA_DATABASE_INIT_ON_STARTUP"):
        asyncio.run(validate_startup_configuration())


def test_production_startup_rejects_localhost_only_cors(monkeypatch):
    import asyncio

    from app.main import validate_startup_configuration

    monkeypatch.setattr("app.main.settings.env", "production")
    monkeypatch.setattr("app.main.settings.auth_secret_key", "strong-unique-auth-secret-xyz")
    monkeypatch.setattr("app.main.settings.admin_api_key", None)
    monkeypatch.setattr("app.main.settings.allow_admin_api_key", False)
    monkeypatch.setattr(
        "app.main.settings.cors_origins",
        ["http://localhost:8080", "http://127.0.0.1:8080"],
    )
    monkeypatch.setattr("app.main.settings.groq_model", "")
    monkeypatch.setattr("app.main.settings.database_url", "postgresql://u:p@localhost/aska")
    monkeypatch.setattr("app.main.settings.database_init_on_startup", False)

    with pytest.raises(RuntimeError, match="localhost"):
        asyncio.run(validate_startup_configuration())


def test_dev_cors_allows_flutter_web_ephemeral_port():
    """Flutter web uses a random localhost port; browsers need ACAO for that origin."""
    from fastapi.testclient import TestClient

    from app.main import _cors_local_origin_regex, app

    assert _cors_local_origin_regex is not None
    client = TestClient(app)
    response = client.get(
        "/kb/categories",
        headers={"Origin": "http://localhost:53247"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == (
        "http://localhost:53247"
    )


def test_require_admin_key_rejects_shared_key_when_disabled(monkeypatch):
    from app.routes.admin.knowledge_base import require_admin_key

    monkeypatch.setattr("app.config.settings.env", "production")
    monkeypatch.setattr("app.config.settings.allow_admin_api_key", False)
    monkeypatch.setattr("app.config.settings.admin_api_key", "strong-unique-admin-key-xyz")
    monkeypatch.setattr(
        "app.routes.admin.knowledge_base.settings.admin_api_key",
        "strong-unique-admin-key-xyz",
    )

    with pytest.raises(HTTPException) as exc:
        require_admin_key(
            x_admin_key="strong-unique-admin-key-xyz",
            authorization=None,
        )
    assert exc.value.status_code == 401
    assert "disabled" in str(exc.value.detail).lower()


def test_admin_kb_bearer_rejects_disabled_account(monkeypatch):
    from app.models.db_models import User
    from app.routes.admin.knowledge_base import _require_admin_bearer_token
    from app.services.auth import create_access_token

    user = User(
        id="admin-disabled",
        email="disabled@test.local",
        password_hash="x",
        full_name="Disabled Admin",
        role="admin",
        is_active=False,
        credentials_version=0,
    )
    token = create_access_token(user)

    class _Session:
        def get(self, _model, _id):
            return user

        def close(self):
            return None

    monkeypatch.setattr(
        "app.routes.admin.knowledge_base.get_session_factory",
        lambda: (lambda: _Session()),
    )

    with pytest.raises(HTTPException) as exc:
        _require_admin_bearer_token(token)
    assert exc.value.status_code == 401
    assert "disabled" in str(exc.value.detail).lower()


def test_admin_kb_bearer_rejects_revoked_credentials(monkeypatch):
    from app.models.db_models import User
    from app.routes.admin.knowledge_base import _require_admin_bearer_token
    from app.services.auth import create_access_token

    user = User(
        id="admin-revoked",
        email="revoked@test.local",
        password_hash="x",
        full_name="Revoked Admin",
        role="admin",
        is_active=True,
        credentials_version=0,
    )
    token = create_access_token(user)
    # Password reset / disable bumps credentials_version after the token was issued.
    user.credentials_version = 1

    class _Session:
        def get(self, _model, _id):
            return user

        def close(self):
            return None

    monkeypatch.setattr(
        "app.routes.admin.knowledge_base.get_session_factory",
        lambda: (lambda: _Session()),
    )

    with pytest.raises(HTTPException) as exc:
        _require_admin_bearer_token(token)
    assert exc.value.status_code == 401
    assert "revoked" in str(exc.value.detail).lower()
