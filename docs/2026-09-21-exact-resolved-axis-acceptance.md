# Candidate–Residue Axis 精确关联：实现验收记录

- 日期：2026-09-21
- 设计：`docs/2026-09-21-exact-resolved-axis-design.md`（状态：已实现并验收）
- 验收主机：`ssh -p 33376 root@connect.weste.seetacloud.com`（AutoDL 容器，128 逻辑核，RTX 4080 SUPER 32 GB）
- 快照：`/root/work/exact-resolved-axis-20260921/source`（复用既有 Python 3.12.14 venv 与 pinned Provider sources）
- 所有测试、构建与 Provider 调用只在该远端执行；本机不做测试或构建。

## 1. 结论

设计文档 §1 的六条完成标准全部满足，全部规定门禁通过：

| 门禁 | 命令 | 结果 |
|---|---|---|
| Routine backend regression | `.venv/bin/python -m verification.backend routine` | **passed** — 1723 passed |
| Deterministic backend acceptance | `.venv/bin/python -m verification.backend deterministic-acceptance` | **passed** |
| Repository v2 examples | `.venv/bin/python -m verification.backend examples-v2` | **passed** |
| Task-shaped Workflow stress | `.venv/bin/python -m verification.backend workflow-stress` | **passed** |
| Repository 7-tier matrix | `verification.acceptance_cli verify-repository --profile …` | **passed** — 7/7 |
| Canonical Acceptance Campaign | `verification.acceptance_cli prepare/run/status` | **passed** — 19/19，`state: passed` |
| WebUI typecheck / real-tests tsc / lint / build / e2e | 见 `webui/README.md` | **passed** — e2e 82 passed |
| Bundled example resource | `verification.webui_example_evidence generate` + `verify` | **passed**，已重生成并回读校验 |

## 2. 验收 Campaign 的 19 个档位

按 Campaign 规范顺序串行执行，一次通过，零 skip、零失败：

| # | 档位 | 结果 |
|---|---|---|
| 1 | `installed-biohub-esmc` | passed |
| 2 | `installed-biohub-esm3` | passed |
| 3 | `installed-biohub-esmfold2` | passed |
| 4 | `installed-local-esm3` | passed |
| 5 | `installed-local-esmfold2` | passed |
| 6 | `installed-mkdssp` | passed |
| 7 | `installed-proteinmpnn` | passed |
| 8 | `installed-simplefold-folding` | passed |
| 9 | `installed-simplefold-confidence` | passed |
| 10 | `installed-soluprot` | passed |
| 11 | `installed-protein-sol` | passed |
| 12 | `fresh-1pga` | passed |
| 13 | `fresh-local-1pga` | passed |
| 14 | `fresh-2emo` | passed |
| 15 | `fresh-local-2emo` | passed |
| 16 | `fresh-canonical-3gb1` | passed |
| 17 | `fresh-local-canonical-3gb1` | passed |
| 18 | `fresh-5g53` | passed |
| 19 | `fresh-local-5g53` | passed |

`status` 输出：`{"passed_tiers": 19, "total_tiers": 19, "state": "passed"}`。

与本设计直接相关的档位：`installed-proteinmpnn`（design/score 仅由 axes 产生 parent slot 与结构主体）、`installed-mkdssp`（`residue_axes` 单例即 annotation subject）、`installed-simplefold-confidence`（subject Port 改为 axes）、`fresh-1pga`（three-way 真实 lineage + align_pairs relation→axis）、`fresh-2emo`（single-axis projection + design + align_pairs）、`fresh-5g53`（inserted-loop 原样透传 + 多组 align_pairs）。

真实 Provider 覆盖：Biohub ESMC / ESM-3 / ESMFold2，本地 ESM-3、本地 ESMFold2、ProteinMPNN、mkdssp、SimpleFold folding 与 confidence、SoluProt、Protein-Sol。**没有任何档位用 mock 替代必需的真实 Provider 调用。**

## 3. 计算设备核实（回应「CPU 高、GPU 低」的观察）

在 Campaign 期间以 2 秒间隔采样 `nvidia-smi`，共 373 个样本：

| 指标 | 观测值 |
|---|---|
| GPU utilization 峰值 | **100 %** |
| 显存峰值 | **29 024 MiB** |
| 非零利用率样本 | 152 / 373 |

结论：真实本地模型档位确实在 GPU 上运行。此前的「CPU 极高、GPU 极低」来自 provider-free 档位（`routine` 按合同用 `pytest -n auto` 铺满 128 核）与真实模型的短时调用，不是 CPU/GPU 误路由：

- `core/local_torch_device.py` 在 Linux 要求 `"cuda"`，`local_torch_device_is_available()` 在 CUDA 不可用时直接让 Binding 失败，没有静默 CPU 回退。
- `tests/support/local_torch_device.py::provider_free_cpu_device_policy` 把 provider-free 测试的平台伪装为 `darwin`，使 `expected_local_torch_device()` 返回 `"cpu"`，这是刻意的设备隔离，不是回退。
- WebUI e2e 的 backend 不注入 Provider 环境，本地模型 Binding 直接报 `*_runtime_unavailable`，不加载模型。

## 4. 实现范围与删除量

`git diff` 核实（不含未跟踪的新文件）：

| 范围 | 文件数 | 增 | 删 |
|---|---|---|---|
| 生产代码 `core/` + `modules/` | 24 | 300 | 426 |
| 测试 | 17 | 610 | 416 |
| 示例与 workflow fixture | 8 | 267 | 561 |
| 合计 | 53 | 1226 | 1416 |

生产代码净减少 **126 行**。新增只有 `modules/structure_transform/candidate_axes.py`（1 个 dataclass + 1 个 join）。

被删除的 Node 输入 Port 共 **11 个**：`structure_candidates` ×6（`extract_sequence_candidates`、`project_single_residue_axis`、`proteinmpnn.design`、`proteinmpnn.score`、`folding.simplefold_confidence`、`structure_annotation.dssp_compute`）、`subjects` ×2（`secondary_structure_agreement`、`align_pairs`）、`references` ×1（`align_pairs`）、`input_structures` ×1（`classify_three_way_consistency`）。

已删除且全仓 0 命中：`axis_for`、`_structure_candidates_with_axes`、`_axes_by_subject`、`def _axis_associations`、`exact_input_candidate_facts`、`require_exact_input_subject`。无旧 constructor alias、无迁移 parser、无新旧 Port 并存。

### 已实施的语义要点

- `CandidateResolvedResidueAxisAssociations` constructor 只冻结 tuples，不再排序；wire codec 与 `scientific_axis_projection` 本来就按 `entries` 顺序，因此 `zip(entries, scientific_axes, strict=True)` 是已定义关系而非位置猜测。
- 顺序 owner 是 resolver producer：entry 顺序 == 输入 Candidate Collection 顺序；该顺序独占 ProteinMPNN parent slot、每 parent 派生 call seed 与输出顺序。改变顺序只改变 population content digest，scalar axis 的 codec digest 与 `ResidueAxisReference.axis_content_digest` 不变。
- `modules/structure_transform/candidate_axes.py::join_candidate_residue_axes` 是两个真实完整-Candidate 消费者（inserted-loop 原样透传、three-way lineage）的唯一共享入口；要求两侧完整 Candidate Data Reference 集合相等，缺失/额外/旧 digest 一律 `ValueError`。
- `core/catalog/builder.py` 的 Produced Observation subject Port 改为要求「已注册 Port Type 同时具备成对 `candidate_data_projection`」，不再要求名义 `candidate.collection`；`subject_direction == "input"` 保留；reference source 仍为 `candidate.collection`。
- `core/execution/output_admission/candidate_identity.py`：父身份来自已准入的完整引用（只在解析某个 parent ID 时要求唯一，同 ID 不同 digest 不得 last-wins）；pass-through 仍要求唯一完整值并拒绝冲突；fresh Score 的完整-Candidate 前提与无变化复制删除，Score Collection identity 构造保留；propagation 的 `require_exact_propagated_subject` 完整保留。
- 保留项全部未被顺手重写：scalar axis codec 与 evidence、pass-through 的 data/lineage/metadata 对比、各 Method 算法与真实 adapter、normalization associations、Prediction Confidence、generic selection/collection、不可变 Commit、durable publication、`rmsd`/`tm_score` 的现有范围声明。

## 5. 实施期间发现并修复的既有缺陷

`tests/support/generate_workflow_stress_fixtures.py` 仍在 `selection.filter` 上写已不存在的顶层 `threshold` 参数（该节点只声明 `selector_ids` 与 `expression`）。按文档合同重新生成 fixture 会让 `multi_selection` 无法编译。生成器改为写 `expression[0].threshold`；重新生成后 `multi_selection` 与 `prompt_conditioning` 与提交版本一致，`multi_parent_batch` 与 `provider_downstream_commit` 只减少本次删除的边。

## 6. Bundled 示例结果重生成

`examples/v2/webui-3gb1.results.zip` 用真实 Provider 重生成，未手改任何 JSON：

```bash
.venv/bin/python -m verification.webui_example_evidence generate \
  --data-root /root/autodl-tmp/exact-resolved-axis-20260921/example-generation-data \
  --profile  /root/autodl-tmp/modules-esm-private/acceptance-profile-c6.json \
  --output   /root/autodl-tmp/exact-resolved-axis-20260921/webui-3gb1.results.zip
```

- Run：`run-b3417a25608b4279ab350488926851c9`，`workflow-commit-ba5a7cc892134f0c8bb4c51a14c4873d`，终态 `succeeded`
- 368 个文件、137 个对象、226 条 ledger transaction
- `sha256:f15eb39e908a97198e27497a331c58a17d80337e8e68596ec1b75b2a32ed1452`
- 无 Provider 回读校验：`typed_value_count=51`、`artifact_count=3`、`status=succeeded`
- 满足 `protein_workbench_public/example_results.py` 的安装合同：受保护 Project、active Commit 与 Draft 均等于 shipped Workflow、全节点 `succeeded` 且 `resolution=executed`、非 derived Run
- `tests/test_webui_example_results_resource.py` 的资源检查保留并通过

重生成前该 zip 仍是旧 66 边 Workflow，它是 `tests/test_webui_example_v2.py` 与两个 `webui-journey` e2e 用例失败的原因；重生成后三者全部通过，`webui-journey` 的持久边数断言由 66 更新为 61。

## 7. WebUI

- `npm run typecheck`、独立 `tsc`（检查 `playwright.real.config.ts` 与 `real-tests/*`）、`npm run lint`、`npm run build` 全部通过。
- `npm run test:e2e`：**82 passed**（含受影响的 `webui-journey` 与 `published-results` specs）。
- 新增真实图回归 `webui-journey.spec.ts` 的 `the example selection chain keeps complete Candidate sources and axes-based score sources`：在 shipped example 的真实 36 节点图上打开选择编辑器，断言完整 Candidate 来源仍来自原 Candidate 分支（`fold-final / structure_candidates`、`take-top-two / candidates`），评分来源来自由有序 axis 承载结构主体的节点（`confidence-final / observations`、`tm-final / scores`），没有任何「已保存来源当前不可用」回退，且已保存观察仍解析到已声明的标量观察。这取代了仅修改手写 UI fixture 的做法。
- `webui/src/published-results.ts` 的 shape 未改动（按 `referenceKey` 建 subject map，本就与顺序无关）。

## 8. 新增/迁移的测试（对应设计 §13 验证矩阵）

新增：

- 有序名义值：输入 B,A 的 roundtrip 仍为 B,A；交换 entries 只改变 population content digest，不改 scalar axis digest。
- 身份分离：两个不同 subject 共享同一结构与 axis 时必须都保留。
- 共享 join：`missing` / `extra` / `stale_digest` 分别拒绝；两侧顺序不同仍关联正确；迭代顺序来自完整 Candidate Collection。
- 父身份：仅由已准入引用提供的 parent 可被接受；未知父仍拒绝；同 ID 对应不同引用时拒绝歧义。
- Pass-through：同 ID 存在冲突完整值时拒绝，不任选一个。
- Fresh Score：不再绑定到同 operation 输出的新身份，subject 原样透传，范围准入由 produced-observation admission 负责。

迁移：`test_structure_transform_candidate_axis_v2.py`、`test_structure_transform_v2.py`、`test_structure_transform_behavior_v2.py`、`test_proteinmpnn_v2.py`、`test_simplefold_confidence_v2.py`、`test_structure_annotation_v2.py`、`test_structure_comparison_v2.py`、`test_operation.py`、`test_pairwise_scoring_v2.py`、`test_folding_v2.py`、`test_module_packages_v2.py`、`tests/acceptance/{test_installed_provider_gates_v2,test_proteinmpnn_scoring_v2,test_simplefold_confidence_v2}.py`。

「双 Port 错配」类用例随被删除的输入关系删除，其科学内容移到各 Method 的单例/条目检查或共享 join；Method 特有拒绝用例（DSSP 多项、scoring 多 parent、SimpleFold 无 CA、relation 范围、SS8 present-pair、track/layout）全部保留。

## 9. 运行位置与证据

- 源码快照：`/root/work/exact-resolved-axis-20260921/source`
- 日志：`/root/work/exact-resolved-axis-20260921/step*.log`、`gpu-campaign.csv`
- Campaign 证据：`/root/autodl-tmp/exact-resolved-axis-20260921/acceptance-campaign/{campaign.json,child-outcomes,results,artifacts}`
- 各档位保留结果：`…/acceptance-campaign/results/<tier>/<UTC-run-id>/`

## 10. 未做与不做

- 未新增 axis subset/reorder Node、未新增「从 axis 重建完整 Candidate」Node、未引入跨请求 axis cache。
- 未重构 ResultBrowser；`published-results.ts` 只验证未改 shape。
- `rmsd`/`tm_score` 未引入 axes，其 `subjects`/`references`/`relation` 范围声明未改。
- 未加兼容 parser、未让新旧 Port 并存、未加 retry/fallback。
- 未做性能 benchmark，不声称运行速度提升百分比；本记录的收益均以删除量与单一 owner 计。

## 11. 审核后的简单修复（2026-09-21）

- 完整 Candidate 与其自身 AdmittedValue 的引用成对保存；另一 Port 的同 ID、不同 digest 引用不再阻断原样透传。
- 只有引用而没有完整 Candidate 时，输出复用该输入 ID 会明确失败；新 Candidate 必须使用 producer-local identity。
- 共享 join 删除 nominal 类型及内部 projection 的重复校验，仅保留跨输入完整引用集合相等检查。
- 新增两个回归测试，其中透传测试覆盖两种输入顺序，共增加 3 个测试实例；同时断言完整值、引用归属和禁止重新计算 hash。

远端复核结果：定向测试 86 passed；routine 1726 passed；deterministic-acceptance 6 passed。日志为 `/root/work/exact-resolved-axis-20260921/review-fix-{focused,routine,deterministic}.log`。独立代码审查与 Python 审查均未发现本轮修复的新问题。本次未重跑真实 Provider Campaign 或 WebUI 门禁，前述记录属于此前验收。
