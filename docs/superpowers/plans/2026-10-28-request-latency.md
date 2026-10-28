# Request latency implementation plan

**Goal:** Deliver verified results without waiting for optional narration; enforce one request budget and evaluate Haiku fairly within MultiAI.

**Spec:** User request of 28 October 2026: ordinary target 3–5s, maximum 10s; complex rebuild 15s; alternatives 20s. Preserve all tools, evidence validation, revision guards, and explicit checkout consent. Never count fallback as LLM success.

**Architecture:** A monotonic request budget follows parsing, synchronous search, tool planning, and optional narration. Search runs off the event loop. Narration starts after the initial result is committed and uses only the originating budget; a separate revision-checked response updates only the explanation panel. No background write can overwrite trip state.

**Execution:** Implement inline in the existing `codex/oplan` branch. Existing uncommitted changes are the working baseline and must be preserved; creating a clean checkout would omit them. The user explicitly requested implementation of the agreed approach, so no additional approval gate is needed. No automatic commits or push.

- [x] Add request budgets and regression tests: classification; parsing/search cancellation; rollback of interrupted mutations; timeout facts and honest modes.
- [x] Defer narration with an immutable snapshot, shared deadline, bounded task lifecycle, revision checks, and tests for stale responses, expiry, exceptions, and checkout safety.
- [x] Update the existing explanation panel independently; abort obsolete fetches, preserve input/focus, exercise desktop/mobile states.
- [x] Build a reproducible sequential paired benchmark: 40 diverse cases per model, domain/tool assertions, uncensored failure counts, successful-call p50/p95 and timeout-inclusive latency. Switch configuration only if Haiku meets the quality and latency gate.
- [x] Run complete Python/JavaScript suites and lint, inspect rendered UI and diff, document measured outcomes and limitations.

**Review focus:** simultaneous edits; cancelled search workers; repeated explanation requests; exhausted/restarted jobs; hypothetical questions and unrequested state changes.

**Review rulings:** retain completed jobs until deadline+30s; resume narration after failed mutations; include storage and encoding in HTTP budgets. SQLite busy-handler waits overshoot wall time on Windows, so deadline-bound operations fail fast on lock contention; failed COMMIT connections are invalidated to prevent later reads committing pending writes. Independent reviewer confirmed writer/reader lock regressions pass with no remaining Important findings. PostgreSQL execution remains unverified. Haiku did not meet the measured replacement gate; Luna remains selected.

**Final evidence:** 454 Python tests passed; 22 JavaScript tests passed; Ruff passed; git diff whitespace check passed. Browser journeys and narration panel inspected at desktop/mobile sizes. Existing Starlette/httpx deprecation warning remains. Paired benchmark and final smoke are linked from `docs/request-latency.md`; `.env` remains ignored and the configured key was absent from task source/report files.
