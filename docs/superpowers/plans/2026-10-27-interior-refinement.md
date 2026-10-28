# Interior refinement implementation plan

> Execute inline using executing-plans. User authorized implementation and autonomous routine design decisions.

**Goal:** Show the selected stay and price immediately, allow direct edits of trip basics, and refine imagery and typography without changing the landing.

**Architecture:** Keep the existing DOM renderer and PATCH API. Extract pure UI value normalization, image assignment and policy formatting into a small ES module; use a native dialog for editing. Keep all new layout rules scoped to internal screens.

**Stack:** Vanilla JavaScript/CSS, FastAPI, Node test runner, pytest, CUA browser verification.

**Spec:** User-approved three priorities from the design review in this chat; original landing remains unchanged.

## Constraints
- Preserve backend rules, required preferences, selected-hotel retention and revision checks.
- Do not apply edits before submit, discard drafts on cancel, preserve drafts after failed save.
- Keep consequential prices, cancellation penalties and clarification messages visible.
- No deployment, new service dependencies or changes to the landing styling/copy.

## Tasks
- [x] Add failing behavior tests for normalized partial edits, invalid/empty numeric inputs, children ages, unique compatible images and readable policies.
- [x] Implement UI helpers and a responsive accessible trip editor using the existing requirements PATCH endpoint.
- [x] Compress selected-plan introduction, consolidate routine explanations, prioritize stay name/image/price; refine internal typography and route layout.
- [x] Add a fourth clearly labelled demo illustration and ensure stable imagery across cards/details/saved trips.
- [x] Run Node and Python checks; exercise editor cancellation, submit, validation, failed save, selected-plan recheck and checkout in the browser.
- [x] Compare desktop/mobile landing baselines, inspect layouts at 1265/768/390/320px, review diff and obtain independent final review.

Implementation note: Windows serves `.mjs` as `text/plain` in this environment. Use `.js` with module syntax and cover its actual response MIME type in an API regression test.

## Evidence
- Nine Node behavior tests passed, each introduced RED before its implementation; 247 pytest tests passed. Ruff and JavaScript syntax checks passed. Existing Starlette/httpx deprecation warning remains.
- CUA: cancel preserves conditions; missing child age blocks submission; age zero and changed nights apply; refundable/quiet priorities remain; selected hotel is retained and requires new-price confirmation.
- CUA: two-tab revision conflict shows an inline error, preserves the edited budget, and retry applies only that budget while preserving the other tab's new duration.
- CUA: selected illustration survives reload; complete checkout with synthetic data creates a demo confirmation.
- CUA: plan/editor checked at 1265/768/390/320px, no horizontal overflow or out-of-dialog fields. Mobile Escape returns focus to edit button. Saved PNGs in ignored `artifacts/refinement/`.
- Landing at 1265×712 and 390×844: all element geometry/styles equal baseline; Pillow pixel comparison has no differing pixels.
- Independent read-only review found one P2: illustration reassignment on reopening a retained hotel. Fixed by persisting sanitized per-session mappings; regression test RED→GREEN. No remaining actionable findings from that review.

## Review focus
- A blank budget removes only the budget, never silently imposes zero.
- Child age zero is valid; missing/new ages block save.
- A failed/stale PATCH preserves the editor draft and never claims success.
- Required preferences survive basic edits and hotel changes require explicit selection.
- Narrow layouts, long names and reduced motion remain usable.
