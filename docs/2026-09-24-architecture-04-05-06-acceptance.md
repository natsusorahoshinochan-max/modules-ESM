# 04/05/06 架构改造验收记录

状态：实现、消费者迁移及本次固定快照的完整远端验收完成。设计与范围见[04/05/06 设计](2026-09-22-architecture-04-05-06-design.md)。

## 最终实现

- 04：Observation 声明和运行计划共用 typed 科学合同，保留真正派生的 Metric facts。
- 05：科学 owner 提供阅读投影，public 负责协议组合；PublishedResults 统一详情、关联和导出读取，删除 core 中面向 public 页面形状的 ResultBrowser。
- 06：WorkspaceEditor 统一参数、Selection、Prompt 的编辑与持久化；流程和明确布局操作共同发布，纯内容长会话不重建布局。删除 Prompt 专用 apply 持久化链。

Run 准备仍遵守 Commit 先保存 Draft 再编译的合同。WorkspaceEditor 在 Commit 成功或编译失败后读取并更新已确认基线，保留 desired 内容与撤销历史；退休会话的迟到结果不覆盖新项目。真实旅程通过 UI 提交并执行保存的 Selection，不再用额外的直接 Commit 悄悄推进浏览器外的 revision。

canonical Workflow 教程及其正常启动安装保留；科学断言、真实 Provider 门槛及未知扩展的原值出口保留。

## 执行与快照

所有测试、类型检查、构建、浏览器与 Provider 执行均在 `connect.westb.seetacloud.com:12933`，本地仅编辑、阅读与摘要/diff 检查。本任务按用户最新指令取消静默等待约定，保留固定快照、整批收集后修复及阶段准入规则。

最终快照：`/root/work/architecture-04-05-06-20260922/round-5/source`。

源码 SHA-256：`9d1558c8b13962a3e819d929a7438040f8bc205a29944b93e107e50af0023faf`。

正式验收根目录：`/root/autodl-tmp/architecture-04-05-06-20260924/final-round-5`。正式验收于 2026-09-24 05:16:11 UTC 开始，05:41:31 UTC 完成。源码完整性前后相同，`source_changes=[]`；收尾文档更新前，本地 846 个文件与该快照逐文件一致。

## 最终结果

| 检查 | 结果 |
| --- | --- |
| focused | 383 通过 |
| routine | 1805 通过 |
| examples-v2 / workflow-stress | 各 11 通过 |
| deterministic-acceptance / scientific-repro | 6 / 1 通过 |
| local-esmfold2-v2-contract / installed-package | 9 / 4 通过 |
| WebUI typecheck、真实旅程独立类型检查、lint、build | 全部通过 |
| 普通 WebUI E2E | 123 通过 |
| 科学基线对照 | 9 类值、28 个 Port、219 个科学 descriptor 一致 |
| 正式 Acceptance Campaign | 19/19 档通过，状态 passed |
| 真实 WebUI 旅程 | 6/6 通过，失败、错误、跳过均为 0 |
| FASTA 证据报告 | 退出码 0 |
| 安装 smoke | 3/3 通过，失败、错误、跳过均为 0 |

十三项非 Provider 检查全部通过后，才以同一快照新建 Campaign 并构建产物。真实 WebUI 使用该 Campaign 的 wheel 和同一快照的 WebUI dist。最终汇总 `summary.json` 为 `passed: true`。

构建产物 SHA-256：

- wheel `protein_workbench-0.1.0-py3-none-any.whl`：`c5e22028f1ef81c8c83c77962790dd8881fa319ba079eeaa61bdd0928cf535b4`。
- sdist `protein_workbench-0.1.0.tar.gz`：`b99b7b75b261886254467358d6fc72902f923bb6f00d80a0401c0ab7481bc1ca`。

非 Provider 逐项日志与退出码位于 `round-5/logs/`，汇总为 `round-5/summary-all.json`。正式记录包括 `campaign/campaign.json`、`campaign/results/`、`ui/ui-evidence/summary.json`、`real-junit.xml`、`smoke-junit.xml` 和浏览器 trace。精简结果已复制到本地忽略目录 `.local/verification-results/architecture-04-05-06-20260924/`，不纳入提交。

## 诊断轮次

1. 第一轮收齐协议测试样例、前端未使用变量及编辑保存相关失败后集中修复。
2. 第二轮仅余 Prompt 成功提示遗漏；修复后第三轮十三项全部通过。
3. 第三轮正式 Campaign 19/19 与安装 smoke 通过，但真实 WebUI 六条失败：五条暴露纯 Prompt 保存额外写布局，一条暴露 Run Commit 后编辑基线未同步。该轮不作为最终验收。
4. 第四轮集中修复上述生产问题及真实旅程中的额外 Commit，新增回归检查。行为测试通过，lint 报告 finally 中显式抛错；整理错误传播后冻结第五轮。
5. 第五轮全部非 Provider、正式 Campaign、真实 WebUI 与安装 smoke 通过，不拼接旧快照结果。

最终验收后仅维护验收记录和文档导航，未修改实现、测试或运行中的快照。未 commit 或 push。
