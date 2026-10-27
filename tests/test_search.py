import importlib
from copy import deepcopy
from datetime import UTC, date, datetime

import pytest

from app.models import TripRequirements
from app.search import find_plan, search, validate_plan


def requirements(**changes):
    return TripRequirements(
        destination="Сочи", check_in=date(2027, 6, 14), budget=400_000, **changes
    )


def test_returns_three_distinct_complete_reproducible_plans_without_mutation():
    req = requirements(children_ages=[5, 12])
    original = req.model_dump()
    result = search(req)
    assert result == search(req)
    assert req.model_dump() == original
    assert len(result["plans"]) == 3
    assert len({p["hotel"]["id"] for p in result["plans"]}) == 3
    for plan in result["plans"]:
        assert plan["price"]["total"] == sum(
            plan["price"][key] for key in ("hotel", "transport", "transfer", "extras")
        )
        assert plan["price"]["transport"] > 0
        assert plan["price"]["transfer"] > 0
        assert plan["room"]["rooms"] * plan["room"]["capacity"] >= 4
        assert plan["dates"]["check_out"] == "2027-06-21"
        assert plan["timeline"] and plan["reasons"] and plan["warnings"]
        assert "демо" in plan["data_label"].lower()
        assert validate_plan(plan, req) == []


def test_hard_constraints_are_all_enforced_but_quiet_is_soft():
    req = requirements(
        breakfast=True,
        refundable=True,
        pets=True,
        pool=True,
        accessible=True,
        max_beach_m=500,
        min_rating=8.5,
        stars=4,
        quiet=True,
    )
    result = search(req)
    assert result["plans"]
    for plan in result["plans"]:
        assert plan["meal"] == "Завтрак включён"
        assert plan["refundable"]
        assert plan["hotel"]["beach_m"] <= 500
        assert plan["hotel"]["rating"] >= 8.5
        assert plan["hotel"]["stars"] >= 4
        assert {"pets", "pool", "accessible"} <= set(plan["hotel"]["features"])
        assert validate_plan(plan, req) == []


def test_all_guests_and_rooms_change_total_and_identifiers():
    pair = search(requirements())["plans"][0]
    family = search(requirements(adults=3, children_ages=[8, 14]))["plans"][0]
    assert family["room"]["rooms"] >= 2
    assert family["price"]["transport"] > pair["price"]["transport"]
    assert family["id"] != pair["id"]
    date_changed = search(
        TripRequirements(destination="Сочи", check_in=date(2027, 6, 15), budget=400_000)
    )
    assert {p["id"] for p in date_changed["plans"]}.isdisjoint({pair["id"]})


def test_find_plan_covers_candidates_beyond_display_limit():
    req = requirements()
    all_plans = search(req, limit=100)["plans"]
    assert len(all_plans) >= 10
    assert find_plan(req, all_plans[-1]["id"]) == all_plans[-1]
    assert find_plan(requirements(breakfast=True), all_plans[-1]["id"]) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["price"].update(total=1),
        lambda p: p["price"].update(transport=0),
        lambda p: p["guests"].update(adults=1),
        lambda p: p["dates"].update(check_out="2027-06-30"),
        lambda p: p["room"].update(rooms=0),
        lambda p: p["transport"].update(arrival="2027-06-30T12:00:00"),
        lambda p: p["transport"].update(return_departure="2027-06-14T12:00:00"),
        lambda p: p["hotel"].update(features=["pets", "pool", "accessible"]),
        lambda p: p["dates"].update(check_in="2027-06-15"),
        lambda p: p["dates"].update(nights=1),
        lambda p: p["transport"].update(return_departure="2027-06-21T08:00:00"),
        lambda p: p["transport"].update(title="Настоящий подтверждённый билет"),
        lambda p: p.update(policy="Полный возврат в любое время"),
        lambda p: p.update(meal="Завтрак включён"),
        lambda p: p.update(reasons=["Выдуманное преимущество"]),
        lambda p: p.update(compromises=[]),
        lambda p: p.update(score=999),
    ],
)
def test_validation_rejects_tampering_independently(mutate):
    req = requirements()
    plan = deepcopy(search(req)["plans"][0])
    mutate(plan)
    assert validate_plan(plan, req)


def test_missing_or_unsupported_requirements_never_produce_fake_routes():
    assert not search(TripRequirements())["plans"]
    assert not search(requirements(origin="Новосибирск"))["plans"]
    assert search(requirements(origin="Новосибирск"))["suggestions"]
    assert not search(requirements(unsupported=["Нужен аквапарк в номере"]))["plans"]
    assert search(requirements(origin="Новосибирск", transport="self"))["plans"]


def test_transport_is_coherent_and_hotel_budget_scope_explicit():
    req = requirements(transport="train")
    plan = search(req)["plans"][0]
    assert plan["transport"]["departure"][:10] == "2027-06-13"
    assert plan["transport"]["arrival"][:10] == "2027-06-14"
    assert plan["transport"]["duration_minutes"] == 1500
    assert validate_plan(plan, req) == []
    hotel_only = TripRequirements(
        destination="Сочи",
        check_in=date(2027, 6, 14),
        budget=35_000,
        budget_scope="hotel",
    )
    plans = search(hotel_only)["plans"]
    assert plans
    assert all(p["price"]["hotel"] <= 35_000 for p in plans)
    assert any(p["price"]["total"] > 35_000 for p in plans)
    assert all(any("бюджет" in warning.lower() for warning in p["warnings"]) for p in plans)


def test_no_results_preserve_requirements_and_offer_explicit_relaxation():
    req = requirements(max_beach_m=0, breakfast=True)
    before = req.model_dump()
    result = search(req)
    assert result["plans"] == []
    assert result["counterfactuals"] == []
    assert result["suggestions"]
    assert req.model_dump() == before
    tiny = search(TripRequirements(destination="Сочи", check_in=date(2027, 6, 14), budget=1000))
    assert tiny["plans"] == [] and tiny["counterfactuals"] == []
    assert any(s["field"] == "budget" for s in tiny["suggestions"])


def test_counterfactuals_compare_same_scope_to_cheapest_strict_plan():
    req = requirements(breakfast=True, refundable=True, max_beach_m=200, min_rating=8.5)
    original = req.model_dump()
    result = search(req, limit=100)
    baseline = min(p["price"]["total"] for p in result["plans"])
    assert result["counterfactuals"]
    for item in result["counterfactuals"]:
        assert "value" in item
        assert item["baseline_total"] == baseline
        assert item["saving"] == baseline - item["alternative_total"] > 0
        relaxed = req.model_copy(
            update={
                item["field"]: {
                    "breakfast": False,
                    "refundable": False,
                    "max_beach_m": None,
                    "min_rating": 0,
                    "stars": 0,
                    "pets": False,
                    "pool": False,
                    "accessible": False,
                }[item["field"]]
            }
        )
        alternative = find_plan(relaxed, item["alternative_plan_id"])
        assert alternative is not None
        assert alternative["price"]["total"] == item["alternative_total"]
    assert req.model_dump() == original


def test_hand_calculated_entire_trip_quote_and_single_field_patch_value():
    req = TripRequirements(
        destination="Адлер",
        check_in=date(2027, 6, 14),
        budget=400_000,
        breakfast=True,
        refundable=True,
        pets=True,
    )
    hotel = next(p for p in search(req, limit=100)["plans"] if p["hotel"]["id"] == "h09")
    # Five 3000-ruble nights plus two 3300 weekends; 8400 breakfasts; 10% flex.
    assert hotel["price"] == {
        "hotel": 33000,
        "transport": 31200,
        "transfer": 2200,
        "extras": 3500,
        "total": 69900,
        "currency": "RUB",
    }
    for item in search(req)["counterfactuals"]:
        assert item["value"] is False


def test_each_room_needs_an_adult_and_inventory_covers_every_night():
    assert search(requirements(adults=1, children_ages=[3, 5, 8, 10, 12, 15]))["plans"] == []
    req = requirements(adults=8, children_ages=[3, 5, 8, 10, 12, 15])
    for plan in search(req, limit=100)["plans"]:
        assert plan["room"]["rooms"] <= 8
        assert plan["room"]["capacity"] * plan["room"]["rooms"] >= 14
        assert validate_plan(plan, req) == []


def test_hotel_budget_includes_mandatory_pet_fee_and_budget_suggestion():
    req = TripRequirements(
        destination="Адлер",
        check_in=date(2027, 6, 14),
        budget=23000,
        budget_scope="hotel",
        pets=True,
    )
    result = search(req)
    assert result["plans"] == []
    assert result["counterfactuals"] == []
    assert (
        next(item["value"] for item in result["suggestions"] if item["field"] == "budget") == 25100
    )
    req.budget = 25100
    hotel = next(p for p in search(req, limit=100)["plans"] if p["hotel"]["id"] == "h09")
    assert hotel["price"]["hotel"] + hotel["price"]["extras"] == 25100


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["hotel"].update(rating=10),
        lambda p: p["hotel"].update(stars=5),
        lambda p: p["hotel"].update(beach_m=0),
        lambda p: p["hotel"].update(id="h09"),
        lambda p: p["guests"].update(children_ages=[1]),
        lambda p: p["price"].update(
            hotel=p["price"]["hotel"] + 100, transport=p["price"]["transport"] - 100
        ),
    ],
)
def test_catalog_attributes_and_offset_price_tampering_are_rejected(mutate):
    req = requirements(children_ages=[8])
    plan = deepcopy(search(req)["plans"][0])
    mutate(plan)
    assert validate_plan(plan, req)


def test_past_dates_are_checked_in_moscow_timezone(monkeypatch):
    module = importlib.import_module("app.search")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2030, 10, 26, 22, 30, tzinfo=UTC)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", Clock)
    req = TripRequirements(destination="Сочи", check_in=date(2030, 10, 26), budget=400000)
    assert search(req)["plans"] == []


@pytest.mark.parametrize("mode", ["flight", "train"])
def test_elapsed_outbound_schedule_never_creates_a_bookable_plan(monkeypatch, mode):
    module = importlib.import_module("app.search")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2030, 10, 27, 12, tzinfo=UTC)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", Clock)
    req = TripRequirements(
        destination="Сочи", check_in=date(2030, 10, 27), budget=400000, transport=mode
    )
    result = search(req)
    assert result["plans"] == []
    assert any(item["field"] == "check_in" for item in result["suggestions"])


def test_expired_free_cancellation_is_not_sold_as_refundable(monkeypatch):
    module = importlib.import_module("app.search")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2030, 10, 27, 12, tzinfo=UTC)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", Clock)
    req = TripRequirements(
        destination="Сочи", check_in=date(2030, 10, 28), budget=400000, refundable=True
    )
    result = search(req)
    assert result["plans"] == []
    assert result["counterfactuals"] == []
    assert any(
        item["field"] == "refundable" and item["value"] is False for item in result["suggestions"]
    )


def test_three_display_choices_include_cheapest_and_keep_strong_fit_and_comfort():
    req = requirements()
    every = search(req, limit=100)["plans"]
    displayed = search(req)["plans"]
    cheapest = min(every, key=lambda p: (p["price"]["total"], p["id"]))
    assert cheapest["id"] in {plan["id"] for plan in displayed}
    assert cheapest["id"] in {p["id"] for p in displayed}
    assert displayed[0]["score"] == max(plan["score"] for plan in every)
    remaining = [p for p in every if p["id"] not in {displayed[0]["id"], cheapest["id"]}]
    assert displayed[2]["hotel"]["rating"] == max(p["hotel"]["rating"] for p in remaining)
    assert len({p["hotel"]["id"] for p in displayed}) == 3
    assert len({p["hotel"]["area"] for p in displayed}) >= 2
    assert all(find_plan(req, p["id"]) == p for p in displayed)
    assert all(validate_plan(p, req) == [] for p in displayed)


def test_quiet_fit_and_cheapest_remain_visible_together():
    req = requirements(quiet=True)
    every = search(req, limit=100)["plans"]
    displayed = search(req)["plans"]
    cheapest = min(every, key=lambda p: (p["price"]["total"], p["id"]))
    assert cheapest["id"] in {p["id"] for p in displayed}
    assert displayed[0]["score"] == max(p["score"] for p in every)
    assert set(p["id"] for p in search(req, limit=2)["plans"]) <= set(p["id"] for p in displayed)


def test_recommendation_labels_are_factual_and_separate_from_canonical_plans(monkeypatch):
    module = importlib.import_module("app.search")
    # Construct the edge case where the cheapest hotel also has the best fit score.
    monkeypatch.setitem(module.HOTELS_BY_ID["h13"], "rating", 10)
    req = requirements()
    result = search(req)
    all_plans = search(req, limit=100)["plans"]
    cheapest = min(all_plans, key=lambda p: (p["price"]["total"], p["id"]))
    assert result["plans"][0]["id"] == cheapest["id"]
    assert result["plan_labels"][cheapest["id"]] == "Самая низкая цена"
    assert len(result["plan_labels"]) == len(result["plans"]) == 3
    assert len({p["hotel"]["id"] for p in result["plans"]}) == 3
    for plan in result["plans"]:
        label = result["plan_labels"][plan["id"]]
        assert label in {"Самая низкая цена", "Высокий рейтинг", "Ближе к пожеланиям"}
        if label == "Высокий рейтинг":
            assert plan["hotel"]["rating"] == max(
                p["hotel"]["rating"] for p in all_plans if p["id"] != cheapest["id"]
            )
        assert find_plan(req, plan["id"]) == plan
        assert validate_plan(plan, req) == []
    one = search(
        TripRequirements(
            destination="Лазаревское", check_in=date(2027, 6, 14), budget=400000, max_beach_m=80
        )
    )
    assert len(one["plans"]) == 1
    assert list(one["plan_labels"].values()) == ["Самая низкая цена"]
