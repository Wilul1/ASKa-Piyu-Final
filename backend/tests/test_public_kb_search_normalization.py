"""Public Knowledge Base search treats punctuation and spacing as non-semantic."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session_factory
from app.main import app
from app.models.db_models import PublishedArticle
from tests.db_helpers import cleanup_all_published_articles

client = TestClient(app)

_EQUIVALENT_QUERIES = (
    "good moral",
    " good moral ",
    "good   moral",
    "good moral!!!",
    "good moral???",
    "good, moral",
    "good-moral",
)


@pytest.fixture(autouse=True)
def _cleanup_articles():
    cleanup_all_published_articles()
    yield
    cleanup_all_published_articles()


def _add_article(*, title: str, content: str, category: str) -> None:
    session = get_session_factory()()
    try:
        session.add(
            PublishedArticle(
                id=str(uuid.uuid4()),
                title=title,
                slug=title.lower().replace(" ", "-"),
                category=category,
                content=content,
                summary="Summary",
                published=True,
                office="OSA",
            )
        )
        session.commit()
    finally:
        session.close()


def _titles(query: str | None) -> list[str]:
    params = {} if query is None else {"q": query}
    response = client.get("/kb/articles", params=params)
    assert response.status_code == 200
    return [item["title"] for item in response.json()["items"]]


def test_punctuation_and_spacing_match_the_plain_query():
    _add_article(
        title="Issuance of Good Moral Certificate",
        content="Students request a good moral certificate from OSAS.",
        category="Student Services",
    )
    _add_article(
        title="Enrollment Process",
        content="Bring the enrollment form to the Registrar.",
        category="Admissions",
    )

    baseline = _titles("good moral")
    assert baseline == ["Issuance of Good Moral Certificate"]
    for query in _EQUIVALENT_QUERIES:
        assert _titles(query) == baseline, query


def test_empty_query_returns_the_published_list_and_nonsense_does_not():
    _add_article(
        title="Issuance of Good Moral Certificate",
        content="Students request a good moral certificate from OSAS.",
        category="Student Services",
    )
    _add_article(
        title="Enrollment Process",
        content="Bring the enrollment form to the Registrar.",
        category="Admissions",
    )

    listed = _titles(None)
    assert set(listed) == {
        "Issuance of Good Moral Certificate",
        "Enrollment Process",
    }
    assert set(_titles("")) == set(listed)
    assert set(_titles("   ")) == set(listed)
    assert _titles("zzzznotatopic999") == []
    assert _titles("!!!") == []
