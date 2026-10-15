# ComfyUI：把可编辑图、执行请求和运行反馈分开研究

本文保存第三方固定源码中的技术事实与使用边界，不定义 Protein Workbench 的产品要求、接入协议或重构方案。本项目要求见[当前决策](../documentation-governance-decisions.md)，实现差异见[治理问题清单](../2026-10-15-documentation-governance-issues.md)。
[研究索引](README.md)。

| 源码 | 读取分支 | 固定 commit | commit 时间 | tag |
|---|---|---|---|---|
| [ComfyUI_frontend][F-root] | main | 2eeecc917a7e4ba2f38f93216b1f78f8bda8da43 | 2026-10-03 05:37:38 UTC | 未选发布 tag，使用分支 HEAD |
| [ComfyUI][B-root] | master | 3c169c2c7de85ccec4582af336a92c469f14df02 | 2026-10-03 03:24:15 UTC | 未选发布 tag，使用分支 HEAD |

这是两个独立仓库的开发分支快照，并非经该次核查运行确认兼容的发布组合。文中的链接全部固定到以上 SHA。

## 核心判断

最值得借鉴的不是节点皮肤，而是 **编辑表示 → 执行表示 → 运行投影** 的分工。
graphToPrompt 一次产出可恢复编辑的 workflow JSON，以及提交执行的 output；后者在 HTTP body 中叫 prompt。两个名字指向不同用途，不能混成一个“图”。[转换实现][F-compile]
这个转换并不纯粹：会调用虚拟节点 applyToGraph、widget.serializeValue；queuePrompt 还会在转换前后调用 widget 回调，seed 可在这些时刻改变。[转换前处理][F-compile] [排队回调][F-submit]
因此，“只有一个转换函数”不等于“只有一个小 Interface”；调用者仍需理解可变图、hook 时序、widget 序列化以及子图 ID 的规则。

另一个重要发现是版本漂移：本快照前端的 getQueue/getHistory 已通过统一 jobs fetcher 读取 /api/jobs，不能照旧教程描述成直接读取 /queue、/history；fetchApi 会为普通 route 加 /api 前缀。[URL 组装][F-api-route]
本地 server 仍提供旧端点，新 jobs 查询由当前队列和内存历史投影出来。[前端 jobs][F-jobs] [server jobs][B-jobs] [旧读取端点][B-history]
把新名称“jobs”误读成新建了持久化任务数据库，会得出错误的架构结论。

## 架构与对象所有权

~~~mermaid
flowchart TD
  N["Python Node classes / V3 schema"] --> O["GET object_info"]
  O --> D["NodeDef → LiteGraph node type"]
  W["Widget registry + extension hooks"] --> D
  D --> G["Live LGraph / subgraphs / widgets"]
  G --> S["graph.serialize: editor workflow"]
  G --> C["graphToPrompt + ExecutableNodeDTO"]
  C --> P["Executable prompt"]
  S --> U["UserData file + browser draft"]
  S --> X["extra_pnginfo.workflow"]
  P --> Q["POST prompt → validate_prompt → PromptQueue"]
  X --> Q
  Q --> E["PromptExecutor + ExecutionList + caches"]
  E --> H["UI outputs + status → queue history"]
  E --> WS["WebSocket execution events"]
  WS --> ES["executionStore / errorStore / graph overlays"]
  H --> J["GET api/jobs / job detail"]
  J --> QS["queueStore / history / workflow recovery"]
~~~

图中前端转换、server 验证与执行、jobs 投影分别有实际实现；不是建议中的未来架构。[转换][F-compile] [提交][B-prompt] [执行][B-execute] [jobs][B-jobs]

| 对象 | 实际 owner | 形状与含义 |
|---|---|---|
| Live LGraph | 浏览器 LiteGraph | 可变节点、连线、组、子图、widget；承担交互与编译输入。[序列化][F-serialize] |
| Workflow JSON | LGraph serializer／workflow management | 节点、links、groups、definitions、config、extra、extensions 等；用于恢复编辑。[序列化][F-serialize] |
| NodeDef | server Node classes → 前端 NodeDef implementation | 输入／输出、顺序、描述、类别、是否输出节点；前端再映射到控件。[object_info][B-def] |
| ExecutableNodeDTO | graphToPrompt 的内部转换 | 展开子图实例、解析跨层链接与提升的 widget；保留实例路径执行 ID。[DTO][F-dto] |
| API prompt | 前端生成；server 接纳／执行 | node ID → inputs、class_type、可选 _meta；不承载画布布局。[schema][F-prompt-schema] |
| Queue item | PromptQueue | 优先数、prompt_id、prompt、extra_data、输出目标等；heap queue 与 running map。[Queue][B-queue] |
| Execution cache | PromptExecutor／CacheSet | 计算 outputs、UI payload、节点对象；与历史列表不是同一个存储。[缓存][B-cache] |
| History／Job view | PromptQueue／server jobs projection | prompt、UI outputs、status；本地实现以进程内 history 字典为来源。[历史][B-queue] [投影][B-jobs] |
| 运行中的前端状态 | executionStore／queueStore | job→workflow 映射、节点进度、错误归属、列表与详情，不是执行调度者。[事件注册][F-events] [列表刷新][F-queue] |

## 调用链一：后端节点如何变成可编辑控件

1. 本地 Node loader 注册 Python class：旧式 NODE_CLASS_MAPPINGS，以及 V3 comfy_entrypoint 返回的 ComfyExtension／node list，都进入同一个映射。[Node loader][B-extensions]
2. GET /object_info 从映射取 class。旧式读取 INPUT_TYPES、RETURN_TYPES、RETURN_NAMES、OUTPUT_NODE、CATEGORY 等；V3 通过 GET_NODE_INFO_V1 投影。[定义出口][B-def]
3. 前端 api.getNodeDefs 以 no-store 取定义；app.registerNodesFromDefs 先调用 addCustomNodeDefs，再逐项 registerNodeDef。[取定义][F-api-def] [注册顺序][F-bootstrap]
4. litegraphService 生成继承 LGraphNode 的 ComfyNode；构造时 addInputs／addOutputs，设置 widget 序列化，并触发 nodeCreated。[构造][F-register]
5. 注册前先给类型设置 comfyClass，再 await beforeRegisterNodeDef(node constructor, V1 definition)；之后构建 ComfyNodeDefImpl 并注册到 LiteGraph。[hook 时序][F-register]
6. addInputs 按 input_order 创建 sockets 和 widgets；addInputWidget 从 widgetStore 按 type 找 constructor，forceInput 则跳过 widget。[输入与控件][F-widgets]
7. Widget constructor 收到 node、input name、输入定义及 app；其产物还可声明 advanced、hidden、socketless 和最小尺寸。[控件 Interface][F-widgets]

这是一条真实的 schema 驱动路径，但 schema 并没有消除专用编辑器。
通用字段靠类型 registry，扩展可贡献自己的 widget constructor；当前 registry 合并顺序让 core widget 在同名键上优先。[Widget registry][F-widget-registry]
定义可重载并刷新 combo，因而节点定义也可包含当前环境的可选资源；不能把 object_info 自然等同为不可变科学定义快照。[reloadNodeDefs][F-reload]


## 调用链二：从点击运行到查看历史

1. app.queuePrompt 针对每个 batch 调用 beforeQueued，并捕获当时的 workflow、view mode 和 error key，避免 HTTP 等待期间切页后把结果归给另一页。[提交入口][F-submit]
2. graphToPrompt 先让虚拟节点应用到图，再保存 workflow；使用 ExecutableNodeDTO 展开子图实例。[编译前半段][F-compile]
3. 可执行 output 排除 virtual、NEVER、BYPASS；widget.options.serialize=false 不入 prompt，widget.serialize 则另管 workflow 持久化。[双重序列化规则][F-compile]
4. 普通 widget 值与链接汇入 inputs。链接是 [origin_id, origin_slot]；数组值用 __value__ 包装，curve 另带 __type__ 标记。[值与链接编码][F-compile]
5. api.queuePrompt 把 output 放到 prompt，把 workflow 放入 extra_data.extra_pnginfo.workflow；client_id 关联实时事件，partial_execution_targets 选择执行目标。[请求构造][F-api-submit]
6. server 先触发 on_prompt handlers、应用 node replacements，再 validate_prompt；接纳后将输出目标连同 prompt 入队，返回 prompt_id、number 和 node_errors。[server 接纳][B-prompt]
7. worker 从 queue 取出 item，调用 PromptExecutor.execute；完成后 task_done 写入 history，并发 executing(node=null)。[worker][B-worker]
8. executor 发 execution_start／execution_cached，构造 ExecutionList，逐项执行；失败发 error/interrupted，成功发 execution_success。[executor][B-execute] [失败分支][B-errors]
9. WebSocket 消息进入 EventTarget，再由 executionStore 与 graph view 处理。事件可能早于 POST 的响应；store 专门缓冲尚未附着到 workflow 的状态／错误。[事件路由][F-ws-events] [早到事件][F-event-race]
10. queueStore 刷新列表；当前 queue/history 都经 jobs 读取。需要完整 workflow／outputs 时，GET /jobs/{id} 单独取 detail。[列表][F-queue] [按需详情][F-jobs]

执行 prompt 的最小示意如下；这里只演示上游 wire shape，不是 Protein Workbench 提案：

~~~json
{
  "10": {"class_type": "Loader", "inputs": {"name": "model.bin"}},
  "20": {"class_type": "Consumer", "inputs": {"model": ["10", 0]}}
}
~~~

这里的 0 是输出 slot 索引，不是名义科学 Port ID；数组 wrapper 是为避开同一 JSON 形状同时表示值和链接的歧义。[prompt schema][F-prompt-schema] [值包装][F-compile]
子图执行 ID 形如 1:2:3，编码“实例路径＋内部节点”，所以两个子图实例能共享定义而有不同运行定位。[实例身份][F-dto]

## Interface 的行为：不能只读方法签名

| Seam | 调用者必须知道的顺序／错误／取消语义 |
|---|---|
| graphToPrompt(graph) | 接受活图而非不可变快照；虚拟节点会修改图；widget.serializeValue 可异步；解析缺失链接或环可能抛错。[compiler][F-compile] [DTO resolveInput][F-resolve] |
| POST prompt | HTTP 200 表示接纳入队；不是完成，也不保证 node_errors 为空。400 可带 prompt-level error 与逐节点错误。[接纳][B-prompt] |
| validate_prompt | 从输出节点验证上游；只要存在 good_outputs 可接纳其子集；失败输出会被忽略并进入 node_errors。[验证收束][B-validation] |
| WebSocket | status、执行节点、执行结果、progress、二进制预览是不同事件；client_id 用于关联会话。[路由][F-ws-events] [握手][B-ws] |
| GET jobs / detail | 列表分页与完整输出分离；本地 jobs 是队列＋history 的投影；不是事件日志重放。[jobs][F-jobs] [server][B-jobs] |
| pending 的取消 | 旧 POST queue delete 从队列移除；不会像正在执行的节点一样触发计算中断。[旧取消][B-cancel-old] |
| running 的取消 | interrupt 是请求设置中断；executor 捕获 InterruptProcessingException 后产生 execution_interrupted。[中断][B-cancel-old] [结果事件][B-errors] |
| 新 cancelJob | server /api/jobs/{id}/cancel 对 running 原子检查后中断，对 pending dequeue，terminal/unknown 为 200 cancelled=false；前端暴露方法，但注释提醒调用者要确认 runtime 支持。[新取消][B-cancel] [前端声明][F-api-cancel] |

当前实际调用也分两条：job 菜单对 running／initialization／pending 调 cancelJob 后刷新队列；通用 Comfy.Interrupt 命令仍调 interrupt(activeJobId) 并显示 toast。[job 取消入口][F-cancel-call] [通用中断入口][F-interrupt-call]
因此应以 executor 的终态事件／后续快照确认取消结果，不能把“按钮返回并出现 interrupted 提示”等同于执行已经结束。

**重要取舍：** 上游允许“部分输出验证失败，但其他输出仍执行”。这适合交互式探索，但会改变用户对“一次运行成功”的理解。

## 断线恢复与错误反馈

WebSocket close 后，当前 socket owner 在 300ms 后重连；首次连接失败可启动队列 polling。替换过的 socket 不再拥有重连权。[socket 生命周期][F-ws-reconnect]
server 重用 clientId 时发送当前 status；若该客户端仍在执行，还发送 last_node_id。没有从 cursor 重放全部遗漏事件的这条逻辑。[server reconnect][B-ws]
前端收到 reconnected 后调用 queueStore.update，再清理已不在 active set 的 active job；queue 获取失败保留上次快照，避免误判为空队列。[reconcile][F-reconcile] [队列刷新][F-queue]
这是一种“事件推动即时反馈，HTTP 快照收敛状态”的方案；不是持久事件流方案。

提交阶段的 PromptExecutionError 分别进入逐节点错误和 prompt-level 错误；已有节点错误时不重复生成顶层错误，UI 可打开 error overlay。[错误归属][F-submit-errors]
运行阶段发送 node_id、class_type、exception_type、traceback 等；中断独立为 execution_interrupted。[运行错误][B-errors]
优点是错误能回到具体节点；代价是 Interface 需要区分编译失败、请求未接纳、运行失败、用户中断、断线和历史读取失败。

## 持久化与缓存：至少四种不同寿命

1. **服务器工作流文件：** workflowService 调用 changeTracker.prepareForSave，再经 workflow.save → api.storeUserData；保存成功才更新 originalContent。[工作流保存][F-save] [文件保存][F-user-file]
2. **浏览器恢复草稿：** rootGraph.serialize，经 512ms 防抖保存到 draft store；pagehide flush，失败可显示 toast；storageIO 使用 localStorage。[草稿入口][F-draft] [存储][F-storage]
3. **本地运行历史：** PromptQueue 的 queue、running、history 都是进程内容器；task_done 保存 prompt、status、UI outputs，并按最大历史规模清理。[内存历史][B-queue]
4. **计算缓存：** CacheSet 可选 classic、LRU、RAM pressure 或 none；output cache 与对象 cache 分开。[缓存策略][B-cache]

所以“刷新恢复编辑”“文件保存”“结果文件存在”“server 重启后仍有完整运行历史”不能互相替代。
本地 server 的 jobs 查询仍读取内存 history；该次核查没有证据可把它描述为可跨重启恢复的 Run ledger。[jobs owner][B-jobs]
history_result 主要由 ui_node_outputs 形成 outputs/meta；节点用于后续计算的全部 Python 对象并不直接成为历史详情。[历史输出构造][B-execute] [计算值与 UI 分离][B-return]

缓存 key 包括 class_type、IS_CHANGED／fingerprint_inputs、常量输入、上游签名；特定情形才纳入 node_id。[签名][B-cache-key] [变化检测][B-changed]
这一点带来增量执行的 Leverage：调整一个下游参数不必重跑未变化上游。
但它不是科学可复现身份的现成定义；class_type 不能单独证明模型版本、单位、残基映射和有效随机条件相同。

## 扩展与测试 seam

前端 extensionService 提供命令、菜单、设置、键位、底栏 tab、widgets 与生命周期 hooks；名字由 extensionStore 唯一注册。[扩展注册][F-ext] [名字约束][F-ext-store]
核心扩展先加载，外部 JS 再并行 import；异步 hook 用 Promise.all 并行调用，错误被捕获记录。[加载][F-ext] [hook dispatcher][F-ext-dispatch]
这让社区扩展十分灵活，但 beforeRegisterNodeDef 能改 constructor 与定义，且各异步 hook 共享可变对象：**推断**，扩展间的修改冲突和顺序假设会扩大 Interface。

server 的扩展 seam 同时包含 Node class、V3 schema、WEB_DIRECTORY，以及提交前 on_prompt handler；它们覆盖执行和编辑两个方向。[server loader][B-extensions] [提交 hook][B-prompt]
这是真实的双侧扩展机制，不是“后端多一个 Python 节点，前端天然无需任何工作”：通用字段可以自动生成，专用交互仍需前端 extension。

| 测试表面 | 上游实际示例 | 测试涉及的行为 |
|---|---|---|
| graph → wire payload | graphToPrompt stability tests 直接创建 LGraph，比较 JSON、重复转换稳定性。[编译测试][F-test-compile] | 把“哪些编辑会改变执行输入”变成小图契约测试。 |
| HTTP jobs adapter | fetchJobs 接受 fetchApi 参数，便于注入 transport；对应测试验证 list/detail 行为。[fetch seam][F-jobs] [测试][F-test-jobs] | 将 UI 状态与协议转换分开，不 mock 整个页面才能测请求。 |
| 运行归属与事件 | executionStore 对早于 HTTP 的事件有显式缓冲。[事件竞态][F-event-race] | 用状态转换场景测试切页、断线和晚到响应。 |
| 取消 | jobs_cancel_test 区分 running、pending、terminal，以及 pending→running 竞态。[取消测试][B-test-cancel] | 测“请求取消后最终发生什么”，而不只测按钮发出 POST。 |

graphToPrompt 的 Interface 看似小，却依赖真实图与 widget 行为；它不是完全脱离编辑器的纯 compiler。
fetchJobs 则通过注入 fetchApi 把传输 seam 收窄，Locality 更清晰；两者适合借鉴的程度不同。
该次核查只阅读这些测试，没有执行，因此不据此声称上游某能力无缺陷。

## 建议源码阅读路线

两个固定快照的仓库根许可证均为 GNU GPL v3：[前端 LICENSE](https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/LICENSE#L1-L8)、[server LICENSE](https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/LICENSE#L1-L8)。本报告提取设计机制；直接复用源码时需按具体代码的许可处理，不能由仓库许可证推定所有自定义节点、模型权重或服务的条件。

1. executionUtil.ts → ExecutableNodeDTO.ts：先看作者图如何成为执行输入。[入口][F-compile] [子图][F-dto]
2. server.py node_info → litegraphService.ts → widgetStore.ts：看 schema 到普通／专用控件的链。[后端][B-def] [前端][F-register]
3. app.ts queuePrompt → api.ts → server.py post_prompt：看快照、回调、接纳和错误。[前端][F-submit] [server][B-prompt]
4. main.py prompt_worker → PromptExecutor → PromptQueue.task_done：看真正的执行与历史 owner。[worker][B-worker] [queue][B-queue]
5. fetchJobs.ts → queueStore → reconnect helper：看事件丢失后如何收敛。[查询][F-jobs] [重连][F-reconcile]
6. workflow persistence 与 extensionService 最后看：理解恢复能力与扩展能力分别付出了什么复杂度。[草稿][F-draft] [扩展][F-ext]

[F-root]: https://github.com/Comfy-Org/ComfyUI_frontend/tree/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43
[B-root]: https://github.com/Comfy-Org/ComfyUI/tree/3c169c2c7de85ccec4582af336a92c469f14df02
[F-compile]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/utils/executionUtil.ts#L59-L206
[F-serialize]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/lib/litegraph/src/LGraph.ts#L2943-L2994
[F-dto]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/lib/litegraph/src/subgraph/ExecutableNodeDTO.ts#L46-L136
[F-resolve]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/lib/litegraph/src/subgraph/ExecutableNodeDTO.ts#L139-L245
[F-prompt-schema]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/platform/workflow/validation/schemas/workflowSchema.ts#L718-L740
[F-api-def]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/scripts/api.ts#L1283-L1285
[F-api-route]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/scripts/api.ts#L535-L545
[F-bootstrap]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/scripts/app.ts#L1165-L1228
[F-register]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/services/litegraphService.ts#L532-L644
[F-widgets]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/services/litegraphService.ts#L284-L363
[F-widget-registry]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/stores/widgetStore.ts#L15-L47
[F-reload]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/scripts/app.ts#L2699-L2720
[F-submit]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/scripts/app.ts#L1911-L2133
[F-submit-errors]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/scripts/app.ts#L2080-L2117
[F-api-submit]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/scripts/api.ts#L1295-L1351
[F-api-cancel]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/scripts/api.ts#L1548-L1591
[F-cancel-call]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/composables/queue/useJobMenu.ts#L83-L96
[F-interrupt-call]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/composables/useCoreCommands.ts#L345-L356
[F-jobs]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/platform/remote/comfyui/jobs/fetchJobs.ts#L50-L187
[F-events]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/stores/executionStore.ts#L445-L456
[F-event-race]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/stores/executionStore.ts#L169-L210
[F-queue]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/stores/queueStore.ts#L318-L404
[F-ws-events]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/scripts/api.ts#L1015-L1138
[F-ws-reconnect]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/scripts/api.ts#L971-L1012
[F-reconcile]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/composables/useReconnectQueueRefresh.ts#L1-L24
[F-save]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/platform/workflow/core/services/workflowService.ts#L322-L354
[F-user-file]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/stores/userFileStore.ts#L138-L159
[F-draft]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/platform/workflow/persistence/composables/useWorkflowPersistenceV2.ts#L95-L143
[F-storage]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/platform/workflow/persistence/base/storageIO.ts#L100-L133
[F-ext]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/services/extensionService.ts#L41-L98
[F-ext-store]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/stores/extensionStore.ts#L58-L72
[F-ext-dispatch]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/services/extensionService.ts#L170-L245
[F-test-compile]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/utils/executionUtil.stability.test.ts#L21-L105
[F-test-jobs]: https://github.com/Comfy-Org/ComfyUI_frontend/blob/2eeecc917a7e4ba2f38f93216b1f78f8bda8da43/src/platform/remote/comfyui/jobs/fetchJobs.test.ts#L290-L329
[B-def]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/server.py#L759-L827
[B-prompt]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/server.py#L1080-L1152
[B-validation]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/execution.py#L1224-L1292
[B-worker]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/main.py#L348-L380
[B-execute]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/execution.py#L730-L835
[B-errors]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/execution.py#L686-L712
[B-return]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/execution.py#L359-L422
[B-queue]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/execution.py#L1294-L1351
[B-jobs]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/server.py#L899-L950
[B-history]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/server.py#L1053-L1078
[B-ws]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/server.py#L272-L315
[B-cancel-old]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/server.py#L1154-L1198
[B-cancel]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/server.py#L952-L995
[B-cache]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/execution.py#L108-L153
[B-cache-key]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/comfy_execution/caching.py#L83-L128
[B-changed]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/execution.py#L71-L105
[B-extensions]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/nodes.py#L2297-L2340
[B-test-cancel]: https://github.com/Comfy-Org/ComfyUI/blob/3c169c2c7de85ccec4582af336a92c469f14df02/tests-unit/jobs_cancel_test/jobs_cancel_test.py#L180-L258
