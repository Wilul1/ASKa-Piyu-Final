from fastapi.testclient import TestClient

from app.main import app
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


def test_kb_articles_returns_articles(monkeypatch):
    store = _override_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 7
    assert data["items"][0]["id"] == "academic-policies:excuse-slip"
    assert data["items"][0]["chunk_id"] == "handbook::1"
    assert data["items"][0]["title"] == "Excuse Slip"
    assert data["items"][0]["source_filename"] == "handbook.pdf"
    assert data["items"][0]["page"] == 12
    assert "article_key" not in data["items"][0]


def test_kb_articles_query_returns_matching_results(monkeypatch):
    store = _override_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles?q=excuse")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Excuse Slip"


def test_kb_articles_semantic_query_groups_matching_sections(monkeypatch):
    store = _override_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles?q=CCS%20Program")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert data["items"][0]["title"] == "College of Computer Studies Programs"
    assert data["items"][0]["category"] == "Programs & Curricular Offerings"
    assert data["items"][0]["page"] == 7
    assert data["items"][0]["matching_sections"] == 2


def test_kb_articles_sort_by_semantic_relevance_not_alphabetical(monkeypatch):
    store = _override_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles?q=Registrar")

    assert response.status_code == 200
    data = response.json()
    assert data["items"][0]["title"] == "Registrar Services"


def test_kb_articles_natural_student_queries(monkeypatch):
    store = _override_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

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
        response = client.get("/kb/articles", params={"q": query})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert expected_title_part in data["items"][0]["title"]


def test_kb_categories_returns_grouped_categories(monkeypatch):
    store = _override_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/categories")

    assert response.status_code == 200
    data = response.json()
    names = {item["name"] for item in data["items"]}
    assert "Student Services" in names
    assert "Academic Policies" in names
    assert all(item["sample_article_titles"] for item in data["items"])


def test_kb_articles_category_returns_focused_academic_policy_titles(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles?category=Academic%20Policies")

    assert response.status_code == 200
    titles = {item["title"] for item in response.json()["items"]}
    assert {
        "Academic Load",
        "Attendance Policy",
        "Excuse Slip",
        "Absence",
        "Grading System",
        "Graduation Requirements",
        "Scholastic Delinquency",
    }.issubset(titles)
    assert all(item["matching_sections"] <= 1 for item in response.json()["items"])


def test_kb_articles_splits_attendance_into_excuse_slip_and_absence(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles?category=Academic%20Policies")

    titles = {item["title"] for item in response.json()["items"]}
    assert "Excuse Slip" in titles
    assert "Absence" in titles


def test_kb_articles_scholastic_delinquency_is_focused_article(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles?category=Academic%20Policies")

    item = next(item for item in response.json()["items"] if item["title"] == "Scholastic Delinquency")
    assert item["subcategory"] == "Retention"
    assert item["page_range"] == "24"


def test_kb_articles_curricular_offerings_split_by_college_topic(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles?category=Programs%20%26%20Curricular%20Offerings")

    titles = {item["title"] for item in response.json()["items"]}
    assert "College of Engineering Programs" in titles
    assert "Undergraduate Programs" in titles


def test_kb_articles_search_excuse_slip_returns_focused_articles(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles?q=excuse%20slip")

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert titles[0] == "Excuse Slip"
    assert all(item["matching_sections"] <= 1 for item in response.json()["items"])


def test_kb_articles_search_scholastic_delinquency_displays_leaf_title(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles", params={"q": "Scholastic Delinquency"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["title"] == "Scholastic Delinquency"
    assert item["path"] == "Academic Policies • Retention"
    assert "Scholastic Delinquency" not in item["path"]


def test_kb_articles_search_excuse_slip_path_does_not_repeat_title(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles", params={"q": "Excuse Slip"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["title"] == "Excuse Slip"
    assert item["path"] == "Academic Policies • Attendance"
    assert "Excuse Slip" not in item["path"]


def test_kb_articles_search_retention_keeps_broad_parent_title(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles", params={"q": "Retention"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["title"] == "Retention Policies"
    assert item["path"] == "Academic Policies"


def test_kb_articles_search_engineering_program_returns_engineering(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles", params={"q": "Engineering Program"})

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert titles[0] == "College of Engineering Programs"
    assert response.json()["items"][0]["path"] == "Programs & Curricular Offerings"


def test_kb_articles_search_ccs_program_returns_computer_studies(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles", params={"q": "CCS Program"})

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert "College of Computer Studies Programs" in titles


def test_kb_articles_search_computer_science_returns_ccs_programs(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles", params={"q": "Computer Science"})

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert "College of Computer Studies Programs" in titles


def test_kb_articles_search_student_records_terms(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    tor_response = client.get("/kb/articles", params={"q": "TOR"})
    good_moral_response = client.get("/kb/articles", params={"q": "Good Moral"})

    assert tor_response.status_code == 200
    assert good_moral_response.status_code == 200
    tor_item = tor_response.json()["items"][0]
    good_moral_item = good_moral_response.json()["items"][0]
    assert tor_item["title"] == "Transcript of Records"
    assert "Transcript of Records" not in tor_item["path"]
    assert good_moral_item["title"] == "Good Moral"
    assert "Good Moral" not in good_moral_item["path"]


def test_kb_articles_search_guidance_counseling(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles", params={"q": "Guidance Counseling"})

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert "Guidance Counseling" in titles


def test_kb_articles_search_portal_password(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles", params={"q": "Portal Password"})

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert "Student Portal Account Recovery" in titles


def test_kb_article_detail_still_opens_for_search_result(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)
    articles_response = client.get("/kb/articles", params={"q": "Scholastic Delinquency"})
    article_id = articles_response.json()["items"][0]["id"]

    response = client.get(f"/kb/articles/{article_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Scholastic Delinquency"
    assert "scholastic delinquency" in data["content"].lower()
    assert data["page_range"] == "24"


def test_kb_articles_search_no_results_returns_suggestions(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles", params={"q": "Engineering Program", "category": "Graduate Studies"})

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert "College of Engineering Programs" in data["suggestions"]


def test_kb_focused_article_detail_excludes_unrelated_sections(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)
    articles_response = client.get("/kb/articles?category=Academic%20Policies")
    article_id = next(
        item["id"]
        for item in articles_response.json()["items"]
        if item["title"] == "Excuse Slip"
    )

    response = client.get(f"/kb/articles/{article_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Excuse Slip"
    assert "secure an excuse slip" in data["content"]
    assert "Absence from class" not in data["content"]
    assert data["source_document"] == "Student Handbook"
    assert data["page_range"] == "12"
    assert data["related_articles"]


def test_kb_article_detail_returns_full_content(monkeypatch):
    store = _override_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles/handbook::1")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "academic-policies:excuse-slip"
    assert data["chunk_id"] == "handbook::1"
    assert "secure an excuse slip" in data["content"]
    assert data["metadata"]["section"] == "Sec. 3 > Excuse Slip"


def test_kb_articles_debug_includes_identity_fields(monkeypatch):
    store = _override_focused_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    response = client.get("/kb/articles", params={"q": "TOR", "debug": "true"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["title"] == "Transcript of Records"
    assert item["article_key"] == "student-records:transcript-of-records"
    assert item["derived_article_title"] == "Transcript of Records"
    assert item["grouping_reason"] == "alias_rule"
    assert "tor" in item["matched_aliases"]


def test_kb_endpoints_are_read_only(monkeypatch):
    store = _override_store()
    monkeypatch.setattr("app.routes.knowledge_base.get_knowledge_base_store", lambda: store)

    client.get("/kb/articles")
    client.get("/kb/categories")
    client.get("/kb/articles/handbook::1")
    client.get("/kb/popular")

    assert store.deleted is False
    assert store.added is False
