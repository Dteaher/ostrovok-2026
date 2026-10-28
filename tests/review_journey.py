"""Independent end-to-end HTTP review; run explicitly, no provider requests."""

import json
import os
import tempfile
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

os.environ.update(TRAVEL_MODE="local", LLM_API_KEY="", AGENT_ENABLED="0")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.service import local_today  # noqa: E402


def run():
    checked = []
    with (
        tempfile.TemporaryDirectory(prefix="rivane-review-") as temporary,
        TestClient(create_app(f"sqlite:///{Path(temporary) / 'review.db'}")) as client,
    ):
        day = local_today() + timedelta(days=45)
        response = client.post("/api/sessions", json={"message":
            f"В Сочи с {day.isoformat()} на 7 ночей, двое взрослых, "
            "бюджет 500 тысяч, завтрак желателен"})
        response.raise_for_status()
        state = response.json()
        assert len(state["plans"]) >= 3
        base = f"/api/sessions/{state['id']}"

        def message(text):
            nonlocal state
            result = client.post(base + "/messages", json={
                "message": text, "revision": state["revision"]})
            result.raise_for_status()
            state = result.json()

        before = deepcopy(state["requirements"])
        message("Сначала покажи дешевле, но завтрак обязателен")
        assert state["requirements"]["breakfast"] is True
        assert state["requirements"]["preference_modes"]["breakfast"] == "required"
        assert all(state["requirements"][key] == before[key]
                   for key in before if key not in {"breakfast", "preference_modes"})
        assert all("завтрак" in plan["meal"].lower() for plan in state["plans"])
        totals = [plan["price"]["total"] for plan in state["plans"]]
        assert totals == sorted(totals)
        checked.append("compound command: required breakfast and ascending price")

        expected = [plan["id"] for plan in state["plans"][1:3]]
        before = deepcopy(state["requirements"])
        message("Сравни второй и третий")
        fact = next(fact for fact in state["agent"]["facts"]
                    if fact["id"] == "comparison_price")
        assert fact["source"]["plan_ids"] == expected
        assert state["requirements"] == before
        checked.append("comparison refers to displayed second and third offers")

        selected = client.post(base + "/select", json={
            "revision": state["revision"], "plan_id": state["plans"][0]["id"]})
        selected.raise_for_status()
        state = selected.json()
        original = deepcopy(state["selected_plan"])
        message("Покажи сначала варианты ближе к морю")
        assert len({plan["hotel"]["id"] for plan in state["plans"]}) >= 3
        beaches = [plan["hotel"]["beach_m"] for plan in state["plans"]]
        assert beaches == sorted(beaches)
        assert state["selected_plan"] == original
        checked.append("sorting after selection keeps alternatives and selected plan")

        before = deepcopy(state["requirements"])
        message("Что будет, если на две ночи короче?")
        assert state["requirements"] == before
        assert state["selected_plan"] == original
        checked.append("hypothetical change leaves actual trip intact")

        changed = client.patch(base + "/requirements", json={
            "revision": state["revision"], "patch": {"nights": 5}})
        changed.raise_for_status()
        state = changed.json()
        assert state["selected_plan"] is None
        assert state["change_receipt"] is not None
        assert state["requirements"]["preference_modes"]["breakfast"] == "required"
        selected = client.post(base + "/select", json={
            "revision": state["revision"], "plan_id": state["plans"][0]["id"]})
        selected.raise_for_status()
        state = selected.json()
        checked.append("recalculation clears confirmation, retains mandatory breakfast")

        saved = client.post(base + "/checkout", json={
            "revision": state["revision"], "accept_demo": True})
        saved.raise_for_status()
        state = saved.json()
        order = deepcopy(state["order"])
        message("Что включено в стоимость и какие условия отмены?")
        assert state["order"] == order
        assert state["stage"] == "booked"
        assert state["agent"] and state["agent"]["facts"]
        restored = client.get(base)
        restored.raise_for_status()
        assert restored.json()["messages"] == state["messages"]
        assert restored.json()["order"] == order
        checked.append("saved plan answers factual questions; full history restores")
    print(json.dumps({"status": "passed", "checked": checked}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
