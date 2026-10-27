from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from app.models import TripRequirements, search_terms
from app.search import find_plan, search, validate_plan


def req(**changes):
    return TripRequirements.model_validate(
        {
            "destination": "Сочи",
            "check_in": date(2027, 6, 14),
            "budget": 400000,
            **changes,
        }
    )


def test_preference_modes_are_bounded_and_legacy_defaults_survive():
    assert req().preference_modes == {}
    for modes in ({"pets": "preferred"}, {"budget": "preferred"}, {"pool": "maybe"}):
        with pytest.raises(ValidationError):
            req(preference_modes=modes)
    cleared = req(
        pool=False,
        min_rating=0,
        max_beach_m=None,
        preference_modes={"pool": "required", "min_rating": "preferred"},
    )
    assert search(cleared)["plans"]


def test_preferred_conditions_rank_without_filtering_and_explain_actual_tariff():
    preferred = req(
        pool=True,
        breakfast=True,
        refundable=True,
        min_rating=9.5,
        preference_modes={
            k: "preferred" for k in ("pool", "breakfast", "refundable", "min_rating")
        },
    )
    result = search(preferred, 100)
    assert result["total_matches"] == search(req(), 100)["total_matches"]
    assert result["plans"][0]["preference_matches"]
    for plan in result["plans"]:
        assert validate_plan(plan, preferred) == []
        if plan["meal"] != "Завтрак включён":
            assert not any("Завтрак включён" in reason for reason in plan["reasons"])
            assert any("Завтрак" in reason for reason in plan["preference_compromises"])
        if "pool" not in plan["hotel"]["features"]:
            assert "Бассейн на территории" not in plan["reasons"]
    tampered = deepcopy(result["plans"][0])
    tampered["preference_matches"] = ["Выдумка"]
    assert validate_plan(tampered, preferred)


def test_required_quiet_and_legacy_pool_filter():
    from app.catalog import HOTELS_BY_ID

    hard = search(req(quiet=True, preference_modes={"quiet": "required"}), 100)
    assert hard["plans"]
    assert all(HOTELS_BY_ID[p["hotel"]["id"]]["quietness"] >= 8 for p in hard["plans"])
    assert search(req(quiet=True), 100)["total_matches"] > hard["total_matches"]
    assert all("pool" in p["hotel"]["features"] for p in search(req(pool=True), 100)["plans"])


def test_conflicting_pair_suggestions_are_verified_with_exact_prices():
    original = req(max_beach_m=0, min_rating=10)
    result = search(original)
    assert result["diagnostic"]["kind"] == "constraints"
    assert result["suggestions"]
    assert all(len(item["patch"]) == 2 for item in result["suggestions"])
    for item in result["suggestions"]:
        updated = req(**{**original.model_dump(), **item["patch"]})
        verified = search(updated, 100)
        assert verified["total_matches"] == item["total_matches"] > 0
        assert min(p["price"]["total"] for p in verified["plans"]) == item["min_total"]


def test_pinned_hotel_conflict_preserves_identity_in_suggestions():
    original = req(pool=True)
    result = search(original, hotel_id="h09")
    assert not result["plans"]
    assert result["diagnostic"]["kind"] == "pinned_hotel_conflict"
    assert result["suggestions"]
    for item in result["suggestions"]:
        updated = req(**{**original.model_dump(), **item["patch"]})
        verified = search(updated, 100, hotel_id="h09")
        assert {p["hotel"]["id"] for p in verified["plans"]} == {"h09"}
    plan = search(req())["plans"][0]
    assert find_plan(req(), plan["id"], hotel_id="missing") is None
    assert search(req(), hotel_id="missing")["diagnostic"]["kind"] == "pinned_hotel_conflict"


def test_pets_accessibility_and_dates_are_never_relaxation_levers():
    impossible = req(pets=True, accessible=True, max_beach_m=0, min_rating=10)
    for item in search(impossible)["suggestions"]:
        assert not {"pets", "accessible", "origin", "check_in"} & item["patch"].keys()


def test_pinned_inventory_failure_is_availability(monkeypatch):
    from app.catalog import HOTELS_BY_ID

    monkeypatch.setitem(HOTELS_BY_ID["h01"], "inventory", 0)
    result = search(req(), hotel_id="h01")
    assert not result["plans"]
    assert result["diagnostic"]["kind"] == "availability"
    assert not result["suggestions"]


def test_preferred_breakfast_can_fall_back_within_strict_budget_and_pet_fee():
    original = req(
        destination="Адлер",
        pets=True,
        budget_scope="hotel",
        budget=25100,
        breakfast=True,
        preference_modes={"breakfast": "preferred"},
    )
    result = search(original, hotel_id="h09")
    assert result["total_matches"] == 1
    plan = result["plans"][0]
    assert plan["meal"] == "Без питания"
    assert plan["price"]["hotel"] + plan["price"]["extras"] == 25100
    assert plan["preference_compromises"] == ["Завтрак не включён"]
    assert validate_plan(plan, original) == []


def test_single_suggestions_precede_pairs_and_include_verified_hotel_budget_prices():
    original = req(destination="Адлер", pets=True, budget_scope="hotel", budget=23000)
    suggestions = search(original)["suggestions"]
    assert suggestions[0]["patch"] == {"budget": 25100}
    for item in suggestions:
        assert len(item["patch"]) == 1
        updated = req(**{**original.model_dump(), **item["patch"]})
        verified = search(updated, 100)
        assert verified["total_matches"] == item["total_matches"]
        assert min(p["price"]["total"] for p in verified["plans"]) == item["min_total"]


@pytest.mark.parametrize(
    "changes,kind",
    [
        ({"destination": "Казань"}, "unsupported_destination"),
        ({"origin": "Казань"}, "unsupported_input"),
        ({"budget": 1000}, "budget"),
        ({"max_beach_m": 0}, "constraints"),
    ],
)
def test_empty_search_diagnostics_are_specific(changes, kind):
    result = search(req(**changes))
    assert not result["plans"]
    assert result["diagnostic"]["kind"] == kind
    assert "демо" in result["diagnostic"]["message"]


def test_elapsed_schedule_suggestions_are_verified_and_require_consent(monkeypatch):
    import importlib
    from datetime import UTC, datetime

    module = importlib.import_module("app.search")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2030, 10, 27, 12, tzinfo=UTC)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", Clock)
    original = req(check_in=date(2030, 10, 27), transport="train")
    result = search(original, hotel_id="h01")
    assert result["suggestions"]
    for item in result["suggestions"]:
        assert item["patch"] == {"check_in": "2030-10-29"}
        assert "согласия" in item["label"]
        changed = req(**{**original.model_dump(), **item["patch"]})
        verified = search(changed, 100, hotel_id="h01")
        assert verified["total_matches"] == item["total_matches"] > 0
        assert min(p["price"]["total"] for p in verified["plans"]) == item["min_total"]
    assert original.check_in == date(2030, 10, 27)
    assert not search(req(check_in=None))["suggestions"]


def test_unsupported_requests_do_not_offer_pairs_of_unrelated_relaxations():
    result = search(req(unsupported=["Аквапарк в номере"], max_beach_m=0))
    assert not result["suggestions"]


def test_lowest_price_label_never_overstates_preferred_tariff():
    original = req(breakfast=True, preference_modes={"breakfast": "preferred"})
    result = search(original, hotel_id="h09")
    assert result["plans"][0]["meal"] == "Завтрак включён"
    assert "Самая низкая цена" not in result["plan_labels"].values()


def test_search_min_total_includes_cheaper_canonical_tariffs_than_soft_preferred_display():
    original = req(breakfast=True, preference_modes={"breakfast": "preferred"})
    result = search(original, hotel_id="h09")
    displayed = result["plans"][0]
    base = search(req(), hotel_id="h09")["plans"][0]
    assert result["min_total"] == base["price"]["total"] < displayed["price"]["total"]
    from app.search import _candidates

    eligible, _ = _candidates(original, hotel_id="h09")
    cheapest = min(eligible, key=lambda plan: plan["price"]["total"])
    canonical = find_plan(original, cheapest["id"], hotel_id="h09")
    assert canonical is not None
    assert canonical["meal"] == "Без питания"
    assert canonical["price"]["total"] == result["min_total"]
    assert validate_plan(canonical, original) == []
    assert search(req(max_beach_m=0))["min_total"] is None


def test_assumption_provenance_does_not_invalidate_semantically_identical_quote():
    original = req(assumptions=["Предполагаем двух взрослых"])
    confirmed = req(assumptions=[])
    plan = search(original)["plans"][0]
    assert find_plan(confirmed, plan["id"]) == plan
    assert validate_plan(plan, confirmed) == []
    assert {p["id"] for p in search(original, 100)["plans"]} == {
        p["id"] for p in search(confirmed, 100)["plans"]
    }


@pytest.mark.parametrize(
    "values,modes",
    [
        ({"breakfast": True}, {"breakfast": "required"}),
        ({"breakfast": False}, {"breakfast": "preferred"}),
        ({"quiet": True}, {"quiet": "preferred"}),
        ({"max_beach_m": None, "stars": 0}, {"max_beach_m": "preferred", "stars": "preferred"}),
    ],
)
def test_default_or_inactive_modes_preserve_semantic_terms_and_canonical_quotes(values, modes):
    implicit = req(**values)
    explicit = req(**values, preference_modes=modes)
    assert search_terms(implicit) == search_terms(explicit)
    assert search(implicit, 100)["plans"] == search(explicit, 100)["plans"]
    plan = search(implicit)["plans"][0]
    assert find_plan(explicit, plan["id"]) == plan
    assert validate_plan(plan, explicit) == []


def test_search_terms_retain_actual_values_unsupported_and_meaningful_modes():
    original = req(
        breakfast=True,
        quiet=True,
        unsupported=["Особое условие"],
        assumptions=["Допущение"],
        preference_modes={"breakfast": "preferred", "quiet": "required"},
    )
    terms = search_terms(original)
    assert terms["breakfast"] is True
    assert terms["quiet"] is True
    assert terms["preference_modes"] == {"breakfast": "preferred", "quiet": "required"}
    assert terms["unsupported"] == ["Особое условие"]
    assert "assumptions" not in terms


def test_diagnostic_budget_requires_an_available_candidate_despite_other_failures(monkeypatch):
    from app.catalog import HOTELS_BY_ID

    monkeypatch.setitem(HOTELS_BY_ID["h01"], "inventory", 0)
    original = req(destination="Хоста", pool=True, budget=1000)
    result = search(original)
    assert {"budget", "occupancy", "pool"} <= result["rejected"].keys()
    assert result["diagnostic"]["kind"] == "budget"
    monkeypatch.setitem(HOTELS_BY_ID["h12"], "inventory", 0)
    result = search(original)
    assert "budget" not in result["rejected"]
    assert result["diagnostic"]["kind"] == "availability"
