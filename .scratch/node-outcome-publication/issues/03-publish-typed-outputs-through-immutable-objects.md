# 03 — 通过 immutable value objects 发布大型 Typed Outputs

> Historical completion evidence only. Checksums, symlink/security probes, Readiness-before-Cache, restart reconstruction, and old verification tiers mentioned below are not current requirements.

**What to build:** 让合法 Typed Outputs 不再内嵌于 Ledger 或 Run Projection，而是由 committed descriptors 指向 Project-scoped immutable values；用户可以按 Run、Node、Port 和 value index 精确获取单个 canonical value。

**Blocked by:** 02 — 将 Run Evidence Ledger 切换为原子 transactions

**Status:** completed

- [x] admitted canonical values 在 Ledger commit 前作为 content-addressed objects durable，Port Value Manifest 保留顺序、Port Type、aggregate digest、value count、per-value digest 与 size。
- [x] successful Node publication transaction 只包含 bounded Typed Output descriptors，不包含 embedded canonical values。
- [x] Run Projection 不再公开 `values`；single-value retrieval 严格 Run-scoped，并返回 exact canonical bytes、size、individual digest、aggregate Port digest、Port Type 和 manifest identity。
- [x] 当前 frontend 能从 descriptor 选择并获取单个值；WebSocket 与 lifecycle events 不携带 scientific values。
- [x] 使用真实注册 ESM-3 Port codecs 的 291-residue、2-sample、reconstruction 与两组 PAE fixture 可完整发布和逐值取回。
- [x] declared `num_samples=100` 的 provider-free fixture 证明 Ledger transaction size 只随 descriptor metadata 增长，不随 scientific bytes 增长。
- [x] embedded/reference dual path 与 superseded embedded-output producers、consumers、fixtures 和 examples 已一起删除。
- [x] 当前 ticket 的 focused object-store、manifest、public protocol、frontend 与 large-output tests 通过。
- [x] 标记完成前，重跑 Tickets 01–03 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- Focused cumulative Tickets 01–03 public, transaction, object-store,
  cleanup, protocol, and large-output matrix: `190 passed, 3 deselected`.
- Final provider-free backend matrix: `routine` (`1225 passed, 45
  deselected`), `examples-v2` (`12 passed`), `deterministic-acceptance` (`8
  passed`), `scientific-repro` (`1 passed`), `local-esmfold2-v2-contract`
  (`6 passed`), `installed-package` (`3 passed`), `provider-isolation` (`16
  passed`), and `security-failure` (`10 passed`).
- Frontend `npm run lint` and `npm run build` passed on the final checkout;
  Vite transformed 178 modules including the mounted Typed Output Explorer.
- Registered ESM-3 regression: seven focused publication tests pass, including
  exact 291-residue, two-sample reconstruction and both PAE groups, plus the
  declared `num_samples=100` bounded-transaction proof.
- Final fixed-point `code-review` against
  `43c5099b283329e579d83aa96076ddf67e19d9ea` reported zero Standards findings
  and zero Spec findings after all repair rounds.
- All verification ran serially without `xdist`, real Provider invocation, or
  concurrent model loading. `git diff --check` and Python compilation passed.
