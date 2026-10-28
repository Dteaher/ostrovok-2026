import asyncio

from app.agent import presentation
from app.evidence import facts_for
from tests.test_request_latency import online, ready


def test_fast_narration_schema_has_only_bounded_existing_fact_ids(monkeypatch):
    from app.agent import evidence_selection_schema
    state = ready()
    facts = facts_for(state)
    schema = evidence_selection_schema(facts)
    assert schema["required"] == ["fact_ids"]
    assert schema["additionalProperties"] is False
    field = schema["properties"]["fact_ids"]
    assert field["maxItems"] == 6 and field["minItems"] == 1
    assert set(field["items"]["enum"]) == {fact["id"] for fact in facts}


def test_fast_selection_keeps_backend_title_and_uses_validated_model_facts(monkeypatch):
    online(monkeypatch)
    monkeypatch.setenv("LLM_STRUCTURED_OUTPUT", "1")
    async def select(messages, **kwargs):
        assert kwargs["output_schema"]["properties"]["fact_ids"]["maxItems"] == 6
        return {"fact_ids": ["comparison_price", "comparison_beach"]}
    monkeypatch.setattr("app.agent.model_json", select)
    result = asyncio.run(presentation(ready(), "Сравни первый и второй", "compare", defer=False))
    assert result["mode"] == "llm"
    assert result["title"] == "Сравнение вариантов"
    assert "comparison_price" in {fact["id"] for fact in result["facts"]}


def test_invalid_fast_selection_is_rejected_without_truncation(monkeypatch):
    online(monkeypatch)
    monkeypatch.setenv("LLM_STRUCTURED_OUTPUT", "1")
    async def invalid(*args, **kwargs):
        return {"fact_ids": ["ranking"] * 9}
    monkeypatch.setattr("app.agent.model_json", invalid)
    result = asyncio.run(presentation(ready(), "Объясни", "explain", defer=False))
    assert result["mode"] == "local" and result["notice"]


def test_comparison_by_criteria_uses_current_pair_without_asking_for_numbers():
    from app.agent import handle_turn
    result = asyncio.run(handle_turn(ready(), "Сравни варианты по цене и расстоянию до моря"))
    assert result["agent"]["tool"] == "compare"
    assert result["agent"]["offer_indices"] == [1, 2]
