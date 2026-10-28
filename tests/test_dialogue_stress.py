from datetime import date

from scripts.compare_llm import assertions, setup
from scripts.dialogue_stress_cases import stress_cases


def test_independent_stress_fixtures_have_valid_states_and_preservation_checks():
    cases = stress_cases(date(2026, 10, 28))
    assert len(cases) >= 30
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        state = setup(case)
        if case["selected"]:
            assert state["selected_plan"]
        for turn in case["turns"]:
            assert "preserve" in turn or turn.get("unchanged")
        if case["category"] == "не по теме":
            assert all(turn["unchanged"] and turn["no_order"] for turn in case["turns"])


def test_stress_judge_detects_unrequested_order():
    before = setup({"initial": {"destination": "Сочи"}})
    after = {**before, "order": {"id": "unrequested"}}
    assert {f["check"] for f in assertions(before, after, {"no_order": True})} == {"unrequested_order"}


def test_stress_judge_detects_unrequested_clarification():
    before = setup({"initial": {"destination": "Сочи"}})
    after = {**before, "clarifications": [{"field": "budget", "question": "unexpected"}]}
    assert {f["check"] for f in assertions(before, after, {"no_new_questions": True})} == {"unrequested_clarification"}
    assert {f["check"] for f in assertions(before, after, {"no_questions": True})} == {"unexpected_clarification"}
