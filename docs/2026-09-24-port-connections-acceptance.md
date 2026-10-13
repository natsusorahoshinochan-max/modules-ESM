# 节点端口与连线编辑验收记录

状态：修复、交叉代码审查及最终固定快照的完整远端验收完成。

## 最终行为

- 连接点由端口行布局定位。角色、简短类型、必选性与数量常驻，键盘可展开完整类型、说明、有序来源、完整节点标题及稳定 node_id。
- 新建、重连、删除通过同一 authoring 入口，边使用端点四元组身份。单值输入一致替换，多值输入同目标替换保留槽位，跨目标追加；重复及原地重连不保存、不增加撤销记录。
- 无效目标和空白落点取消重连并保留原边。折叠节点保留独立锚点，展开后才能编辑。先选中边再重连；选中边置顶，避免共享端口处的其他路径或透明热区截获操作。
- raw 参数与待保存队列先检查；接纳前拒绝保持原图，接纳后写入失败保留 WorkspaceEditor 待保存内容，使用现有明确重试与撤销。边数标题明确表示草稿连接数。
- 保留且具有 source_merges 的 Prompt，已有 merge_sources 必须保持为完整前缀。阻止替换、删除、移出和重排，允许追加；同时删除 Prompt 本身不阻止该组删除，其他保留 Prompt 仍检查。批量删除整体接纳或整体保留，并保留 Selection 引用清理。
- 保护提示提供 Studio 入口。清除合并意图、Preview、应用并保存后可修改来源，其他轨道编辑保留。保护错误不误报为可重试的保存失败，保存后清除旧提示。

当前合同见 [Workspace 编辑规格](2026-09-17-project-workspace-spec.md#canvas-connection-editing) 与 [Prompt 编辑规格](2026-09-17-prompt-editing-spec.md#画布修改合并来源)。科学类型、canonical 编码、source_index 合同及后端科学校验未变；未新增 API、兼容层或保存机制。

## 固定快照与结果

全部自动测试、类型检查、构建、浏览器与 Provider 执行均在远端 `connect.westb.seetacloud.com:12933`。本地仅编辑、静态检查、读取日志及截图。按用户指令不采用静默等待约定。

最终源码：`/root/work/port-edit-20260924/round-5/source`，849 个文件。

SHA-256：`eaafaf815c838f4dbb179d42f75e393eaf9bc6d9638ba23e1ccdf3678f0e94c7`。

正式验收：`/root/autodl-tmp/port-edit-20260924/final-round-5`，2026-09-24 09:05:49–09:33:32 UTC。十三项检查全通过后才启动正式 Campaign；真实 WebUI 使用同一快照的 dist 与该 Campaign 的 wheel。最终 `passed: true`，验收前后 `source_changes=[]`。收尾文档更新前，本地 849 个文件逐一匹配该快照。

| 检查 | 结果 |
| --- | --- |
| focused | 383 通过 |
| routine | 1805 通过 |
| examples-v2 / workflow-stress | 各 11 通过 |
| deterministic-acceptance / scientific-repro | 6 / 1 通过 |
| local-esmfold2-v2-contract / installed-package | 9 / 4 通过 |
| WebUI typecheck、真实旅程独立类型检查、lint、build | 全部通过 |
| 普通 WebUI E2E | 147 通过 |
| 科学基线对照 | 9 类值、28 个 Port、219 个科学 descriptor 一致 |
| 正式 Acceptance Campaign | 19/19 档通过 |
| 真实 WebUI 旅程 | 6/6 通过，失败、错误、跳过均为 0 |
| FASTA 证据报告 | 退出码 0 |
| 安装 smoke | 3/3 通过，失败、错误、跳过均为 0 |

端口浏览器回归覆盖实际中心坐标（偏差小于 2 屏幕像素）、缩放、折叠重展、键盘详情、来源顺序、空白/不兼容重连、单值替换、多值保序与撤销、raw 输入拒绝、保护提示、Studio 解锁、批量删除和写入失败后明确重试。具有相同残基布局但不同序列值的来源用于核对既有 source_index 意图。最终截图另存于验收证据目录。

构建产物 SHA-256：wheel `c5e22028f1ef81c8c83c77962790dd8881fa319ba079eeaa61bdd0928cf535b4`；sdist `b99b7b75b261886254467358d6fc72902f923bb6f00d80a0401c0ab7481bc1ca`。这些后端产物与前次架构验收相同，本轮前端与测试改动仍经过新的完整 Campaign。

## 诊断与剩余边界

远端 red 首先复现几何偏差及重复多值连接意外改变顺序。诊断轮次还发现并修正装饰提示层挡住节点按钮、保护提示重复与未清除，以及共享端口上的重连热区冲突。独立远端 probe 确认 ReactFlow 默认未提升选中边，显式启用后实际层级从 0 变为 1000，命中正确端点。旧测试随文案和真实键盘选择入口同步迁移。每轮整批收齐后集中修复；只有 round-5 全部结果构成最终验收，不拼接历史通过项。

不新增手动来源排序，不自动重映射 source_index，不跟踪所有上游内容变化；完整 Workflow 科学校验继续由后端 owner 负责。保留用户已存布局，不自动挪动手动放置的节点。既有本地手动测试数据保留，未 commit 或 push。

远端逐项记录在 `round-5/logs/`、`summary-all.json`，正式记录在 `campaign/campaign.json`、`ui/ui-evidence/`。精简结果及截图复制至本地忽略目录 `.local/verification-results/port-edit-20260924/`。最终验收后仅更新本记录与文档导航，未修改实现或测试。
