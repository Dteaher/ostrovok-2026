"""Browser acceptance of concierge comparison and priority actions."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def run():
    base = os.getenv("OPLAN_TEST_URL", "http://127.0.0.1:8081")
    chrome = os.getenv("OPLAN_CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    target = Path("artifacts/agent-ui")
    target.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chrome)
        for width in (1440, 768, 390, 320):
            page = browser.new_page(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda error, captured=errors: captured.append(str(error)))
            page.goto(base)
            page.locator("#trip-message").fill("В Сочи с 20 декабря 2026 на 7 ночей, двое взрослых, бюджет 500 тысяч, с завтраком")
            with page.expect_response(lambda r: r.url.endswith("/api/sessions") and r.request.method == "POST") as created:
                page.locator(".composer-submit").click()
            initial = created.value.json()
            expect(page.locator(".hotel-card")).to_have_count(3)
            if not page.locator("#travel-chat").is_visible():
                page.locator(".chat-toggle").click()
            page.locator("#refine-message").fill("Сравни первый и второй отель")
            with page.expect_response(lambda r: r.url.endswith("/messages")) as compared:
                page.locator(".composer-compact button[type=submit]").click()
            comparison = compared.value.json()
            assert comparison["requirements"] == initial["requirements"]
            assert comparison["order"] is None
            expect(page.locator(".concierge-notes details")).to_have_attribute("open", "")
            expect(page.locator(".concierge-facts")).to_contain_text("дешевле")
            page.locator(".concierge-notes").screenshot(path=str(target / f"compare-{width}.png"))
            with page.expect_response(lambda r: r.url.endswith("/messages")) as ranked:
                if page.get_by_role("button", name="Ниже цена", exact=True).count():
                    page.get_by_role("button", name="Ниже цена", exact=True).first.click()
                else:
                    page.locator("#refine-message").fill("Покажи сначала более дешёвые варианты")
                    page.locator(".composer-compact button[type=submit]").click()
            sorted_state = ranked.value.json()
            assert sorted_state["requirements"] == initial["requirements"]
            totals = [plan["price"]["total"] for plan in sorted_state["plans"]]
            assert totals == sorted(totals)
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            page.screenshot(path=str(target / f"priority-{width}.png"), full_page=True)
            assert not errors, errors
            page.close()
        browser.close()
    print("PASS: concierge comparison, real priority action, state retention, no orders, 1440/768/390/320; no overflow or browser errors")


if __name__ == "__main__":
    run()
