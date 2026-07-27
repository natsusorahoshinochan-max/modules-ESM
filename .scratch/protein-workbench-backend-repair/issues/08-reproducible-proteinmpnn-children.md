# 08 — Generate reproducible ProteinMPNN children per selected parent

**What to build:** ProteinMPNN can redesign either one structure or an explicit CandidateCollection, producing the requested number of independently scored, reproducible children for each actual parent Candidate.

**Blocked by:** 07 — Enforce the complete ProteinMPNN constraints contract.

**Status:** completed

- [x] The Module declares separate single-structure and collection behavior and accepts exactly one of those inputs.
- [x] For collection design, `num_sequences` is applied per input parent; three parents with five sequences yield exactly fifteen children.
- [x] Every child Candidate references its actual input Candidate and records sample index, constraint identity, effective seed, provider/model identity, and sampling parameters.
- [x] Every generated sequence receives a score computed from its own tokens.
- [x] A scoring failure or incomplete declared output fails the Node rather than returning an empty successful output.
- [x] Explicit Node seed overrides and the run seed deterministically control ProteinMPNN generation and are reflected in cache identity.
