import asyncio
from datetime import date

import httpx
import pytest


def test_forecast_never_relabels_current_weather_as_trip_weather():
    from app.destination_context import weather_view
    data = {"current": {"temperature_2m": 20, "time": "2026-10-28T12:00"}, "daily": {
        "time": ["2026-10-28", "2026-10-29"], "temperature_2m_max": [21, 22],
        "temperature_2m_min": [14, 15], "precipitation_probability_max": [10, 20],
        "weather_code": [0, 3]}}
    result = weather_view(data, date(2026, 12, 20), 7)
    assert result["days"] == [] and result["coverage"] == "outside_forecast"
    assert result["current"]["temperature_c"] == 20
    partial = weather_view(data, date(2026, 10, 29), 7)
    assert len(partial["days"]) == 1 and partial["coverage"] == "partial"


def test_history_ignores_null_and_is_explicitly_not_forecast():
    from app.destination_context import history_view
    result = history_view({"daily": {"temperature_2m_max": [10, None, 14],
        "temperature_2m_min": [2, 4, None], "precipitation_sum": [1, 2, 0]}}, "2025-12")
    assert result["mean_high_c"] == 12
    assert result["mean_low_c"] == 3
    assert result["kind"] == "historical_month" and result["month"] == "2025-12"


def test_poi_links_are_generated_from_osm_ids_not_untrusted_websites():
    from app.destination_context import places_view
    data = {"elements": [{"type": "node", "id": 123, "lat": 43.6, "lon": 39.7,
        "tags": {"tourism": "museum", "name": "Музей", "website": "javascript:alert(1)"}},
        {"type": "way", "id": 456, "center": {"lat": 43.7, "lon": 39.8},
         "tags": {"railway": "station", "name": "Вокзал"}}]}
    result = places_view(data)
    assert result["attractions"][0]["url"] == "https://www.openstreetmap.org/node/123"
    assert len(result["transport_points"]) == 1


def test_partial_overpass_results_are_not_presented_as_complete():
    from app.destination_context import places_view
    with pytest.raises(ValueError):
        places_view({"remark": "runtime error: Query timed out", "elements": []})


def test_service_caches_geocoding_and_handles_one_provider_failure():
    from app.destination_context import DestinationContext
    counts = {}
    def handler(request):
        host = request.url.host
        counts[host] = counts.get(host, 0) + 1
        if host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json={"results": [{"name": "Сочи", "latitude": 43.6,
                "longitude": 39.7, "country_code": "RU", "timezone": "Europe/Moscow"}]})
        if host == "api.open-meteo.com":
            return httpx.Response(200, json={"current": {"temperature_2m": 20}, "daily": {"time": []}})
        return httpx.Response(503)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = DestinationContext(client)
            first = await service.get("Сочи", None, 7, "Москва")
            second = await service.get("Сочи", None, 7, "Москва")
            assert first["location"]["name"] == "Сочи"
            assert first["weather"]["status"] == "ok"
            assert first["places"]["status"] == "unavailable"
            assert second["weather"] == first["weather"]
            assert counts["geocoding-api.open-meteo.com"] == 2  # destination and origin
    asyncio.run(run())


def test_read_only_endpoint_checks_revision_and_never_alters_trip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.destination_context import DestinationContext
    from app.main import create_app
    from tests.test_request_latency import ready
    async def context(self, destination, check_in, nights, origin):
        return {"status": "ok", "location": {"name": destination}, "weather": {"status": "unavailable"}}
    monkeypatch.setattr(DestinationContext, "get", context)
    with TestClient(create_app("sqlite:///" + str(tmp_path / "context.db"))) as client:
        state = ready()
        client.app.state.db.create(state)
        url = f"/api/sessions/{state['id']}"
        result = client.get(url + "/destination-context?revision=1")
        assert result.status_code == 200 and result.json()["revision"] == 1
        after = client.get(url).json()
        assert after["revision"] == 1 and after["requirements"] == state["requirements"]
        assert after["order"] is None
        assert client.get(url + "/destination-context?revision=2").status_code == 409


def test_stale_endpoint_cannot_publish_after_trip_edit(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.destination_context import DestinationContext
    from app.main import create_app
    from tests.test_request_latency import ready
    app = create_app("sqlite:///" + str(tmp_path / "context.db"))
    state = ready()
    async def context(self, *args):
        state["revision"] = 2
        app.state.db.save(state, expected=1)
        return {"status": "ok", "location": {"name": "Сочи"}}
    monkeypatch.setattr(DestinationContext, "get", context)
    with TestClient(app) as client:
        app.state.db.create(state)
        assert client.get(f"/api/sessions/{state['id']}/destination-context?revision=1").status_code == 409
