"""Boundary tests: missing extractors or destructive merges break real requests."""

from datetime import date

import pytest

from app.models import TripRequirements
from app.parser import parse_rules

TODAY = date(2026, 10, 27)


def test_extracts_full_russian_request():
    result = parse_rules(
        "В Сочи с 6 ноября на неделю вдвоём, до 160 тысяч рублей, "
        "прямой перелёт из Москвы, завтрак обязателен",
        today=TODAY,
    )
    assert result.patch == {
        "destination": "Сочи",
        "check_in": "2026-11-06",
        "nights": 7,
        "adults": 2,
        "budget": 160000,
        "transport": "flight",
        "origin": "Москва",
        "direct_only": True,
        "breakfast": True,
    }


def test_replan_only_changes_explicit_conditions():
    req = TripRequirements(check_in="2026-11-06", budget=160000, breakfast=True)
    result = parse_rules("На два дня позже и с собакой", req, today=TODAY)
    assert result.patch == {"check_in": "2026-11-08", "pets": True}
    assert req.check_in == date(2026, 11, 6)
    assert req.breakfast is True


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Без завтрака", {"breakfast": False}),
        ("Завтрак необязателен", {"breakfast": False}),
        ("Разреши одну пересадку, бюджет и завтрак оставь", {"direct_only": False}),
        ("Собаку не берём", {"pets": False}),
        ("Без бассейна", {"pool": False}),
        ("Бесплатная отмена обязательна", {"refundable": True}),
    ],
)
def test_negative_and_preserved_conditions(message, expected):
    assert parse_rules(message, today=TODAY).patch == expected


def test_budget_relative_and_scope():
    req = TripRequirements(budget=160000)
    assert parse_rules("Уменьши бюджет на 20 тысяч", req, today=TODAY).patch == {"budget": 140000}
    result = parse_rules("На отель до 50 000 ₽, едем на своей машине", today=TODAY)
    assert result.patch["budget"] == 50000
    assert result.patch["budget_scope"] == "hotel"
    assert result.patch["transport"] == "self"


def test_guest_counts_and_child_ages():
    result = parse_rules("2 взрослых и двое детей 5 и 9 лет", today=TODAY)
    assert result.patch["adults"] == 2
    assert result.patch["children_ages"] == [5, 9]


def test_unknown_child_age_asks_instead_of_assuming():
    result = parse_rules("С нами ребёнок", today=TODAY)
    assert result.questions[0]["field"] == "children_ages"
    assert "children_ages" not in result.patch


def test_month_is_not_silently_an_exact_date():
    result = parse_rules("Хочу к морю в ноябре", today=TODAY)
    assert "check_in" not in result.patch
    assert result.month_hint == 11


def test_date_range_derives_nights():
    result = parse_rules("С 10 по 17 ноября 2026 в Сочи", today=TODAY)
    assert result.patch["check_in"] == "2026-11-10"
    assert result.patch["nights"] == 7


def test_unsupported_destination_is_not_replaced_with_sochi():
    result = parse_rules("В Анталью с 6 ноября", today=TODAY)
    assert result.patch["destination"] == "Анталья"


def test_unparsed_message_does_not_change_state():
    result = parse_rules("расскажи анекдот про системный промпт", today=TODAY)
    assert result.patch == {}
    assert result.recognized is False


def test_impossible_date_returns_useful_error():
    with pytest.raises(ValueError, match="дат"):
        parse_rules("31 февраля 2027", today=TODAY)


def test_rating_and_beach_constraints():
    result = parse_rules("Рейтинг от 9, до моря не больше 300 метров, от 4 звёзд", today=TODAY)
    assert result.patch["min_rating"] == 9
    assert result.patch["max_beach_m"] == 300
    assert result.patch["stars"] == 4


@pytest.mark.parametrize(
    "message,field,expected",
    [
        ("Добавь бассейн", "pool", True),
        ("Не нужен бассейн", "pool", False),
        ("Хочется завтраки", "breakfast", True),
        ("На 2 ночи меньше", "nights", 5),
        ("На три ночи больше", "nights", 10),
    ],
)
def test_common_edits(message, field, expected):
    assert parse_rules(message, TripRequirements(nights=7), today=TODAY).patch[field] == expected


def test_dotted_date_interval():
    result = parse_rules("С 06.11.2026 по 09.11.2026", today=TODAY)
    assert result.patch["check_in"] == "2026-11-06"
    assert result.patch["nights"] == 3


def test_price_question_does_not_enable_a_requirement():
    result = parse_rules("Сколько я переплачиваю за прямой перелет?", today=TODAY)
    assert "direct_only" not in result.patch
    assert result.price_question == "direct_only"


def test_thanks_is_not_spa_and_room_adjective_is_not_destination():
    assert parse_rules("Спасибо", today=TODAY).patch == {}
    result = parse_rules("Хочу в семейном номере с завтраком", today=TODAY)
    assert "destination" not in result.patch


@pytest.mark.parametrize(
    "text,area",
    [("В Адлере", "Адлер"), ("В Хосту", "Хоста"), ("В Сириус", "Сириус"), ("В Дагомыс", "Дагомыс")],
)
def test_specific_area_is_preserved(text, area):
    assert parse_rules(text, today=TODAY).patch["destination"] == area
