"""Browser acceptance for local preference edits and safe retained-hotel offers."""

import os
import shutil
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def run():
    base = os.getenv("OPLAN_TEST_URL", "http://127.0.0.1:8080")
    chrome = os.getenv("OPLAN_CHROME_PATH") or shutil.which("google-chrome") or shutil.which("chromium")
    installed = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome and installed.exists():
        chrome = str(installed)
    output = Path("artifacts/dialog-core")
    output.mkdir(parents=True, exist_ok=True)
    day = (date.today() + timedelta(days=40)).isoformat()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **({"executable_path": chrome} if chrome else {}))
        errors = []
        for width in (1440, 390):
            context = browser.new_context(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)

            def act(action, target=page):
                with target.expect_response(lambda r: "/api/sessions" in r.url and r.request.method in {"POST", "PATCH"}):
                    action()
                expect(target.locator("#main")).to_have_attribute("aria-busy", "false")

            def say(message, target=page):
                if target.locator('.refine-disclosure').count() and target.locator('.refine-disclosure').get_attribute('open') is None:
                    target.locator('.refine-disclosure > summary').click()
                target.locator(".composer textarea").fill(message)
                act(lambda: target.locator(".composer-submit").click())

            def state(target=page, target_context=context):
                session_id = target.evaluate("localStorage.getItem('oplan-session-v1')")
                return target_context.request.get(f"{base}/api/sessions/{session_id}").json()

            say(f"В Сочи с {day} на 7 ночей вдвоём до 500 тысяч, желательно с завтраком")
            expect(page.locator(".conditions")).to_contain_text("Завтрак — желательно")
            say("Теперь завтрак обязателен")
            expect(page.locator(".conditions")).to_contain_text("Завтрак — обязательно")
            assert all(p["meal"] == "Завтрак включён" for p in state()["plans"])
            act(lambda target=page: target.locator(".hotel-card .button").first.click())
            original = state()
            expect(page.locator('h1')).to_have_text(original['hotel_intent']['name'])
            say("Что изменится, если убрать завтрак?")
            compared = state()
            assert compared["selected_plan"] == original["selected_plan"]
            expect(page.get_by_role("button", name="Применить это изменение", exact=True)).to_be_visible()
            say("Оставь этот отель, но сократи поездку на день")
            repriced = state()
            assert repriced["requirements"]["nights"] == 6
            assert repriced["hotel_intent"] == original["hotel_intent"]
            assert repriced["selected_plan"] is None
            expect(page.locator(".hotel-card")).to_have_count(1)
            expect(page.locator(".checkout-submit")).to_have_count(0)
            page.screenshot(path=str(output / f"repriced-{width}.png"), full_page=True)
            act(lambda target=page: target.locator(".hotel-card .button").first.click())
            say("Добавь ребёнка")
            expect(page.locator(".decision-continue")).to_be_disabled()
            expect(page.locator(".clarification-questions")).to_contain_text("Сколько лет")
            page.screenshot(path=str(output / f"pending-age-{width}.png"), full_page=True)
            say("6 лет")
            assert state()["requirements"]["children_ages"] == [6]
            act(lambda target=page: target.locator(".hotel-card .button").first.click())
            expect(page.locator(".decision-continue")).to_be_enabled()
            page.get_by_role('button', name='К вариантам поездки', exact=True).click()
            act(lambda target=page: target.get_by_role("button", name="Рассмотреть другие отели", exact=True).click())
            assert state()["hotel_intent"] is None
            assert state()["requirements"]["children_ages"] == [6]
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            # Empty constraints produce actionable, verified pairs in the same UI.
            say("Рейтинг от 10, до 0 м до моря")
            empty = state()
            assert not empty["plans"] and empty["suggestions"]
            choice = empty["suggestions"][0]
            assert len(choice["patch"]) == 2
            page.screenshot(path=str(output / f"conflict-{width}.png"), full_page=True)
            act(lambda target=page, label=choice["label"]: target.get_by_role("button", name=label, exact=False).click())
            assert state()["total_matches"] == choice["total_matches"]
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            context.close()
        assert not errors, errors
        browser.close()
    print("PASS: desktop/mobile priorities, what-if preservation, hotel retention/repricing, required reconfirmation, child-age checkout guard, context answer, explicit hotel release and verified pair repair; no page errors/overflow.")


if __name__ == "__main__":
    run()
