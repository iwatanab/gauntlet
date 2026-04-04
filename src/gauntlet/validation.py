"""validation.py — Input guard and injection detection."""
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

    if not req.claim.strip():
        errors.append("claim must not be empty")
    elif len(req.claim) > 2000:
        errors.append(f"claim length {len(req.claim)} exceeds 2000 characters")

    for pat in _INJECTIONS:
        if pat.search(req.claim):
            errors.append("claim rejected: potential prompt injection detected")
            break

    if not req.domain_standard.strip():
        errors.append("domain_standard must not be empty")
    elif len(req.domain_standard) > 1000:
        errors.append("domain_standard exceeds 1000 characters")

    if req.grounds:
        for i, g in enumerate(req.grounds):
            if not (0.0 <= g.probative_weight <= 1.0):
                errors.append(f"grounds[{i}].probative_weight out of range [0.0, 1.0]")

    if errors:
        raise ValidationError(errors)
