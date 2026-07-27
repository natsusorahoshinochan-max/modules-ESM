# 06 — Rank Candidates only from complete, unambiguous scores

**What to build:** Weighted ranking selects Candidates only when every required objective is tied to the intended Candidate exactly once, preserving the distinct 3GB1 and paired-ESM3 objectives.

**Blocked by:** 05 — Produce standard reference-normalized TM-scores.

**Status:** completed

- [x] Every structure score names the Candidate it evaluates.
- [x] The 3GB1 and paired-ESM3 TM-score objectives retain distinct score IDs through merge and ranking.
- [x] Weighted ranking applies the configured 0.7 and 0.3 weights to the intended score for each Candidate.
- [x] Missing required score IDs, missing Candidate subjects, and duplicate Candidate/score pairs fail validation.
- [x] Exact weighted arithmetic and deterministic top-three ordering remain correct for a complete ScoreCollection.
