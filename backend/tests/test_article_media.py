from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db_session, initialize_database
from app.main import app
from app.models.db_models import Office, PublishedArticle, User
from app.services.article_html import html_to_plain, sanitize_article_html
from app.services.auth import create_access_token
from app.services.passwords import hash_password

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
    b"\xe2!\xbc3"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"


@pytest.fixture()
def article_media_client(monkeypatch, tmp_path) -> Generator[tuple[TestClient, sessionmaker], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )

    def override_get_db_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    media_dir = tmp_path / "kb-media"
    media_dir.mkdir()
    monkeypatch.setattr("app.services.auth.settings.auth_secret_key", "test-auth-secret")
    monkeypatch.setattr("app.routes.auth.settings.signup_invite_code", None)
    monkeypatch.setattr("app.routes.auth.settings.signup_allowed_email_domains", None)
    monkeypatch.setattr("app.routes.admin.knowledge_base.settings.admin_api_key", None)
    monkeypatch.setattr("app.routes.admin.knowledge_base.get_session_factory", lambda: session_factory)
    monkeypatch.setattr("app.services.kb_media.settings.kb_media_dir", str(media_dir))
    monkeypatch.setattr("app.services.article_rag_indexer.index_published_article", lambda session, art: None)
    app.dependency_overrides[get_db_session] = override_get_db_session

    session = session_factory()
    ict = Office(name="ICT Office")
    registrar = Office(name="Registrar")
    session.add_all([ict, registrar])
    session.flush()
    admin = User(
        email="admin@media.edu",
        password_hash=hash_password("correct horse battery staple1"),
        full_name="Admin",
        role="admin",
        email_verified=True,
    )
    ict_user = User(
        email="ict@media.edu",
        password_hash=hash_password("correct horse battery staple1"),
        full_name="ICT Staff",
        role="office",
        office_id=ict.id,
        email_verified=True,
    )
    registrar_user = User(
        email="reg@media.edu",
        password_hash=hash_password("correct horse battery staple1"),
        full_name="Registrar Staff",
        role="office",
        office_id=registrar.id,
        email_verified=True,
    )
    student = User(
        email="student@media.edu",
        password_hash=hash_password("correct horse battery staple1"),
        full_name="Student",
        role="student",
        email_verified=True,
    )
    session.add_all([admin, ict_user, registrar_user, student])
    session.commit()
    session.close()

    try:
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.clear()


def _headers(session_factory, email: str) -> dict[str, str]:
    session = session_factory()
    try:
        user = session.query(User).filter(User.email == email).one()
        token = create_access_token(user)
    finally:
        session.close()
    return {"Authorization": f"Bearer {token}"}


def test_sanitize_strips_script_and_javascript_href():
    cleaned = sanitize_article_html(
        '<p>Hello<script>alert(1)</script></p><a href="javascript:alert(1)">x</a>'
        '<a href="//evil.example/phish">bad</a>'
        '<a href="https://lspu.edu.ph">LSPU</a>'
    )
    assert "script" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()
    assert "alert(1)" not in cleaned
    assert "evil.example" not in cleaned
    assert 'href="https://lspu.edu.ph"' in cleaned
    assert "Hello" in cleaned


def test_sanitize_allows_only_kb_media_images():
    cleaned = sanitize_article_html(
        '<p><img src="/kb/media/abc.png" alt="ok">'
        '<img src="https://evil.example/x.png">'
        '<img src="data:image/png;base64,aaaa"></p>'
    )
    assert "/kb/media/abc.png" in cleaned
    assert "evil.example" not in cleaned
    assert "data:image" not in cleaned


def test_html_to_plain_strips_tags():
    assert html_to_plain("<h2>Hours</h2><p>Open <strong>8am</strong></p>") == "Hours\nOpen 8am"


def test_create_draft_with_rich_html(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    response = client.post(
        "/admin/kb/articles",
        headers=headers,
        json={
            "title": "Library hours",
            "category": "Library Services",
            "content": "<h2>Hours</h2><p>The library is <strong>open</strong>.</p>",
            "content_format": "html",
            "publish_status": False,
            "force_create": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content_format"] == "html"
    assert "<strong>open</strong>" in body["content"]
    assert "<script>" not in body["content"]
    session = session_factory()
    try:
        art = session.get(PublishedArticle, body["id"])
        assert art is not None
        assert art.published is False
        assert art.content_format == "html"
    finally:
        session.close()


def test_publish_rich_article_and_public_render(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    created = client.post(
        "/admin/kb/articles",
        headers=headers,
        json={
            "title": "ID validation",
            "category": "Student Services",
            "content": "<blockquote>Bring a valid ID.</blockquote><p><em>OSA window</em></p>",
            "content_format": "html",
            "publish_status": True,
            "force_create": True,
        },
    )
    assert created.status_code == 200, created.text
    article_id = created.json()["id"]
    public = client.get(f"/kb/articles/{article_id}")
    assert public.status_code == 200
    detail = public.json()
    assert detail["content_format"] == "html"
    assert "<blockquote>" in detail["content"]
    assert "<em>OSA window</em>" in detail["content"]
    assert "Bring a valid ID" in detail["text"]


def test_plain_article_roundtrip_unchanged(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    created = client.post(
        "/admin/kb/articles",
        headers=headers,
        json={
            "title": "AWOL policy",
            "category": "Academic Policies",
            "content": "Overview\nStudents who are AWOL must report to OSA.",
            "publish_status": False,
            "force_create": True,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["content_format"] == "plain"
    assert body["content"].startswith("Overview")
    patched = client.patch(
        f"/admin/kb/articles/{body['id']}",
        headers=headers,
        json={"content": "Overview\nStudents who are AWOL must report to OSA."},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["content_format"] == "plain"


def test_inline_image_upload_persists_and_reloads(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    uploaded = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("campus.png", PNG_BYTES, "image/png")},
        data={"kind": "inline_image"},
    )
    assert uploaded.status_code == 200, uploaded.text
    media = uploaded.json()
    html = f'<p>See map</p><p><img src="{media["url"]}" alt="campus"></p>'
    created = client.post(
        "/admin/kb/articles",
        headers=headers,
        json={
            "title": "Campus map",
            "category": "Student Services",
            "content": html,
            "content_format": "html",
            "media_ids": [media["id"]],
            "publish_status": True,
            "force_create": True,
        },
    )
    assert created.status_code == 200, created.text
    article_id = created.json()["id"]
    fetched = client.get(f"/admin/kb/articles/{article_id}", headers=headers)
    assert media["url"] in fetched.json()["content"]
    public_img = client.get(media["url"])
    assert public_img.status_code == 200
    assert public_img.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_invalid_mime_and_oversized_image_rejected(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    exe = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("payload.exe", b"MZ" + b"\x00" * 32, "application/octet-stream")},
        data={"kind": "inline_image"},
    )
    assert exe.status_code == 400
    huge = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("huge.png", PNG_BYTES + b"0" * (5 * 1024 * 1024), "image/png")},
        data={"kind": "inline_image"},
    )
    assert huge.status_code == 400


def test_student_cannot_upload_article_media(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "student@media.edu")
    uploaded = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("campus.png", PNG_BYTES, "image/png")},
        data={"kind": "inline_image"},
    )
    assert uploaded.status_code in {401, 403}


def test_office_cannot_modify_other_office_media(article_media_client):
    client, session_factory = article_media_client
    admin = _headers(session_factory, "admin@media.edu")
    ict = _headers(session_factory, "ict@media.edu")
    registrar = _headers(session_factory, "reg@media.edu")
    uploaded = client.post(
        "/admin/kb/media",
        headers=ict,
        files={"file": ("osa.png", PNG_BYTES, "image/png")},
        data={"kind": "inline_image"},
    )
    assert uploaded.status_code == 200, uploaded.text
    created = client.post(
        "/admin/kb/articles",
        headers=ict,
        json={
            "title": "ICT lab rules",
            "category": "ICT Services",
            "content": f'<p><img src="{uploaded.json()["url"]}" alt="lab"></p>',
            "content_format": "html",
            "media_ids": [uploaded.json()["id"]],
            "publish_status": False,
            "force_create": True,
        },
    )
    assert created.status_code == 200, created.text
    article_id = created.json()["id"]
    denied = client.post(
        f"/admin/kb/articles/{article_id}/media",
        headers=registrar,
        files={"file": ("form.pdf", PDF_BYTES, "application/pdf")},
        data={"kind": "attachment"},
    )
    assert denied.status_code == 403
    listed = client.get(f"/admin/kb/articles/{article_id}/media", headers=registrar)
    assert listed.status_code == 403
    deleted = client.delete(f"/admin/kb/media/{uploaded.json()['id']}", headers=registrar)
    assert deleted.status_code == 403
    admin_list = client.get("/admin/kb/articles", headers=admin)
    assert admin_list.status_code == 200


def test_attachment_upload_list_and_authorized_delete(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    created = client.post(
        "/admin/kb/articles",
        headers=headers,
        json={
            "title": "Clearance form",
            "category": "Student Services",
            "content": "<p>Download the form.</p>",
            "content_format": "html",
            "publish_status": True,
            "force_create": True,
        },
    )
    assert created.status_code == 200, created.text
    article_id = created.json()["id"]
    uploaded = client.post(
        f"/admin/kb/articles/{article_id}/media",
        headers=headers,
        files={"file": ("clearance.pdf", PDF_BYTES, "application/pdf")},
        data={"kind": "attachment"},
    )
    assert uploaded.status_code == 200, uploaded.text
    media_id = uploaded.json()["id"]
    listed = client.get(f"/admin/kb/articles/{article_id}/media", headers=headers)
    names = {item["original_filename"] for item in listed.json()}
    assert "clearance.pdf" in names
    public = client.get(f"/kb/articles/{article_id}")
    assert public.status_code == 200
    assert any(item["id"] == media_id for item in public.json()["attachments"])
    public_file = client.get(uploaded.json()["url"])
    assert public_file.status_code == 200
    assert public_file.content.startswith(b"%PDF")
    removed = client.delete(f"/admin/kb/media/{media_id}", headers=headers)
    assert removed.status_code == 200
    listed_after = client.get(f"/admin/kb/articles/{article_id}/media", headers=headers)
    assert listed_after.json() == []


def test_invalid_and_oversized_attachment_rejected(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    created = client.post(
        "/admin/kb/articles",
        headers=headers,
        json={
            "title": "Docs",
            "category": "Student Services",
            "content": "<p>Files</p>",
            "content_format": "html",
            "force_create": True,
        },
    )
    article_id = created.json()["id"]
    exe = client.post(
        f"/admin/kb/articles/{article_id}/media",
        headers=headers,
        files={"file": ("virus.exe", b"MZ" + b"\x00" * 20, "application/x-msdownload")},
        data={"kind": "attachment"},
    )
    assert exe.status_code == 400
    huge = client.post(
        f"/admin/kb/articles/{article_id}/media",
        headers=headers,
        files={"file": ("huge.pdf", PDF_BYTES + b"0" * (10 * 1024 * 1024), "application/pdf")},
        data={"kind": "attachment"},
    )
    assert huge.status_code == 400


def test_cancelled_create_deletes_pending_upload(article_media_client, tmp_path):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "ict@media.edu")
    uploaded = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("temp.png", PNG_BYTES, "image/png")},
        data={"kind": "inline_image"},
    )
    assert uploaded.status_code == 200, uploaded.text
    media_id = uploaded.json()["id"]
    stored = uploaded.json()["stored_filename"]
    pending = client.get(uploaded.json()["url"], headers=headers)
    assert pending.status_code == 200
    anonymous = client.get(uploaded.json()["url"])
    assert anonymous.status_code == 404
    deleted = client.delete(f"/admin/kb/media/{media_id}", headers=headers)
    assert deleted.status_code == 200
    media_dir = tmp_path / "kb-media"
    assert not (media_dir / stored).exists()


def test_svg_and_html_uploads_rejected(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    svg = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("icon.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml")},
        data={"kind": "inline_image"},
    )
    assert svg.status_code == 400
    html = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("page.html", b"<!doctype html><script>alert(1)</script>", "text/html")},
        data={"kind": "attachment"},
    )
    assert html.status_code == 400
    traversal = client.get("/kb/media/..%2F..%2Fetc%2Fpasswd")
    assert traversal.status_code in {400, 404, 422}


def test_unpublished_media_not_public(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    uploaded = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("draft.png", PNG_BYTES, "image/png")},
        data={"kind": "inline_image"},
    )
    created = client.post(
        "/admin/kb/articles",
        headers=headers,
        json={
            "title": "Draft map",
            "category": "Student Services",
            "content": f'<p><img src="{uploaded.json()["url"]}" alt="draft"></p>',
            "content_format": "html",
            "media_ids": [uploaded.json()["id"]],
            "publish_status": False,
            "force_create": True,
        },
    )
    assert created.status_code == 200
    public_article = client.get(f"/kb/articles/{created.json()['id']}")
    assert public_article.status_code == 404
    public_img = client.get(uploaded.json()["url"])
    assert public_img.status_code == 404
    editor_img = client.get(uploaded.json()["url"], headers=headers)
    assert editor_img.status_code == 200


def test_edit_html_roundtrip_does_not_strip(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    created = client.post(
        "/admin/kb/articles",
        headers=headers,
        json={
            "title": "Library hours rich",
            "category": "Library Services",
            "content": "<h2>Hours</h2><p>The desk is <strong>open</strong> <em>today</em>.</p>"
            "<ul><li>Bring ID</li></ul><blockquote>Quiet please.</blockquote>"
            '<p><a href="https://lspu.edu.ph">LSPU</a></p>',
            "content_format": "html",
            "force_create": True,
        },
    )
    assert created.status_code == 200, created.text
    article_id = created.json()["id"]
    original = created.json()["content"]
    patched = client.patch(
        f"/admin/kb/articles/{article_id}",
        headers=headers,
        json={"content": original, "content_format": "html"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()["content"]
    assert patched.json()["content_format"] == "html"
    assert "<strong>open</strong>" in body
    assert "<em>today</em>" in body
    assert "<ul>" in body
    assert "<blockquote>" in body
    assert "https://lspu.edu.ph" in body


def test_spoofed_content_type_rejected(article_media_client):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    spoofed = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("campus.pdf", PNG_BYTES, "application/pdf")},
        data={"kind": "attachment"},
    )
    assert spoofed.status_code == 400


def test_office_cannot_attach_foreign_pending_media(article_media_client):
    client, session_factory = article_media_client
    ict = _headers(session_factory, "ict@media.edu")
    registrar = _headers(session_factory, "reg@media.edu")
    uploaded = client.post(
        "/admin/kb/media",
        headers=ict,
        files={"file": ("lab.png", PNG_BYTES, "image/png")},
        data={"kind": "inline_image"},
    )
    assert uploaded.status_code == 200, uploaded.text
    stolen = client.post(
        "/admin/kb/articles",
        headers=registrar,
        json={
            "title": "Stolen image",
            "category": "Registrar Services",
            "content": f'<p><img src="{uploaded.json()["url"]}" alt="lab"></p>',
            "content_format": "html",
            "media_ids": [uploaded.json()["id"]],
            "force_create": True,
        },
    )
    assert stolen.status_code == 403


def test_stale_pending_media_is_cleaned(article_media_client, tmp_path):
    from datetime import datetime, timedelta, timezone

    from app.models.db_models import ArticleMedia
    from app.services.article_media import cleanup_pending_media

    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    uploaded = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("stale.png", PNG_BYTES, "image/png")},
        data={"kind": "inline_image"},
    )
    assert uploaded.status_code == 200, uploaded.text
    media_id = uploaded.json()["id"]
    stored = uploaded.json()["stored_filename"]
    session = session_factory()
    try:
        row = session.get(ArticleMedia, media_id)
        assert row is not None
        row.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
        session.commit()
        removed = cleanup_pending_media(session)
        session.commit()
        assert removed == 1
        assert session.get(ArticleMedia, media_id) is None
    finally:
        session.close()
    assert not (tmp_path / "kb-media" / stored).exists()


def test_unlink_media_file_raises_and_leaves_file_when_os_error(monkeypatch, tmp_path):
    from pathlib import Path

    from app.services.article_media import ArticleMediaFileError, _unlink_media_file

    media_dir = tmp_path / "kb-media-unit"
    media_dir.mkdir()
    monkeypatch.setattr("app.services.kb_media.settings.kb_media_dir", str(media_dir))
    target = media_dir / "unit-test-file.png"
    target.write_bytes(PNG_BYTES)

    def _boom(self):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(Path, "unlink", _boom)
    with pytest.raises(ArticleMediaFileError):
        _unlink_media_file("unit-test-file.png")
    assert target.exists()


def test_unlink_media_file_is_idempotent_when_already_missing(tmp_path, monkeypatch):
    from app.services.article_media import _unlink_media_file

    media_dir = tmp_path / "kb-media-unit2"
    media_dir.mkdir()
    monkeypatch.setattr("app.services.kb_media.settings.kb_media_dir", str(media_dir))
    _unlink_media_file("never-existed.png")  # must not raise


def test_delete_media_keeps_row_and_file_protected_when_unlink_fails(
    article_media_client, monkeypatch
):
    from app.services.article_media import ArticleMediaFileError

    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    uploaded = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("protected.png", PNG_BYTES, "image/png")},
        data={"kind": "inline_image"},
    )
    assert uploaded.status_code == 200, uploaded.text
    media_id = uploaded.json()["id"]
    media_url = uploaded.json()["url"]

    def _boom(stored_filename):
        raise ArticleMediaFileError("simulated disk failure")

    monkeypatch.setattr("app.services.article_media._unlink_media_file", _boom)
    failed = client.delete(f"/admin/kb/media/{media_id}", headers=headers)
    assert failed.status_code == 500

    # Row must still exist (the file could not be confirmed deleted), so the
    # media stays exactly as protected as before the failed delete attempt:
    # not public to an anonymous caller, still reachable by its uploader.
    session = session_factory()
    try:
        from app.models.db_models import ArticleMedia

        assert session.get(ArticleMedia, media_id) is not None
    finally:
        session.close()
    anonymous = client.get(media_url)
    assert anonymous.status_code == 404
    owner = client.get(media_url, headers=headers)
    assert owner.status_code == 200


def test_delete_media_succeeds_once_file_already_missing(article_media_client, tmp_path):
    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    uploaded = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("goneearly.png", PNG_BYTES, "image/png")},
        data={"kind": "inline_image"},
    )
    assert uploaded.status_code == 200, uploaded.text
    media_id = uploaded.json()["id"]
    stored = uploaded.json()["stored_filename"]
    (tmp_path / "kb-media" / stored).unlink()  # simulate the file vanishing out-of-band

    removed = client.delete(f"/admin/kb/media/{media_id}", headers=headers)
    assert removed.status_code == 200, removed.text
    session = session_factory()
    try:
        from app.models.db_models import ArticleMedia

        assert session.get(ArticleMedia, media_id) is None
    finally:
        session.close()


def test_article_delete_rolls_back_when_media_file_deletion_fails(
    article_media_client, monkeypatch
):
    from app.services.article_media import ArticleMediaFileError

    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    created = client.post(
        "/admin/kb/articles",
        headers=headers,
        json={
            "title": "Undeleteable attachment",
            "category": "Student Services",
            "content": "<p>Has a stuck attachment.</p>",
            "content_format": "html",
            "publish_status": True,
            "force_create": True,
        },
    )
    assert created.status_code == 200, created.text
    article_id = created.json()["id"]
    uploaded = client.post(
        f"/admin/kb/articles/{article_id}/media",
        headers=headers,
        files={"file": ("stuck.pdf", PDF_BYTES, "application/pdf")},
        data={"kind": "attachment"},
    )
    assert uploaded.status_code == 200, uploaded.text
    media_id = uploaded.json()["id"]

    def _boom(stored_filename):
        raise ArticleMediaFileError("simulated disk failure")

    monkeypatch.setattr("app.services.article_media._unlink_media_file", _boom)
    failed = client.delete(f"/admin/kb/articles/{article_id}", headers=headers)
    assert failed.status_code == 500

    # The whole delete must have rolled back: article and its media both remain.
    still_there = client.get(f"/admin/kb/articles/{article_id}", headers=headers)
    assert still_there.status_code == 200
    still_listed = client.get(f"/admin/kb/articles/{article_id}/media", headers=headers)
    assert any(item["id"] == media_id for item in still_listed.json())


def test_cleanup_pending_media_retries_after_unlink_failure(article_media_client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.models.db_models import ArticleMedia
    from app.services.article_media import ArticleMediaFileError, cleanup_pending_media

    client, session_factory = article_media_client
    headers = _headers(session_factory, "admin@media.edu")
    uploaded = client.post(
        "/admin/kb/media",
        headers=headers,
        files={"file": ("flaky.png", PNG_BYTES, "image/png")},
        data={"kind": "inline_image"},
    )
    assert uploaded.status_code == 200, uploaded.text
    media_id = uploaded.json()["id"]

    session = session_factory()
    try:
        row = session.get(ArticleMedia, media_id)
        row.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
        session.commit()

        def _boom(stored_filename):
            raise ArticleMediaFileError("simulated disk failure")

        monkeypatch.setattr("app.services.article_media._unlink_media_file", _boom)
        removed_first = cleanup_pending_media(session)
        session.commit()
        assert removed_first == 0
        assert session.get(ArticleMedia, media_id) is not None

        monkeypatch.undo()
        removed_second = cleanup_pending_media(session)
        session.commit()
        assert removed_second == 1
        assert session.get(ArticleMedia, media_id) is None
    finally:
        session.close()
