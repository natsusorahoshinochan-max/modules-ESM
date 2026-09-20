# Run 范围与保留结果复用合同

本规格落实 WebUI 集成计划 P0/P2 的 D01–D03、D12。Run 始终绑定已经 admission 的确定 Workflow Commit；前端不删除图节点来模拟范围。

## 范围

`full` 执行完整 Execution Plan，保留现行缓存政策。`to_node` 执行选择的 Nodes 和所有祖先。`from_node` 执行选择的 Nodes 和所有后代，全部强制执行，即使存在缓存也不重放；effective randomness 保持当前 Commit/输入确定的值，不隐式换 seed。

继续使用一个明确的 terminal source Run 和一个明确的当前 Commit。范围外但被执行区域依赖的全部祖先只从该 source Run 已原子发布的成果复用，包含连接的 optional Ports，绝不执行 Provider、补跑上游或读取其他 Run 的缓存来补缺。其余 Nodes 完全不进入本次 Run。预览返回执行、强制重算、复用和范围外 Node IDs，并指出缺少 publication 的上游。预览不准备执行输入、不恢复结果、不计算 Result Identity；依赖实际值的可复用性在启动时判定。

## 复用

按当前 Plan 拓扑顺序，使用正常 Node Attempt owner 的输入组合、Project Input 内容身份、effective randomness 和 Result Identity 计算。每个复用 Node 必须有 source Run 的成功 publication，且当前 Result Identity 与 publication 的精确身份相同。通过 ResultStore 从该 publication 的 immutable manifest 恢复值；缺失、身份不符或持久值不可读都会拒绝整个继续请求，在 Run admission 前返回 blocker。选择范围内发生失败时保留真实失败，不回退缓存。

显式复用是用户选定旧结果作为继续的输入，允许复用非 cacheable 的已发布结果；这不放宽自动 cache replay 条件。重新运行时仍执行正常 effective randomness resolver。需要上游实际值才能求得的预览随机性标记为待输入，不猜测。

后端重启时从持久 Ledger 读取 publication，按正常 authoring owner 重新 admission 当前 Commit。旧 Run 的 interrupted 结论保持不变；继续产生新的 Run identity。source Run 的保留 in-memory Plan 不是必要条件。

## Evidence 与 closure

Run scope 记录 mode、selected/execution/reuse/out-of-scope IDs、范围外 Selection IDs 与 source Run。Ledger 的 Plan 只包含执行 Nodes 和复用祖先，保持依赖闭合。复用通过正常 Node Attempt publication 留下 `cache_replayed` resolution 和原 producer Run，绝不产生 Operation/Engine Invocation。范围外 Nodes 没有 Node Disposition，也不占本次 Selection terminal keys；界面按 scope 标为范围外，不能当作 failed/blocked/cancelled。

Selection terminal keys 只包含执行区域内的 Selection consumers。复用区域中的 Selection 输出可作为输入，但不冒充本次重新执行的筛选结论。其余 lifecycle、取消、部分 publication 可见性与 closure 沿用现行 Ledger 合同。

预览和启动共享范围计算；仅启动执行一次输入准备、科学身份匹配与结果恢复。已恢复节点沿用正常 Attempt 生命周期，直接发布复用记录，不再次准备输入。Availability 只是目录诊断，预览不触发 Readiness 或 Provider，不保证未来执行一定成功。
