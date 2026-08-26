---
status: accepted
---

# Result Identity is a scientific cache key

Result Identity is derived from admitted scientific inputs, resolved Node and
Binding parameters, Method and implementation identity, effective randomness,
and the declared output contracts. Project, Run, credential, local-path,
timestamp, presentation, Provider installation form, and CPU/GPU device values
do not participate. CPU/GPU tiny numerical variation is accepted within the
same scientific and Cache identity.

The physical Cache remains Project-scoped. A hit replays the retained result;
a miss executes the Binding. Failed, cancelled, interrupted, uncontrolled
stochastic, and insufficiently identified results are not cached.

When the current checkout changes a result-affecting definition without changing
its stable ID, the new checkout must clear or isolate Cache entries written by
the superseded definition before execution begins. Development Cache state is
invalidated rather than migrated or incorporated into a versioned identity.

The trusted runtime treats Result Identity as a Cache key, not as a second
cross-Run consistency authority. It does not compare a deterministic Binding
against unrelated Cache bytes or expose a Result Identity conflict error.
