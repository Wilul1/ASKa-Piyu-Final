"""Reject empty or unreadable ticket subject/description text."""

from __future__ import annotations

import re

_ALPHA_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
_CONSONANT_RUN_RE = re.compile(r"[bcdfghjklmnpqrstvwxyz]{6,}", re.IGNORECASE)
_VOWELS = set("aeiouáéíóúäëïöüàèìòùâêîôû")


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip()


def _letter_counts(text: str) -> tuple[int, int]:
    letters = [ch for ch in text.lower() if ch.isalpha()]
    vowels = sum(1 for ch in letters if ch in _VOWELS)
    return len(letters), vowels


def _alpha_words(text: str) -> list[str]:
    return _ALPHA_WORD_RE.findall(text)


def validate_ticket_subject(value: str) -> str:
    cleaned = _normalize(value)
    if len(cleaned) < 8:
        raise ValueError(
            "Subject must be at least 8 characters. Summarize what you need help with."
        )
    words = _alpha_words(cleaned)
    if len(words) < 2:
        raise ValueError(
            "Subject needs at least two real words so the office can understand it."
        )
    _reject_unreadable(cleaned, words, field="Subject", min_letters=6)
    return cleaned


def validate_ticket_description(value: str) -> str:
    cleaned = _normalize(value)
    if len(cleaned) < 20:
        raise ValueError(
            "Description must be at least 20 characters. Add dates, steps tried, or what you need."
        )
    words = _alpha_words(cleaned)
    if len(words) < 4:
        raise ValueError(
            "Description needs at least four real words so the office has enough context."
        )
    _reject_unreadable(cleaned, words, field="Description", min_letters=10)
    return cleaned


def _reject_unreadable(
    cleaned: str,
    words: list[str],
    *,
    field: str,
    min_letters: int,
) -> None:
    letters, vowels = _letter_counts(cleaned)
    if letters < min_letters:
        raise ValueError(
            f"{field} looks incomplete. Please write a clearer message in plain language."
        )
    vowel_ratio = vowels / letters
    if vowel_ratio < 0.18 or vowel_ratio > 0.72:
        raise ValueError(
            f"{field} does not look like readable text. Please rewrite it in plain language."
        )
    for word in words:
        if len(word) < 10:
            continue
        word_letters, word_vowels = _letter_counts(word)
        if word_vowels / max(word_letters, 1) < 0.2:
            raise ValueError(
                f"{field} contains unreadable text. Please rewrite it in plain language."
            )
    if _CONSONANT_RUN_RE.search(cleaned):
        raise ValueError(
            f"{field} contains unreadable text. Please rewrite it in plain language."
        )
    lowered = cleaned.lower()
    for ch in set(lowered):
        if ch.isalpha() and (ch * 5) in lowered:
            raise ValueError(
                f"{field} contains unreadable text. Please rewrite it in plain language."
            )
