"""Read-only public travel data, isolated from catalogue/LLM and trip mutations."""

import asyncio
import calendar
import math
import time
from copy import deepcopy
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def source(name, url):
    return {"name": name, "url": url}


WEATHER_SOURCE = source("Open-Meteo · CC BY 4.0", "https://open-meteo.com/")
OSM_SOURCE = source("© OpenStreetMap contributors · ODbL", "https://www.openstreetmap.org/copyright")


def weather_view(data, check_in, nights):
    current = data.get("current") or {}
    daily = data.get("daily") or {}
    days = []
    for index, value in enumerate(daily.get("time", [])):
        day = date.fromisoformat(value)
        if check_in and not check_in <= day < check_in + timedelta(days=nights):
            continue
        row = {"date": value}
        for remote, local in [("temperature_2m_max", "high_c"), ("temperature_2m_min", "low_c"),
                              ("precipitation_probability_max", "rain_probability_pct"),
                              ("weather_code", "weather_code")]:
            values = daily.get(remote) or []
            row[local] = values[index] if index < len(values) and number(values[index]) else None
        days.append(row)
    return {"status": "ok", "source": WEATHER_SOURCE,
        "coverage": "upcoming" if check_in is None else "full" if len(days) == nights else "partial" if days else "outside_forecast",
        "current": {"temperature_c": current.get("temperature_2m") if number(current.get("temperature_2m")) else None,
                    "time": current.get("time")}, "days": days}


def history_view(data, month):
    daily = data.get("daily") or {}
    def average(key):
        values = [x for x in daily.get(key, []) if number(x)]
        return round(sum(values) / len(values), 1) if values else None
    return {"status": "ok", "kind": "historical_month", "month": month,
            "mean_high_c": average("temperature_2m_max"), "mean_low_c": average("temperature_2m_min"),
            "source": WEATHER_SOURCE}


def places_view(data):
    if data.get("remark") or not isinstance(data.get("elements"), list):
        raise ValueError("Incomplete OpenStreetMap response")
    attractions, transport = [], []
    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        name = tags.get("name:ru") or tags.get("name")
        kind, identity = element.get("type"), element.get("id")
        center = element.get("center") or element
        if (not isinstance(name, str) or not name.strip() or kind not in {"node", "way", "relation"}
                or not isinstance(identity, int) or identity <= 0
                or not number(center.get("lat")) or not number(center.get("lon"))
                or not -90 <= center["lat"] <= 90 or not -180 <= center["lon"] <= 180):
            continue
        row = {"name": name[:180], "latitude": center["lat"], "longitude": center["lon"],
               "url": f"https://www.openstreetmap.org/{kind}/{identity}"}
        tourism = tags.get("tourism")
        if tourism in {"attraction", "museum", "viewpoint"}:
            row["kind"] = {"attraction": "Достопримечательность", "museum": "Музей", "viewpoint": "Смотровая площадка"}[tourism]
            attractions.append(row)
        elif tags.get("railway") == "station" or tags.get("aeroway") == "aerodrome" or tags.get("amenity") == "bus_station":
            row["kind"] = "Вокзал" if tags.get("railway") == "station" else "Аэропорт" if tags.get("aeroway") else "Автостанция"
            transport.append(row)
    return {"status": "ok", "attractions": attractions[:8], "transport_points": transport[:5],
            "source": OSM_SOURCE}


class DestinationContext:
    def __init__(self, client):
        self.client = client
        self.cache = {}
        self.inflight = {}
        self.limit = asyncio.Semaphore(4)

    async def cached(self, key, ttl, fetch):
        entry = self.cache.get(key)
        if entry and entry[0] > time.monotonic():
            return deepcopy(entry[1])
        if key not in self.inflight:
            async def update():
                try:
                    async with self.limit, asyncio.timeout(7):
                        result = await fetch()
                except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, IndexError):
                    result = {"status": "unavailable"}
                if len(self.cache) >= 256:
                    self.cache.pop(next(iter(self.cache)))
                result["fetched_at"] = datetime.now(ZoneInfo("Europe/Moscow")).isoformat()
                self.cache[key] = (time.monotonic() + (30 if result.get("status") == "unavailable" else ttl), result)
                return result
            self.inflight[key] = asyncio.create_task(update())
        task = self.inflight[key]
        try:
            return deepcopy(await asyncio.shield(task))
        finally:
            if task.done() and self.inflight.get(key) is task:
                del self.inflight[key]

    async def json(self, url, params):
        response = await self.client.get(url, params=params, timeout=httpx.Timeout(6, connect=2))
        response.raise_for_status()
        return response.json()

    async def geocode(self, name):
        async def fetch():
            data = await self.json("https://geocoding-api.open-meteo.com/v1/search",
                {"name": name, "count": 5, "language": "ru", "format": "json"})
            options = data.get("results") or []
            if not options:
                return {"status": "not_found"}
            # Current catalogue is Russian; prefer its country for ambiguous names.
            place = next((p for p in options if p.get("country_code") == "RU"), options[0])
            lat, lon = place["latitude"], place["longitude"]
            if not number(lat) or not number(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError("Invalid coordinates")
            return {"status": "ok", "name": str(place["name"])[:100], "latitude": lat,
                    "longitude": lon, "country": str(place.get("country", ""))[:100],
                    "timezone": place.get("timezone", "Europe/Moscow"),
                    "source": source("Open-Meteo / GeoNames", "https://open-meteo.com/en/docs/geocoding-api")}
        return await self.cached(("geo", name.casefold()), 86400, fetch)

    async def get(self, destination, check_in, nights, origin):
        stamp = datetime.now(ZoneInfo("Europe/Moscow"))
        place = await self.geocode(destination)
        if place["status"] != "ok":
            return {"status": "unavailable", "location": None, "updated_at": stamp.isoformat()}
        lat, lon = place["latitude"], place["longitude"]
        coords = {"latitude": lat, "longitude": lon, "timezone": "Europe/Moscow"}

        async def weather():
            async def fetch():
                data = await self.json("https://api.open-meteo.com/v1/forecast", coords | {
                    "current": "temperature_2m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                    "forecast_days": 16})
                return data
            data = await self.cached(("forecast", lat, lon), 900, fetch)
            return data if data.get("status") == "unavailable" else weather_view(data, check_in, nights) | {"fetched_at": data["fetched_at"]}

        async def history():
            if check_in is None or check_in <= stamp.date() + timedelta(days=15):
                return None
            year, month = stamp.year - 1, check_in.month
            start, end = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
            async def fetch():
                data = await self.json("https://archive-api.open-meteo.com/v1/archive", coords | {
                    "start_date": start.isoformat(), "end_date": end.isoformat(),
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum"})
                return history_view(data, start.strftime("%Y-%m"))
            return await self.cached(("history", lat, lon, year, month), 86400, fetch)

        async def places():
            async def fetch():
                query = (f'[out:json][timeout:4];(nwr(around:12000,{lat},{lon})'
                    '[tourism~"^(attraction|museum|viewpoint)$"][name];'
                    f'nwr(around:30000,{lat},{lon})[railway=station][name];'
                    f'nwr(around:30000,{lat},{lon})[aeroway=aerodrome][name];'
                    f'nwr(around:12000,{lat},{lon})[amenity=bus_station][name];);out center 80;')
                data = await self.json("https://overpass-api.de/api/interpreter", {"data": query})
                return places_view(data)
            return await self.cached(("places", lat, lon), 21600, fetch)

        async def road():
            start = await self.geocode(origin)
            if start["status"] != "ok":
                return {"status": "unavailable"}
            async def fetch():
                data = await self.json("https://router.project-osrm.org/route/v1/driving/"
                    f'{start["longitude"]},{start["latitude"]};{lon},{lat}', {"overview": "false"})
                route = data["routes"][0]
                km, hours = route["distance"] / 1000, route["duration"] / 3600
                if not number(km) or not number(hours) or km < 0 or hours < 0:
                    raise ValueError("Invalid route")
                return {"status": "ok", "distance_km": round(km), "duration_hours": round(hours, 1),
                    "origin": start["name"], "destination": place["name"],
                    "source": source("OSRM / OpenStreetMap", "https://project-osrm.org/"),
                    "url": "https://www.openstreetmap.org/directions?" + urlencode({
                        "engine": "fossgis_osrm_car", "route": f'{start["latitude"]},{start["longitude"]};{lat},{lon}'})}
            return await self.cached(("road", start["latitude"], start["longitude"], lat, lon), 21600, fetch)

        weather_data, history_data, places_data, road_data = await asyncio.gather(weather(), history(), places(), road())
        return {"status": "ok", "location": place, "weather": weather_data, "history": history_data,
                "places": places_data, "road": road_data, "updated_at": stamp.isoformat(),
                "map_url": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=12/{lat}/{lon}",
                "map_embed_url": "https://www.openstreetmap.org/export/embed.html?" + urlencode({
                    "bbox": f"{lon-.08},{lat-.05},{lon+.08},{lat+.05}", "layer": "mapnik", "marker": f"{lat},{lon}"})}

    async def close(self):
        tasks = list(self.inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.inflight.clear()
