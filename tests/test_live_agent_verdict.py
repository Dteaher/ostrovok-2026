import pytest

from scripts.verify_live_agent import verdict


@pytest.mark.parametrize("parser,mode,local,read,quality,expected", [
    ("llm", "local", False, True, True, "fallback_or_partial"),
    ("llm", "local", False, False, True, "fallback_or_partial"),
    ("fallback", "llm", False, False, True, "fallback_or_partial"),
    ("llm", "llm", False, False, False, "fallback_or_partial"),
    ("llm", "llm", False, True, True, "llm"),
    ("llm", "llm", False, False, True, "llm"),
    ("llm", "local", True, False, True, "local_operation"),
])
def test_llm_verdict_requires_current_stage_and_correct_business_result(parser, mode, local, read, quality, expected):
    assert verdict(parser, {"mode": mode}, local=local, read=read, quality=quality) == expected
