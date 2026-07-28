# 02 — Publish canonical nominal Port Types

**What to build:** A client can query exact, versioned nominal Port Types from the v2 Catalog Snapshot and rely on their validators, canonical codecs, content digests, and contract identities to mean the same thing in source and installed deployments.

**Blocked by:** 01 — Freeze the v2 public protocol contract.

**Status:** ready-for-agent

- [ ] Every Port Type has an exact ID, version, closed canonical descriptor, contract digest, runtime validator, canonical codec, and content-digest procedure.
- [ ] Callable behavior is represented by explicit stable behavior ID/version and immutable declaration parameters, never by object repr, memory address, source path, source text, or bytecode.
- [ ] Catalog Snapshot exposes stable Port Type contracts without exposing private Python implementation details.
- [ ] Direct connection compatibility accepts only the same Port Type ID/version; unknown types, structural similarity, subtyping, implicit coercion, and version ranges fail closed.
- [ ] Codec round-trip and content-digest tests cover complete valid values, malformed values, non-canonical values, and the requirement for explicit conversion Nodes.
- [ ] Golden and differential vectors prove the required ordering, default materialization, Unicode, I-JSON, RFC 8785, and SHA-256 rules, including rejection of negative zero, NaN, Infinity, duplicate keys, and unversioned behavior.
- [ ] Source-checkout and installed-artifact Catalog probes produce byte-identical Port Type descriptors and digests.
