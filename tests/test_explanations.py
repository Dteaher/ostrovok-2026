import asyncio
import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_request_latency import online, ready


def pending(state, deadline=None):
    state["_explanation"] = {"message": "Объясни выбор", "tool": "explain", "indices": None,
                             "deadline": deadline or time.monotonic() + 1}
    state["agent"]["explanation_status"] = "pending"
    return state


def test_expired_explanation_never_calls_provider(monkeypatch):
    from app.explanations import ExplanationJobs
    online(monkeypatch)
    async def forbidden(*args, **kwargs):
        pytest.fail("Expired explanation called provider")
    monkeypatch.setattr("app.agent.model_json", forbidden)
    async def scenario():
        jobs = ExplanationJobs()
        state = pending(ready(), time.monotonic() - 1)
        jobs.start(state)
        result = await jobs.get(state)
        assert result["mode"] == "local"
        assert result["explanation_status"] == "timeout"
        await jobs.close()
    asyncio.run(scenario())


def test_explanation_deduplicates_and_does_not_mutate_live_trip(monkeypatch):
    from app.explanations import ExplanationJobs
    online(monkeypatch)
    calls = []
    async def model(*args, **kwargs):
        calls.append(1)
        await asyncio.sleep(.01)
        return {"title": "Почему эти варианты", "fact_ids": ["ranking"], "ask_priority": False}
    monkeypatch.setattr("app.agent.model_json", model)
    async def scenario():
        jobs = ExplanationJobs()
        state = pending(ready())
        before = deepcopy(state)
        jobs.start(state)
        jobs.start(state)
        a, b = await asyncio.gather(jobs.get(state), jobs.get(state))
        assert a == b and a["mode"] == "llm"
        assert calls == [1]
        assert state == before
        await jobs.close()
    asyncio.run(scenario())


def test_new_revision_cancels_old_explanation(monkeypatch):
    from app.explanations import ExplanationJobs
    online(monkeypatch)
    cancelled = []
    entered = asyncio.Event()
    finished = asyncio.Event()
    async def model(*args, **kwargs):
        try:
            entered.set()
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)
            finished.set()
    monkeypatch.setattr("app.agent.model_json", model)
    async def scenario():
        jobs = ExplanationJobs()
        state = pending(ready())
        jobs.start(state)
        await asyncio.wait_for(entered.wait(), 1)
        changed = deepcopy(state)
        changed["revision"] += 1
        changed.pop("_explanation")
        jobs.start(changed)
        await asyncio.wait_for(finished.wait(), 1)
        assert cancelled == [True]
        await jobs.close()
    asyncio.run(scenario())


def test_cancelled_job_returns_local_result_to_existing_waiter(monkeypatch):
    from app.explanations import ExplanationJobs
    online(monkeypatch)
    entered = asyncio.Event()
    async def model(*args, **kwargs):
        entered.set()
        await asyncio.sleep(1)
    monkeypatch.setattr("app.agent.model_json", model)
    async def scenario():
        jobs = ExplanationJobs()
        state = pending(ready())
        jobs.start(state)
        waiter = asyncio.create_task(jobs.get(state))
        await asyncio.wait_for(entered.wait(), 1)
        changed = deepcopy(state)
        changed["revision"] += 1
        changed.pop("_explanation")
        jobs.start(changed)
        result = await waiter
        assert result["mode"] == "local"
        await jobs.close()
    asyncio.run(scenario())


def test_explanation_endpoint_never_overwrites_trip_revision(tmp_path, monkeypatch):
    online(monkeypatch)
    async def model(*args, **kwargs):
        return {"title": "Сравнение вариантов", "fact_ids": ["comparison_price"], "ask_priority": False}
    monkeypatch.setattr("app.agent.model_json", model)
    with TestClient(create_app("sqlite:///" + str(tmp_path / "trip.db"))) as client:
        state = ready()
        # Seed without a paid parsing request.
        client.app.state.db.create(state)
        url = f"/api/sessions/{state['id']}"
        initial = client.post(url + "/messages", json={"message": "Сравни первый и второй", "revision": 1}).json()
        assert initial["agent"]["mode"] == "local"
        assert initial["agent"]["explanation_status"] == "pending"
        response = client.post(url + "/explanation", json={"revision": initial["revision"]})
        assert response.status_code == 200
        result = response.json()
        assert result["agent"]["mode"] == "llm"
        assert result["revision"] == initial["revision"]
        stored = client.get(url).json()
        assert stored["requirements"] == initial["requirements"]
        assert stored["revision"] == initial["revision"]
        edited = client.patch(url + "/requirements", json={"revision": initial["revision"], "patch": {"budget": 200000}}).json()
        assert edited["revision"] > initial["revision"]
        assert client.post(url + "/explanation", json={"revision": initial["revision"]}).status_code == 409


def test_other_trips_cannot_discard_completed_explanation(monkeypatch):
    from app.explanations import ExplanationJobs
    online(monkeypatch)
    async def model(*args, **kwargs):
        return {"title": "Почему эти варианты", "fact_ids": ["ranking"], "ask_priority": False}
    monkeypatch.setattr("app.agent.model_json", model)
    async def scenario():
        jobs = ExplanationJobs()
        first = pending(ready())
        jobs.start(first)
        assert (await jobs.get(first))["mode"] == "llm"
        jobs.start(ready())
        assert (await jobs.get(first))["mode"] == "llm"
        await jobs.close()
    asyncio.run(scenario())
