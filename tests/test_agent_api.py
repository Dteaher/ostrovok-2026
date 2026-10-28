from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import create_app
from app.service import local_today


def test_persistent_history_tools_and_checkout_do_not_bypass_revision_or_consent(tmp_path):
    app = create_app("sqlite:///" + str(tmp_path / "agent.db"))
    day = local_today() + timedelta(days=45)
    with TestClient(app) as client:
        state = client.post("/api/sessions", json={"message": f"В Сочи с {day.isoformat()} на 7 ночей, двое взрослых, бюджет 500 тысяч, с завтраком"}).json()
        assert state["agent"]["facts"]
        session_id = state["id"]
        def message(text):
            nonlocal state
            response = client.post(f"/api/sessions/{session_id}/messages", json={"message": text, "revision": state["revision"]})
            assert response.status_code == 200
            state = response.json()
        message("На два дня позже")
        message("Добавь собаку")
        # Load back from the database before restoration: history is server-side.
        state = client.get(f"/api/sessions/{session_id}").json()
        message("Верни первоначальные даты")
        assert state["requirements"]["check_in"] == day.isoformat()
        assert state["requirements"]["pets"] is True
        old_revision = state["revision"]
        message("Сравни первый и второй отель")
        assert state["agent"]["tool"] == "compare"
        assert client.post(f"/api/sessions/{session_id}/messages", json={"message": "Покажи дешевле", "revision": old_revision}).status_code == 409
        state = client.post(f"/api/sessions/{session_id}/select", json={"plan_id": state["plans"][0]["id"], "revision": state["revision"]}).json()
        message("Оформи поездку")
        assert state["order"] is None and state["stage"] == "selected"
        assert state["agent"] is None  # form instructions must not be hidden by old comparison
        payload = {"revision": state["revision"], "accept_demo": True, "traveler_name": "Demo Guest", "email": "demo@example.com"}
        booked = client.post(f"/api/sessions/{session_id}/checkout", json=payload)
        assert booked.status_code == 200
        repeated = client.post(f"/api/sessions/{session_id}/checkout", json=payload)
        assert repeated.json()["order"]["id"] == booked.json()["order"]["id"]


def test_direct_patch_invalidates_old_explanation(tmp_path):
    with TestClient(create_app("sqlite:///" + str(tmp_path / "agent.db"))) as client:
        day = local_today() + timedelta(days=45)
        state = client.post("/api/sessions", json={"message": f"В Сочи с {day.isoformat()} на 7 ночей, бюджет 500 тысяч"}).json()
        assert state["agent"]["facts"]
        changed = client.patch(f"/api/sessions/{state['id']}/requirements", json={"revision": state["revision"], "patch": {"nights": 5}})
        assert changed.status_code == 200
        result = changed.json()
        assert result["agent"]["facts"]
        new_ids = {p["id"] for p in result["plans"]}
        assert all(not fact["source"].get("plan_id") or fact["source"]["plan_id"] in new_ids for fact in result["agent"]["facts"])
        assert not new_ids.intersection({p["id"] for p in state["plans"]})
