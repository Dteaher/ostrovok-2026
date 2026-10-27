"""Browser acceptance check against the running local demonstration service."""

import json
import os
import shutil
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def run():
    base = os.environ.get("OPLAN_TEST_URL", "http://127.0.0.1:8080")
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        chrome_path = os.environ.get("OPLAN_CHROME_PATH")
        if not chrome_path:
            chrome_path = next(
                (
                    path
                    for command in (
                        "google-chrome",
                        "google-chrome-stable",
                        "chromium",
                        "chromium-browser",
                        "chrome",
                    )
                    if (path := shutil.which(command))
                ),
                None,
            )
        if not chrome_path:
            windows_chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
            if windows_chrome.is_file():
                chrome_path = str(windows_chrome)
        launch_options = {"headless": True}
        if chrome_path:
            launch_options["executable_path"] = chrome_path
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def act(target_page, action):
            with target_page.expect_response(
                lambda response: (
                    "/api/sessions" in response.url and response.request.method in ("POST", "PATCH")
                )
            ):
                action()
            expect(target_page.locator("#main")).to_have_attribute("aria-busy", "false")

        page.goto(base)
        expect(page.locator(".example-button")).to_have_count(4)
        page.screenshot(path=str(output / "ui-desktop.png"), full_page=True)
        act(page, lambda: page.locator(".example-button").first.click())
        expect(page.locator(".hotel-card")).to_have_count(3)
        page.screenshot(path=str(output / "ui-results.png"), full_page=True)
        session_id = page.evaluate("localStorage.getItem('oplan-session-v1')")
        before = context.request.get(f"{base}/api/sessions/{session_id}").json()
        breakfast_change = next(
            (item for item in before["counterfactuals"] if item["field"] == "breakfast"), None
        )
        assert breakfast_change and breakfast_change["value"] is False
        act(
            page,
            lambda: page.get_by_role("button", name=breakfast_change["label"], exact=False).click(),
        )
        changed = context.request.get(f"{base}/api/sessions/{session_id}").json()
        assert changed["requirements"]["breakfast"] is False
        assert (
            breakfast_change["baseline_total"] - breakfast_change["alternative_total"]
            == breakfast_change["saving"]
        )
        page.locator("#refine-message").fill("Нужен завтрак")
        act(page, lambda: page.locator(".composer-submit").click())
        page.locator("#refine-message").fill("Нужен бассейн")
        act(page, lambda: page.locator(".composer-submit").click())
        expect(page.locator(".changes-note")).to_be_visible()
        after = context.request.get(f"{base}/api/sessions/{session_id}").json()
        assert after["requirements"]["pool"] is True
        for field in (
            "destination",
            "check_in",
            "nights",
            "adults",
            "budget",
            "breakfast",
            "direct_only",
        ):
            assert after["requirements"][field] == before["requirements"][field], field
        # Advance the session in another client, then verify the visible 409 recovery.
        response = context.request.patch(
            f"{base}/api/sessions/{session_id}/requirements",
            data={"revision": after["revision"], "patch": {"quiet": True}},
        )
        assert response.ok
        act(page, lambda: page.locator(".hotel-card .button").first.click())
        expect(page.locator(".alert-error")).to_contain_text("другой вкладке")
        act(page, lambda: page.locator(".hotel-card .button").first.click())
        expect(page.locator(".checkout-panel")).to_be_visible()
        page.screenshot(path=str(output / "ui-checkout.png"), full_page=True)
        page.locator("#traveler-name").fill("Тестовый Путешественник")
        page.locator("#traveler-email").fill("demo@example.test")
        page.locator("#demo-agreement").check()
        act(page, lambda: page.locator(".checkout-submit").click())
        expect(page.locator(".booked-section > h2")).to_contain_text("готова")
        reference = page.locator(".order-reference").inner_text()
        page.reload()
        expect(page.locator(".order-reference")).to_have_text(reference)
        with page.expect_download() as download_info:
            page.get_by_role("button", name="Скачать заявку").click()
        download_path = download_info.value.path()
        order = json.loads(Path(download_path).read_text(encoding="utf-8"))
        assert order["status"] == "demo_confirmed"
        page.screenshot(path=str(output / "ui-order.png"), full_page=True)
        mobile = browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            reduced_motion="reduce",
        )
        mobile_page = mobile.new_page()
        mobile_page.on("pageerror", lambda error: errors.append(str(error)))
        mobile_page.goto(base)
        expect(mobile_page.locator(".example-button")).to_have_count(4)
        mobile_page.screenshot(path=str(output / "ui-mobile.png"), full_page=True)
        act(mobile_page, lambda: mobile_page.locator(".example-button").first.click())
        expect(mobile_page.locator(".hotel-card")).to_have_count(3)
        assert mobile_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
            "Mobile horizontal overflow"
        )
        mobile_page.screenshot(path=str(output / "ui-mobile-results.png"), full_page=True)
        act(mobile_page, lambda: mobile_page.locator(".hotel-card .button").first.click())
        expect(mobile_page.locator(".checkout-panel")).to_be_visible()
        assert mobile_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
            "Checkout horizontal overflow"
        )
        mobile_page.screenshot(path=str(output / "ui-mobile-checkout.png"), full_page=True)
        mobile_page.locator("#new-trip").click()
        mobile_page.locator("#trip-message").fill("Хочу в Сочи")
        act(mobile_page, lambda: mobile_page.locator(".composer-submit").click())
        expect(mobile_page.locator(".clarify-section")).to_be_visible()
        assert mobile_page.locator(".choice-chip").count() > 0
        act(mobile_page, lambda: mobile_page.locator(".choice-chip").first.click())
        expect(mobile_page.locator(".hotel-card")).to_have_count(3)
        mobile_page.screenshot(path=str(output / "ui-clarified.png"), full_page=True)
        # Unpriced self travel is visibly excluded instead of being advertised as free.
        mobile_page.locator("#new-trip").click()
        mobile_page.locator("#trip-message").fill(
            "В Сочи с 6 ноября 2026 на 7 ночей вдвоем на своей машине до 160 тысяч"
        )
        act(mobile_page, lambda: mobile_page.locator(".composer-submit").click())
        expect(mobile_page.locator(".hotel-card")).to_have_count(3)
        for caption in mobile_page.locator(".total-price > span").all():
            expect(caption).to_contain_text("без самостоятельной дороги")
            assert "с дорогой" not in caption.inner_text()
        act(mobile_page, lambda: mobile_page.locator(".hotel-card .button").first.click())
        expect(mobile_page.locator(".mobile-checkout-link p span")).to_have_text(
            "За всех · без самостоятельной дороги"
        )
        expect(mobile_page.locator(".checkout-panel .price-breakdown h3")).to_have_text(
            "Стоимость включённых услуг"
        )
        expect(mobile_page.locator(".checkout-panel .price-exclusion-note")).to_have_text(
            "Стоимость самостоятельной дороги и трансфера не рассчитана и не включена в сумму."
        )
        price_rows = mobile_page.locator(".checkout-panel .price-breakdown dl > div")
        expect(price_rows.nth(1).locator("dd")).to_have_text("Не рассчитано")
        expect(price_rows.nth(2).locator("dd")).to_have_text("Не рассчитано")
        self_session_id = mobile_page.evaluate("localStorage.getItem('oplan-session-v1')")
        self_session = mobile.request.get(f"{base}/api/sessions/{self_session_id}").json()
        self_plan = self_session["selected_plan"]
        assert self_plan["transport"]["mode"] == "self"
        assert self_plan["price"]["total"] == self_plan["price"]["hotel"] + self_plan["price"]["extras"]
        assert mobile_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        mobile_page.screenshot(path=str(output / "ui-self-checkout.png"), full_page=True)
        response = mobile.request.patch(
            f"{base}/api/sessions/{self_session_id}/requirements",
            data={"revision": self_session["revision"], "patch": {"max_beach_m": 0}},
        )
        assert response.ok
        mobile_page.reload()
        expect(mobile_page.locator(".condition-list")).to_contain_text("Море до 0 м")
        # An impossible budget remains explicit and receives a useful empty state.
        mobile_page.locator("#new-trip").click()
        mobile_page.locator("#trip-message").fill(
            "В Сочи с 6 ноября 2026 на 7 ночей вдвоем до 1000 рублей"
        )
        act(mobile_page, lambda: mobile_page.locator(".composer-submit").click())
        expect(mobile_page.locator(".empty-state")).to_be_visible()
        mobile_page.screenshot(path=str(output / "ui-empty.png"), full_page=True)
        # Input is displayed as text, never inserted as executable markup.
        mobile_page.locator("#new-trip").click()
        mobile_page.locator("#trip-message").fill(
            'В Сочи с 6 ноября 2026 на 7 ночей <img src=x onerror="alert(1)">'
        )
        act(mobile_page, lambda: mobile_page.locator(".composer-submit").click())
        mobile_page.locator(".history summary").click()
        expect(mobile_page.locator(".history")).to_contain_text("<img src=x")
        assert mobile_page.locator(".history img").count() == 0
        # A failed request gives a visible recovery message and preserves the draft.
        mobile_page.locator("#new-trip").click()
        mobile_page.route("**/api/sessions", lambda route: route.abort())
        draft = "Хочу в Сочи с 6 ноября 2026"
        mobile_page.locator("#trip-message").fill(draft)
        mobile_page.locator(".composer-submit").click()
        expect(mobile_page.locator(".alert-error")).to_contain_text("Не удалось связаться")
        expect(mobile_page.locator("#trip-message")).to_have_value(draft)
        mobile_page.screenshot(path=str(output / "ui-error.png"), full_page=True)
        assert not errors, errors
        browser.close()
        print(
            "PASS: desktop/mobile, full API journey, condition retention, stale recovery, demo checkout, restore, order download, typed clarification, self-travel price exclusions, zero beach boundary, empty budget, safe text rendering, network recovery; no page errors or horizontal overflow."
        )


if __name__ == "__main__":
    run()
