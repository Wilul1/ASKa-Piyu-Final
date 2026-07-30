"""Tests for the provider-agnostic LLM endpoint settings in app.config.

The "groq_" setting names are historical; llm_base_url/llm_extra_headers_json
let the same code call any OpenAI-compatible chat-completions endpoint (e.g.
GitHub Models), which matters because Groq blocks requests from cloud/
datacenter IPs (Azure, AWS, GCP) at Cloudflare's edge.
"""

from unittest.mock import patch

from app.config import llm_extra_headers, settings


def test_llm_extra_headers_defaults_to_empty_dict():
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


def test_llm_base_url_defaults_to_groq_endpoint():
    assert settings.llm_base_url == "https://api.groq.com/openai/v1/chat/completions"
