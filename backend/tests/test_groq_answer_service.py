import pytest

from app.services.qa.groq_answer_service import build_groq_messages, format_groq_answer


def test_groq_prompt_uses_full_policy_context_for_scholastic_delinquency():
    context = """
Title: Scholastic Delinquency
Path: Undergraduate Academic Policies > Retention Policies > Scholastic Delinquency
Page: 35

Content:
The University Academic Council shall promulgate rules and guidelines governing scholastic delinquency.
Warning applies when a student fails 25% to 49% of registered academic units.
Probation applies when a student fails 50% to 74% of registered academic units.
""".strip()

    messages = build_groq_messages(question="What is scholastic delinquency?", context=context)
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]

    assert "policy rules, conditions, standards, thresholds, consequences, or procedures" in system_prompt
    assert "Be concise" in system_prompt
    assert "Answer the question directly first" in system_prompt
    assert "Prefer bullet points" in system_prompt
    assert "Do not include \"Source:\" or \"Sources:\" lines" in system_prompt
    assert "student-friendly explanation" in user_prompt
    assert "Use bullet points for thresholds" in user_prompt
    assert "Do not include Source or Sources lines" in user_prompt
    assert "The University Academic Council shall promulgate rules and guidelines" in user_prompt
    assert "Probation applies when a student fails 50% to 74%" in user_prompt
    assert "What is scholastic delinquency?" in user_prompt


@pytest.mark.parametrize(
    "question",
    [
        "What is scholastic delinquency?",
        "What happens if I fail 75% of my units?",
        "What is retention policy?",
        "What are the warning and probation rules?",
    ],
)
def test_academic_policy_prompt_answers_from_rules_not_direct_definitions(question: str):
    context = """
Title: Scholastic Delinquency
Path: Undergraduate Academic Policies > Retention Policies > Scholastic Delinquency
Page: 35

Content:
The University Academic Council shall promulgate rules and guidelines governing scholastic delinquency.
Warning applies when a student fails 25% to 49% of registered academic units.
Probation applies when a student fails 50% to 74% of registered academic units.
Dismissal from the College may apply when a student fails more than 75% of registered academic units.
""".strip()

    messages = build_groq_messages(question=question, context=context)
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]

    assert "policy rules, conditions, standards, thresholds, consequences, or procedures" in system_prompt
    assert "Do not say the context lacks a direct definition" in system_prompt
    assert "Do not start every answer" in system_prompt
    assert "Answer the question directly first" in system_prompt
    assert "Prefer bullet points" in system_prompt
    assert "truly unrelated" in system_prompt
    assert "Treat related policy rules, conditions, standards, thresholds, consequences, and procedures as enough context to answer" in user_prompt
    assert "Do not say there is no direct definition" in user_prompt
    assert "Use bullet points for thresholds" in user_prompt
    assert "Dismissal from the College may apply when a student fails more than 75%" in user_prompt
    assert f"Question: {question}" in user_prompt


def test_groq_answer_formatter_removes_source_lines():
    answer = """
Scholastic delinquency refers to poor academic performance based on failed academic units.

Under the retention policy:
- 25%-49% failed units: Warning
- 50%-74% failed units: Probation

Sources: Scholastic Delinquency
""".strip()

    formatted = format_groq_answer(answer)

    assert "Sources:" not in formatted
    assert "Source:" not in formatted
    assert "- 25%-49% failed units: Warning" in formatted


def test_scholastic_delinquency_answer_style_uses_bullet_thresholds_without_sources():
    answer = """
Scholastic delinquency refers to poor academic performance based on failed academic units.

Under the LSPU retention policy:
- 25%-49% failed units: Warning
- 50%-74% failed units: Probation
- More than 75% failed units: Dismissal from the College

Source: Scholastic Delinquency
""".strip()

    formatted = format_groq_answer(answer)

    assert "Source:" not in formatted
    assert formatted.splitlines()[0].startswith("Scholastic delinquency refers")
    assert "- 25%-49% failed units: Warning" in formatted
    assert "- 50%-74% failed units: Probation" in formatted
    assert "- More than 75% failed units: Dismissal from the College" in formatted


def test_excuse_slip_answer_style_is_short_direct_and_source_free():
    answer = """
You can get an excuse slip from:
- Office of the Students Affairs Services
- Guidance Office

If your absence is due to illness, a medical certificate is also required.

Sources: Attendance Policy
""".strip()

    formatted = format_groq_answer(answer)

    assert "Sources:" not in formatted
    assert formatted.startswith("You can get an excuse slip from:")
    assert "- Office of the Students Affairs Services" in formatted
    assert "- Guidance Office" in formatted
    assert len([line for line in formatted.splitlines() if line.strip()]) <= 5


def test_out_of_scope_answer_style_refuses_without_hallucinating():
    answer = """
I can only answer based on the indexed ASKa-Piyu university documents. The current knowledge base does not contain information about the president of the Philippines.

Sources: Scholastic Delinquency
""".strip()

    formatted = format_groq_answer(answer)

    assert "Sources:" not in formatted
    assert "Ferdinand" not in formatted
    assert "Bongbong" not in formatted
    assert "indexed ASKa-Piyu university documents" in formatted
    assert "does not contain information about the president of the Philippines" in formatted


def test_prompt_requires_short_direct_excuse_slip_answer():
    context = """
Title: Attendance Policy
Path: Undergraduate Academic Policies > Attendance
Page: 34

Content:
Excuse slips for absences may be secured from the Office of the Students Affairs Services or the Guidance Office.
If absence is due to illness, a medical certificate is required.
""".strip()

    messages = build_groq_messages(question="Where can I get an excuse slip?", context=context)
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]

    assert "Be concise" in system_prompt
    assert "Answer the question directly first" in system_prompt
    assert "Prefer bullet points" in system_prompt
    assert "Office of the Students Affairs Services" in user_prompt
    assert "Guidance Office" in user_prompt
    assert "medical certificate is required" in user_prompt


def test_prompt_keeps_out_of_scope_questions_grounded():
    context = """
Title: Scholastic Delinquency
Path: Undergraduate Academic Policies > Retention Policies

Content:
Warning applies when a student fails 25% to 49% of registered academic units.
""".strip()

    messages = build_groq_messages(question="Who is the president of the Philippines?", context=context)
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]

    assert "Never invent" in system_prompt
    assert "only when the retrieved context is truly unrelated" in system_prompt
    assert "Use the insufficient-information response only when no retrieved policy details answer the question" in user_prompt
    assert "Who is the president of the Philippines?" in user_prompt


def test_broad_prompt_requests_grouped_deduplicated_summary():
    context = """
Title: Undergraduate Programs
Path: Curricular Offerings > College of Computer Studies > Undergraduate Programs

Content:
Programs: BS Computer Science, BS Information System, BS Information Technology.
""".strip()

    messages = build_groq_messages(
        question="What programs are offered by the university?",
        context=context,
        broad_mode=True,
    )
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]

    assert "Broad/list-style or collection question mode" in system_prompt
    assert "grouped by category, college, office, service area, or source section" in system_prompt
    assert "College Name, then bullet the programs under that college" in system_prompt
    assert "Deduplicate repeated items" in system_prompt
    assert "This is a broad/list-style question" in user_prompt
    assert "preserve each College heading and list only its programs underneath" in user_prompt
    assert "avoid inventing items not present in context" in user_prompt
