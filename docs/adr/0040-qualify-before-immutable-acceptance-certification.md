---
status: accepted
---

# Qualify before immutable acceptance certification

One Acceptance Campaign binds a clean source revision, exact built artifacts,
public and Catalog contracts, Provider assets/configuration, and a private
Execution Profile identity. Every one of its 15 tiers must first produce a
current Qualification Result against that same candidate. Qualification is
explicitly non-authoritative, may run tiers in risk order, and may rerun a
failed or interrupted tier while the candidate identity remains unchanged.

Only a fully qualified candidate may start a Certification Generation.
Certification always executes all tiers again as one fresh canonical serial
sequence. Its passed results are authoritative; a failed or interrupted tier
is durable and terminal, and qualification evidence is never promoted,
combined, or substituted for certification evidence.

This separates defect discovery from evidence issuance. It accepts the cost of
executing the real acceptance surface twice so late defects do not repeatedly
invalidate partially completed authoritative generations. The controller owns
the campaign state, exact execution environment, child lifecycle, and retained
diagnostics; shell history and operator memory are not part of the contract.
