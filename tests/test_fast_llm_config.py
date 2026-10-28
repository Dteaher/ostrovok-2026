import pytest

from app.llm_config import LLMConfig


def test_reasoning_is_explicit_and_does_not_change_provider_or_key(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://multiai.store/v1")
    monkeypatch.setenv("LLM_API_KEY", "unit-only-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "none")
    config = LLMConfig.from_env()
    assert config.request_body([])["reasoning_effort"] == "none"
    assert config.base_url == "https://multiai.store/v1"
    assert config.api_key == "unit-only-key"


def test_evidence_schema_constrains_array_length_and_allowed_ids(monkeypatch):
    monkeypatch.setenv("LLM_STRUCTURED_OUTPUT", "1")
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"fact_ids": {"type": "array", "minItems": 1, "maxItems": 6,
                  "items": {"type": "string", "enum": ["ranking", "comparison_price"]}}},
              "required": ["fact_ids"]}
    body = LLMConfig.from_env().request_body([], output_schema=schema, schema_name="evidence")
    assert body["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "evidence", "strict": True, "schema": schema}}


@pytest.mark.parametrize("value", ["unexpected", "0", "None"])
def test_invalid_reasoning_configuration_is_rejected(monkeypatch, value):
    monkeypatch.setenv("LLM_REASONING_EFFORT", value)
    with pytest.raises(ValueError, match="LLM_REASONING_EFFORT"):
        LLMConfig.from_env()


def test_unconfigured_adapter_keeps_json_object_compatibility(monkeypatch):
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("LLM_STRUCTURED_OUTPUT", raising=False)
    body = LLMConfig.from_env().request_body([])
    assert "reasoning_effort" not in body
    assert body["response_format"] == {"type": "json_object"}
