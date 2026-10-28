# O!RIVANE: bounded concierge agent

## Audit / priorities

- P0: no persistent initial-value restoration; no read-only explanation/comparison tools; extraction owns all natural language. Preserve existing CAS, canonical validation and checkout idempotency.
- P0: explanations must be assembled only from current server facts. Model chooses tool, focus, evidence order and useful next question; no arbitrary model claim is published.
- P0: Docker Engine/Desktop and usable WSL are unavailable. Do not install system components or claim execution. Review Compose/build inputs and document the remaining verification gap.
- P1: replace mixed score ranking with explicit preference-count, price, rating and beach ordering; allow user price/beach/rating priority without relaxing constraints.
- P1: one visible clarification at a time; unobtrusive rationale and compare actions in existing interior style.

## Implementation

1. Add failing state-history and ranking tests. Record bounded private initial values and history on backend; restore only requested scopes and recompute canonical offers.
2. Add `app/agent.py`: strict decision schema, allowlisted tools for explain/compare/details/alternative/prioritize/restore/prepare checkout. Bounded model cycle and sanitized failures. Read-only tools cannot buy or modify prices. Existing extraction remains the edit tool.
3. Add `app/evidence.py`: facts from canonical plans/search only, pairwise backend differences, unsupported-feature disclosures, fact IDs and claim validation. Generated presentation chooses validated IDs; no free model assertions reach UI.
4. Hook dispatcher into `process_message`, add public agent result/next action and preserve existing API. Add shared provider transport only if needed for bounded retries/deadlines; do not change MultiAI.
5. Add minimal responsive UI for rationale, comparisons and next actions. Reuse existing CSS/fonts, preserve landing. Confirm checkout through existing form only.
6. Add 25+ agent/tool/API scenarios, malicious/failure tests, actual provider probes, full HTTP and browser journey. Review Docker/README/security/diff and report limits.

## Verification

Unit tests before implementation, then targeted pytest/Ruff; full suite at integration boundaries. Real network tests are separate from pytest and use synthetic inputs only. Desktop/mobile visual verification and checkout idempotency before delivery. No submission tag, publishing or remote push.
