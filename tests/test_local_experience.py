"""Local demonstration must be independent of saved provider credentials."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import TripRequirements
from app.parser import configured_mode
from app.search import search


def test_default_is_local_even_with_saved_credentials(monkeypatch):
    monkeypatch.delenv("TRAVEL_MODE", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "unused-test-key")
    monkeypatch.setenv("LLM_MODEL", "unused-model")
    assert configured_mode() == "rules"


@pytest.fixture
def local_client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAVEL_MODE", "local")
    monkeypatch.setenv("LLM_API_KEY", "unused-test-key")
    monkeypatch.setenv("LLM_MODEL", "unused-model")
    async def forbidden(*args, **kwargs):
        raise AssertionError("Local journey attempted a provider request")
    monkeypatch.setattr("httpx.AsyncClient.post", forbidden)
    with TestClient(create_app("sqlite:///" + (tmp_path / "local.db").as_posix())) as client:
        yield client


def selected_trip(client):
    day = (date.today() + timedelta(days=35)).isoformat()
    result = client.post("/api/sessions", json={"message": f"В Сочи с {day} на 7 ночей вдвоём, до 160 тысяч, желательно с завтраком"})
    assert result.status_code == 200, result.text
    state = result.json()
    result = client.post(f"/api/sessions/{state['id']}/select", json={"revision": state["revision"], "plan_id": state["plans"][0]["id"]})
    assert result.status_code == 200, result.text
    return result.json()


def test_local_replan_has_verified_price_receipt(local_client):
    state = selected_trip(local_client)
    before = state["selected_plan"]
    result = local_client.post(f"/api/sessions/{state['id']}/messages", json={"revision": state["revision"], "message": "Оставь этот отель, но сократи поездку на день"})
    assert result.status_code == 200, result.text
    updated = result.json()
    receipt = updated["change_receipt"]
    assert receipt["before_total"] == before["price"]["total"]
    assert receipt["after_total"] == updated["plans"][0]["price"]["total"]
    assert receipt["before_nights"] == 7 and receipt["after_nights"] == 6
    assert receipt["hotel_preserved"] is True
    assert updated["parser_mode"] == "rules"
    assert "недоступен" not in updated["assistant_message"]


def test_save_without_contacts_is_persistent_and_idempotent(local_client):
    state = selected_trip(local_client)
    body = {"revision": state["revision"], "accept_demo": True}
    url = f"/api/sessions/{state['id']}/checkout"
    response = local_client.post(url, json=body)
    assert response.status_code == 200, response.text
    order = response.json()["order"]
    assert order["email"] is None and order["traveler_name"] is None
    assert local_client.post(url, json=body).json()["order"]["id"] == order["id"]
    assert local_client.get(f"/api/sessions/{state['id']}").json()["order"] == order


@pytest.mark.parametrize("contact", [{"email": "broken"}, {"traveler_name": "Я"}])
def test_optional_contacts_are_still_validated(local_client, contact):
    state = selected_trip(local_client)
    response = local_client.post(f"/api/sessions/{state['id']}/checkout", json={"revision": state["revision"], "accept_demo": True, **contact})
    assert response.status_code == 422


def test_local_multiturn_conflict_recovery_and_hypothetical(local_client):
    state = selected_trip(local_client)
    sid = state["id"]
    hotel = state["hotel_intent"]

    def say(message):
        nonlocal state
        response = local_client.post(f"/api/sessions/{sid}/messages", json={"revision": state["revision"], "message": message})
        assert response.status_code == 200, response.text
        state = response.json()
        return state

    say("Теперь завтрак обязателен")
    assert state["requirements"]["preference_modes"]["breakfast"] == "required"
    say("Оставь этот отель, но сократи поездку на день")
    say("На два дня позже, остальное без изменений")
    assert state["requirements"]["nights"] == 6
    assert state["hotel_intent"] == hotel
    assert state["requirements"]["adults"] == 2
    requirements = state["requirements"].copy()
    plans = state["plans"]
    say("А если убрать завтрак?")
    assert state["requirements"] == requirements
    assert state["plans"] == plans
    say("Бюджет 1000 рублей")
    assert not state["plans"] and state["diagnostic"] and state["suggestions"]
    assert state["hotel_intent"] == hotel
    proposal = state["suggestions"][0]
    response = local_client.patch(f"/api/sessions/{sid}/requirements", json={"revision": state["revision"], "patch": proposal["patch"]})
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["plans"] and state["hotel_intent"] == hotel
    assert state["requirements"]["nights"] == 6
    assert state["requirements"]["breakfast"] is True


def test_reordering_clears_outdated_price_receipt(local_client):
    state = selected_trip(local_client)
    url = f"/api/sessions/{state['id']}/messages"
    state = local_client.post(url, json={"revision": state["revision"], "message": "Сократи поездку на день"}).json()
    assert state["change_receipt"]
    state = local_client.post(url, json={"revision": state["revision"], "message": "Покажи сначала дешевле"}).json()
    assert state["change_receipt"] is None


def test_conflict_names_conditions_and_preserves_numeric_limits_when_relaxing():
    req = TripRequirements(destination="Сочи", check_in=date.today() + timedelta(days=35), min_rating=10, max_beach_m=0, budget=160000)
    result = search(req)
    assert not result["plans"]
    assert "10" in result["diagnostic"]["message"] and "0 м" in result["diagnostic"]["message"]
    proposal = result["suggestions"][0]
    assert 0 < proposal["patch"]["min_rating"] < 10
    assert 0 < proposal["patch"]["max_beach_m"] <= 10000
    checked = search(req.model_copy(update=proposal["patch"]))
    assert checked["total_matches"] == proposal["total_matches"]
    assert checked["min_total"] == proposal["min_total"]


def test_relaxations_never_tighten_an_unrelated_numeric_condition():
    req = TripRequirements(destination="Сочи", check_in=date.today() + timedelta(days=35), min_rating=8, max_beach_m=100, pool=True, budget=1000)
    result = search(req)
    patches = [item["patch"] for item in result["suggestions"]]
    assert patches
    assert len({repr(sorted(patch.items())) for patch in patches}) == len(patches)
    for patch in patches:
        assert patch.get("min_rating", req.min_rating) <= req.min_rating
        assert patch.get("max_beach_m", req.max_beach_m) >= req.max_beach_m
