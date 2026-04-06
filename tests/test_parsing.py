"""test_parsing.py - Preflight parsing helpers."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from gauntlet.models import TokenUsage
from gauntlet.parsing import InputError, ParsedInput, check_and_parse, grounds_from_parsed


class StubClient:
    def __init__(self, result: ParsedInput):
        self.result = result

    async def complete_structured(self, **_kwargs):
        return self.result, [], TokenUsage(input_tokens=10, output_tokens=3)


@pytest.mark.asyncio
async def test_check_and_parse_rejects_multiple_claims():
    client = StubClient(ParsedInput(
        valid=True,
        atomic=False,
        claims=["Enable SSO.", "Require hardware keys."],
    ))
    with pytest.raises(InputError) as exc:
        await check_and_parse(
            "Enable SSO and require hardware keys.",
            SimpleNamespace(model="test", max_tokens=100, retries=0),
            client,
        )
    assert exc.value.code == "multiple_claims"
    assert exc.value.claims == ["Enable SSO.", "Require hardware keys."]


def test_grounds_from_parsed_preserves_verbatim_strings():
    grounds = grounds_from_parsed([
        "Troponin T+0: 6 ng/L from the hospital lab report",
        "Serial ECG unchanged compared with prior tracing",
    ])
    assert [ground.content for ground in grounds] == [
        "Troponin T+0: 6 ng/L from the hospital lab report",
        "Serial ECG unchanged compared with prior tracing",
    ]
    assert all(ground.user_provided for ground in grounds)
    assert all(ground.source == "user-provided" for ground in grounds)
