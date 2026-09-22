"""Tests for application-wide logging configuration (app.main's
logging.basicConfig call, added to fix a confirmed production gap).

CRITICAL: these tests deliberately do NOT rely on pytest's caplog fixture.
caplog installs its own handler during each test, which would mask exactly
the gap this fix addresses -- a fresh production process, with no pytest
machinery at all, previously dropped every INFO-level application log
silently (see backend/benchmarks/async_shadow_phase2_production_staging.json
for how this was discovered live). Every test here launches a brand-new
Python subprocess that imports app.main exactly as uvicorn would, and
inspects that subprocess's own stdout/stderr.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_isolated(code: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    """Runs `code` in a brand-new Python subprocess, cwd=backend/, with no
    pytest machinery loaded in that process at all."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_isolated_process_info_log_reaches_output_after_importing_app_main():
    """The core regression test for the discovered production gap: import
    app.main (which now calls logging.basicConfig) in a FRESH subprocess,
    then log one INFO message -- it must appear in the subprocess output."""
    code = (
        "import app.main\n"
        "import logging\n"
        "logging.getLogger('app.services.qa.citation_verification_jobs').info('ISOLATED_INFO_MARKER_9f3a')\n"
    )
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "ISOLATED_INFO_MARKER_9f3a" in combined


def test_other_app_loggers_stay_suppressed_at_info_this_is_scoped_not_global():
    """The key safety property of this fix's design: enabling INFO is
    scoped to app.services.qa.citation_verification_jobs only (the one
    reviewed-safe event), NOT a blanket root-level INFO enablement -- an
    audit found other existing INFO log sites (e.g.
    question_answering.py's conversational-fallback trigger, which can
    embed a raw exception string) that are not reviewed as production-log
    safe. Their INFO calls must remain suppressed exactly as before this
    fix, at the root's WARNING default."""
    code = (
        "import app.main\n"
        "import logging\n"
        "logging.getLogger('app.services.qa.question_answering').info('UNSCOPED_INFO_MARKER_should_not_appear')\n"
        "logging.getLogger('app.services.qa.question_answering').warning('UNSCOPED_WARNING_MARKER_should_appear')\n"
    )
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "UNSCOPED_INFO_MARKER_should_not_appear" not in combined
    assert "UNSCOPED_WARNING_MARKER_should_appear" in combined


def test_isolated_process_warning_still_reaches_output():
    code = (
        "import app.main\n"
        "import logging\n"
        "logging.getLogger('app.services.qa.citation_verification_jobs').warning('ISOLATED_WARNING_MARKER_7e21')\n"
    )
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "ISOLATED_WARNING_MARKER_7e21" in combined


def test_isolated_process_error_still_reaches_output():
    code = (
        "import app.main\n"
        "import logging\n"
        "logging.getLogger('app.services.qa.citation_verification_jobs').error('ISOLATED_ERROR_MARKER_1c88')\n"
    )
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "ISOLATED_ERROR_MARKER_1c88" in combined


def test_isolated_process_one_info_call_produces_exactly_one_log_line():
    """No duplication: a single logger.info() call must produce exactly
    one line containing the marker -- not zero, not two."""
    code = (
        "import app.main\n"
        "import logging\n"
        "logging.getLogger('app.services.qa.citation_verification_jobs').info('ISOLATED_DUP_CHECK_MARKER_5b60')\n"
    )
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    occurrences = combined.count("ISOLATED_DUP_CHECK_MARKER_5b60")
    assert occurrences == 1, f"expected exactly 1 occurrence, got {occurrences}: {combined!r}"


def test_basicconfig_is_idempotent_across_repeated_calls_same_process():
    """Calling logging.basicConfig() more than once in the same process
    (as could happen with repeated module-import attempts) must not add a
    second handler to the root logger -- proves no handler multiplication."""
    code = (
        "import logging\n"
        "import app.main\n"
        "root = logging.getLogger()\n"
        "before = len(root.handlers)\n"
        "logging.basicConfig(level=logging.INFO)\n"
        "logging.basicConfig(level=logging.INFO)\n"
        "after = len(root.handlers)\n"
        "print(f'HANDLER_COUNT_BEFORE={before}')\n"
        "print(f'HANDLER_COUNT_AFTER={after}')\n"
    )
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr
    assert "HANDLER_COUNT_BEFORE=1" in result.stdout
    assert "HANDLER_COUNT_AFTER=1" in result.stdout


def test_uvicorn_loggers_unaffected_by_app_main_logging_config():
    """Confirm importing app.main does not touch uvicorn's own logger
    objects at all -- this fix only configures the root logger, which
    uvicorn's separately-configured, propagate=False loggers never use."""
    code = (
        "import app.main\n"
        "import logging\n"
        "for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):\n"
        "    lg = logging.getLogger(name)\n"
        "    print(f'{name}:handlers={len(lg.handlers)}:propagate={lg.propagate}')\n"
    )
    result = _run_isolated(code)
    assert result.returncode == 0, result.stderr
    # Merely importing app.main (without uvicorn's own CLI-driven
    # configure_logging() step, which runs separately in real deployment)
    # must leave these loggers at their untouched defaults: no handlers of
    # their own added by US, and default propagate=True (uvicorn's own CLI
    # step is what later sets propagate=False and attaches handlers -- this
    # fix must not preempt or conflict with that).
    for line in result.stdout.splitlines():
        if line.startswith("uvicorn"):
            assert "handlers=0" in line, f"app.main unexpectedly added a handler: {line}"


def test_citation_verification_async_completed_event_visible_in_isolated_process():
    """The actual target of this whole fix: exercise the REAL async
    orchestration path (create_job -> run_verification_job -> the real
    verify_citations(), transport mocked below it) inside a FRESH
    subprocess that never had pytest's caplog installed, and prove the
    structured event reaches output and remains valid, parseable JSON."""
    code = r'''
import json
import app.main
from unittest.mock import MagicMock, patch
from app.services.qa import citation_verification_jobs as jobs
from app.services.qa.citation_verification import CandidateEvidence

candidates = [CandidateEvidence(citation_id="tor::1", title="Transcript of Records", source_section="Sec. 1", source_filename="doc.pdf", text="Fee: P75 per page.")]
answer = "The fee is P75 per page."

mock_response = MagicMock()
mock_response.raise_for_status.return_value = None
mock_response.json.return_value = {"choices": [{"message": {"content": json.dumps({"claims": [{"claim_id": "c1", "supporting_citation_ids": ["S1"]}]})}}]}
mock_client = MagicMock()
mock_client.__enter__.return_value = mock_client
mock_client.__exit__.return_value = False
mock_client.post.return_value = mock_response

vid = jobs.create_job(answer=answer, candidates=candidates, mode="async_shadow", v1_citation_ids=["tor::1"])
with patch("httpx.Client", return_value=mock_client), patch.multiple(
    "app.services.qa.citation_verification.settings",
    groq_api_key="test-key",
    llm_base_url="https://openrouter.ai/api/v1/chat/completions",
    groq_model="test-model",
    groq_timeout_seconds=5.0,
):
    jobs.run_verification_job(vid)
'''
    result = _run_isolated(code, timeout=30.0)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    lines = [
        line for line in combined.splitlines()
        if "citation_verification_async_completed" in line and "{" in line
    ]
    assert len(lines) == 1, f"expected exactly one event line, got {len(lines)}: {combined!r}"
    line = lines[0]
    payload = json.loads(line[line.index("{"):])
    assert payload["mode"] == "async_shadow"
    assert payload["status"] == "verified"
    assert payload["v1_citation_ids"] == ["tor::1"]
    assert payload["v2_citation_ids"] == ["tor::1"]
    assert isinstance(payload["duration_ms"], (int, float))
    assert payload["failure_category"] is None
    # No sensitive content anywhere in the subprocess's combined output.
    assert "Fee: P75 per page." not in combined
    assert "The fee is P75 per page." not in combined
    assert "test-key" not in combined
