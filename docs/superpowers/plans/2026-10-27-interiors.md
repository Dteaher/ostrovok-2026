# O!RIVANE internal screens

**Goal:** Make existing post-landing trip planning clear, compact, coherent and premium without changing the landing or backend behavior.

**Direction:** Calm editorial travel service: cream paper, navy text, restrained brass accents, medium serif headings, readable sans-serif facts. Hotel proposals lead the results page; a chosen trip uses a compact visual summary, grouped itinerary and one clear checkout area.

**Isolation:** Add only scoped `interiors.css` rules under `.has-session` and `.trips-dialog`. Preserve existing landing DOM/functions, all original styles/assets and header/footer behavior. Capture and compare full-page landing pixels at 1440/768/390 before/after.

- [x] Capture initial landing and inspect current flow.
- [x] Redesign intro/conditions/cards/clarification/empty/error states.
- [x] Redesign selected plan, checkout, booked result and saved trips.
- [x] Add clearly marked local fictional accommodation imagery.
- [x] Verify full journey, state regressions, keyboard, focus, loading, long names, desktop/mobile and exact landing preservation.
- [x] Review actual screenshots, polish and run all project checks. 246 tests + four browser scripts pass; 0 landing pixel differences at 1440/768/390; interiors additionally checked at 320, with independent checkout at 560/851/1024.

No new providers, backend changes, major features, publishing or deployment. Existing semantic conditions, prices, canonical validation and revision handling remain authoritative.
