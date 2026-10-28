"""Real browser verification for the reference-based visual redesign."""

import os
import re
import shutil
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def run():
    output = Path("artifacts/rivane")
    output.mkdir(parents=True, exist_ok=True)
    base = os.getenv("OPLAN_TEST_URL", "http://127.0.0.1:8080")
    chrome = (
        os.getenv("OPLAN_CHROME_PATH") or shutil.which("google-chrome") or shutil.which("chromium")
    )
    installed = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome and installed.exists():
        chrome = str(installed)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, **({"executable_path": chrome} if chrome else {})
        )
        errors = []
        for width in (1440, 768, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 1000}, reduced_motion="reduce"
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/api/sessions/*/destination-context?*", lambda route: route.abort())
            page.goto(base, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            expect(page.locator("#home-link")).to_contain_text("RIVANE")
            expect(page.locator("#hero-title")).to_contain_text("с одного желания")
            expect(page.locator(".theme-chip")).to_have_count(4)
            expect(page.locator(".destination-card")).to_have_count(6)
            expect(page.locator(".journey-steps li")).to_have_count(4)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator(".lux-hero-image").evaluate(
                "img => img.complete && img.naturalWidth > 0"
            )
            for image in page.locator(".destination-card img").all():
                image.scroll_into_view_if_needed()
                expect(image).to_be_visible()
                image.evaluate("img => img.decode()")
            page.evaluate("scrollTo(0,0)")
            page.screenshot(path=str(output / f"home-{width}.png"), full_page=True)

            # Every destination is a real query seed, not an unavailable country.
            page.get_by_role("button", name="Спланировать отдых: Хоста", exact=True).click()
            expect(page.locator("#trip-message")).to_be_focused()
            expect(page.locator("#trip-message")).to_have_value(re.compile("В Хосту"))
            with page.expect_response(
                lambda r: r.url.endswith("/api/sessions") and r.request.method == "POST"
            ):
                page.locator(".composer-submit").click()
            expect(page.locator(".hotel-card")).to_have_count(3)
            expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            session_id = page.evaluate("localStorage.getItem('oplan-session-v1')")
            response = context.request.get(f"{base}/api/sessions/{session_id}").json()
            assert response["requirements"]["destination"] == "Хоста"
            assert all(plan["hotel"]["area"] == "Хоста" for plan in response["plans"])
            page.screenshot(path=str(output / f"results-{width}.png"), full_page=True)

            # Saved sessions remain recoverable after returning to the home page.
            page.locator("#home-link").click()
            if width <= 850:
                page.locator("#mobile-menu").click()
                expect(page.locator("#mobile-menu")).to_have_attribute("aria-expanded", "true")
            page.locator("#trips-link").click()
            expect(page.get_by_role("dialog")).to_be_visible()
            expect(page.locator(".saved-trip-button")).to_have_count(1)
            page.screenshot(path=str(output / f"trips-{width}.png"), full_page=True)
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).to_have_count(0)
            if width <= 850:
                expect(page.locator("#mobile-menu")).to_be_focused()
                expect(page.locator("#mobile-menu")).to_have_attribute(
                    "aria-label", "Открыть навигацию"
                )
            if width <= 850:
                page.locator("#mobile-menu").click()
            page.locator("#trips-link").click()
            page.locator(".saved-trip-button").first.click()
            expect(page.locator(".hotel-card")).to_have_count(3)
            expect(page.get_by_role("dialog")).to_have_count(0)
            assert page.evaluate("localStorage.getItem('oplan-session-v1')") == session_id
            # Closing a slow history lookup must not reopen that trip later.
            page.locator("#home-link").click()
            if width <= 850:
                page.locator("#mobile-menu").click()
            page.locator("#trips-link").click()
            held = []
            page.route(
                f"**/api/sessions/{session_id}",
                lambda route, _request, held=held: held.append(route),
            )
            page.locator(".saved-trip-button").click()
            expect(page.locator(".saved-trip-error")).to_contain_text("Возвращаем")
            page.keyboard.press("Escape")
            held[0].fulfill(json=response)
            expect(page.locator("#hero-title")).to_be_visible()
            assert page.evaluate("localStorage.getItem('oplan-session-v1')") is None
            if width == 1440:
                # Consent and traveler details belong to the selected trip.
                page.locator(".theme-chip").first.click()
                expect(page.locator("#trip-message")).not_to_have_value("")
                with page.expect_response(
                    lambda r: r.url.endswith("/api/sessions") and r.request.method == "POST"
                ):
                    page.locator(".composer-submit").click()
                expect(page.locator(".hotel-card")).to_have_count(3)
                page.locator(".hotel-card .button").first.click()
                expect(page.locator("#traveler-name")).to_be_visible()
                second_trip_id = page.evaluate("localStorage.getItem('oplan-session-v1')")
                page.locator("#home-link").click()
                page.locator(".theme-chip").nth(1).click()
                expect(page.locator("#trip-message")).not_to_have_value("")
                with page.expect_response(
                    lambda r: r.url.endswith("/api/sessions") and r.request.method == "POST"
                ):
                    page.locator(".composer-submit").click()
                expect(page.locator(".hotel-card")).to_have_count(3)
                page.locator(".hotel-card .button").first.click()
                expect(page.locator("#traveler-name")).to_be_visible()
                page.locator("#traveler-name").fill("Иван Тестовый")
                page.locator("#traveler-email").fill("ivan@example.test")
                page.locator("#demo-agreement").check()
                page.locator("#trips-link").click()
                page.locator(".saved-trip-button").nth(1).click()
                expect(page.get_by_role("dialog")).to_have_count(0)
                expect(page.locator("#traveler-name")).to_be_visible()
                assert page.evaluate("localStorage.getItem('oplan-session-v1')") == second_trip_id
                expect(page.locator("#traveler-name")).to_have_value("")
                expect(page.locator("#traveler-email")).to_have_value("")
                expect(page.locator("#demo-agreement")).not_to_be_checked()
            context.close()
        browser.close()
        assert not errors, errors
    print(
        "PASS: 1440/768/390; local photographs/fonts, six real area seeds, four steps, API results, saved trip restore, native dialog Escape and mobile navigation; no overflow or JS errors."
    )


if __name__ == "__main__":
    run()
