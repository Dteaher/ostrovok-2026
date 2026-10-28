import asyncio
import time
from copy import deepcopy
from datetime import timedelta

import pytest

from app.parser import ParsedIntent
from app.service import compile_state, local_today, new_state, process_message


def ready():
    return compile_state(new_state(), ParsedIntent(recognized=True, patch={
        "destination": "Сочи", "check_in": (local_today() + timedelta(days=55)).isoformat(),
        "budget": 500000,
    }))


def online(monkeypatch):
    monkeypatch.setenv("AGENT_ENABLED", "1")
    monkeypatch.setenv("LLM_MODEL", "fake")
    monkeypatch.setenv("LLM_API_KEY", "fake")


def test_latency_classes_have_exact_user_limits():
    from app.request_budget import request_seconds
    assert request_seconds(ready(), "Объясни выбор") == 10
    assert request_seconds(ready(), "Теперь бюджет 150 тысяч") == 10
    assert request_seconds(ready(), "Перенеси даты и сократи поездку, бюджет 150 тысяч") == 15
    assert request_seconds(ready(), "Предложи альтернативы") == 20
    assert request_seconds(ready(), "Полностью пересобери поездку") == 15
    assert request_seconds(ready(), "В мае, бюджет 200 тысяч") == 15


def test_search_results_do_not_wait_for_optional_second_llm(monkeypatch):
    online(monkeypatch)
    async def extract(*args):
        return ParsedIntent(recognized=True, patch={"budget": 300000}, mode="llm")
    async def forbidden(*args, **kwargs):
        pytest.fail("Optional narration blocked initial search results")
    monkeypatch.setattr("app.service.extract_intent", extract)
    monkeypatch.setattr("app.agent.model_json", forbidden)
    result = asyncio.run(process_message(ready(), "бюджэт 300 тыщ"))
    assert result["requirements"]["budget"] == 300000
    assert result["plans"] and result["agent"]["facts"]
    assert result["agent"]["mode"] == "local"
    assert result["agent"]["explanation_status"] == "pending"
    assert result["_explanation"]["deadline"] - time.monotonic() <= 10


def test_entire_request_timeout_keeps_previous_verified_results(monkeypatch):
    online(monkeypatch)
    monkeypatch.setattr("app.service.request_seconds", lambda *args: .04)
    async def slow(*args):
        await asyncio.sleep(1)
    monkeypatch.setattr("app.service.extract_intent", slow)
    state = ready()
    before = deepcopy(state)
    started = time.monotonic()
    result = asyncio.run(process_message(state, "неформальный запрос"))
    assert time.monotonic() - started < .3
    assert result["requirements"] == before["requirements"]
    assert result["plans"] == before["plans"]
    assert result["agent"]["mode"] == "local"
    assert result["response_timing"]["timed_out"] is True
    assert "время" in result["assistant_message"].lower()
    assert state == before


def test_search_cannot_block_event_loop_or_publish_after_deadline(monkeypatch):
    online(monkeypatch)
    monkeypatch.setattr("app.service.request_seconds", lambda *args: .04)
    async def extract(*args):
        return ParsedIntent(recognized=True, patch={"budget": 123000}, mode="llm")
    original = compile_state
    def slow(*args, **kwargs):
        time.sleep(.15)
        return original(*args, **kwargs)
    monkeypatch.setattr("app.service.extract_intent", extract)
    monkeypatch.setattr("app.service.compile_state", slow)
    async def scenario():
        state = ready()
        before = deepcopy(state)
        started = time.monotonic()
        result = await process_message(state, "неформальное изменение бюджета")
        elapsed = time.monotonic() - started
        await asyncio.sleep(.2)
        assert state == before
        assert result["requirements"] == before["requirements"]
        assert elapsed < .12
    asyncio.run(scenario())


def test_initial_search_timeout_still_shows_verified_local_results(monkeypatch):
    online(monkeypatch)
    monkeypatch.setattr("app.service.request_seconds", lambda *args: .06)
    async def slow(*args):
        await asyncio.sleep(1)
    monkeypatch.setattr("app.service.extract_intent", slow)
    message = f"В Сочи с {(local_today() + timedelta(days=55)).isoformat()} на 7 ночей, бюджет 300 тысяч"
    result = asyncio.run(process_message(new_state(), message))
    assert result["plans"]
    assert result["requirements"]["budget"] == 300000
    assert result["parser_mode"] == "fallback"
    assert result["agent"]["mode"] == "local"
    assert result["response_timing"]["timed_out"] is True


def test_provider_cleanup_cannot_extend_the_user_deadline(monkeypatch):
    online(monkeypatch)
    monkeypatch.setattr("app.service.request_seconds", lambda *args: .04)
    async def slow(*args):
        try:
            await asyncio.sleep(1)
        finally:
            await asyncio.sleep(.2)
    monkeypatch.setattr("app.service.extract_intent", slow)
    async def scenario():
        state = ready()
        started = time.monotonic()
        result = await process_message(state, "неформальный запрос")
        elapsed = time.monotonic() - started
        assert result["response_timing"]["timed_out"]
        await asyncio.sleep(.25)
        assert elapsed < .12
    asyncio.run(scenario())


def test_alternative_planning_timeout_keeps_verified_alternatives(monkeypatch):
    from app.negotiation import explore

    online(monkeypatch)
    state = ready()
    # Isolate the provider deadline from OS scheduling of three catalogue
    # searches. Slow catalogue rollback is covered separately above. These
    # proposals are real verified results for this unchanged trip, not mocks.
    verified = explore(state)
    monkeypatch.setattr("app.negotiation.explore", lambda snapshot: deepcopy(verified))
    monkeypatch.setattr("app.service.request_seconds", lambda *args: .3)
    model_started = []
    async def slow(*args, **kwargs):
        model_started.append(True)
        await asyncio.sleep(1)
    monkeypatch.setattr("app.agent.model_json", slow)
    started = time.monotonic()
    result = asyncio.run(process_message(state, "Предложи альтернативы"))
    assert time.monotonic() - started < .55
    assert model_started
    assert result["response_timing"]["timed_out"] is True
    assert result["agent"]["tool"] == "alternatives"
    assert result["agent"]["facts"]
    assert result["agent"]["mode"] == "local"
    assert result["order"] is None
