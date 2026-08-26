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

The current checkout owns the meaning of every stable ID. Development Cache
state has no compatibility contract across checkout changes and remains ordinary
Project state. The runtime does not detect definition changes, namespace Cache
generations, or perform an automatic clear or isolation protocol.

The trusted runtime treats Result Identity as a Cache key, not as a second
cross-Run consistency authority. It does not compare a deterministic Binding
against unrelated Cache bytes or expose a Result Identity conflict error.
