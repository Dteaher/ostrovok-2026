"""Interior acceptance and immutable landing screenshots against a local service.

Capture once with --baseline before editing. Normal runs compare exact RGBA pixels
and DOM text/styles, then exercise the internal screens at three viewport widths.
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

OUTPUT = Path("artifacts/interiors")
WIDTHS = (1440, 768, 390)
BASE = os.getenv("OPLAN_TEST_URL", "http://127.0.0.1:8080")


def settled(page):
    page.evaluate("document.fonts.ready")
    page.evaluate("""async () => {
      for (const image of document.images) {
        image.loading = 'eager';
        if (!image.complete) await new Promise(resolve => {
          image.addEventListener('load', resolve, {once:true});
          image.addEventListener('error', resolve, {once:true});
        });
        if (image.naturalWidth) await image.decode();
      }
      scrollTo(0, 0);
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }""")
    page.screenshot(animations="disabled")


def pixel_difference(browser, before, after):
    """Decode both PNGs in Chrome; compare RGBA, independent of PNG encoding."""
    page = browser.new_page()
    urls = ["data:image/png;base64," + base64.b64encode(data).decode("ascii") for data in (before, after)]
    result = page.evaluate("""async urls => {
      const images = await Promise.all(urls.map(src => new Promise(resolve => {
        const image = new Image(); image.onload = () => resolve(image); image.src = src;
      })));
      if (images[0].width !== images[1].width || images[0].height !== images[1].height)
        return {dimensionsChanged:true};
      const canvas = document.createElement('canvas');
      canvas.width = images[0].width; canvas.height = images[0].height;
      const context = canvas.getContext('2d');
      const pixels = images.map(image => {
        context.clearRect(0,0,canvas.width,canvas.height); context.drawImage(image,0,0);
        return context.getImageData(0,0,canvas.width,canvas.height).data;
      });
      let changed = 0;
      for (let i=0; i<pixels[0].length; i+=4)
        if ([0,1,2,3].some(channel => pixels[0][i+channel] !== pixels[1][i+channel])) changed++;
      return {dimensionsChanged:false,changedPixels:changed};
    }""", urls)
    page.close()
    return result


def landing_snapshot(page):
    return page.evaluate("""() => ({
      text: document.body.innerText,
      elements: [...document.querySelectorAll('body *')].map(el => {
        const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
        return {tag:el.tagName,id:el.id,classes:el.className,
          x:rect.x,y:rect.y,width:rect.width,height:rect.height,
          font:style.font,color:style.color,background:style.background,
          display:style.display,position:style.position,
          src:el.getAttribute('src'),href:el.getAttribute('href')};
      })
    })""")


def verify_landing(browser, baseline):
    manifest = {}
    for width in WIDTHS:
        context = browser.new_context(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
        page = context.new_page()
        page.goto(BASE, wait_until="networkidle")
        settled(page)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        stem = f"home-{'before' if baseline else 'after'}-{width}"
        png = page.screenshot(path=str(OUTPUT / f"{stem}.png"), full_page=True, animations="disabled")
        snapshot = landing_snapshot(page)
        (OUTPUT / f"{stem}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest[str(width)] = {"sha256": hashlib.sha256(png).hexdigest(), "bytes": len(png)}
        if not baseline:
            before = OUTPUT / f"home-before-{width}.png"
            assert before.exists(), "Capture the clean landing first with --baseline"
            difference = pixel_difference(browser, before.read_bytes(), png)
            assert difference == {"dimensionsChanged": False, "changedPixels": 0}, f"Landing changed at {width}px: {difference}"
            expected = json.loads((OUTPUT / f"home-before-{width}.json").read_text(encoding="utf-8"))
            assert snapshot == expected, f"Landing text, geometry, or computed styles changed at {width}px"
        context.close()
    (OUTPUT / ("baseline-manifest.json" if baseline else "comparison-manifest.json")).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def verify_interior_width(browser, width, day):
    errors = []
    context = browser.new_context(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE, wait_until="networkidle")

    def act(action):
        with page.expect_response(lambda response: "/api/sessions" in response.url and response.request.method in {"POST", "PATCH"}):
            action()
        expect(page.locator("#main")).to_have_attribute("aria-busy", "false")

    def say(message):
        page.locator(".composer textarea").fill(message)
        act(lambda: page.locator(".composer-submit").click())

    def state():
        session_id = page.evaluate("localStorage.getItem('oplan-session-v1')")
        return context.request.get(f"{BASE}/api/sessions/{session_id}").json()

    def capture(name):
        settled(page)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Overflow: {name} at {width}px"
        page.screenshot(path=str(OUTPUT / f"{name}-{width}.png"), full_page=True, animations="disabled")
        if name in {"results", "details-checkout", "booked", "saved-trips"}:
            page.screenshot(path=str(OUTPUT / f"preview-{name}-{width}.png"), full_page=False, animations="disabled")

    def trips():
        if width <= 850:
            page.locator("#mobile-menu").click()
        page.locator("#trips-link").click()
        expect(page.get_by_role("dialog")).to_be_visible()

    # Keyboard entry, loading feedback, and focused input all remain usable.
    page.locator("#trip-message").focus()
    expect(page.locator("#trip-message")).to_be_focused()
    held = []
    page.route("**/api/sessions", lambda route: held.append(route))
    page.locator("#trip-message").fill(f"В Сочи с {day} на 7 ночей вдвоём до 500 тысяч")
    page.locator(".composer-submit").click()
    expect(page.locator("#main")).to_have_attribute("aria-busy", "true")
    capture("loading")
    assert held, "Expected a held session creation request"
    held[0].fulfill(response=held[0].fetch())
    page.unroute("**/api/sessions")
    expect(page.locator(".hotel-card")).to_have_count(3)
    expect(page.locator("#main")).to_have_attribute("aria-busy", "false")
    capture("results")
    initial = state()
    say("Нужен бассейн")
    assert state()["requirements"]["pool"] is True
    assert state()["requirements"]["check_in"] == initial["requirements"]["check_in"]
    capture("updated")

    # Select with keyboard and review the complete trip before submitting.
    page.locator(".hotel-card .button").first.focus()
    act(lambda: page.keyboard.press("Enter"))
    expect(page.locator(".checkout-panel")).to_be_visible()
    expect(page.locator(".trip-detail-content")).to_be_visible()
    capture("details-checkout")
    selected = state()["selected_plan"]
    days = {item["time"][:10] for item in selected["timeline"]}
    expect(page.locator(".timeline-section .route-group")).to_have_count(len(days))
    route_summary = page.locator(".timeline-section > .route-details > summary")
    route_summary.focus()
    page.keyboard.press("Enter")
    expect(page.locator(".timeline-section > .route-details")).to_have_attribute("open", "")
    for item in selected["timeline"]:
        expect(page.locator(".timeline-section > .route-details")).to_contain_text(item["detail"])
    page.keyboard.press("Enter")
    expect(page.locator(".timeline-section > .route-details")).not_to_have_attribute("open", "")
    page.locator(".checkout-submit").click()
    expect(page.locator("#traveler-name")).to_be_focused()
    page.locator("#traveler-name").fill("Тестовый Путешественник")
    page.locator("#traveler-email").fill("demo@example.test")
    page.locator("#demo-agreement").check()
    act(lambda: page.locator(".checkout-submit").click())
    expect(page.locator(".booked-section")).to_be_visible()
    reference = page.locator(".order-reference").inner_text()
    capture("booked")
    page.locator(".order-details > summary").click()
    expect(page.locator(".order-details .trip-detail-content")).to_be_visible()
    capture("booked-details")
    page.reload(wait_until="networkidle")
    expect(page.locator(".order-reference")).to_have_text(reference)
    with page.expect_download() as download:
        page.get_by_role("button", name="Скачать заявку", exact=False).click()
    order = json.loads(Path(download.value.path()).read_text(encoding="utf-8"))
    assert order["status"] == "demo_confirmed"

    # Saved trip dialog, native Escape and restore of a completed order.
    page.locator("#home-link").click()
    trips()
    expect(page.locator(".saved-trip-button")).to_have_count(1)
    capture("saved-trips")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    if width <= 850:
        expect(page.locator("#mobile-menu")).to_be_focused()
    trips()
    page.locator(".saved-trip-button").first.click()
    expect(page.locator(".order-reference")).to_have_text(reference)

    # Clarification and explicit empty states have actionable recovery.
    page.locator("#new-trip").click()
    say("Хочу в Сочи")
    expect(page.locator(".clarify-section")).to_be_visible()
    capture("clarification")
    act(lambda: page.locator(".choice-chip").first.click())
    expect(page.locator(".hotel-card")).to_have_count(3)
    page.locator("#new-trip").click()
    say(f"В Сочи с {day} на 7 ночей вдвоём до 1000 рублей")
    expect(page.locator(".empty-state")).to_be_visible()
    capture("empty")

    # Network failure keeps the user's draft and allows retry.
    page.locator("#new-trip").click()
    draft = f"В Сочи с {day} на 7 ночей вдвоём до 500 тысяч"
    page.route("**/api/sessions", lambda route: route.abort())
    page.locator("#trip-message").fill(draft)
    page.locator(".composer-submit").click()
    expect(page.locator(".alert-error")).to_contain_text("Не удалось связаться")
    expect(page.locator("#trip-message")).to_have_value(draft)
    capture("error")
    page.unroute("**/api/sessions")
    act(lambda: page.locator(".composer-submit").click())
    expect(page.locator(".hotel-card")).to_have_count(3)

    # A failed refinement remains in the internal screen and preserves draft.
    failed_edit = "Нужен бассейн"
    page.route("**/api/sessions/*/messages", lambda route: route.abort())
    page.locator("#refine-message").fill(failed_edit)
    page.locator(".composer-submit").click()
    expect(page.locator(".alert-error")).to_contain_text("Не удалось связаться")
    expect(page.locator("#refine-message")).to_have_value(failed_edit)
    expect(page.locator(".hotel-card")).to_have_count(3)
    capture("error-interior")
    page.unroute("**/api/sessions/*/messages")
    act(lambda: page.locator(".composer-submit").click())
    expect(page.locator(".alert-error")).to_have_count(0)
    assert state()["requirements"]["pool"] is True

    # Stress long genuine text slots without changing persisted API data.
    session_id = page.evaluate("localStorage.getItem('oplan-session-v1')")
    response = state()
    long_name = "Прибрежная резиденция с панорамным видом на горы и Чёрное море — семейный курортный комплекс"
    for plan in response["plans"]:
        plan["hotel"]["name"] = long_name
    page.route(f"**/api/sessions/{session_id}", lambda route: route.fulfill(json=response))
    page.reload(wait_until="networkidle")
    expect(page.locator(".hotel-card h3").first).to_have_text(long_name)
    capture("long-title")
    context.close()
    return errors


def verify_interiors(browser):
    errors = []
    day = (date.today() + timedelta(days=40)).isoformat()
    for width in (*WIDTHS, 320):
        errors.extend(verify_interior_width(browser, width, day))
    assert not errors, errors


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--landing-only", action="store_true")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    chrome = os.getenv("OPLAN_CHROME_PATH") or shutil.which("google-chrome") or shutil.which("chromium")
    installed = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome and installed.exists():
        chrome = str(installed)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True,
            args=["--disable-gpu", "--disable-lcd-text", "--font-render-hinting=none"],
            **({"executable_path": chrome} if chrome else {}))
        verify_landing(browser, args.baseline)
        if not args.baseline and not args.landing_only:
            verify_interiors(browser)
        browser.close()
    result = "clean landing baseline captured" if args.baseline else "landing has zero differing pixels; text, geometry and computed styles exactly unchanged"
    if not args.baseline and not args.landing_only:
        result += "; keyboard/loading/results/update/details/checkout/booked/download/reload/saved restore/clarification/empty/error retry/long titles verified with no overflow or page errors"
    print(f"PASS: {result}; landing 1440/768/390px, interiors also 320px")


if __name__ == "__main__":
    run()
