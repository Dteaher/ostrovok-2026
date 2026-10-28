"""Real local search and public-data UI at desktop/mobile sizes."""

import json
import re
from datetime import date, timedelta
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def run():
    base = "http://127.0.0.1:8082"
    output = Path("artifacts/destination-ui")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        for width in (1440, 390, 320):
            response = httpx.post(base + "/api/sessions", json={"message": f"В Сочи с {(date.today()+timedelta(days=3)).isoformat()} на 7 ночей, бюджет 300 тысяч"}, trust_env=False)
            response.raise_for_status()
            session = response.json()
            page = browser.new_page(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda error, captured=errors: captured.append(str(error)))
            page.add_init_script("localStorage.setItem('oplan-session-v1', " + json.dumps(session["id"]) + ")")
            page.goto(base)
            expect(page.locator(".hotel-card")).to_have_count(3)
            expect(page.locator(".context-weather")).to_be_visible(timeout=15000)
            expect(page.locator(".context-weather")).to_contain_text("Прогноз на даты поездки")
            expect(page.locator(".context-road")).to_contain_text("На автомобиле")
            assert page.locator(".context-map-frame").count() == 0
            page.locator(".destination-context").scroll_into_view_if_needed()
            page.locator(".destination-context").screenshot(path=str(output / f"context-{width}.png"))
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            # The map is explicitly loaded only after pressing its button.
            page.get_by_role("button", name="Показать интерактивную карту").click()
            expect(page.locator(".context-map-frame")).to_have_attribute("src", re.compile(r"^https://www.openstreetmap.org/export/embed.html"))
            assert not errors, errors
            page.close()
        browser.close()
    print("PASS: live forecast/route; search cards remain; consent-triggered map; desktop/mobile 1440/390/320; no overflow or browser errors")


if __name__ == "__main__":
    run()
