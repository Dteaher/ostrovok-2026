# Dialog core implementation plan

**Goal:** Reliable local changes of travel requirements, preference-aware search, and retained hotel intent with newly verified offers.

**Architecture:** Extend the existing FastAPI/Pydantic/search service. Retain scalar requirement fields and add an optional priority map for backward compatibility. Keep selected hotel intention separate from a priced offer. No external APIs, dependencies, publishing, or destructive data changes.

**Spec:** User request in attachment `354d0f1f-bc06-4148-bf6d-9b9e785d5e85/Вставленный текст.txt`.

- [x] Add required/preferred semantics and verified conflict suggestions in models/search; test legacy and new requirements.
- [x] Extend finite local parser for priorities, neutral conditions, relative changes and hypothetical questions; test without network.
- [x] Add explicit state transition rules, pinned hotel intent, safe re-selection and checkout validation; test through HTTP.
- [x] Display preference fulfillment, conflicts and pinned hotel intentions in existing UI without redesign.
- [x] Run regression, browser, lint and diff reviews; final integration and repairs completed. 246 tests, three browser checks and 12/12 HTTP cases passed. Docker unavailable; external provider intentionally not called.

Review focus: no unintended field resets; no stale offers after date/guest/priority changes; no silent hotel replacement; hypothetical and ambiguous messages preserve trip and selection; suggestions must reproduce real search results and never remove pet/accessibility needs.
