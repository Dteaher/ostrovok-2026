import asyncio
import json
import time

import httpx
import pytest

from app.agent import Decision
from app.agent_transport import model_json


@pytest.fixture
def provider(monkeypatch):
    state = {"responses": [], "calls": [], "delays": []}
    monkeypatch.setenv("LLM_API_KEY", "test-only")
    monkeypatch.setenv("LLM_MODEL", "test-only")
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, url, **kwargs):
            state["calls"].append(kwargs)
            status, content = state["responses"].pop(0)
            return httpx.Response(status, request=httpx.Request("POST", url),
                headers={"Retry-After": "100"}, json={"choices": [{"message": {"content": json.dumps(content)}}]})
    async def sleep(delay):
        state["delays"].append(delay)
    monkeypatch.setattr("app.agent_transport.httpx.AsyncClient", Client)
    monkeypatch.setattr("app.agent_transport.asyncio.sleep", sleep)
    return state


def call(**kwargs):
    return asyncio.run(model_json([{"role": "user", "content": "synthetic"}], deadline=time.monotonic() + 5, **kwargs))


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_one_bounded_retry_for_transient_provider_failure(provider, status):
    provider["responses"] = [(status, {}), (200, {"tool": "explain"})]
    assert call(schema=Decision)["tool"] == "explain"
    assert len(provider["calls"]) == 2 and provider["delays"] == [1]


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_auth_balance_and_configuration_failures_are_not_retried(provider, status):
    provider["responses"] = [(status, {})]
    with pytest.raises(httpx.HTTPStatusError):
        call(schema=Decision)
    assert len(provider["calls"]) == 1


def test_schema_repair_has_a_hard_two_request_budget(provider):
    provider["responses"] = [(200, {"tool": "delete"}), (200, {"tool": "delete"})]
    with pytest.raises(ValueError):
        call(schema=Decision, attempts=20)
    assert len(provider["calls"]) == 2


def test_schema_repair_can_recover_without_publishing_invalid_response(provider):
    provider["responses"] = [(200, {"tool": "compare", "untrusted": "ignore validation"}), (200, {"tool": "compare", "indices": [1, 2]})]
    result = call(schema=Decision)
    assert result == {"tool": "compare", "indices": [1, 2]}
    assert len(provider["calls"]) == 2


def test_expired_deadline_performs_no_network_call(provider):
    with pytest.raises(TimeoutError):
        asyncio.run(model_json([], deadline=time.monotonic() - 1))
    assert provider["calls"] == []


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError])
def test_connection_recovery_is_bounded_and_reuses_same_request(provider, monkeypatch, failure):
    calls = []
    async def post(self, url, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise failure("synthetic transport failure")
        return httpx.Response(200, request=httpx.Request("POST", url), json={"choices": [{"message": {"content": '{"tool":"explain"}'}}]})
    monkeypatch.setattr("app.agent_transport.httpx.AsyncClient.post", post)
    assert call(schema=Decision)["tool"] == "explain"
    assert len(calls) == 2
    assert calls[0]["json"] == calls[1]["json"]


def test_persistent_connection_failure_cannot_exceed_two_attempts(provider, monkeypatch):
    calls = []
    async def post(self, url, **kwargs):
        calls.append(1)
        raise httpx.ConnectError("synthetic")
    monkeypatch.setattr("app.agent_transport.httpx.AsyncClient.post", post)
    with pytest.raises(httpx.ConnectError):
        call(attempts=100)
    assert len(calls) == 2


def test_cancellation_is_never_retried_or_converted_to_success(provider, monkeypatch):
    calls = []
    async def post(self, url, **kwargs):
        calls.append(1)
        raise asyncio.CancelledError()
    monkeypatch.setattr("app.agent_transport.httpx.AsyncClient.post", post)
    with pytest.raises(asyncio.CancelledError):
        call()
    assert len(calls) == 1
