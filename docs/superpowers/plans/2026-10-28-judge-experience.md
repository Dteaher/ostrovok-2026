# Reliable local travel experience

Goal: make the existing local journey fast, explainable and easy to change without external APIs.
Approach: preserve the current Python domain and visual identity; improve the interaction layer and add explicit offline operation. A redesign or new booking integration would not address the observed problems.

- [x] Explicit local mode, no model requests even with saved credentials; optional validated contact details for saved plans.
- [x] Visible journey composer, transparent preference strength, concise verified before/after price and duration summary, explicit undo.
- [x] Factual comparisons against the cheapest displayed offer, without implying that higher prices are justified by services the user did not request.
- [x] Exercise a multi-turn journey, hypothetical change, empty results/recovery, save/restore, mobile and desktop; run regressions and quality checks.

Additional findings addressed: hypothetical minimum prices must show both comparison bases; conflict repair should name failing constraints and retain concrete numeric bounds. Numeric repairs are verified again and never tighten unrelated thresholds. Browser acceptance covered no overflow at 320/390/768/1440px, save without contacts and reload persistence, explicit undo and verified conflict repair. Local search measured 156–187ms in two browser runs. No claim of unrestricted language understanding or live inventory.

Constraints: preserve pre-existing uncommitted work; no external API requests, deployment, fabricated inventory or automatic relaxation. Implement inline, test behavior before changing it. User authorized autonomous decisions and requested no intermediate approval gates.
