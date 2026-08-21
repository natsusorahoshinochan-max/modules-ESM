---
status: accepted
---

# Result Identity is a scientific cache key

Result Identity is derived from admitted scientific inputs, resolved Node and
Binding parameters, Method and implementation identity, effective randomness,
and the declared output contracts. Project, Run, credential, local-path,
timestamp, and presentation values do not participate.

The physical Cache remains Project-scoped. A hit replays the retained result;
a miss executes the Binding. Failed, cancelled, interrupted, uncontrolled
stochastic, and insufficiently identified results are not cached.

The trusted runtime treats Result Identity as a Cache key, not as a second
cross-Run consistency authority. It does not compare a deterministic Binding
against unrelated Cache bytes or expose a Result Identity conflict error.
