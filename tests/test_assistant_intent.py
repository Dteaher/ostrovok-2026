"""Regression cases from real-provider failures, without paid network calls."""

import asyncio
import json
from datetime import date

import httpx
import pytest

from app.models import TripRequirements
from app.parser import extract_intent, parse_rules


@pytest.fixture
def model_reply(monkeypatch):
    reply = {}
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
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "choices": [{"message": {"content": json.dumps(reply)}}],
            })
    monkeypatch.setattr("app.parser.httpx.AsyncClient", Client)
    return reply


@pytest.mark.parametrize("text,patch,evidence", [
    ("пёс едет с нами", {"pets": True}, {"pets": "пёс едет с нами"}),
    ("мелкому 6 лет", {"children_ages": [6]}, {"children_ages": "мелкому 6 лет"}),
    ("бюджэт 140 тыщ", {"budget": 140000}, {"budget": "140 тыщ"}),
    ("завтраки было бы кайф, но без них переживу",
     {"breakfast": True, "preference_modes": {"breakfast": "preferred"}},
     {"breakfast": "завтраки было бы кайф, но без них переживу"}),
    ("Сочи не хочу, давай в Прагу", {"destination": "Прага"}, {"destination": "давай в Прагу"}),
    ("сократи поездку на день", {"nights": 6}, {"nights": "сократи поездку на день"}),
])
def test_evidenced_model_intent_survives_local_parser(model_reply, text, patch, evidence):
    model_reply.update(action="change", patch=patch, evidence=evidence, questions=[])
    req = TripRequirements(destination="Сочи", budget=300000)
    result = asyncio.run(extract_intent(text, req, date(2026, 10, 28)))
    assert result.mode == "llm"
    assert result.patch == patch


def test_hypothetical_model_patch_never_becomes_live_edit(model_reply):
    text = "Сравни вариант без завтрака"
    model_reply.update(action="hypothetical", patch={"breakfast": False},
                       evidence={"breakfast": "без завтрака"}, questions=[])
    result = asyncio.run(extract_intent(text, TripRequirements(breakfast=True), date(2026, 10, 28)))
    assert result.hypothetical and result.patch == {}
    assert result.hypothetical_patch == {"breakfast": False}


@pytest.mark.parametrize("proposal", [
    {"action": "change", "patch": {"budget": 1000}, "evidence": {"budget": "выдуманная цитата"}, "questions": []},
    {"action": "change", "patch": {"budget": 1000}, "evidence": {"budget": "пёс едет"}, "questions": []},
    {"action": "change", "patch": {"pets": True, "budget": 1000}, "evidence": {"pets": "пёс едет"}, "questions": []},
    {"action": "clarify", "patch": {"budget": 1000}, "evidence": {}, "questions": []},
    {"action": "change", "patch": {"children_ages": [30]}, "evidence": {"children_ages": "ребёнку 30 лет"}, "questions": []},
])
def test_invalid_or_unrelated_evidence_falls_back(model_reply, proposal):
    model_reply.update(proposal)
    result = asyncio.run(extract_intent("пёс едет, ребёнку 6 лет", TripRequirements(budget=300000), date(2026, 10, 28)))
    assert result.mode == "rules"
    assert result.patch.get("budget", 300000) == 300000


def test_colloquial_shift_is_deterministic_and_preserves_duration():
    req = TripRequirements(check_in="2026-12-06", nights=7)
    result = parse_rules("перенеси заезд на пару дней попозже, всё остальное оставь", req)
    assert result.patch == {"check_in": "2026-12-08"}
    assert not result.questions


def test_rejected_destination_is_not_reselected_by_offline_fallback():
    result = parse_rules("Сочи не хочу, давай в Прагу", TripRequirements(destination="Сочи"))
    assert result.patch.get("destination") != "Сочи"
    assert result.patch.get("destination") or result.questions


def test_explicit_do_not_change_is_safe_without_provider():
    result = parse_rules("а чё будет, если от завтраков отказаться? пока ничего не меняй", TripRequirements(breakfast=True))
    assert result.hypothetical and result.patch == {}
    assert result.hypothetical_patch["breakfast"] is False


def test_preserved_budget_cannot_be_replaced_by_incidental_surcharge(model_reply):
    model_reply.update(action="change", patch={"budget": 5000},
                       evidence={"budget": "доплата 5 тысяч"}, questions=[])
    result = asyncio.run(extract_intent("Бюджет тот же, добавь собаку, доплата 5 тысяч",
                                       TripRequirements(budget=300000), date(2026, 10, 28)))
    assert result.patch.get("budget", 300000) == 300000


def test_exact_local_number_beats_model_arithmetic_error(model_reply):
    model_reply.update(action="change", patch={"budget": 14000},
                       evidence={"budget": "бюджет 140 тысяч"}, questions=[])
    result = asyncio.run(extract_intent("бюджет 140 тысяч", TripRequirements(), date(2026, 10, 28)))
    assert result.patch["budget"] == 140000


def test_model_cannot_soften_pet_constraint(model_reply):
    model_reply.update(action="change", patch={"pets": True, "preference_modes": {"pets": "preferred"}},
                       evidence={"pets": "пёс едет"}, questions=[])
    result = asyncio.run(extract_intent("пёс едет", TripRequirements(), date(2026, 10, 28)))
    assert result.mode == "rules"


def test_soft_wish_with_concession_is_not_a_comparison(model_reply):
    text = "с завтраками было бы кайф, но если без них сильно дешевле — переживу"
    model_reply.update(action="hypothetical", patch={"breakfast": True, "preference_modes": {"breakfast": "preferred"}},
                       evidence={"breakfast": "с завтраками было бы кайф"}, questions=[])
    result = asyncio.run(extract_intent(text, TripRequirements(breakfast=True), date(2026, 10, 28)))
    assert not result.hypothetical
    assert result.patch["preference_modes"]["breakfast"] == "preferred"


@pytest.mark.parametrize("action", ["change", "unknown"])
def test_explicit_neutral_amenity_is_not_lost_when_model_omits_it(model_reply, action):
    model_reply.update(action=action, patch={}, evidence={}, questions=[])
    result = asyncio.run(extract_intent("завтрак неважен, не отсекай отели из-за него",
                                       TripRequirements(breakfast=True), date(2026, 10, 28)))
    assert result.patch["breakfast"] is False


@pytest.mark.parametrize("action", ["unknown", "change", "clarify"])
def test_explicit_pet_command_survives_empty_model_reply(model_reply, action):
    questions = [{"field": "pets", "question": "Что значит добавить кошку?"}] if action == "clarify" else []
    model_reply.update(action=action, patch={}, evidence={}, questions=questions)
    result = asyncio.run(extract_intent("Добавь кошку", TripRequirements(budget=250000), date(2026, 10, 28)))
    assert result.patch == {"pets": True}


def test_model_unknown_cannot_erase_unsupported_mandatory_wish(model_reply):
    model_reply.update(action="unknown", patch={}, evidence={}, questions=[])
    result = asyncio.run(extract_intent("Обязательно спа и вид из номера на море", TripRequirements(), date(2026, 10, 28)))
    assert result.patch["unsupported"]
    assert "origin" not in result.patch


def test_hypothetical_keeps_live_selection_and_conditions(model_reply):
    from app.service import process_message
    from scripts.compare_llm import setup
    state = setup({"initial": {"destination": "Сочи", "check_in": "2027-05-14", "budget": 500000, "breakfast": True}, "selected": True})
    before = {k: state[k] for k in ("requirements", "selected_plan", "hotel_intent")}
    model_reply.update(action="hypothetical", patch={"breakfast": False},
                       evidence={"breakfast": "без завтрака"}, questions=[])
    state = asyncio.run(process_message(state, "Сравни вариант без завтрака"))
    for key, value in before.items():
        assert state[key] == value
    assert state["hypothetical"]["patch"]["breakfast"] is False


@pytest.mark.parametrize("action", ["change", "unknown", "clarify"])
def test_model_cannot_drop_explicit_absolute_budget_command(model_reply, action):
    model_reply.update(action=action, patch={}, evidence={}, questions=[{"field": "budget", "question": "Какой бюджет?"}] if action == "clarify" else [])
    current = TripRequirements(destination="Сочи", check_in=date(2026, 12, 20), budget=150000)
    result = asyncio.run(extract_intent("Снизь бюджет до 1000 рублей", current, date(2026, 10, 29)))
    assert result.patch.get("budget") == 1000
    assert not result.questions
