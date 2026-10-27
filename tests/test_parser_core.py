"""Local edit semantics and the optional extractor trust boundary."""

import asyncio
import json
from datetime import date

import httpx
import pytest

from app.models import TripRequirements
from app.parser import extract_intent, parse_rules

TODAY = date(2026, 10, 27)


def test_keep_hotel_and_shorten_only_duration():
    req = TripRequirements(check_in="2026-11-06", nights=7, budget=180000)
    result = parse_rules("Оставь этот отель, но сократи поездку на день", req, today=TODAY)
    assert result.keep_hotel
    assert result.patch == {"nights": 6}


@pytest.mark.parametrize("message", ["Другой отель", "Убери закрепление отеля"])
def test_explicit_release_hotel(message):
    assert parse_rules(message).release_hotel


def test_shift_does_not_change_duration_or_other_conditions():
    req = TripRequirements(check_in="2026-11-06", nights=7, budget=180000)
    assert parse_rules("На два дня позже", req, today=TODAY).patch == {"check_in": "2026-11-08"}


def test_preferred_breakfast_then_required_merges_existing_modes():
    req = TripRequirements(preference_modes={"pool": "preferred"})
    soft = parse_rules("Лучше с завтраком, но можно без", req)
    assert soft.patch["breakfast"] is True
    assert soft.patch["preference_modes"] == {"pool": "preferred", "breakfast": "preferred"}
    req = TripRequirements.model_validate(req.model_dump() | soft.patch)
    hard = parse_rules("Теперь завтрак обязателен", req)
    assert hard.patch["breakfast"] is True
    assert hard.patch["preference_modes"] == {"pool": "preferred", "breakfast": "required"}


@pytest.mark.parametrize("message", ["Завтрак неважен", "Не нужен завтрак", "Убери требование завтрака"])
def test_neutral_breakfast_removes_requirement(message):
    result = parse_rules(message, TripRequirements(breakfast=True))
    assert result.patch["breakfast"] is False


def test_same_budget_and_add_dog_does_not_invent_budget():
    req = TripRequirements(budget=180000, breakfast=True)
    assert parse_rules("Бюджет тот же, добавь собаку", req).patch == {"pets": True}


def test_hypothetical_never_mutates_even_with_other_recognizers():
    result = parse_rules("Что изменится, если убрать завтрак и добавить собаку?", TripRequirements(breakfast=True))
    assert result.hypothetical
    assert result.patch == {}
    assert result.hypothetical_patch["breakfast"] is False
    assert result.hypothetical_patch["pets"] is True


def test_cheaper_asks_concrete_question_without_mutation():
    result = parse_rules("Сделай дешевле", TripRequirements(budget=180000))
    assert result.patch == {}
    assert result.questions


@pytest.mark.parametrize("text,key", [("Желательно с бассейном", "pool"), ("Лучше с бесплатной отменой", "refundable"), ("Тишина обязательна", "quiet")])
def test_other_preferences_have_explicit_modes(text, key):
    result = parse_rules(text)
    assert result.patch[key] is True
    assert result.patch["preference_modes"][key] == ("required" if key == "quiet" else "preferred")


def test_desirable_adjective_is_soft():
    result = parse_rules("Завтрак желателен")
    assert result.patch["breakfast"] is True
    assert result.patch["preference_modes"]["breakfast"] == "preferred"


@pytest.mark.parametrize("text,key", [
    ("Без обязательного завтрака", "breakfast"),
    ("Без обязательного бассейна", "pool"),
])
def test_without_required_amenity_is_neutral(text, key):
    assert parse_rules(text).patch[key] is False


@pytest.mark.parametrize("text,key", [
    ("Лучше без завтрака", "breakfast"),
    ("Желательно без бассейна", "pool"),
])
def test_preferred_without_amenity_does_not_enable_it(text, key):
    result = parse_rules(text, TripRequirements(preference_modes={key: "preferred"}))
    assert result.patch[key] is False
    assert key not in result.patch.get("preference_modes", {})


@pytest.mark.parametrize("text,key", [
    ("Без завтрака не рассматриваю", "breakfast"),
    ("Без бассейна не подходит", "pool"),
])
def test_explicit_rejection_of_missing_amenity_is_required(text, key):
    req = TripRequirements(preference_modes={key: "preferred"})
    result = parse_rules(text, req)
    assert result.patch[key] is True
    assert result.patch["preference_modes"][key] == "required"


def test_date_shift_and_absolute_duration_are_both_applied():
    result = parse_rules("На два дня позже, но на 5 ночей", TripRequirements(check_in="2026-11-06"))
    assert result.patch == {"check_in": "2026-11-08", "nights": 5}


def test_contradictory_amenity_asks_without_applying_partial_changes():
    req = TripRequirements(breakfast=True, budget=180000)
    result = parse_rules("Бюджет 200 тысяч, завтрак обязателен, но завтрак не нужен", req)
    assert result.patch == {}
    assert any(q["field"] == "breakfast" for q in result.questions)


@pytest.mark.parametrize("text,key,value", [
    ("Будет ли дешевле без завтрака?", "breakfast", False),
    ("Что изменится без завтрака?", "breakfast", False),
    ("Можно ли с собакой?", "pets", True),
])
def test_comparison_and_eligibility_questions_are_pure(text, key, value, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "unused")
    monkeypatch.setenv("LLM_MODEL", "unused")
    def forbidden(**kwargs):
        raise AssertionError("Pure questions must stay local")
    monkeypatch.setattr("app.parser.httpx.AsyncClient", forbidden)
    result = asyncio.run(extract_intent(text, TripRequirements(breakfast=True), TODAY))
    assert result.hypothetical
    assert result.patch == {}
    assert result.hypothetical_patch[key] is value


@pytest.mark.parametrize("text", [
    "Если убрать завтрак, будет дешевле?",
    "Если убрать завтрак, как изменится стоимость?",
])
def test_leading_conditional_comparison_is_pure(text, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "unused")
    monkeypatch.setenv("LLM_MODEL", "unused")
    def forbidden(**kwargs):
        raise AssertionError("Comparison questions must stay local")
    monkeypatch.setattr("app.parser.httpx.AsyncClient", forbidden)
    result = asyncio.run(extract_intent(text, TripRequirements(breakfast=True), TODAY))
    assert result.hypothetical and result.patch == {}
    assert result.hypothetical_patch == {"breakfast": False}


def test_polite_conditional_imperative_is_applied():
    result = parse_rules("Если можно, добавь завтрак")
    assert not result.hypothetical
    assert result.patch["breakfast"] is True


def test_contradiction_question_names_amenity_in_russian():
    result = parse_rules("Завтрак обязателен, но завтрак не нужен")
    assert "Завтрак" in result.questions[0]["question"]


def test_contradiction_does_not_apply_later_location_recognizer():
    result = parse_rules("Завтрак обязателен, но завтрак не нужен, в Адлер")
    assert result.patch == {}
    assert result.questions


def test_hypothetical_skips_optional_provider(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "unused")
    monkeypatch.setenv("LLM_MODEL", "unused")
    def forbidden(**kwargs):
        raise AssertionError("Hypothetical must stay local")
    monkeypatch.setattr("app.parser.httpx.AsyncClient", forbidden)
    result = asyncio.run(extract_intent("Что изменится, если убрать завтрак?", TripRequirements(breakfast=True), TODAY))
    assert result.hypothetical and not result.patch


@pytest.mark.parametrize("patch", [
    {"preference_modes": {"pets": "preferred"}},
    {"preference_modes": {"breakfast": "optional"}},
    {"preference_modes": {"pool": "preferred"}},
    {"budget": 180000},
    {"budget": 999999},
])
def test_untrusted_model_cannot_backfill_or_change_unmentioned_modes(monkeypatch, patch):
    monkeypatch.setenv("LLM_API_KEY", "unused")
    monkeypatch.setenv("LLM_MODEL", "unused")
    class FakeClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, url, **kwargs):
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "choices": [{"message": {"content": json.dumps({"patch": patch})}}],
            })
    monkeypatch.setattr("app.parser.httpx.AsyncClient", FakeClient)
    result = asyncio.run(extract_intent("Бюджет тот же, лучше с завтраком", TripRequirements(budget=180000), TODAY))
    assert result.patch == {"breakfast": True, "preference_modes": {"breakfast": "preferred"}}
    assert result.mode == "rules"


@pytest.mark.parametrize("text,key,value", [
    ("Рейтинг неважен", "min_rating", 0),
    ("Убери требование звезд", "stars", 0),
    ("Расстояние до пляжа неважно", "max_beach_m", None),
])
def test_numeric_neutral_values_validate(text, key, value):
    req = TripRequirements(min_rating=9, stars=4, max_beach_m=300)
    result = parse_rules(text, req)
    assert result.patch[key] == value
    TripRequirements.model_validate(req.model_dump() | result.patch)


@pytest.mark.parametrize("message", [
    "2 взрослых и двое детей",
    "2 взрослых и двое детей 5 лет",
    "С нами ребенок 5 лет и ребенок",
])
def test_child_questions_retain_known_count_and_offer_no_single_child_answer(message):
    result = parse_rules(message)
    questions = [q for q in result.questions if q["field"] == "children_ages"]
    assert questions
    assert "children_ages" not in result.patch
    assert all(q["expected_count"] == 2 for q in questions)
    assert all(len(option["value"]) == 2 for q in questions for option in q["options"])


@pytest.mark.parametrize("text,value", [
    ("Рейтинг от 10, до 0 м до моря", 10),
    ("Рейтинг от 10.0", 10),
    ("Рейтинг от 9.55", 9.55),
    ("Рейтинг от 11", 11),
])
def test_rating_is_complete_numeric_value_never_prefix(text, value):
    result = parse_rules(text)
    assert result.patch["min_rating"] == value
    assert "check_in" not in result.patch
    if value > 10:
        with pytest.raises(ValueError):
            TripRequirements.model_validate(TripRequirements().model_dump() | result.patch)


@pytest.mark.parametrize("message,expected", [
    ("Добавь ребёнка 4 лет", [6, 4]),
    ("Ещё одного ребёнка 4 лет", [6, 4]),
    ("Добавь двоих детей 4 и 9 лет", [6, 4, 9]),
])
def test_additional_children_append_known_ages(message, expected):
    req = TripRequirements(children_ages=[6])
    result = parse_rules(message, req)
    assert result.patch["children_ages"] == expected
    assert req.children_ages == [6]


@pytest.mark.parametrize("message,count", [
    ("Добавь ребёнка", 1),
    ("Ещё одного ребёнка", 1),
    ("Добавь двух детей", 2),
    ("Добавь двух детей 4 лет", 2),
])
def test_additional_unknown_children_question_preserves_prior_guests(message, count):
    req = TripRequirements(children_ages=[6])
    result = parse_rules(message, req)
    assert "children_ages" not in result.patch
    question = next(q for q in result.questions if q["field"] == "children_ages")
    assert question["existing_ages"] == [6]
    assert question["additional_count"] == count
    assert question["expected_count"] == 1 + count
    assert question["options"] == []


def test_explicit_full_children_list_still_replaces():
    result = parse_rules("Дети 5 и 9 лет", TripRequirements(children_ages=[6]))
    assert result.patch["children_ages"] == [5, 9]


@pytest.mark.parametrize("message", ["Ребёнку 7 лет", "Сыну 7 лет"])
def test_singular_age_edit_does_not_remove_other_children(message):
    result = parse_rules(message, TripRequirements(children_ages=[6, 10]))
    assert "children_ages" not in result.patch
    question = next(q for q in result.questions if q["field"] == "children_ages")
    assert question["expected_count"] == 2
    assert question["options"] == []


@pytest.mark.parametrize("message,ages", [
    ("Теперь один ребёнок 7 лет", [7]),
    ("Дети 7 и 10 лет", [7, 10]),
])
def test_explicit_new_guest_count_or_complete_ages_can_replace(message, ages):
    result = parse_rules(message, TripRequirements(children_ages=[6, 10]))
    assert result.patch["children_ages"] == ages


def test_preserved_budget_does_not_become_incidental_surcharge():
    result = parse_rules("Бюджет тот же, добавь собаку, доплата 5 тысяч", TripRequirements(budget=180000))
    assert result.patch == {"pets": True}


@pytest.mark.parametrize("message", [
    "Бюджет тот же, но бюджет 200 тысяч",
    "Бюджет тот же, но до 200 тысяч",
    "Бюджет тот же, но увеличь бюджет на 20 тысяч",
])
def test_conflicting_preserved_and_revised_budget_asks(message):
    result = parse_rules(message, TripRequirements(budget=180000))
    assert result.patch == {}
    assert any(q["field"] == "budget" for q in result.questions)
