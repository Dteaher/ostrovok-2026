from datetime import timedelta

import pytest

from app.models import TripRequirements
from app.parser import ParsedIntent
from app.search import search, validate_plan
from app.service import compile_state, local_today, new_state


def ready():
    return compile_state(new_state(), ParsedIntent(patch={"destination": "Сочи", "check_in": (local_today() + timedelta(days=45)).isoformat(), "budget": 500000, "breakfast": True}, recognized=True))


def test_initial_values_and_history_survive_multiple_edits():
    state = ready()
    first = state["requirements"]["check_in"]
    state = compile_state(state, ParsedIntent(patch={"check_in": (local_today() + timedelta(days=48)).isoformat()}, recognized=True))
    state = compile_state(state, ParsedIntent(patch={"pets": True}, recognized=True))
    assert state["_initial_values"]["check_in"] == first
    assert len(state["_requirement_history"]) == 3
    assert state["_requirement_history"][-1]["fields"] == ["pets"]


@pytest.mark.parametrize("priority", ["balanced", "price", "beach", "rating"])
def test_explicit_ranking_is_deterministic_and_keeps_all_hard_constraints(priority):
    req = TripRequirements.model_validate(ready()["requirements"])
    result = search(req, ranking=priority)
    assert result == search(req, ranking=priority)
    assert result["plans"]
    assert all(not validate_plan(plan, req) for plan in result["plans"])
    first = result["plans"][0]
    all_plans = search(req, 100, ranking=priority)["plans"]
    if priority == "price":
        assert first["price"]["total"] == min(p["price"]["total"] for p in all_plans)
    if priority == "beach":
        assert first["hotel"]["beach_m"] == min(p["hotel"]["beach_m"] for p in all_plans)
    if priority == "rating":
        assert first["hotel"]["rating"] == max(p["hotel"]["rating"] for p in all_plans)
