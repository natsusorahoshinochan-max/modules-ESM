# 12 — Prove the zero-Core extension journey

**What to build:** A repository maintainer can add one conforming test Module Package, validate it with the shared Contract Test Kit, and use it through startup discovery and the complete installed-backend public journey without modifying Core dispatch or inventing package-specific test infrastructure.

**Blocked by:** 08 — Cancel and derive Runs without rewriting history; 11 — Resolve pairwise Observation counterparts.

**Status:** ready-for-agent

- [ ] Contract Test Kit consumes the production Module Package registration plus independent test cases and fixtures rather than embedding test data in the registration.
- [ ] The kit builds an isolated temporary FrozenCatalog and exercises registration, Definitions, Port Types, parameters, Availability, Readiness, provenance, Result Identity, Candidates, Metrics, and produced observations through the unified execution interface.
- [ ] A conforming synthetic package is discovered at startup, appears in Catalog Snapshot, compiles, executes, replays, and retrieves output through the public protocol with no Core dispatch edit.
- [ ] Negative conformance cases cover malformed resources, unknown fields/schema, eager optional dependencies, duplicate or conflicting identities, dangling/cyclic references, invalid codecs, false readiness, and incomplete provenance.
- [ ] Source checkout and installed artifact discover equivalent contracts and behavior identities for the extension, and package-local tests and fixtures are excluded from the production wheel.
- [ ] The production FrozenCatalog does not expose the synthetic echo capability; it remains test support only.
- [ ] Routine CTK and public journey tests are deterministic, isolated, provider-free, and prove no secret, private path, or unsafe diagnostic is published.
- [ ] The resulting maintainer workflow is documented by executable contracts rather than a second package template or Core-specific registration path.
