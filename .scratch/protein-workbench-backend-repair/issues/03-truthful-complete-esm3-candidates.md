# 03 — Emit truthful, complete ESM3 Candidates

**What to build:** ESM3 generation returns scientifically classified Candidates and complete metrics that accurately describe what the provider generated, including valid coordinate-free sequence generation and sampled sequence/structure pairs.

**Blocked by:** 02 — Preserve ProteinPrompt scientific intent at the ESM3 provider boundary.

**Status:** completed

- [x] Coordinate-free sequence generation succeeds without fabricating or serializing a structure.
- [x] A request for paired outputs performs the documented sequence-then-structure operation and returns the requested number of index-paired sequence and structure Candidates.
- [x] Every returned structure is classified as prompt reconstruction or sampled structure according to the operation that produced it.
- [x] Candidate metadata records provider, model, operation, sample index, and relevant source classification.
- [x] pTM and PAE are accepted only from documented shapes, residue axes, and units; malformed responses fail with a structured diagnostic.
- [x] Provider errors and missing declared outputs fail the Node instead of producing an apparently successful partial result.
