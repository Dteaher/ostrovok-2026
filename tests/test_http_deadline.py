import sqlite3
import threading
import time

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.main import create_app
from tests.test_request_latency import ready


def test_http_deadline_includes_database_contention_and_prevents_late_save(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.request_seconds", lambda *args: .08, raising=False)
    path = tmp_path / "locked.db"
    with TestClient(create_app("sqlite:///" + str(path))) as client:
        state = ready()
        client.app.state.db.create(state)
        connection = sqlite3.connect(path, check_same_thread=False)
        connection.execute("BEGIN IMMEDIATE")
        release = threading.Timer(.3, connection.rollback)
        release.start()
        try:
            started = time.monotonic()
            response = client.post(f"/api/sessions/{state['id']}/messages", json={
                "revision": state["revision"], "message": "Добавь собаку"})
            elapsed = time.monotonic() - started
        finally:
            release.join()
            connection.close()
        assert response.status_code == 504
        assert elapsed < .22
        after = client.get(f"/api/sessions/{state['id']}").json()
        assert after["revision"] == state["revision"]
        assert after["requirements"]["pets"] is False


def test_reader_lock_cannot_commit_a_trip_after_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.request_seconds", lambda *args: .14)
    path = tmp_path / "reader.db"
    with TestClient(create_app("sqlite:///" + str(path))) as client:
        state = ready()
        database = client.app.state.db
        database.create(state)
        def delayed_update(connection, cursor, statement, parameters, context, many):
            if statement.startswith("UPDATE travel_sessions"):
                time.sleep(.08)
        event.listen(database.engine, "before_cursor_execute", delayed_update)
        reader = sqlite3.connect(path, check_same_thread=False)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM travel_sessions").fetchall()
        release = threading.Timer(.19, reader.rollback)
        release.start()
        try:
            response = client.post(f"/api/sessions/{state['id']}/messages", json={
                "revision": 1, "message": "Добавь собаку"})
        finally:
            release.join()
            reader.close()
        # Wait until the detached storage worker also finished its commit/rollback.
        time.sleep(.1)
        assert response.status_code == 504
        after = client.get(f"/api/sessions/{state['id']}").json()
        assert after["revision"] == 1
        assert after["requirements"]["pets"] is False
