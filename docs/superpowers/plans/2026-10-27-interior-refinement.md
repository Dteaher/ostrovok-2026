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
- [ ] Add failing behavior tests for normalized partial edits, invalid/empty numeric inputs, children ages, unique compatible images and readable policies.
- [ ] Implement UI helpers and a responsive accessible trip editor using the existing requirements PATCH endpoint.
- [ ] Compress selected-plan introduction, consolidate routine explanations, prioritize stay name/image/price; refine internal typography and route layout.
- [ ] Add a fourth clearly labelled demo illustration and ensure stable imagery across cards/details/saved trips.
- [ ] Run Node and Python checks; exercise editor cancellation, submit, validation, failed save, selected-plan recheck and checkout in the browser.
- [ ] Compare desktop/mobile landing baselines, inspect layouts at 1265/768/390/320px, review diff and obtain independent final review.

Implementation note: Windows serves `.mjs` as `text/plain` in this environment. Use `.js` with module syntax and cover its actual response MIME type in an API regression test.

## Review focus
- A blank budget removes only the budget, never silently imposes zero.
- Child age zero is valid; missing/new ages block save.
- A failed/stale PATCH preserves the editor draft and never claims success.
- Required preferences survive basic edits and hotel changes require explicit selection.
- Narrow layouts, long names and reduced motion remain usable.
