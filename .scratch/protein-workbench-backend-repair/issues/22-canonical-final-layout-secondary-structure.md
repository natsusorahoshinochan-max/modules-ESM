# 22 — Preserve canonical secondary-structure intent in the final layout

**What to build:** A canonical 3GB1 request reaches the scientific provider with the requested secondary-structure assignments at their intended final sequence positions, including when insertion edits change the sequence layout.

**Blocked by:** 21 — Capture the review findings as deterministic red reproductions.

**Status:** completed

- [x] Canonical provider-bound secondary structure has the final sequence length of 71 and exactly preserves every requested assignment at its intended final position.
- [x] SS8 assignments remain unchanged, and final positions with no requested assignment use the documented sentinel value.
- [x] The canonical seed 4242 and at least one additional insertion pattern prove that absolute intent is resolved against the final layout rather than shifted by edit order.
- [x] The repair remains backend-only and does not modify or test the React frontend.
- [x] Before ticket 23 starts, all completed repair checks plus the routine, deterministic-acceptance, and installed-package gates pass; only explicitly deferred findings may remain red, and no unknown failure is accepted.

## Verification evidence

- `repair-findings`: 1 passed / 3 known deferred failures. The canonical secondary-structure finding is green for seeds 4242 and 7; only the Ticket 23 export, Ticket 24 SimpleFold staging, and Tickets 25–26 manifest findings remain red.
- `routine`: 636 selected / exit 0.
- `deterministic-acceptance`: 8 selected / exit 0.
- `installed-package`: 3 selected / exit 0.
- The canonical Workflow now inserts the computed secondary-structure track into the final 71-position layout before applying the absolute `clear_unmentioned` overrides.
- No React frontend source or frontend test was inspected, modified, or executed.
