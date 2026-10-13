# 四项架构修改完整远端验收

最后更新：2026-09-21。结论：完整通过。

本次覆盖项目 trash／永久删除协调、统一结果读取状态、集中 workspace 发布、局部解码归属 codec 四项修改。全部最终结果来自同一固定快照 `four-changes-acceptance-20260921-02`，没有拼接发现阶段快照的结果。

测试、构建、typecheck 和 lint 均在远端执行，复用已有 Python 3.12 虚拟环境；本地只编辑、审查和核对文件哈希。正式 campaign 完成于 `2026-09-20T21:25:45.940392+00:00`（UTC）。本记录描述该快照的验收结果，后续文档更新不改写其源码清单。

## 完整结果

| 验收组 | 通过数量 |
|---|---:|
| routine | 1713 |
| examples-v2 | 11 |
| workflow-stress | 11 |
| deterministic-acceptance | 6 |
| scientific-repro | 1 |
| local-esmfold2-v2-contract | 9 |
| installed-package | 4 |
| 普通 Playwright | 81 |
| 真实浏览器旅程 | 6 |
| 安装 smoke | 3 |
| 正式 Provider campaign | 19/19 tiers |

后端七组共 1755 项通过。所有测试零失败、零错误、零跳过；前端 typecheck、真实旅程独立 typecheck、lint、build 均退出 0。正式 `acceptance_cli prepare/run` campaign 状态为 `passed`。

六条真实浏览器旅程覆盖 FASTA、Prompt→ESM3→重折叠比较、ProteinMPNN 谱系，以及取消、取消后删除、等待完成后删除。已查看真实旅程 trace 中的 Prompt、ESM3 比较、MPNN 已发布对齐和 FASTA 截图。

## 发现与批量修复

发现阶段汇总完整矩阵的问题后，集中完成三项修复，再以新固定快照重跑整个矩阵：

- README 的四个仓库文档链接改为绝对地址，满足源码包文档合同。
- 保存 Workflow 时保留已有 ReactFlow 节点的 `measured`，修复连续保存后画布节点不可见。
- 真实旅程通过 `PublishedResults` 读取完整结果，移除已删除的接口引用和额外 Run 读取。

产品与测试修改通过代码和 TypeScript 静态审查；临时验收脚本通过代码和 Python 审查。

## 固定快照与证据

远端服务器：`ssh -p 19081 root@connect.westc.seetacloud.com`。

证据根目录：`/root/work/webui-integration-20260917/four-changes-acceptance-20260921-02`。

验收时，785 个源码文件哈希与本地文件一致；复用的 `repositories/` Provider 源目录不在该清单内。wheel、sdist 与前端 dist 共 9 个产物哈希未变化。

以下路径相对证据根目录：

| 路径 | 内容 |
|---|---|
| `candidate/campaign.json` | 正式 campaign、各 tier 状态与证据索引 |
| `source-manifest.json`、`artifact-manifest.json` | 源码与产物 SHA-256 |
| `offline-status.jsonl`、`ui-evidence/commands.jsonl`、`formal-status.jsonl` | 执行命令、时间与退出码 |
| `results/`、`candidate/results/` | 后端 JUnit、日志、各 Provider 的 Run labels、IDs 与 projections |
| `ordinary-playwright.xml`、`ui-evidence/real-junit.xml`、`ui-evidence/smoke-junit.xml` | 浏览器测试计数 |
| `ui-evidence/real-results/` | 真实旅程 trace 与附件 |
| `ui-evidence/fasta/` | 原始完整 Run 报告、projection、阶段结果及 Commit |

FASTA 报告固定使用原始完整 Run receipt，而非后续局部 Run 或 `latestRun`：

- Project：`53c1a240-61fa-401b-ac53-228209272376`。
- 完整 Run：`run-63e6d6d203d54445a9847506083d6576`，状态 `succeeded`。
- Commit：`workflow-commit-25e2a2d9bf54460fbde0abf19102bec3`。
- 阶段计数：导入 2；溶解性预筛选、折叠、置信度排序、后筛选和最终交集各 1。

验证入口见 [WebUI README](../webui/README.md)。[09-19 集成验收记录](2026-09-19-webui-integration-progress.md)保留此前快照的证据；其计数不代表本次结果。
