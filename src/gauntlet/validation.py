"""validation.py - Input guard for the single-string public API."""
from __future__ import annotations

import re

from gauntlet.models import EvaluateRequest

_INJECTIONS = [re.compile(p, re.IGNORECASE) for p in [
    r"ignore\s+(previous|above|all|prior)\s+instructions?",
    r"disregard\s+your\s+(instructions?|system\s+prompt|role)",
    r"you\s+are\s+now\s+(?:a\s+)?different",
    r"new\s+(?:instruction|prompt|system\s+prompt|role):",
    r"forget\s+(?:\w+\s+){0,4}instructions?",
    r"jailbreak",
    r"developer\s+mode",
    r"override\s+(?:your|all)\s+(?:safety|instructions?)",
]]


class ValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_request(req: EvaluateRequest) -> None:
    errors: list[str] = []
    text = req.input

    if not text.strip():
        errors.append("input must not be empty")
    elif len(text) > 4000:
        errors.append(f"input length {len(text)} exceeds 4000 characters")

    for pat in _INJECTIONS:
        if pat.search(text):
            errors.append("input rejected: potential prompt injection detected")
            break

    if errors:
        raise ValidationError(errors)
