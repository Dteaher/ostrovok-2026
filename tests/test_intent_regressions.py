"""Final review regressions: preserve the meaning before canonical search."""

import asyncio
from datetime import date

import pytest

from app.parser import parse_rules
from app.service import new_state, process_message


@pytest.mark.parametrize("text,nights", [("На две недели", 14), ("На шесть ночей", 6)])
def test_duration_words_are_not_destinations(text, nights):
    result = parse_rules(text)
    assert result.patch["nights"] == nights
    assert "destination" not in result.patch


def test_people_reference_is_not_origin():
    result = parse_rules("Нас трое, из них ребенок 6 лет")
    assert result.patch["adults"] == 2
    assert "origin" not in result.patch


def test_affirmed_aircraft_beats_negated_train():
    assert parse_rules("Не поездом, только самолетом").patch["transport"] == "flight"


def test_iso_interval_is_three_nights():
    result = parse_rules("Сочи с 2026-11-06 по 2026-11-09", today=date(2026, 10, 27))
    assert result.patch["check_in"] == "2026-11-06"
    assert result.patch["nights"] == 3


def test_repeated_children_are_all_counted():
    result = parse_rules("2 взрослых и ребенок 5 лет и ребенок 9 лет")
    assert result.patch["children_ages"] == [5, 9]


def test_daughter_is_child_not_an_unpriced_traveler():
    result = parse_rules("2 взрослых, дочь 6 лет")
    assert result.patch["children_ages"] == [6]


@pytest.mark.parametrize("text", ["Не Сочи, а Адлер", "В Адлере, район Сочи", "В Сочи, в Адлере"])
def test_specific_non_rejected_area_is_the_destination(text):
    assert parse_rules(text).patch["destination"] == "Адлер"


def test_negative_refund_request_does_not_enable_refund():
    assert parse_rules("Не хочу возвратный тариф").patch["refundable"] is False


def test_separate_bedrooms_cannot_be_silently_guaranteed():
    result = parse_rules("В Сочи с двумя спальнями, бюджет 180 тысяч")
    assert result.patch["unsupported"]


def test_initial_search_is_not_presented_as_a_replan():
    state = asyncio.run(
        process_message(new_state(), "В Сочи с 6 ноября 2027 на неделю вдвоем до 180 тысяч")
    )
    assert state["changes"] == []
