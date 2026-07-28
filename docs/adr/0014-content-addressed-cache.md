---
status: superseded by ADR-0031
---

# Content-addressed cache with manual invalidation

The cache key is a hash of (module_id, module_version, input hashes,
normalized_parameters, seed). Cache stores successful node outputs as
pickle files in cache/{node_id}_{cache_key}.pkl.

Only successful runs are cached. Failed nodes are never served from cache.
There is no TTL or staleness check; cache entries live until manually
deleted. Node position, color, and annotation (UI-only fields) are excluded
from the cache key, consistent with the architecture document.

This is the simplest caching strategy that meets the personal local use
case. No cache eviction policy, no automatic invalidation on code changes,
no distributed cache coherence.
