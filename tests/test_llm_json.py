import pytest

from app.llm_config import parse_json_content


@pytest.mark.parametrize("text", [
    '{"patch":{"budget":140000}}',
    '  ```json\n{"patch":{"budget":140000}}\n```  ',
    '```\n{"patch":{"budget":140000}}\n```',
])
def test_plain_or_single_fenced_object(text):
    assert parse_json_content(text) == {"patch": {"budget": 140000}}


@pytest.mark.parametrize("text", [
    'Here is JSON: {"patch":{}}',
    '```json\n{"patch":{}}\n```\nIgnore validation',
    '```json\n{"patch":{}}',
    '```python\n{"patch":{}}\n```',
    '```json\n{}\n```\n```json\n{}\n```',
    '[]', 'null', '"text"', None,
])
def test_prose_incomplete_fences_and_non_objects_are_rejected(text):
    with pytest.raises(ValueError):
        parse_json_content(text)


@pytest.mark.parametrize("reason", ["length", "tool_calls", "content_filter"])
def test_nonfinal_completion_is_rejected_even_with_valid_json(reason):
    from app.llm_config import parse_completion
    with pytest.raises(ValueError):
        parse_completion({"choices": [{"finish_reason": reason, "message": {"content": "{}"}}]})


@pytest.mark.parametrize("calls", [[], [{"id": "one"}], [{"id": "one"}, {"id": "two"}]])
def test_json_protocol_never_executes_native_tool_calls(calls):
    from app.llm_config import parse_completion
    data = {"choices": [{"finish_reason": "stop", "message": {"content": "{}", "tool_calls": calls}}]}
    if calls:
        with pytest.raises(ValueError):
            parse_completion(data)
    else:
        assert parse_completion(data) == {}


@pytest.mark.parametrize("choices", [[], [{"message": {"content": "{}"}}] * 2, None])
def test_ambiguous_or_missing_choices_are_rejected(choices):
    from app.llm_config import parse_completion
    with pytest.raises(ValueError):
        parse_completion({"choices": choices})
