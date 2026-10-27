"""Record the real local application in Chromium; no synthetic response screens."""

import os
import shutil
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    chrome = (
        os.getenv("OPLAN_CHROME_PATH") or shutil.which("google-chrome") or shutil.which("chromium")
    )
    windows_chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome and windows_chrome.exists():
        chrome = str(windows_chrome)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, **({"executable_path": chrome} if chrome else {})
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            record_video_dir=str(output / "video"),
            record_video_size={"width": 1440, "height": 1000},
            reduced_motion="reduce",
        )
        page = context.new_page()

        def pause(seconds=5):
            page.wait_for_timeout(seconds * 1000)

        def act(action):
            with page.expect_response(
                lambda r: "/api/sessions" in r.url and r.request.method in {"POST", "PATCH"}
            ):
                action()
            expect(page.locator("#main")).to_have_attribute("aria-busy", "false")

        page.goto(os.getenv("OPLAN_TEST_URL", "http://127.0.0.1:8080"))
        pause(6)
        page.locator("#trip-message").press_sequentially(
            "В Сочи с 6 ноября 2026 на неделю вдвоём, до 160 тысяч, с завтраком и прямым перелётом",
            delay=35,
        )
        pause(3)
        act(lambda: page.locator(".composer-submit").click())
        expect(page.locator(".hotel-card")).to_have_count(3)
        pause(6)
        page.locator(".hotel-grid").scroll_into_view_if_needed()
        pause(10)
        page.locator(".alternatives").scroll_into_view_if_needed()
        pause(8)
        page.locator("#refine-message").press_sequentially("Сколько стоит мой завтрак?", delay=45)
        act(lambda: page.locator(".composer-submit").click())
        page.locator(".assistant-message").scroll_into_view_if_needed()
        pause(10)
        page.locator("#refine-message").scroll_into_view_if_needed()
        page.locator("#refine-message").press_sequentially("На два дня позже, с собакой", delay=60)
        act(lambda: page.locator(".composer-submit").click())
        page.locator(".conditions").scroll_into_view_if_needed()
        pause(8)
        page.locator(".hotel-grid").scroll_into_view_if_needed()
        pause(7)
        act(
            lambda: (
                page.locator(".hotel-card")
                .nth(1)
                .get_by_role("button", name="Посмотреть план")
                .click()
            )
        )
        page.locator(".detail-summary").scroll_into_view_if_needed()
        pause(9)
        page.locator(".timeline-section").scroll_into_view_if_needed()
        pause(10)
        page.locator(".checkout-form").scroll_into_view_if_needed()
        pause(5)
        page.locator("#traveler-name").fill("Демо путешественник")
        page.locator("#traveler-email").fill("demo@example.com")
        page.locator("#demo-agreement").check()
        pause(5)
        act(lambda: page.locator(".checkout-submit").click())
        expect(page.locator(".booked-section")).to_be_visible()
        pause(10)
        page.reload()
        expect(page.locator(".booked-section")).to_be_visible()
        pause(7)
        video = page.video
        await_path = video.path()
        context.close()
        browser.close()
        shutil.copyfile(await_path, output / "demo.webm")
        print("Recorded actual browser flow:", output / "demo.webm")


if __name__ == "__main__":
    main()
