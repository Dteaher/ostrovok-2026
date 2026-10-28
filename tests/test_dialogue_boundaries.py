import asyncio

import pytest

from app.models import TripRequirements
from app.parser import parse_rules
from app.service import process_message
from scripts.compare_llm import setup


@pytest.mark.parametrize("text", [
    "Напиши рецепт завтрака на двоих за 500 рублей",
    "Посоветуй ноутбук с бюджетом 80 тысяч рублей. Поездку не меняй",
    "Купи мне телефон за 90 тысяч рублей",
])
def test_nontravel_prices_do_not_change_trip_or_order(text, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    state = setup({"initial": {"destination": "Сочи", "check_in": "2027-05-14", "budget": 500000, "breakfast": True}, "selected": True})
    before = {key: state[key] for key in ("requirements", "selected_plan", "order")}
    state = asyncio.run(process_message(state, text))
    assert all(state[key] == value for key, value in before.items())


def test_room_view_is_not_departure_city():
    result = parse_rules("Обязательно спа и вид из номера на море")
    assert "origin" not in result.patch
    assert result.patch["unsupported"]


@pytest.mark.parametrize("text", [
    "Бюджет двести сорок тысяч рублей на всех",
    "Дорогу организуем сами, не включай её в расчёт",
    "На всё готов потратить 180,5 тыс рублей",
    "С нами человек на инвалидной коляске, нужна доступная среда",
])
def test_non_geographic_prepositions_do_not_block_model(text):
    result = parse_rules(text)
    assert not any(q["field"] == "destination" for q in result.questions)


def test_child_pronoun_answer_preserves_existing_children():
    state = setup({"initial": {"destination": "Сочи", "check_in": "2027-05-14", "children_ages": [5], "budget": 500000}})
    state = asyncio.run(process_message(state, "Добавь ещё одного ребёнка"))
    state = asyncio.run(process_message(state, "Ему 8 лет"))
    assert state["requirements"]["children_ages"] == [5, 8]


def test_unsupported_city_replacing_sochi_is_not_reset_to_sochi():
    result = parse_rules("Хочу в Тбилиси вместо Сочи", TripRequirements(destination="Сочи"))
    assert result.patch.get("destination") != "Сочи"


def test_explicit_neutral_transport_phrase():
    result = parse_rules("Дорогу организуем сами, не включай её в расчёт")
    assert result.patch["transport"] == "self"
