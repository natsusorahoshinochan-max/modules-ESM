# WebUI 集成交付与验收记录

[集成交付范围](2026-09-17-webui-full-integration-plan.md)的 P0–P7 已完成验收。
本文记录 2026-09-19 冻结快照的结果；本次文档整理未重新执行测试。

## 当前实现边界

- Run preview 展示范围与已发布状态；启动时恢复上游并准备执行一次。
- 已发布 Input、Object 和候选引用由读取方信任；结果按页解码、按需加载。
- Selection 直接使用原始评分，后端提供观察选项；按完整 Candidate Data Reference 匹配。
- Prompt 保存已确认的 normalized preview；持久化 owner 保留一次 Draft revision 冲突判断。
- 预置结果直接安装可信包内原始记录，最后原子发布 Run。

## 尚未完成的减法事项

Selector/Objective 的 `candidate_input`、`score_collection_input` 仍与连线并存。
一个 scores 端口可连多个集合，精确来源承担每项 preference 选择哪个集合的语义。
进一步简化需要保留这一选择语义；该项不计为完成，也不属于此次验收通过的范围。

## 验收环境

- 主机：`root@connect.westc.seetacloud.com:19081`。
- 源码目录：`/root/work/webui-integration-20260917/source`。
- Python 3.12、Node.js 22；全部测试、构建、lint 和类型检查在远端执行。

## 最终验收快照 03

远端根目录：`/root/work/webui-integration-20260917/full-acceptance-03/`。普通浏览器 71/71、真实旅程 6/6、安装后冒烟 3/3 已通过，均无 skip/retry。typecheck、lint、build、真实测试独立类型检查通过。后端七组均通过，其中 routine 1673 passed、deterministic-acceptance 6 passed。正式 campaign 19/19 通过，`candidate/campaign.json` 最终状态 `passed`。本计划完整验收已完成。所有执行均在远端，本机只编辑和查看报告/截图。

### 需求与证据

| 需求 | 最终快照的验收行为 | 证据边界 |
|---|---|---|
| G01–G03 | 参数与 Binding 恢复、Palette/右键搜索、复制粘贴及撤销、真实 Port 替换连线 | 普通浏览器套件；不是仅类型检查 |
| G04–G05 | 非法 FASTA 整批阻止、重复记录保留、1000 条真实导入与分页、FASTA→筛选→折叠→排序 | 普通浏览器 + 真实 FASTA 旅程 |
| G06、G13 | AND/OR 分组合同、Utility 编辑、结果保存 filter/Top-N/manual，并实际局部执行核对输出候选 | 真实三条旅程 + Selection 后端合同；Selector/Objective 来源字段减法仍另列未完成 |
| G07–G09 | 局部强制运行、范围外分支、缺上游拒绝、事件断连恢复、不重复启动、错误节点定位、取消并读取部分结果 | 普通浏览器 + 真实取消；服务重启后复用由 run-scope/restart 后端合同覆盖，不冒充浏览器进程重启测试 |
| G10–G14 | 中间阶段、分数与科学定义、完整父谱系、已发布 alignment 叠加、结构/序列混合导出 | 真实 FASTA/Prompt/MPNN，保存实际 ZIP 与截图/trace；容量另由1000条测试覆盖 |
| G15 | 修改科学内容提示过期，改回解除；布局折叠/重载不使结果过期 | 普通浏览器新增回归 |
| G16–G21 | 多轨预览/撤销、随机已实现选择、Mask/手动对应合并、Function 身份、连续刚体变换与原子几何中心、合并后布局、Draft 冲突；编辑 Prompt 后真实 ESM3/refold | Prompt 浏览器 + 后端科学合同 + 真实 Prompt 旅程；未引入自动残基对应 |
| G22–G23 | 版本先查看/首次修改/返回、复制改名回收恢复、来源取消不改图；运行中不自动取消，分别等待删除与取消后删除，恢复同身份与原 Run 证据 | 普通浏览器 + 两条真实删除旅程；每条独立浏览器上下文，无共享浏览器状态 |
| G24 | 新 wheel 在源码目录外安装，五个科学包来自安装环境；预置结果无 Provider 首开、第一次编辑和版本/项目管理 | installed-smoke 三项 + installed-package；WebUI 使用同一源码快照的生产 dist，由临时服务挂载，不能声称 wheel 内含 WebUI |
| G25 | 已接线入口、过时断言与 README 校正，真实结构/分数/来源展示 | 全部普通浏览器与真实旅程；已查看真实 Prompt、阶段比较和 alignment 截图 |

### 真实 Run 标识

- FASTA：Project `5556ba79-3d1b-44ae-b9f7-daf1322d2c27`，Run `run-0e51be1036074dd886fb8c05f393c52e`。
- Prompt：Project `154fcee1-cd06-4c0d-9351-9bd381e1f971`，Run `run-15c081cd99ce4f9795525bf143426ed9`。
- MPNN：Project `ebe18dbf-470f-43b3-a0d2-0833ac43ef8a`，Run `run-b79688115f7745aab13b35167de57b52`。
- Selection 后续 Run、取消/删除 Run 与保留 projection 均在 `real-report/` 和 `real-results/` 的附件/trace 中。最终报告 `real.xml` 明确为 6 tests、0 failures、0 skipped、0 errors。

本次只修复验收实际暴露的产品接口/默认参数与测试；未新增哈希、重复准入、响应修补、兼容路径、重试或独立测试框架。现有 Provider campaign 定义与 fail-fast 行为保持不变。

### 最终结论

- `frontend-status.tsv`：typecheck、lint、build、real-typecheck、playwright 全部退出 0；普通浏览器 **71 passed**。
- `ui-status.tsv`：真实旅程 **6 passed**、安装后冒烟 **3 passed**；无失败、跳过或重试。
- `repository-status.tsv`：routine、examples-v2、workflow-stress、deterministic-acceptance、scientific-repro、local-esmfold2-v2-contract、installed-package 全部退出 0；routine **1673 passed**，deterministic **6 passed**。
- `candidate/campaign.json`：正式 canonical campaign **19/19 passed**，整体 `state: passed`；`formal-campaign.log` 对应命令正常结束。此结论来自最终快照正式执行，不是第一轮单项发现结果的拼接。
- 生产构建仍有既有 3Dmol eval / 大 bundle 提示，不影响本次构建通过。未进行提交或推送；临时验收 UI 服务已停止，所有报告与原始证据保留在上述远端目录。

已修复的产品问题共两类：未完成 Selection 配置阻止观察选项查询；结果保存筛选/Top-N 时错误拒绝范围外评分。其余修复是过时断言、定位器/删除完成条件、类型声明与容量测试等待预算。没有增加产品校验、哈希、防御性层或重复实现。此前明确排除的 Selector/Objective 来源字段减法仍未完成，不因本次验收通过而重标。
