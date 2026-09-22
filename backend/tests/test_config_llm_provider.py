"""Tests for the provider-agnostic LLM endpoint settings in app.config.

The "groq_" setting names are historical; llm_base_url/llm_extra_headers_json
let the same code call any OpenAI-compatible chat-completions endpoint (e.g.
GitHub Models), which matters because Groq blocks requests from cloud/
datacenter IPs (Azure, AWS, GCP) at Cloudflare's edge.
"""

from unittest.mock import patch

from app.config import Settings, llm_extra_headers, settings


def test_llm_extra_headers_defaults_to_empty_dict():
    with patch.object(settings, "llm_extra_headers_json", None):
        assert llm_extra_headers() == {}


def test_llm_extra_headers_parses_json_object():
    with patch.object(
        settings,
        "llm_extra_headers_json",
        '{"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}',
    ):
        assert llm_extra_headers() == {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }


def test_llm_extra_headers_ignores_malformed_json():
    with patch.object(settings, "llm_extra_headers_json", "{not valid json"):
        assert llm_extra_headers() == {}


def test_llm_extra_headers_ignores_non_object_json():
    with patch.object(settings, "llm_extra_headers_json", "[1, 2, 3]"):
        assert llm_extra_headers() == {}


def test_llm_base_url_field_default_is_groq_endpoint():
    """Checks the pydantic field default directly (a local .env can legitimately
    override the live settings.llm_base_url to a non-Groq provider)."""
    assert Settings.model_fields["llm_base_url"].default == "https://api.groq.com/openai/v1/chat/completions"


def test_citation_verifier_model_field_default_is_none():
    """Unset by default -- preserves today's behavior (verifier falls back
    to groq_model) until an operator explicitly opts in."""
    assert Settings.model_fields["citation_verifier_model"].default is None


def test_citation_verifier_model_env_var_override(monkeypatch):
    monkeypatch.setenv("ASKA_CITATION_VERIFIER_MODEL", "some-verifier-model")
    fresh_settings = Settings(_env_file=None)
    assert fresh_settings.citation_verifier_model == "some-verifier-model"


def test_citation_verifier_model_unset_when_env_var_absent(monkeypatch):
    monkeypatch.delenv("ASKA_CITATION_VERIFIER_MODEL", raising=False)
    fresh_settings = Settings(_env_file=None)
    assert fresh_settings.citation_verifier_model is None
