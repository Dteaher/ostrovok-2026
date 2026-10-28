"""UI contract test with real local results and a controlled narration response."""

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def run():
    base = os.getenv("OPLAN_TEST_URL", "http://127.0.0.1:8082")
    chrome = os.getenv("OPLAN_CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    target = Path("artifacts/latency-ui")
    target.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chrome)
        for width in (1440, 390, 320):
            response = httpx.post(base + "/api/sessions", json={"message": "В Сочи с 20 декабря 2026 на 7 ночей, двое взрослых, бюджет 500 тысяч, с завтраком"}, trust_env=False)
            response.raise_for_status()
            initial = response.json()
            initial["agent"]["explanation_status"] = "pending"
            initial["response_timing"] = {"limit_seconds": 10, "elapsed_seconds": .1}
            page = browser.new_page(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
            errors = []
            pending = []
            page.on("pageerror", lambda error, captured=errors: captured.append(str(error)))
            page.add_init_script("localStorage.setItem('oplan-session-v1', " + json.dumps(initial["id"]) + ")")
            url = base + "/api/sessions/" + initial["id"]
            page.route(url, lambda route, request, value=initial: route.fulfill(json=value))
            page.route(url + "/explanation", lambda route, request, waiting=pending: waiting.append(route))
            page.goto(base)
            expect(page.locator(".hotel-card")).to_have_count(3)
            if not page.locator("#travel-chat").is_visible():
                page.locator(".chat-toggle").click()
            expect(page.locator(".concierge-notice")).to_contain_text("Варианты уже готовы")
            expect(page.locator("#new-trip")).to_be_enabled()
            assert pending
            page.locator(".concierge-notes summary").click()
            field = page.locator("#refine-message")
            field.fill("Мой незавершённый запрос")
            field.focus()
            if width == 1440:
                page.route(url + "/messages", lambda route: route.fulfill(status=422, json={"detail": "Проверьте условия"}))
                with page.expect_request(url + "/explanation"):
                    page.locator(".composer-compact button[type=submit]").click()
                expect(page.locator(".alert-error")).to_contain_text("Проверьте условия")
                expect(field).to_have_value("Мой незавершённый запрос")
                pending[0].abort()
                page.locator(".concierge-notes summary").click()
                field.focus()
            card = page.locator(".hotel-card").first.element_handle()
            page.screenshot(path=str(target / f"pending-{width}.png"), full_page=True)
            page.locator(".concierge-notes").screenshot(path=str(target / f"pending-panel-{width}.png"))
            agent = deepcopy(initial["agent"])
            agent.update(mode="llm", explanation_status="complete", notice=None)
            pending[-1].fulfill(json={"revision": initial["revision"], "agent": agent})
            expect(page.locator(".concierge-notice")).to_have_count(0)
            expect(field).to_have_value("Мой незавершённый запрос")
            expect(field).to_be_focused()
            assert card.evaluate("element => element.isConnected"), f"Card replaced at {width}px"
            assert page.locator(".concierge-notes details").evaluate("element => element.open")
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            page.screenshot(path=str(target / f"complete-{width}.png"), full_page=True)
            page.locator(".concierge-notes").screenshot(path=str(target / f"complete-panel-{width}.png"))
            assert not errors, errors
            page.close()
        browser.close()
    print("PASS: immediate cards; independent narration; retained draft, focus, cards and expanded facts; 1440/390/320; no overflow or browser errors. Provider response controlled for UI testing.")


if __name__ == "__main__":
    run()
