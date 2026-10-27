"""User-visible state transitions through HTTP, without a model provider."""

from copy import deepcopy
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import TripRequirements
from app.search import search


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with TestClient(create_app("sqlite:///" + (tmp_path / "dialog.db").as_posix())) as client:
        yield client


def trip(client, extra=""):
    day = (date.today() + timedelta(days=40)).isoformat()
    response = client.post("/api/sessions", json={
        "message": f"В Сочи с {day} на 7 ночей вдвоём, до 500 тысяч {extra}",
    })
    assert response.status_code == 200, response.text
    return response.json()


def say(client, state, message):
    response = client.post(f"/api/sessions/{state['id']}/messages", json={
        "revision": state["revision"], "message": message,
    })
    assert response.status_code == 200, response.text
    return response.json()


def select(client, state, plan=None):
    response = client.post(f"/api/sessions/{state['id']}/select", json={
        "revision": state["revision"], "plan_id": (plan or state["plans"][0])["id"],
    })
    assert response.status_code == 200, response.text
    return response.json()


def checkout(client, state):
    return client.post(f"/api/sessions/{state['id']}/checkout", json={
        "revision": state["revision"], "accept_demo": True,
        "traveler_name": "Анна Иванова", "email": "anna@example.com",
    })


def test_shorten_reprices_same_hotel_and_requires_offer_confirmation(client):
    original = select(client, trip(client))
    old = original["selected_plan"]
    updated = say(client, original, "Оставь этот отель, но сократи поездку на день")
    assert updated["requirements"]["nights"] == 6
    assert updated["requirements"]["budget"] == original["requirements"]["budget"]
    assert updated["hotel_intent"]["id"] == old["hotel"]["id"]
    assert updated["stage"] == "results"
    assert updated["selected_plan"] is None
    assert updated["plans"]
    assert all(p["hotel"]["id"] == old["hotel"]["id"] for p in updated["plans"])
    assert updated["plans"][0]["id"] != old["id"]
    assert updated["plans"][0]["price"]["total"] < old["price"]["total"]
    assert checkout(client, updated).status_code == 409
    assert checkout(client, select(client, updated)).status_code == 200


@pytest.mark.parametrize("message", [
    "Теперь бюджет 500 тысяч", "Привет!", "Сколько стоит прямой перелёт?",
    "Что изменится, если убрать завтрак?",
])
def test_noop_question_and_unknown_keep_selection(client, message):
    original = select(client, trip(client, ", с завтраком"))
    updated = say(client, original, message)
    assert updated["requirements"] == original["requirements"]
    assert updated["selected_plan"] == original["selected_plan"]
    assert updated["stage"] == "selected"
    assert not updated["changes"]


def test_hypothetical_compares_search_without_mutating_trip(client):
    original = select(client, trip(client, ", с завтраком"))
    updated = say(client, original, "Что изменится, если убрать завтрак?")
    assert updated["requirements"] == original["requirements"]
    comparison = updated["hypothetical"]
    assert comparison["patch"]["breakfast"] is False
    assert comparison["total_matches"] > 0
    assert comparison["min_total"] > 0
    assert "без изменения" in updated["assistant_message"].lower()
    assert checkout(client, updated).status_code == 200


def test_unavailable_pinned_hotel_does_not_silently_replace_it(client):
    state = trip(client)
    chosen = next(p for p in state["plans"] if "pets" not in p["hotel"]["features"])
    original = select(client, state, chosen)
    updated = say(client, original, "Бюджет тот же, добавь собаку")
    assert updated["hotel_intent"]["id"] == chosen["hotel"]["id"]
    assert updated["requirements"]["pets"] is True
    assert not updated["plans"]
    assert updated["selected_plan"] is None
    assert updated["diagnostic"]["kind"] == "pinned_hotel_conflict"
    assert updated["hotel_alternative"]["total_matches"] > 0
    assert checkout(client, updated).status_code == 409
    released = say(client, updated, "Покажи другие отели")
    assert released["hotel_intent"] is None
    assert released["plans"]
    assert all("pets" in p["hotel"]["features"] for p in released["plans"])


def test_ambiguous_request_preserves_trip_and_offer_until_answer(client):
    original = select(client, trip(client))
    updated = say(client, original, "Сделай дешевле")
    assert updated["requirements"] == original["requirements"]
    assert updated["selected_plan"] == original["selected_plan"]
    assert updated["request_status"] == "needs_clarification"
    assert any(q["field"] == "budget" for q in updated["clarifications"])
    answered = say(client, updated, "Бюджет 300 тысяч")
    assert answered["requirements"]["budget"] == 300000
    assert answered["requirements"]["check_in"] == original["requirements"]["check_in"]
    assert not answered["clarifications"]
    assert answered["hotel_intent"]["id"] == original["selected_plan"]["hotel"]["id"]


def test_required_preferred_neutral_and_partial_priority_patch(client):
    state = trip(client, ", желательно с завтраком и с бассейном")
    assert state["requirements"]["preference_modes"]["breakfast"] == "preferred"
    state = say(client, state, "Теперь завтрак обязателен")
    assert state["requirements"]["preference_modes"]["breakfast"] == "required"
    assert all(p["meal"] == "Завтрак включён" for p in state["plans"])
    state = say(client, state, "Завтрак неважен")
    assert state["requirements"]["breakfast"] is False
    assert state["requirements"]["pool"] is True
    assert state["requirements"]["budget"] == 500000


def test_empty_search_suggestion_reproduces_verified_counts(client):
    state = trip(client, ", с завтраком")
    response = client.patch(f"/api/sessions/{state['id']}/requirements", json={
        "revision": state["revision"], "patch": {"budget": 1000, "stars": 5},
    })
    state = response.json()
    assert not state["plans"]
    assert state["suggestions"]
    suggestion = state["suggestions"][0]
    response = client.patch(f"/api/sessions/{state['id']}/requirements", json={
        "revision": state["revision"], "patch": suggestion["patch"],
    })
    updated = response.json()
    assert updated["total_matches"] == suggestion["total_matches"]
    assert updated["plans"]


def test_keep_without_selected_hotel_asks_instead_of_guessing(client):
    original = trip(client)
    updated = say(client, original, "Оставь этот отель")
    assert updated["hotel_intent"] is None
    assert updated["requirements"] == original["requirements"]
    assert updated["request_status"] == "needs_clarification"
    assert "выбер" in updated["assistant_message"].lower()


def test_pending_child_age_blocks_checkout_and_accepts_short_contextual_answer(client):
    original = select(client, trip(client))
    pending = say(client, original, "Добавь ребёнка")
    assert pending["selected_plan"] == original["selected_plan"]
    assert pending["request_status"] == "needs_clarification"
    assert checkout(client, pending).status_code == 409
    answered = say(client, pending, "6 лет")
    assert answered["requirements"]["children_ages"] == [6]
    assert not answered["clarifications"]
    assert answered["selected_plan"] is None
    assert checkout(client, answered).status_code == 409


def test_budget_clarification_can_be_cancelled_without_losing_selection(client):
    original = select(client, trip(client))
    pending = say(client, original, "Сделай дешевле")
    assert checkout(client, pending).status_code == 409
    answered = say(client, pending, "Бюджет тот же")
    assert not answered["clarifications"]
    assert answered["selected_plan"] == original["selected_plan"]
    assert checkout(client, answered).status_code == 200


def test_two_children_need_two_ages_across_followup_answers(client):
    original = select(client, trip(client))
    pending = say(client, original, "Добавь 2 детей")
    child = next(q for q in pending["clarifications"] if q["field"] == "children_ages")
    assert child["expected_count"] == 2
    assert not child["options"]
    partial = say(client, pending, "6 лет")
    assert partial["requirements"]["children_ages"] == []
    assert partial["selected_plan"] == original["selected_plan"]
    assert checkout(client, partial).status_code == 409
    answered = say(client, partial, "6 и 10 лет")
    assert answered["requirements"]["children_ages"] == [6, 10]
    assert not answered["clarifications"]
    assert answered["hotel_intent"] == original["hotel_intent"]


def test_partial_priority_update_preserves_other_modes(client):
    original = trip(client, ", желательно с завтраком, желательно с бассейном")
    response = client.patch(f"/api/sessions/{original['id']}/requirements", json={
        "revision": original["revision"], "patch": {"preference_modes": {"breakfast": "required"}},
    })
    assert response.status_code == 200
    modes = response.json()["requirements"]["preference_modes"]
    assert modes == {"breakfast": "required", "pool": "preferred"}


@pytest.mark.parametrize("question", [
    "Будет ли дешевле без завтрака?", "Что изменится без завтрака?", "Можно ли с собакой?",
])
def test_other_bounded_comparison_questions_never_apply_changes(client, question):
    original = select(client, trip(client, ", с завтраком"))
    updated = say(client, original, question)
    assert updated["requirements"] == original["requirements"]
    assert updated["selected_plan"] == original["selected_plan"]
    assert updated["hypothetical"]


def test_short_priority_answer_resolves_contradiction_without_resetting_other_conditions(client):
    original = select(client, trip(client))
    pending = say(client, original, "Завтрак обязателен и завтрак не нужен")
    assert pending["request_status"] == "needs_clarification"
    assert pending["requirements"] == original["requirements"]
    assert checkout(client, pending).status_code == 409
    answered = say(client, pending, "Желательно")
    assert not answered["clarifications"]
    assert answered["requirements"]["breakfast"] is True
    assert answered["requirements"]["preference_modes"]["breakfast"] == "preferred"
    assert answered["requirements"]["budget"] == original["requirements"]["budget"]


def test_new_selection_clears_previous_hypothetical_context_and_booked_has_no_action(client):
    original = trip(client, ", с завтраком")
    selected = select(client, original)
    compared = say(client, selected, "Что изменится, если убрать завтрак?")
    assert compared["hypothetical"]
    other = next(p for p in original["plans"] if p["hotel"]["id"] != selected["hotel_intent"]["id"])
    changed = select(client, compared, other)
    assert changed["hypothetical"] is None
    compared = say(client, changed, "Что изменится, если убрать завтрак?")
    booked = checkout(client, compared)
    assert booked.status_code == 200
    assert booked.json()["hypothetical"] is None


def test_confirming_existing_default_priority_is_semantic_noop(client):
    original = select(client, trip(client, ", с завтраком"))
    response = client.patch(f"/api/sessions/{original['id']}/requirements", json={
        "revision": original["revision"], "patch": {"preference_modes": {"breakfast": "required"}},
    })
    assert response.status_code == 200
    updated = response.json()
    assert updated["selected_plan"] == original["selected_plan"]
    assert updated["stage"] == "selected"
    assert not updated["changes"]
    assert checkout(client, updated).status_code == 200


def test_sequential_add_child_preserves_existing_child_and_other_requirements(client):
    original = trip(client, ", ребёнок 6 лет")
    assert original["requirements"]["children_ages"] == [6]
    pending = say(client, original, "Добавь ещё одного ребёнка")
    assert pending["requirements"]["children_ages"] == [6]
    answered = say(client, pending, "4 года")
    assert answered["requirements"]["children_ages"] == [6, 4]
    assert answered["requirements"]["budget"] == original["requirements"]["budget"]
    assert not answered["clarifications"]


@pytest.mark.parametrize("answer", ["6 лет", "Ребёнку 6 лет", "Один ребёнок 6 лет"])
def test_hypothetical_followup_age_stays_in_comparison_until_explicit_apply(client, answer):
    original = select(client, trip(client))
    pending = say(client, original, "Что изменится, если добавить ребёнка?")
    assert pending["requirements"] == original["requirements"]
    pending = say(client, pending, "Ага")
    answered = say(client, pending, answer)
    assert answered["requirements"] == original["requirements"]
    assert answered["selected_plan"] == original["selected_plan"]
    assert answered["hypothetical"]["patch"]["children_ages"] == [6]
    assert answered["hypothetical"]["total_matches"] > 0
    applied = client.patch(f"/api/sessions/{answered['id']}/requirements", json={
        "revision": answered["revision"], "patch": answered["hypothetical"]["patch"],
    }).json()
    assert applied["requirements"]["children_ages"] == [6]
    assert applied["selected_plan"] is None


def test_hypothetical_never_bypasses_pending_live_guest_clarification(client):
    original = select(client, trip(client))
    pending = say(client, original, "Добавь ребёнка")
    compared = say(client, pending, "Что изменится, если убрать завтрак?")
    assert compared["hypothetical"] is None
    assert compared["clarifications"] == pending["clarifications"]
    assert checkout(client, compared).status_code == 409


def test_invalid_guest_patch_during_count_clarification_is_atomic_422(client):
    state = say(client, trip(client), "Добавь двух детей")
    response = client.patch(f"/api/sessions/{state['id']}/requirements", json={
        "revision": state["revision"], "patch": {"children_ages": 6},
    })
    assert response.status_code == 422
    restored = client.get(f"/api/sessions/{state['id']}").json()
    assert restored["revision"] == state["revision"]
    assert restored["requirements"] == state["requirements"]
    assert restored["clarifications"] == state["clarifications"]


def test_changed_dates_can_make_retained_hotel_unavailable_without_replacement(client):
    # Find real, reproducible inventory boundaries in the versioned demo data,
    # rather than mocking the availability check under test.
    first = date.today() + timedelta(days=40)
    req = TripRequirements(
        destination="Сочи", check_in=first, nights=1, adults=8,
        children_ages=[2, 4, 6, 8, 10, 12], budget=5000000, transport="self",
    )
    available = unavailable = None
    for offset in range(30):
        candidate = req.model_copy(update={"check_in": first + timedelta(days=offset)})
        result = search(candidate, hotel_id="h09")
        if result["plans"]:
            available = (candidate, result["plans"][0])
        elif result["diagnostic"]["kind"] == "availability":
            unavailable = candidate.check_in
        if available and unavailable:
            break
    assert available and unavailable
    req, plan = available
    state = trip(client)
    response = client.patch(f"/api/sessions/{state['id']}/requirements", json={
        "revision": state["revision"],
        "patch": req.model_dump(mode="json", exclude={"assumptions"}),
    })
    assert response.status_code == 200
    selected = select(client, response.json(), plan)
    updated = say(client, selected, f"На {unavailable.isoformat()}, остальное без изменений")
    assert updated["hotel_intent"]["id"] == "h09"
    assert not updated["plans"] and updated["selected_plan"] is None
    assert updated["diagnostic"]["kind"] == "availability"
    assert updated["hotel_alternative"]["total_matches"] > 0
    assert updated["requirements"]["children_ages"] == req.children_ages
    assert checkout(client, selected).status_code == 409
    assert checkout(client, updated).status_code == 409


def test_explicit_other_selection_is_allowed_and_comparison_uses_that_hotel(client):
    state = trip(client, ", с завтраком")
    selected = select(client, state)
    other = next(p for p in state["plans"] if p["hotel"]["id"] != selected["hotel_intent"]["id"])
    selected = select(client, selected, other)
    assert selected["hotel_intent"]["id"] == other["hotel"]["id"]
    expected = search(TripRequirements.model_validate(selected["requirements"]), hotel_id=other["hotel"]["id"])
    assert selected["counterfactuals"] == expected["counterfactuals"]
    compared = say(client, selected, "Сколько переплачиваю за завтрак?")
    assert compared["selected_plan"] == selected["selected_plan"]


@pytest.mark.parametrize("was_selected", [False, True])
def test_legacy_sessions_keep_requirements_but_refresh_old_offer_ids(client, was_selected):
    state = trip(client, ", с завтраком")
    if was_selected:
        state = select(client, state)
    legacy = client.app.state.db.load(state["id"])
    old_hotel = legacy["selected_plan"]["hotel"]["id"] if was_selected else None
    legacy.pop("schema_version")
    legacy["requirements"].pop("preference_modes")
    for key in ("hotel_intent", "hotel_alternative", "diagnostic", "hypothetical", "request_status"):
        legacy.pop(key, None)
    legacy["plans"] = deepcopy(legacy["plans"])
    for plan in legacy["plans"]:
        plan["id"] = "legacy-id"
        plan.pop("preference_matches", None)
        plan.pop("preference_compromises", None)
    client.app.state.db.save(legacy, expected=state["revision"])
    restored = client.get(f"/api/sessions/{state['id']}").json()
    assert restored["schema_version"] == 2
    assert restored["requirements"]["breakfast"] is True
    assert restored["requirements"]["preference_modes"] == {}
    assert restored["plans"] and all(p["id"] != "legacy-id" for p in restored["plans"])
    assert restored["selected_plan"] is None
    if was_selected:
        assert restored["hotel_intent"]["id"] == old_hotel
        assert all(p["hotel"]["id"] == old_hotel for p in restored["plans"])
    assert checkout(client, restored).status_code == 409
    assert checkout(client, select(client, restored)).status_code == 200
