"""
Windows console fixes for ML libraries (EasyOCR, tqdm, PyTorch).

Those libraries print progress bars with block characters (U+2588) that
cp1252 consoles cannot encode, causing:
  'charmap' codec can't encode character '\\u2588' ...
"""

from __future__ import annotations

import contextlib
import io
import os
import sys


def configure_console_encoding() -> None:
    """Call once at process start (before EasyOCR / torch load)."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("TQDM_DISABLE", "1")

    if sys.platform != "win32":
        return

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


@contextlib.contextmanager
def suppress_ml_progress_output():
    """
    Suppress tqdm / model-download progress on Windows during OCR.

    Even with UTF-8 mode, some libraries still break in embedded terminals;
    discarding their stdout/stderr during init is safe for API workers.
    """
    if sys.platform != "win32":
        yield
        return

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        yield
