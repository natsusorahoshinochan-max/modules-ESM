# 科学单次准入与 I-JSON owner：实施与验收记录

基线：`68666d8f`。规格：[完整设计](2026-09-21-single-admission-i-json-design.md)。状态：实施及全部远端验收完成；最终无失败、阻塞或未执行项。

## 实施范围

- `PortTypeDefinition.validate` 负责 nominal 科学条件；encode、digest、from_wire、projection、restore 不隐含科学准入。decode 保留 canonical envelope 与表示一致性检查。
- 现有 operation-scoped source encoder 首次验证并保留 bytes/digest；最终 Candidate owner 只检查身份、lineage、集合与 metadata。直接完整 Candidate fixture 复用 source 编排，保留 ID。
- fresh materializer 输出必须使用已有 intent。Confidence 与 normalization 完整值只用于已发布恢复或显式 owner fixture。
- constructor 仅表示转换；原科学条件迁移表见设计第 16 节。bool/字符串坐标不强制转换为合法 float。
- `datatypes.i_json` 集中值域、freeze/thaw 与 canonical/hash；删除 core canonical 副本、Workflow 副本、Prediction hash 副本及参数 thaw/refreeze。
- public 请求严格拒绝负零和非法 Unicode key；重复键解析、missing/null、有效值相等语义不变。

不新增验证状态、品牌、模式参数、全局缓存、兼容路径。ObjectStore 完整性、durable write 与真实跨输入关系检查保留。

## 验证方法

所有测试与构建仅在 `connect.weste.seetacloud.com:33376` 的独立快照执行。本地只阅读、编辑、搜索和 diff 检查。远端复用 Python 3.12、已安装前端依赖及私有 profile；凭据不进入源码或日志。

每轮先完成所有独立检查，分别保存退出码与日志，再统一按根因修复。仓库七档逐档执行，不改验证框架。运行中的快照不修改。真实 Provider 阶段从用户要求生效后只每 30 分钟轮询。

任务根目录：`/root/work/single-admission-20260921`。

## 第一轮：完整诊断

源码快照：`round-1/source`。

SHA-256：`a448e3947d53f0e3e6256c4b36266e2ce1ce4f99bc80a627ac8e1c01dd8b73f8`。检查前后源码无变化。

| 检查 | 结果 |
|---|---|
| 定向行为 | 通过 |
| routine | 1700 通过，56 失败 |
| examples-v2 | 通过 |
| workflow-stress | 通过 |
| deterministic-acceptance | 通过 |
| scientific-repro | 通过 |
| local-esmfold2-v2-contract | 通过 |
| installed-package | 通过 |
| WebUI typecheck、real-tests tsc、lint、build | 全部通过 |
| WebUI E2E | 81 通过，1 失败 |
| 真实 Provider 独立诊断 | 19/19 通过；不替代最终正式 Campaign |

日志：`round-1/logs/`；汇总：`round-1/summary-{repository,webui}.json`。
Provider 汇总：`/root/autodl-tmp/single-admission-20260921/round-1-diagnostics/diagnostic-summary.json`，各档均有 outcome。

完整批次结束后统一修复：

- 将仍要求 constructor/codec 拒绝非法科学值的测试迁到实际 nominal owner；保留原科学失败条件。
- 错误详情改用共享 thaw 比较完整 JSON；修正测试局部导入和非有限数错误文案匹配。
- UI 观察选项使用可重试等待，保留原数量要求；运行线程 1 秒阈值不放宽，下一轮降低 CPU 并发。
- canonical parser 映射纯编码异常；Score 去重纯比较区分正负零，保证非法负零到达 nominal owner。
- 补齐直接 Python raw JSON 和 owner fixture source 入口，不向 compiler 或 final facts 增加补验。

## 身份与职责证据

远端与基线比较完全一致：9 类科学 canonical payload/digest、Prediction Key、28 个完整 Port descriptor、219 个科学身份 descriptor。
结果文件：任务根目录 `golden-baseline.json` 与 `round-1/golden-current.json`。

完整链回归覆盖：confidence/normalization source 与 final 各一次、resolved axis/PDB 各一次、Candidate metadata 一次、已发布 ResultStore 恢复不调用科学/JSON validator。既有损坏对象、缺失对象和写失败测试保留。

补充科学负例包括：bool/字符串坐标、四类 Prompt track 长度、annotation 顺序/重复、残缺 axis evidence、两种顺序与嵌套值的负零去重。合法零和其他有限浮点的相等语义保持。

## 最终验收

第二轮快照：`round-2/source`，源码 SHA-256：`94642e8b74873a12a8eeba100044a61792175b41a936d0dbf77c7532736044fa`。835 个源码文件前后摘要相同，`source_changes=[]`；Golden 比较再次通过。后端与 WebUI 顺序批测，CPU worker 数降到 4；不改任何时间断言。

13 项独立检查全部退出码 0，无失败、阻塞或未执行：

| 第二轮检查 | 通过数量 |
|---|---:|
| focused | 131 |
| routine | 1780 |
| examples-v2 | 11 |
| workflow-stress | 11 |
| deterministic-acceptance | 6 |
| scientific-repro | 1 |
| local-esmfold2-v2-contract | 9 |
| installed-package | 4 |
| WebUI E2E | 82 |
| WebUI typecheck、real-tests tsc、lint、build | 全部通过 |

汇总：`round-2/summary-all.json`；完整日志：`round-2/logs/`。

最终正式 Campaign 使用第二轮源码新 prepare，根目录 `/root/autodl-tmp/single-admission-20260921/final-campaign-round-2`。`prepare.exit=0`、`run.exit=0`，`campaign.json` 状态为 `passed`：定义 19 档、执行 19 档，每档均通过且 `failures=0, skipped=0`。台北时间 20:40:45 启动，21:07:34 完成，21:12 按约定轮询读取结果。没有用第一轮独立诊断代替正式 Campaign。

十九档覆盖 Biohub ESMC/ESM3/ESMFold2、本地 ESM3/ESMFold2、mkdssp、ProteinMPNN、SimpleFold folding/confidence、SoluProt、Protein-Sol，以及远端/本地各自的 1PGA、2EMO、canonical 3GB1、5G53 完整流程。各档保留 JUnit、运行证据及所要求的 lifecycle receipt。

新产物 SHA-256：wheel `68db2843636f77315fb9e2feece9309a45abad4a67cfa4bee3d1473cd46b89b7`；sdist `e4cfe97912fd4fa9bd1c9e9a9565d948eb42b40c3b46b941eef104c90775a190`。Campaign 后重新计算源码摘要仍为上述第二轮摘要，变化列表为空。

本记录在测试快照冻结后补记，不修改正在运行的快照，也不把待运行或阻塞检查记为通过。

## 删除统计

生产实现（含 tools）：新增 693 行、删除 877 行，净减少 184 行。无新增生产文件。最终统计包含新增测试和文档文件，不将它们遗漏。

远端另用标准库 tokenize 与 AST 对比基线和第二轮的全部生产 Python 文件（含新增/删除文件）：排除空白、注释和 docstring 后，有效代码行 `44976 → 44795`（减少 181），有效 token `221834 → 221330`（减少 504）。这项统计不包含 YAML 或 TypeScript，与总 diff 分列；没有用注释删行掩盖实现增长。

逐文件数据：`round-2/code-counts.json`。

| 类别（包含所有新增文件） | 新增行 | 删除行 | 净变化 |
|---|---:|---:|---:|
| 生产实现（含 tools） | 693 | 877 | -184 |
| 测试（含新建 test_i_json.py 及 WebUI E2E） | 612 | 181 | +431 |
| 文档（设计与本验收记录两个新文件） | 432 | 0 | +432 |

仅验收记录与设计状态在快照之后补记；生产、测试及其他非文档文件与已验收快照的逐文件 SHA-256 一致。未在本地执行测试或构建，未自动提交或 push。
