"""Validate evaluation gates independently of external model output."""

import asyncio
from datetime import date

from app.models import TripRequirements
from scripts.compare_llm import assertions, cases, evaluate, informal_cases, setup
from scripts.compare_llm_direct import Intent, assess


def test_all_evaluation_fixtures_are_valid_and_selected_offers_exist():
    dataset = cases(date(2026, 10, 27)) + informal_cases(date(2026, 10, 27))
    assert len(dataset) == 30
    assert len({case["id"] for case in dataset}) == len(dataset)
    for case in dataset:
        state = setup(case)
        TripRequirements.model_validate(state["requirements"])
        if case.get("selected"):
            assert state["selected_plan"] and state["hotel_intent"]


def test_hypothetical_mutation_and_lost_selection_fail_the_judge():
    state = setup({"initial": {"destination": "Сочи", "check_in": "2027-05-14", "breakfast": True}, "selected": True})
    changed = {**state, "requirements": {**state["requirements"], "breakfast": False}, "selected_plan": None}
    failures = assertions(state, changed, {"unchanged": True, "selection": True})
    assert {item["check"] for item in failures} >= {"unchanged_trip", "selection"}


def test_offline_success_is_reported_without_any_claim_of_model_calls():
    report = asyncio.run(evaluate(["offline-rules"], rules_only=True))
    summary = report["summary"][0]
    assert summary["turns"] == 24
    assert summary["provider_calls"] == summary["http_200"] == summary["llm_applied_turns"] == 0
    assert summary["local_only_turns"] == 24
    assert report["rules_only"]


def test_direct_judge_rejects_wrong_action_and_unrequested_changes():
    req = TripRequirements(budget=500000, breakfast=True)
    wrong = Intent(action="change", patch={"breakfast": False, "budget": 1000}, questions=[])
    failures = assess(wrong, req, "hypothetical", {"breakfast": False})
    assert {item["check"] for item in failures} == {"action", "unrequested:budget"}


def test_direct_judge_does_not_accept_empty_clarification():
    failures = assess(Intent(action="clarify", patch={}, questions=[]), TripRequirements(), "clarify", {})
    assert failures == [{"check": "clarification_without_guess"}]
