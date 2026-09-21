# Catalog、Selection 与 Run 阅读：实施与验收记录

基线：`2b83d8e3`。设计：[四项分析与设计](2026-09-21-next-four-architecture-design.md)。状态：实现及全部远端验收完成，失败、阻塞和未执行项清零。

## 实施边界

本轮仅实施 04、12、07。05 科学阅读投影未达到净减法门槛，暂缓；不新增 public 协议或展示 registry。

- FrozenCatalog 在启动构建中持有已有 typed Observation plan；Compiler 和 capability 推导消费相同事实。
- Selection 复用原 selector 和已准入参数，删除等价包装；保留 objective 的新增事实、identity 与 evidence 的语义区别。
- PublishedResults 统一拥有当前 Run 的阅读会话。REST 决定持久生命周期，WebSocket 更新实时活动、诊断和连接并触发刷新；完成状态允许晚一个 REST 请求显示。

## 验证规则

测试、类型检查、构建和 Provider 仅在 `connect.weste.seetacloud.com:33376` 执行。本地仅阅读、编辑、搜索和 diff 检查。

任务目录：`/root/work/catalog-selection-run-20260921`。每轮固定源码，保存逐文件摘要、独立检查退出码、日志和结构化结果；运行中的快照不修改。

每轮收齐定向测试、七档后端和 WebUI 五项检查后，再按共同根因批量修复。所有非真实 Provider 检查通过、失败与阻塞清零，才启动同一源码新构建的正式十九档 Campaign 与 WebUI 真实旅程。真实 Provider 阶段每三十分钟检查一次，不增加中间轮询。

## 验收结果

第一轮非 Provider 批次于 2026-09-21 13:47 UTC 启动。快照：`round-1/source`；源码摘要：`24eb94f2d4bea942e757f15b3fe29c6eee9361ebcfffa7bbb25e6fb3bc7228eb`。全部十三项已收齐，前后源码清单及摘要无变化。

| 检查 | 第一轮结果 |
|---|---|
| 定向行为 | 191 通过，6 失败 |
| routine | 1762 通过，19 失败 |
| examples-v2 / workflow-stress | 各 11 通过 |
| deterministic-acceptance / scientific-repro | 6 / 1 通过 |
| local-esmfold2-v2-contract / installed-package | 9 / 4 通过 |
| WebUI typecheck / real-tests 类型检查 / lint / build | 全部通过 |
| WebUI E2E | 87 通过 |

收齐结果后统一修复：Catalog 测试中的不完整定义与未登记 Binding、Operation fixture 的旧 resolver 形状，以及仍禁止 Scoring 消费已准入参数 model 的旧架构断言。科学行为断言保留；不在生产实现添加兼容或 fallback。第一轮未启动真实 Provider。

Golden 与基线一致：9 类科学值的 canonical bytes/digest、Prediction Key、28 个 Port descriptor、219 个科学身份 descriptor。该结果不能替代行为测试或真实 Provider 验收。

第二轮快照 `round-2/source` 于 14:09 UTC 启动；源码摘要：`68c55b05a8211db84f2a81ab17fe6ade0dea4a7006eefef6c1a062c0d6a5fb1c`。仅修复上述测试迁移问题，生产实现与第一轮一致。全部检查完成前不进入真实 Provider。

第二轮十三项独立检查全部退出 0：定向 197、routine 1781、examples-v2 11、workflow-stress 11、deterministic-acceptance 6、scientific-repro 1、local-esmfold2-v2-contract 9、installed-package 4、WebUI E2E 87；WebUI typecheck、real-tests 类型检查、lint、build 全部通过。Golden 一致，完整文件清单及摘要前后无变化，失败与阻塞清零。汇总：`round-2/summary-all.json`。

正式 Provider 阶段于 14:28:25 UTC 启动，根目录 `/root/autodl-tmp/catalog-selection-run-20260921/final-round-2`。启动包装器先核对十三项结果、Golden 和源码完整性，再新建十九档 Campaign，随后用同一 wheel 与本轮 WebUI dist 运行真实浏览器旅程。包装器于 15:00:13 UTC 完成；首次定时检查在 15:00:31 UTC 到达，超过约定的最早检查时间 14:58:35 UTC，期间没有中间轮询。

| 正式验收 | 最终结果 |
|---|---|
| 新 prepare / Campaign run | 退出码均为 0，Campaign 状态 `passed` |
| 十九档真实 Provider | 19/19 通过，每档 failures=0、skipped=0 |
| 真实 WebUI 旅程 | 6/6 通过，零失败、错误和跳过 |
| FASTA 证据报告 | 退出码 0 |
| 安装产物 smoke | 3/3 通过，零失败、错误和跳过 |
| 完整源码清单及 SHA-256 | 前后相同，`source_changes=[]` |

Campaign 记录：`campaign/campaign.json`，各档 JUnit 与运行证据保存在 `campaign/results/`。真实 UI 记录：`ui/ui-evidence/summary.json`、`real-junit.xml`、`smoke-junit.xml` 及 trace；总汇总为 `summary.json`。正式验收覆盖远端与本地模型、完整科学流程，以及浏览器中的 FASTA、Prompt/ESM3、MPNN 谱系、取消和删除，不复用旧通过记录。

本轮 wheel SHA-256：`978ca72dd90f5dd6f3aa4307811d18568b60aeb5d43d2fd9bcfb64f65c194882`；sdist：`7fe299cbea67f96c31ae6ba6e248c458d163f5b620c09c8b0d92e11362e378f8`。

验收完成时，本地全部非 Markdown 文件通过逐文件 SHA-256 对照，与第二轮测试快照一致。随后文档维护同步了现行职责、验收导航与远端执行规则，删除旧设计诊断和迁移步骤；未修改实现、测试或运行快照。未在本地运行测试或构建，未提交或 push。

## 删除统计

以下统计记录实施验收完成时相对基线的变更，覆盖当时所有新增文件；文档数字是后续文档清理之前的交付快照，不是当前工作树计数。生产有效代码另排除空白、注释和 docstring。文件移动不记作职责删除，不以其他候选的删行抵消新增复杂机制。

生产实现新增 308 行、删除 435 行，净减少 127 行；测试新增 311 行、删除 287 行，净增加 24 行。均包含新增文件。

| 类别（包含全部新增文件） | 新增行 | 删除行 | 净变化 |
|---|---:|---:|---:|
| 生产实现 | 308 | 435 | -127 |
| 测试 | 311 | 287 | +24 |
| 验收时文档快照（设计与验收记录） | 334 | 0 | +334 |

远端统计 Python 使用 tokenizer 与 AST docstring 排除，TS/TSX 使用 TypeScript parser 的叶 token，排除 trivia、注释和纯空白 JSX 文本；有效行是具有这些 token 的物理行，不是复杂度或性能指标。

| 生产范围 | 物理行变化 | 有效行变化 | token 变化 |
|---|---:|---:|---:|
| Python | -108 | -92 | -374 |
| TypeScript | -19 | -18 | -445 |
| 合计 | -127 | -110 | -819 |

对应 `round-2/code-counts.json`。没有以删除注释或移动文件掩盖实现增长。
