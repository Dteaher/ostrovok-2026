import asyncio
from copy import deepcopy
from datetime import timedelta

import pytest

from app.agent import handle_turn, local_presentation, presentation
from app.models import TripRequirements
from app.negotiation import explore, proposal_facts
from app.parser import ParsedIntent
from app.search import search
from app.service import compile_state, local_today, new_state


def ready(**patch):
    return compile_state(new_state(), ParsedIntent(recognized=True, patch={
        "destination": "Сочи", "check_in": (local_today() + timedelta(days=55)).isoformat(),
        "budget": 500000, **patch}))


@pytest.mark.parametrize("patch", [
    {"budget": 1000}, {"stars": 5, "budget": 40000}, {"pool": True},
    {"pets": True}, {"accessible": True}, {"nights": 1}, {"nights": 14},
    {"breakfast": True, "refundable": True}, {"transport": "self"},
    {"budget_scope": "hotel", "budget": 30000},
])
def test_exploration_preserves_live_state_and_only_reports_searchable_branches(patch):
    state = ready(**patch)
    before = deepcopy(state)
    proposals = explore(state)
    assert state == before
    assert len(proposals) <= 7
    for item in proposals:
        result = search(TripRequirements.model_validate(state["requirements"] | item["patch"]))
        assert result["total_matches"] == item["total_matches"]
        assert result["min_total"] == item["min_total"]
        assert not set(item["patch"]) & {"pets", "accessible", "adults", "children_ages", "unsupported"}


@pytest.mark.parametrize("field,value", [("budget", 450000), ("nights", 6), ("adults", 3),
    ("pets", True), ("pool", True), ("breakfast", True), ("refundable", True),
    ("max_beach_m", 500), ("stars", 4), ("transport", "self")])
def test_stale_confirmation_cannot_overwrite_new_user_conditions(field, value):
    state = ready()
    proposal_facts(state)
    state = compile_state(state, ParsedIntent(recognized=True, patch={field: value}))
    before = deepcopy(state["requirements"])
    result = asyncio.run(handle_turn(state, "Подтверждаю компромисс 1"))
    assert result["requirements"] == before
    assert "устарело" in result["assistant_message"]
    assert result["order"] is None


@pytest.mark.parametrize("message", ["да", "ок", "первый", "наверное", "подумаю", "нравится", "хорошо", "1"])
def test_ambiguous_acknowledgment_does_not_apply_proposal(message):
    state = ready()
    proposal_facts(state)
    before = deepcopy(state["requirements"])
    assert asyncio.run(handle_turn(state, message)) is None
    assert state["requirements"] == before


@pytest.mark.parametrize("message", ["не согласен", "отказываюсь", "не менять условия"])
def test_rejection_preserves_trip(message):
    state = ready()
    proposal_facts(state)
    before = deepcopy(state["requirements"])
    result = asyncio.run(handle_turn(state, message))
    assert result["requirements"] == before
    assert result["_agent_proposals"] is None


def test_confirmed_compromise_changes_exact_patch_and_is_not_a_booking():
    state = ready(pets=True)
    proposal_facts(state)
    patch = state["_agent_proposals"]["items"][0]["patch"]
    expected = state["requirements"] | patch
    result = asyncio.run(handle_turn(state, "Подтверждаю компромисс 1"))
    for field, value in expected.items():
        if field != "assumptions":
            assert result["requirements"][field] == value
    assert result["order"] is None
    assert result["plans"]
    after = deepcopy(result["requirements"])
    result = asyncio.run(handle_turn(result, "Подтверждаю компромисс 1"))
    assert result["requirements"] == after


def test_hotel_scope_change_invalidates_proposal():
    state = ready()
    proposal_facts(state)
    state["hotel_intent"] = {"id": state["plans"][0]["hotel"]["id"], "name": "selected"}
    before = deepcopy(state["requirements"])
    result = asyncio.run(handle_turn(state, "Подтверждаю компромисс 1"))
    assert result["requirements"] == before
    assert "устарело" in result["assistant_message"]


@pytest.mark.parametrize("message,excluded", [("Не меняй количество ночей", {"nights"}),
    ("Не меняй длительность", {"nights"}), ("Не меняй даты", {"nights", "check_in"})])
def test_explicit_locks_constrain_exploration(message, excluded):
    state = asyncio.run(handle_turn(ready(), message))
    assert all(not set(p["patch"]) & excluded for p in explore(state))


def test_previous_dates_differ_from_initial_dates():
    state = ready()
    second = (local_today() + timedelta(days=57)).isoformat()
    state = compile_state(state, ParsedIntent(recognized=True, patch={"check_in": second}))
    state = compile_state(state, ParsedIntent(recognized=True, patch={"check_in": (local_today() + timedelta(days=60)).isoformat()}))
    result = asyncio.run(handle_turn(state, "Верни прошлые даты"))
    assert result["requirements"]["check_in"] == second


def test_local_empty_results_have_actionable_verified_question():
    state = ready(budget=40000, stars=5)
    result = local_presentation(state)
    assert result["actions"] and result["question"]
    assert all(a["message"].startswith("Подтверждаю компромисс ") for a in result["actions"])


def test_no_fabricated_alternatives_without_complete_dates():
    state = new_state()
    assert explore(state) == []


def test_narrated_actions_reference_only_displayed_evidence():
    state = ready(budget=40000)
    result = asyncio.run(presentation(state, "Предложи альтернативы", "alternatives", use_model=False))
    ids = {f["id"] for f in result["facts"]}
    for action in result["actions"]:
        i = int(action["message"].split()[-1]) - 1
        assert f"alternative_{i}" in ids


def test_preference_provenance_retains_repetition_without_inventing_weights():
    from app.evidence import facts_for
    state = ready()
    for message in ("Мне важна тишина", "Ещё раз: хочу тихий отель"):
        state = compile_state(state, ParsedIntent(recognized=True, patch={"quiet": True}), user_text=message)
    fact = next(f for f in facts_for(state) if f["id"] == "preference_quiet")
    assert "несколько раз" in fact["text"]
    assert len(fact["source"]["dialogue_entries"]) == 2
    state = compile_state(state, ParsedIntent(recognized=True, patch={"quiet": False}), user_text="Тишина больше не важна")
    assert not any(f["id"] == "preference_quiet" for f in facts_for(state))
