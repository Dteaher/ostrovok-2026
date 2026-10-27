"""Independent regressions for ordinary language that must not silently alter a trip."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta

import pytest

from app.parser import parse_rules
from app.service import local_today, new_state, process_message
from app.storage import Database, StaleRevision


def test_budget_scope_does_not_change_flight_to_train():
    result = parse_rules("Бюджет 180 тысяч на всю поездку")
    assert result.patch.get("transport", "flight") == "flight"


def test_beach_distance_is_not_a_budget():
    result = parse_rules("До моря до 300 метров")
    assert result.patch.get("max_beach_m") == 300
    assert "budget" not in result.patch


@pytest.mark.parametrize(
    "message,field",
    [
        ("Без бесплатной отмены", "refundable"),
        ("Не хочу с завтраком", "breakfast"),
    ],
)
def test_common_negations_do_not_enable_the_rejected_feature(message, field):
    result = parse_rules(message)
    assert result.patch.get(field) is not True


def test_repeated_month_date_range_is_not_silently_seven_nights():
    result = parse_rules("С 6 ноября по 9 ноября", today=date(2026, 10, 27))
    assert result.patch.get("nights") == 3 or result.questions


def test_total_people_including_child_is_not_all_adults_plus_child():
    result = parse_rules("Нас трое, включая ребенка 6 лет")
    assert result.patch.get("adults") == 2 or result.questions


def test_missing_second_child_age_requires_clarification():
    result = parse_rules("2 взрослых и двое детей 5 лет")
    assert result.questions or len(result.patch.get("children_ages", [])) == 2


@pytest.mark.parametrize(
    "message",
    [
        "Лучше в Прагу на 5 ночей",
        "Хочу отель только для взрослых с завтраком",
        "Вылет из Новосибирска, бюджет 180 тысяч",
    ],
)
def test_partly_understood_mandatory_change_does_not_claim_full_match(message, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    day = local_today() + timedelta(days=35)

    async def journey():
        state = await process_message(
            new_state(), f"В Сочи с {day.isoformat()} на 7 ночей вдвоем до 180 тысяч"
        )
        assert state["plans"]
        return await process_message(state, message)

    result = asyncio.run(journey())
    assert not result["plans"], result["assistant_message"]


def test_simultaneous_storage_updates_have_only_one_winner(tmp_path):
    database = Database("sqlite:///" + (tmp_path / "race.db").as_posix())
    database.initialize()
    state = new_state()
    database.create(state)

    def update(value):
        changed = deepcopy(state)
        changed["revision"] = 2
        changed["requirements"]["budget"] = value
        try:
            database.save(changed, expected=1)
            return True
        except StaleRevision:
            return False

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(update, [100000, 200000])) == [False, True]
        assert database.load(state["id"])["revision"] == 2
    finally:
        database.close()


def test_simultaneous_checkout_returns_one_persistent_order(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from app.main import create_app
    from app.storage import orders

    app = create_app("sqlite:///" + (tmp_path / "checkout-race.db").as_posix())
    with TestClient(app) as client:
        day = local_today() + timedelta(days=35)
        state = client.post(
            "/api/sessions",
            json={"message": f"В Сочи с {day.isoformat()} на 7 ночей вдвоем до 180 тысяч"},
        ).json()
        selected = client.post(
            f"/api/sessions/{state['id']}/select",
            json={"revision": state["revision"], "plan_id": state["plans"][0]["id"]},
        ).json()
        payload = {
            "revision": selected["revision"],
            "accept_demo": True,
            "traveler_name": "Анна Иванова",
            "email": "anna@example.com",
        }

        def checkout(_):
            return client.post(f"/api/sessions/{state['id']}/checkout", json=payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(checkout, range(2)))
        assert [response.status_code for response in replies] == [200, 200]
        assert replies[0].json()["order"] == replies[1].json()["order"]
        restored = client.get(f"/api/sessions/{state['id']}").json()
        assert restored["order"] == replies[0].json()["order"]
        with app.state.db.engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(orders)) == 1
