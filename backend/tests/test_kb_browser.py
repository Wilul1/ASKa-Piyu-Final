from fastapi.testclient import TestClient

from app.main import app
from app.routes import knowledge_base as kb_routes
from app.services.chroma_store import RetrievedChunk
from app.services.retrieval_reranker import expand_query, rerank_chunks

client = TestClient(app)


class FakeKnowledgeBaseStore:
    def __init__(self) -> None:
        self.deleted = False
        self.added = False
        self.chunks = [
            {
                "id": "handbook::1",
                "text": "Students who were absent due to illness should secure an excuse slip with supporting documents.",
                "metadata": {
                    "title": "Student Handbook",
                    "source_filename": "handbook.pdf",
                    "chapter": "Chapter 5 > Student Services",
                    "article": "Article 2 > Attendance",
                    "section": "Sec. 3 > Excuse Slip",
                    "page_start": 12,
                    "content_type": "procedure",
                },
            },
            {
                "id": "handbook::3",
                "text": "The College of Computer Studies offers BS Computer Science, BS Information System, and BS Information Technology programs.",
                "metadata": {
                    "title": "Student Handbook",
                    "source_filename": "handbook.pdf",
                    "document_id": "handbook",
                    "chapter": "Chapter 3 > Curricular Offerings",
                    "article": "Article 1 > Curricular Offerings",
                    "section": "College of Computer Studies > Undergraduate Programs",
                    "page_start": 7,
                    "content_type": "program_listing",
                },
            },
            {
                "id": "handbook::4",
                "text": "BSCS means Bachelor of Science in Computer Science under the College of Computer Studies.",
                "metadata": {
                    "title": "Student Handbook",
                    "source_filename": "handbook.pdf",
                    "document_id": "handbook",
                    "chapter": "Chapter 3 > Curricular Offerings",
                    "article": "Article 1 > Curricular Offerings",
                    "section": "College of Computer Studies > BSCS",
                    "page_start": 8,
                    "content_type": "program_listing",
                },
            },
            {
                "id": "handbook::5",
                "text": "Scholarship grants are available to qualified students who meet grade and documentary requirements.",
                "metadata": {
                    "title": "Student Handbook",
                    "source_filename": "handbook.pdf",
                    "document_id": "handbook",
                    "chapter": "Chapter 5 > Student Services",
                    "article": "Article 4 > Scholarship",
                    "section": "Sec. 1 > Scholarship Grants",
                    "page_start": 18,
                    "content_type": "policy",
                },
            },
            {
                "id": "handbook::6",
                "text": "Enrollment requires registration, assessment of fees, and confirmation through the registrar.",
                "metadata": {
                    "title": "Student Handbook",
                    "source_filename": "handbook.pdf",
                    "document_id": "handbook",
                    "chapter": "Chapter 4 > Admission and Registration",
                    "article": "Article 2 > Enrollment",
                    "section": "Sec. 1 > Enrollment Procedure",
                    "page_start": 10,
                    "content_type": "procedure",
                },
            },
            {
                "id": "handbook::7",
                "text": "The registrar maintains student records, registration documents, grades, and transfer credentials.",
                "metadata": {
                    "title": "Student Handbook",
                    "source_filename": "handbook.pdf",
                    "document_id": "handbook",
                    "chapter": "Chapter 5 > Student Services",
                    "article": "Article 5 > Registrar",
                    "section": "Sec. 1 > Registrar Services",
                    "page_start": 20,
                    "content_type": "office",
                },
            },
            {
                "id": "handbook::2",
                "text": "Students under scholastic delinquency are subject to retention policies and academic standing rules.",
                "metadata": {
                    "title": "Student Handbook",
                    "source_filename": "handbook.pdf",
                    "chapter": "Chapter 6 > Academic Policies",
                    "article": "Article 1 > Retention Policies",
                    "section": "Sec. 1 > Scholastic Delinquency",
                    "page_start": 24,
                    "content_type": "policy",
                },
            },
        ]

    def list_chunks(self):
        return list(self.chunks)

    def get_chunk(self, chunk_id: str):
        return next((chunk for chunk in self.chunks if chunk["id"] == chunk_id), None)

    def search(self, query: str, *, top_k: int | None = None, raw_k: int | None = None):
        normalized = query.lower()
        semantic_scores = {
            "handbook::1": 0.92 if "excuse" in normalized or "absence" in normalized else 0.2,
            "handbook::2": 0.86 if "retention" in normalized else 0.15,
            "handbook::3": 0.9
            if any(term in normalized for term in ("ccs", "computer science", "program", "bscs"))
            else 0.2,
            "handbook::4": 0.88
            if any(term in normalized for term in ("ccs", "computer science", "program", "bscs"))
            else 0.2,
            "handbook::5": 0.91 if "scholarship" in normalized else 0.18,
            "handbook::6": 0.91 if "enrollment" in normalized else 0.18,
            "handbook::7": 0.91 if "registrar" in normalized else 0.18,
        }
        retrieved = []
        for chunk in self.chunks:
            metadata = dict(chunk["metadata"])
            document_id = str(metadata.get("document_id") or "handbook")
            chunk_index = int(chunk["id"].rsplit("::", 1)[-1])
            score = semantic_scores[chunk["id"]]
            retrieved.append(
                RetrievedChunk(
                    document_id=document_id,
                    title=str(metadata.get("title") or ""),
                    source_filename=str(metadata.get("source_filename") or ""),
                    chunk_index=chunk_index,
                    text=chunk["text"],
                    relevance_score=score,
                    original_score=score,
                    reranked_score=score,
                    metadata=metadata,
                )
            )
        ranked = rerank_chunks(expand_query(query), retrieved)
        return ranked[: top_k or 5]

    def delete_document(self, document_id: str) -> None:
        self.deleted = True

    def add_document_chunks(self, **kwargs) -> int:
        self.added = True
        return 0


class FocusedKnowledgeBaseStore:
    def __init__(self) -> None:
        self.deleted = False
        self.added = False
        self.chunks = [
            self._chunk(
                "focused::1",
                "Attendance policy explains regular class attendance expectations.",
                "Academic Policies",
                "Attendance",
                "Article 2 > Attendance",
                "Attendance Policy",
                11,
            ),
            self._chunk(
                "focused::2",
                "Students who were absent due to illness should secure an excuse slip with supporting documents.",
                "Academic Policies",
                "Attendance",
                "Article 2 > Attendance",
                "Sec. 3 > Excuse Slip",
                12,
            ),
            self._chunk(
                "focused::3",
                "Absence from class may be excused only for valid reasons.",
                "Academic Policies",
                "Attendance",
                "Article 2 > Attendance",
                "Sec. 4 > Absence",
                13,
            ),
            self._chunk(
                "focused::4",
                "Students under scholastic delinquency are subject to retention policies and academic standing rules.",
                "Academic Policies",
                "Retention",
                "Article 1 > Retention Policies",
                "Sec. 1 > Scholastic Delinquency",
                24,
            ),
            self._chunk(
                "focused::5",
                "Academic load rules define minimum and maximum subject units.",
                "Academic Policies",
                "Academic Load",
                "Article 3 > Academic Load",
                "Academic Load",
                15,
            ),
            self._chunk(
                "focused::6",
                "The grading system defines final grades, incomplete grades, and passing marks.",
                "Academic Policies",
                "Grading System",
                "Article 4 > Grading System",
                "Grading System",
                18,
            ),
            self._chunk(
                "focused::7",
                "Graduation requirements include completion of curriculum and clearance.",
                "Academic Policies",
                "Graduation",
                "Article 5 > Graduation",
                "Graduation Requirements",
                30,
            ),
            self._chunk(
                "focused::8",
                "The College of Engineering offers engineering degree programs.",
                "Programs & Curricular Offerings",
                "College of Engineering",
                "Article 1 > Curricular Offerings",
                "College of Engineering",
                41,
                content_type="program_listing",
            ),
            self._chunk(
                "focused::9",
                "The College of Computer Studies offers BS Computer Science and BS Information Technology.",
                "Programs & Curricular Offerings",
                "College of Computer Studies",
                "Article 1 > Curricular Offerings",
                "College of Computer Studies",
                42,
                content_type="program_listing",
            ),
            self._chunk(
                "focused::14",
                "Undergraduate programs include BS Computer Science and BS Information Technology.",
                "Programs & Curricular Offerings",
                "Undergraduate Programs",
                "Article 1 > Curricular Offerings",
                "College of Computer Studies > Undergraduate Programs",
                43,
                content_type="program_listing",
            ),
            self._chunk(
                "focused::10",
                "Students may request an official transcript of records from the Registrar.",
                "Student Records",
                "Transcript of Records",
                "Article 1 > Student Records",
                "Transcript of Records",
                50,
            ),
            self._chunk(
                "focused::11",
                "Students may request a certificate of good moral character from Student Records.",
                "Student Records",
                "Good Moral",
                "Article 1 > Student Records",
                "Good Moral",
                51,
            ),
            self._chunk(
                "focused::12",
                "Guidance and counseling services help students through consultation and referral.",
                "Student Services",
                "Guidance and Counseling",
                "Article 3 > Student Services",
                "Guidance Counseling",
                60,
            ),
            self._chunk(
                "focused::13",
                "Students who forgot their portal password may request student portal account recovery.",
                "Technical Support",
                "Student Portal",
                "Article 1 > Technical Support",
                "Student Portal Account Recovery",
                70,
            ),
        ]

    def _chunk(
        self,
        chunk_id: str,
        text: str,
        category: str,
        subcategory: str,
        article: str,
        section: str,
        page: int,
        *,
        content_type: str = "policy",
    ) -> dict:
        return {
            "id": chunk_id,
            "text": text,
            "metadata": {
                "title": "Student Handbook",
                "source_document": "Student Handbook",
                "source_filename": "handbook.pdf",
                "document_id": "focused",
                "chapter": f"Chapter 6 > {category}",
                "article": article,
                "section": section,
                "category": category,
                "subcategory": subcategory,
                "responsible_office": "Registrar",
                "page_start": page,
                "content_type": content_type,
            },
        }

    def list_chunks(self):
        return list(self.chunks)

    def get_chunk(self, chunk_id: str):
        return next((chunk for chunk in self.chunks if chunk["id"] == chunk_id), None)

    def search(self, query: str, *, top_k: int | None = None, raw_k: int | None = None):
        normalized = query.lower()
        retrieved = []
        for chunk in self.chunks:
            text = f"{chunk['text']} {chunk['metadata']['section']}".lower()
            score = 0.2
            if "excuse slip" in normalized and "excuse slip" in text:
                score = 0.94
            elif "excuse slip" in normalized and "attendance" in text:
                score = 0.82
            elif "scholastic delinquency" in normalized and "scholastic delinquency" in text:
                score = 0.94
            elif "retention" in normalized and "retention" in text:
                score = 0.94
            elif any(term in normalized for term in ("engineering", "program")) and "engineering" in text:
                score = 0.92
            elif any(term in normalized for term in ("ccs", "computer science", "computer studies")) and "computer studies" in text:
                score = 0.92
            elif any(term in normalized for term in ("tor", "transcript")) and "transcript of records" in text:
                score = 0.92
            elif "good moral" in normalized and "good moral" in text:
                score = 0.92
            elif any(term in normalized for term in ("guidance", "counseling")) and "guidance" in text:
                score = 0.92
            elif any(term in normalized for term in ("portal password", "account recovery")) and "portal" in text:
                score = 0.92
            metadata = dict(chunk["metadata"])
            retrieved.append(
                RetrievedChunk(
                    document_id="focused",
                    title=str(metadata.get("title") or ""),
                    source_filename=str(metadata.get("source_filename") or ""),
                    chunk_index=int(chunk["id"].rsplit("::", 1)[-1]),
                    text=chunk["text"],
                    relevance_score=score,
                    original_score=score,
                    reranked_score=score,
                    metadata=metadata,
                )
            )
        ranked = rerank_chunks(expand_query(query), retrieved)
        return ranked[: top_k or 5]

    def delete_document(self, document_id: str) -> None:
        self.deleted = True

    def add_document_chunks(self, **kwargs) -> int:
        self.added = True
        return 0


def _override_store() -> FakeKnowledgeBaseStore:
    store = FakeKnowledgeBaseStore()
    app.dependency_overrides.clear()
    return store


def _override_focused_store() -> FocusedKnowledgeBaseStore:
    store = FocusedKnowledgeBaseStore()
    app.dependency_overrides.clear()
    return store


def _display(articles: list[dict], *, q: str = "", debug: bool = False) -> list[dict]:
    displayed = kb_routes._prepare_article_display(articles, q=q)
    if not debug:
        displayed = [kb_routes._without_identity_debug(item) for item in displayed]
    return displayed


def test_focused_article_groups_returns_articles():
    store = _override_store()
    articles = _display(kb_routes._focused_article_groups(store.list_chunks()))

    assert len(articles) == 7
    assert articles[0]["id"] == "academic-policies:excuse-slip"
    assert articles[0]["title"] == "Excuse Slip"
    assert articles[0]["source_filename"] == "handbook.pdf"
    assert articles[0]["page"] == 12
    assert "article_key" not in articles[0]


def test_semantic_query_returns_matching_results():
    store = _override_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="excuse", category=None, limit=24, offset=0
        ),
        q="excuse",
    )

    assert len(articles) == 1
    assert articles[0]["title"] == "Excuse Slip"


def test_semantic_query_groups_matching_sections():
    store = _override_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="CCS Program", category=None, limit=24, offset=0
        ),
        q="CCS Program",
    )

    assert len(articles) >= 1
    assert articles[0]["title"] == "College of Computer Studies Programs"
    assert articles[0]["category"] == "Programs & Curricular Offerings"
    assert articles[0]["page"] == 7
    assert articles[0]["matching_sections"] == 2


def test_semantic_sort_by_relevance_not_alphabetical():
    store = _override_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="Registrar", category=None, limit=24, offset=0
        ),
        q="Registrar",
    )

    assert articles[0]["title"] == "Registrar Services"


def test_natural_student_queries():
    store = _override_store()
    cases = {
        "CCS Program": "College of Computer Studies Programs",
        "Computer Science": "College of Computer Studies Programs",
        "BSCS": "College of Computer Studies Programs",
        "Excuse Slip": "Excuse Slip",
        "Scholarship": "Scholarship Grants",
        "Enrollment": "Enrollment Procedure",
        "Registrar": "Registrar Services",
    }

    for query, expected_title_part in cases.items():
        articles = _display(
            kb_routes._semantic_article_search(
                store, q=query, category=None, limit=24, offset=0
            ),
            q=query,
        )
        assert len(articles) >= 1
        assert expected_title_part in articles[0]["title"]


def test_focused_groups_cover_identity_titles():
    store = _override_store()
    articles = kb_routes._focused_article_groups(store.list_chunks())
    assert any(item["title"] == "Excuse Slip" for item in articles)


def test_focused_academic_policy_titles():
    store = _override_focused_store()
    articles = _display(
        kb_routes._filter_articles(
            kb_routes._focused_article_groups(store.list_chunks()),
            q=None,
            category="Academic Policies",
        )
    )

    titles = {item["title"] for item in articles}
    assert {
        "Academic Load",
        "Attendance Policy",
        "Excuse Slip",
        "Absence",
        "Grading System",
        "Graduation Requirements",
        "Scholastic Delinquency",
    }.issubset(titles)
    assert all(item["matching_sections"] <= 1 for item in articles)


def test_attendance_splits_into_excuse_slip_and_absence():
    store = _override_focused_store()
    articles = kb_routes._filter_articles(
        kb_routes._focused_article_groups(store.list_chunks()),
        q=None,
        category="Academic Policies",
    )
    titles = {item["title"] for item in articles}
    assert "Excuse Slip" in titles
    assert "Absence" in titles


def test_scholastic_delinquency_is_focused_article():
    store = _override_focused_store()
    articles = kb_routes._filter_articles(
        kb_routes._focused_article_groups(store.list_chunks()),
        q=None,
        category="Academic Policies",
    )
    item = next(item for item in articles if item["title"] == "Scholastic Delinquency")
    assert item["subcategory"] == "Retention"
    assert item["page_range"] == "24"


def test_curricular_offerings_split_by_college_topic():
    store = _override_focused_store()
    articles = kb_routes._filter_articles(
        kb_routes._focused_article_groups(store.list_chunks()),
        q=None,
        category="Programs & Curricular Offerings",
    )
    titles = {item["title"] for item in articles}
    assert "College of Engineering Programs" in titles
    assert "Undergraduate Programs" in titles


def test_search_excuse_slip_returns_focused_articles():
    store = _override_focused_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="excuse slip", category=None, limit=24, offset=0
        ),
        q="excuse slip",
    )
    assert articles[0]["title"] == "Excuse Slip"
    assert all(item["matching_sections"] <= 1 for item in articles)


def test_search_scholastic_delinquency_displays_leaf_title():
    store = _override_focused_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="Scholastic Delinquency", category=None, limit=24, offset=0
        ),
        q="Scholastic Delinquency",
    )
    item = articles[0]
    assert item["title"] == "Scholastic Delinquency"
    assert item["path"] == "Academic Policies • Retention"
    assert "Scholastic Delinquency" not in item["path"]


def test_search_excuse_slip_path_does_not_repeat_title():
    store = _override_focused_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="Excuse Slip", category=None, limit=24, offset=0
        ),
        q="Excuse Slip",
    )
    item = articles[0]
    assert item["title"] == "Excuse Slip"
    assert item["path"] == "Academic Policies • Attendance"
    assert "Excuse Slip" not in item["path"]


def test_search_retention_keeps_broad_parent_title():
    store = _override_focused_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="Retention", category=None, limit=24, offset=0
        ),
        q="Retention",
    )
    item = articles[0]
    assert item["title"] == "Retention Policies"
    assert item["path"] == "Academic Policies"


def test_search_engineering_program_returns_engineering():
    store = _override_focused_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="Engineering Program", category=None, limit=24, offset=0
        ),
        q="Engineering Program",
    )
    assert articles[0]["title"] == "College of Engineering Programs"
    assert articles[0]["path"] == "Programs & Curricular Offerings"


def test_search_ccs_program_returns_computer_studies():
    store = _override_focused_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="CCS Program", category=None, limit=24, offset=0
        ),
        q="CCS Program",
    )
    titles = [item["title"] for item in articles]
    assert "College of Computer Studies Programs" in titles


def test_search_computer_science_returns_ccs_programs():
    store = _override_focused_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="Computer Science", category=None, limit=24, offset=0
        ),
        q="Computer Science",
    )
    titles = [item["title"] for item in articles]
    assert "College of Computer Studies Programs" in titles


def test_search_student_records_terms():
    store = _override_focused_store()
    tor_articles = _display(
        kb_routes._semantic_article_search(
            store, q="TOR", category=None, limit=24, offset=0
        ),
        q="TOR",
    )
    good_moral_articles = _display(
        kb_routes._semantic_article_search(
            store, q="Good Moral", category=None, limit=24, offset=0
        ),
        q="Good Moral",
    )
    assert tor_articles[0]["title"] == "Transcript of Records"
    assert "Transcript of Records" not in tor_articles[0]["path"]
    assert good_moral_articles[0]["title"] == "Good Moral"
    assert "Good Moral" not in good_moral_articles[0]["path"]


def test_search_guidance_counseling():
    store = _override_focused_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="Guidance Counseling", category=None, limit=24, offset=0
        ),
        q="Guidance Counseling",
    )
    titles = [item["title"] for item in articles]
    assert "Guidance Counseling" in titles


def test_search_portal_password():
    store = _override_focused_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="Portal Password", category=None, limit=24, offset=0
        ),
        q="Portal Password",
    )
    titles = [item["title"] for item in articles]
    assert "Student Portal Account Recovery" in titles


def test_focused_article_detail_still_opens_for_search_result(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="Scholastic Delinquency", category=None, limit=24, offset=0
        ),
        q="Scholastic Delinquency",
    )
    article_id = articles[0]["id"]
    detail = kb_routes._focused_article_detail(article_id)
    assert detail is not None
    assert detail["title"] == "Scholastic Delinquency"
    assert "scholastic delinquency" in detail["content"].lower()
    assert detail["page_range"] == "24"


def test_search_no_results_returns_empty_for_mismatched_category():
    store = _override_focused_store()
    articles = kb_routes._semantic_article_search(
        store,
        q="Engineering Program",
        category="Graduate Studies",
        limit=24,
        offset=0,
    )
    assert articles == []
    suggestions = kb_routes._search_suggestions("Engineering Program")
    assert "College of Engineering Programs" in suggestions


def test_focused_article_detail_excludes_unrelated_sections(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)
    articles = kb_routes._filter_articles(
        kb_routes._focused_article_groups(store.list_chunks()),
        q=None,
        category="Academic Policies",
    )
    article_id = next(item["id"] for item in articles if item["title"] == "Excuse Slip")
    detail = kb_routes._focused_article_detail(article_id)
    assert detail is not None
    assert detail["title"] == "Excuse Slip"
    assert "secure an excuse slip" in detail["content"]
    assert "Absence from class" not in detail["content"]
    assert detail["source_document"] == "Student Handbook"
    assert detail["page_range"] == "12"
    assert detail["related_articles"]


def test_chunk_detail_helper_returns_full_content():
    store = _override_store()
    chunk = store.get_chunk("handbook::1")
    assert chunk is not None
    # Public HTTP no longer serves Chroma chunks; helper remains for RAG tooling.
    data = kb_routes._article_detail(chunk)
    assert "secure an excuse slip" in data["content"]
    assert data["metadata"]["section"] == "Sec. 3 > Excuse Slip"


def test_debug_includes_identity_fields():
    store = _override_focused_store()
    articles = _display(
        kb_routes._semantic_article_search(
            store, q="TOR", category=None, limit=24, offset=0
        ),
        q="TOR",
        debug=True,
    )
    item = articles[0]
    assert item["title"] == "Transcript of Records"
    assert item["article_key"] == "student-records:transcript-of-records"
    assert item["derived_article_title"] == "Transcript of Records"
    assert item["grouping_reason"] == "alias_rule"
    assert "tor" in item["matched_aliases"]


def test_public_kb_endpoints_do_not_mutate_chroma(monkeypatch):
    store = _override_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    client.get("/kb/articles")
    client.get("/kb/categories")
    client.get("/kb/articles/handbook::1")
    client.get("/kb/popular")

    assert store.deleted is False
    assert store.added is False
    # Public article endpoints ignore Chroma content.
    assert client.get("/kb/articles").json()["total"] == 0
    assert client.get("/kb/articles/handbook::1").status_code == 404
