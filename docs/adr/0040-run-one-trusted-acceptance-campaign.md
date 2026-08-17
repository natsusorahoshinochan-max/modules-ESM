---
status: accepted
---

# Run one trusted acceptance campaign

An Acceptance Campaign binds one clean source revision, builds one wheel and
sdist, and executes the 15 canonical tiers once in serial order with one private
Execution Profile. The first failure terminates the Campaign. A passed Campaign
means every tier passed in that one run.

The former Qualification/Certification split is removed. Running the same
expensive Provider and model surface twice added state, retry policy, digest
graphs, evidence promotion rules, and additional failure modes without adding
scientific information. This project trusts its single-user execution process;
it does not need to prove that an operator, process, or filesystem did not alter
an already completed result.

Each tier remains responsible for exact scientific assertions. The Campaign
owns only artifact preparation, canonical serial order, Execution Profile
injection, child execution, retained result locations, and terminal status.
Retained public observations support inspection but are not wrapped in a second
integrity protocol.
