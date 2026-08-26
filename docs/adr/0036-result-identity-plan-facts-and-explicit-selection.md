---
status: accepted
---

# Result Identity uses compiler-owned plan facts and Selection is explicit

Result Identity identifies one reproducible scientific Node result. It is
independent of Workflow layout and authoring locators. Node Instance IDs,
Workflow edge locators, Selection Objective labels, Run IDs, Project IDs, and
unrelated downstream definitions cannot change the identity of an otherwise
identical result. The in-process Execution Plan remains topology-sensitive.

The compiler owns the static Result Identity facts. For every compiled Node it
creates one typed `ResultIdentityPlanFacts` value containing the stable
result-affecting Node Type, Binding, Method, input and output Port IDs, produced
Observation definitions, and only the Selection Objectives or Observation
Selectors consumed by that Node. Presentation fields and locator-like parameter
indirections are excluded. Scientific objective facts such as Metric, Method,
Observation Context, Utility Transform, weight, and missing-value policy remain
included.

At execution time the runtime extends that projection with admitted scientific
input content identities, normalized Node and Binding parameters, resolved
scientific resource content identities, and effective randomness. It does not
reconstruct static facts from the Workflow or scan the Catalog. Provider source,
checkpoint, installation form, and CPU/GPU device are excluded. CPU/GPU tiny
numerical variation is accepted and does not create device-specific Cache keys.

An opaque Project Input locator and its filename are storage and provenance
labels rather than scientific identity. The runtime resolves the locator before
identity construction and uses the resource's semantic role and scientific
content identity. Renaming the locator or filename for identical scientific
bytes preserves Result Identity; changing those bytes changes it.

Result Identity remains the Project-scoped Cache key. Internal Cache entries and
manifests use only the fields required for replay; they do not require a
versioned namespace, descriptor digest, exact closed JSON shape, or canonical
metadata text. The Run Evidence Ledger records the stable IDs and minimum
scientific definitions needed to interpret the result rather than a duplicate
plan-facts digest.

Stable IDs name the current definitions. The runtime does not retain historical
definition generations or perform a Cache cutover when a checkout changes.
Existing Cache entries remain ordinary Project development state; there is no
version namespace, compatibility migration, descriptor digest, or cross-Run
conflict check.

Selection executes only through an explicit Selection Node and its canonical
scientific operation. Every Workflow Selection Objective and Observation
Selector must be consumed by one declared consumer; unconsumed facts and
multiple consumers of the same declaration are compile errors. There is no
end-of-Run weighted-selection fallback or synthetic `__workflow__` operation.
Selection therefore receives the same Method, Result Identity, Cache, Operation
Attempt, output admission, lineage, and evidence treatment as every other
scientific operation.

ADR-0031 defines scientific Result Identity and Project-scoped replay;
ADR-0039 defines atomic value publication.
