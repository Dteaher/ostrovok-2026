# Core reliability implementation plan

**Goal:** Correct the demonstrated causes of slow/invalid model responses while keeping MultiAI, the key, VPN, all agent tools, state guards and 10/15/20s budgets.

**Authority:** The user explicitly requested continuous implementation and testing without another planning/approval stop. Work in the existing dirty workspace; preserve unrelated edits. No push or deployment.

**Approach:** Configure reasoning explicitly; constrain model output with an actual evidence schema and compact prompts; share a bounded HTTP connection pool across parsing and deferred narration. Keep validation fail-closed and local responses honestly labelled. Validate actual schema support before enabling it. Network connection failures get a short connection budget and at most one safe retry within the original deadline; authentication/balance failures are never retried.

- [x] RED/GREEN configuration, strict schemas and reusable transport tests.
- [x] Integrate parser, model tools, application lifespan and standalone benchmark session with the shared transport.
- [x] Repeated paid protocol probes, then 40 diverse production scenarios; report core success and narration separately, never count local fallback.
- [x] Fix demonstrated domain failures and repeat affected cases before the final broad run.
- [x] Full Python/JS tests, lint, author review, real HTTP and rendered UI verification. No new independent reviewer dispatched; residual limitations recorded in docs/core-reliability.md.

**Success gate:** No unrequested state/order changes or ungrounded facts; at least 95% successful required LLM stages in the diverse run, normal p50 first-results <=5s and normal deadline <=10s, complex <=15s and alternatives <=20s. Optional narration is measured separately and must not delay ready results. One clean test run is evidence for that run, not an availability guarantee.
