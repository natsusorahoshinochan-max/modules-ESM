# 16 — Execute the canonical 3GB1 Workflow to fifteen auditable PDB artifacts

**What to build:** A backend client can run the canonical 3GB1 Workflow and retrieve exactly fifteen final structures whose complete scientific lineage is recorded from ESM3 generation through ranking and ProteinMPNN redesign.

**Blocked by:** 03 — Emit truthful, complete ESM3 Candidates; 06 — Rank Candidates only from complete, unambiguous scores; 08 — Generate reproducible ProteinMPNN children per selected parent; 14 — Expose run recovery and Cache operations to backend clients; 15 — Give the canonical 3GB1 seed a stable, protected identity.

**Status:** ready-for-agent

- [ ] The canonical Workflow validates with zero graph or Port compatibility errors before execution.
- [ ] It produces ten index-paired ESM3 sequence/structure Candidates and ten corresponding initial ESMFold2 structures.
- [ ] Each folded Candidate receives distinct standard TM-scores against 3GB1 and its paired sampled ESM3 structure, and weighted ranking selects the top three.
- [ ] Three distinct selected parent Candidates each produce five ProteinMPNN children with five per-sequence scores.
- [ ] All fifteen children are folded and materialized as exactly fifteen nonempty canonical PDB artifacts under the run namespace.
- [ ] Candidate-to-file mapping is stable, and every recorded artifact size and hash matches the retrieved file.
- [ ] Manifest lineage traces every final PDB through its ProteinMPNN child, selected parent, ranking scores, paired ESM3 generation, effective seeds, and provider calls.
