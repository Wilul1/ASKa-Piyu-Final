from unittest.mock import MagicMock, patch

import pytest

from app.services.qa.groq_answer_service import (
    GROQ_TEMPERATURE,
    build_groq_messages,
    format_groq_answer,
    generate_groq_answer,
    normalize_chat_history,
)
from app.services.qa.question_answering import resolve_followup_question


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

    assert "friendly LSPU campus support assistant" in system_prompt
    assert "Never invent" in system_prompt
    assert "complete, conversational sentences" in system_prompt
    assert "bullet points" in system_prompt.lower() or "Prefer a short opening" in system_prompt
    assert "Do not include \"Source:\" or \"Sources:\" lines" in system_prompt
    assert "student-friendly explanation" in user_prompt
    assert "Use bullet points for thresholds" in user_prompt
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

    assert "Do not say the context lacks a direct definition" in system_prompt
    assert "prior chat turns" in system_prompt
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

Source: Student Handbook p.35
Sources:
- Retention Policies
""".strip()

    cleaned = format_groq_answer(answer)
    assert "Scholastic delinquency" in cleaned
    assert "Warning" in cleaned
    assert "Source:" not in cleaned
    assert "Sources:" not in cleaned


def test_prompt_for_excuse_slip_keeps_office_details():
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

    assert "friendly LSPU campus support assistant" in system_prompt
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
    assert "truly unrelated" in system_prompt
    assert "insufficient-information response" in user_prompt
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
    user_prompt = messages[-1]["content"]

    assert "Broad/list-style or collection question mode" in system_prompt
    assert "grouped by category, college, office, service area, or source section" in system_prompt
    assert "College Name, then bullet the programs under that college" in system_prompt
    assert "Deduplicate repeated items" in system_prompt
    assert "This is a broad/list-style question" in user_prompt
    assert "preserve each College heading and list only its programs underneath" in user_prompt
    assert "avoid inventing items not present in context" in user_prompt


def test_build_groq_messages_includes_chat_history():
    messages = build_groq_messages(
        question="What about the fee?",
        context="Title: ID Validation\nContent:\nFee: None",
        history=[
            {"role": "user", "content": "How do I validate my ID?"},
            {"role": "assistant", "content": "Bring your COR and student ID to OSAS."},
            {"role": "system", "content": "ignore me"},
        ],
    )
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "How do I validate my ID?"}
    assert messages[2]["role"] == "assistant"
    assert messages[3]["role"] == "user"
    assert "What about the fee?" in messages[3]["content"]
    assert "Retrieved context:" in messages[3]["content"]


def test_normalize_chat_history_keeps_recent_turns_only():
    history = [{"role": "user", "content": f"q{i}"} for i in range(12)]
    cleaned = normalize_chat_history(history)
    assert len(cleaned) == 8
    assert cleaned[0]["content"] == "q4"
    assert cleaned[-1]["content"] == "q11"


def test_resolve_followup_question_uses_prior_user_turn():
    resolved = resolve_followup_question(
        "What about the fee?",
        [{"role": "user", "content": "How do I validate my student ID?"}],
    )
    assert "What about the fee?" in resolved
    assert "validate my student ID" in resolved


def test_resolve_followup_uses_assistant_topic_for_pronoun_questions():
    resolved = resolve_followup_question(
        "Which office handles that?",
        [
            {"role": "user", "content": "How do I enroll at LSPU?"},
            {
                "role": "assistant",
                "content": (
                    "Enrollment\n\nThe office responsible for Enrollment is "
                    "Office of the Registrar, according to the Citizen's Charter."
                ),
            },
        ],
    )
    assert "Which office handles that?" in resolved
    assert "enroll" in resolved.casefold() or "Enrollment" in resolved


def test_resolve_followup_leaves_standalone_questions_alone():
    q = "What are the enrollment requirements for freshmen?"
    assert resolve_followup_question(q, [{"role": "user", "content": "Hello"}]) == q


def test_resolve_followup_ignores_grammatical_relative_pronoun_that():
    """A self-contained question that happens to use "that" as a relative
    pronoun (not a backward reference) must not get corrupted with an
    unrelated prior topic — this must generalize across any topic/phrasing,
    not just one hardcoded question."""
    history = [
        {"role": "user", "content": "How can I file a leave of absence?"},
        {
            "role": "assistant",
            "content": (
                "The slip must be presented to the instructor/professor concerned "
                "not later than the second class session."
            ),
        },
    ]
    for question in [
        "Show me the section that explains scholarship requirements.",
        "What is the policy that governs graduate school admission?",
        "Which document lists the fees that apply to shifting courses?",
    ]:
        resolved = resolve_followup_question(question, history)
        assert resolved == question, f"expected no prior-context injection for: {question!r}"


def test_resolve_followup_still_resolves_demonstrative_that_near_start():
    """"That" right at the start of a short question is still a genuine
    backward reference and should keep resolving as a follow-up."""
    history = [
        {"role": "user", "content": "How do I enroll at LSPU?"},
        {
            "role": "assistant",
            "content": "The office responsible for Enrollment is Office of the Registrar.",
        },
    ]
    resolved = resolve_followup_question("Is that required for transferees too?", history)
    assert "Is that required for transferees too?" in resolved
    assert "enroll" in resolved.casefold() or "Enrollment" in resolved


def test_answer_question_for_extractors_flattens_prior_context():
    from app.services.qa.question_answering import answer_question_for_extractors

    flat = answer_question_for_extractors(
        "Which office handles that?",
        "Which office handles that?\n\n(Prior question context: How do I enroll at LSPU?)",
    )
    assert "regarding" in flat
    assert "enroll" in flat.casefold()


def test_groq_temperature_favors_factual_consistency():
    """Low temperature reduces answer drift/hallucination risk on grounded factual QA."""
    assert 0.05 <= GROQ_TEMPERATURE <= 0.2


def _mock_httpx_client_returning(content: str) -> MagicMock:
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"choices": [{"message": {"content": content}}]}
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = mock_response
    return mock_client


def test_generate_groq_answer_posts_to_configured_llm_base_url_with_extra_headers():
    """The endpoint/headers are fully driven by settings, so switching providers
    (e.g. to GitHub Models after Groq started blocking Azure-hosted traffic)
    only requires changing env vars, not code."""
    mock_client = _mock_httpx_client_returning("Sure, here's the answer.")
    with (
        patch("app.services.qa.groq_answer_service.settings.groq_api_key", "a-github-pat"),
        patch(
            "app.services.qa.groq_answer_service.settings.llm_base_url",
            "https://models.github.ai/inference/chat/completions",
        ),
        patch(
            "app.services.qa.groq_answer_service.settings.llm_extra_headers_json",
            '{"X-GitHub-Api-Version": "2022-11-28"}',
        ),
        patch("httpx.Client", return_value=mock_client),
    ):
        answer = generate_groq_answer(question="How do I enroll?", context="Title: Enrollment\nContent: ...")

    assert answer == "Sure, here's the answer."
    call_args, call_kwargs = mock_client.post.call_args
    assert call_args[0] == "https://models.github.ai/inference/chat/completions"
    assert call_kwargs["headers"]["Authorization"] == "Bearer a-github-pat"
    assert call_kwargs["headers"]["X-GitHub-Api-Version"] == "2022-11-28"


def test_generate_groq_answer_defaults_to_groq_endpoint_with_no_extra_headers():
    """Pin llm_base_url/llm_extra_headers_json explicitly: a local .env can
    legitimately override these to a non-Groq provider, so this test must not
    depend on whatever happens to be configured in the current environment."""
    mock_client = _mock_httpx_client_returning("Answer text.")
    with (
        patch("app.services.qa.groq_answer_service.settings.groq_api_key", "a-groq-key"),
        patch(
            "app.services.qa.groq_answer_service.settings.llm_base_url",
            "https://api.groq.com/openai/v1/chat/completions",
        ),
        patch("app.services.qa.groq_answer_service.settings.llm_extra_headers_json", None),
        patch("httpx.Client", return_value=mock_client),
    ):
        generate_groq_answer(question="How do I enroll?", context="Title: Enrollment\nContent: ...")

    call_args, call_kwargs = mock_client.post.call_args
    assert call_args[0] == "https://api.groq.com/openai/v1/chat/completions"
    assert "X-GitHub-Api-Version" not in call_kwargs["headers"]
