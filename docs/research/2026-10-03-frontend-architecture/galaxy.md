# Galaxy：把流程编辑、运行请求与执行结果分开

[返回总览](README.md)。查阅日期：2026-10-03。

源码快照：[`galaxyproject/galaxy`，`dev@11e413dc58be6f8ddc26fdd7a997c44a184c3ec8`](https://github.com/galaxyproject/galaxy/tree/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8)。这是开发分支快照，不代表某个稳定发行版。下文代码链接固定到该提交；没有安装或执行 Galaxy。

本篇将我们现有实现作为比较背景，不要求保留现有科学契约、ADR、API 或产品范围。“借鉴建议”是可供后续选择的设计，不是已决定的架构。

## 先读结论

Galaxy 最值得学的是：**用户保存的 Workflow、一次调用的参数与数据、调度过程、具体 Job、输出数据，是不同对象。** 前端因此可以分别编辑、提交、查询和解释它们，不需要从画布动画猜测运行发生了什么。

它也展示了大型系统的成本：状态分布在编辑 store、请求缓存、页面轮询、服务、数据库模型和 runner 中；一些历史 API 与新客户端并存。借鉴时应选择确实解决我们问题的 seam，不按其目录数量照搬架构。

优先阅读四个机制：

1. Workflow 版本如何成为持久的 `WorkflowInvocation`。
2. “已经调度”与“所有 Job 已终止”如何分别表达。
3. 编辑命令与 undo/redo 如何跨多个 store 协调。
4. 工具格式与执行环境如何分别通过两处真实 seam 扩展。

## 对象与状态归属

| 对象 | 主要负责什么 | 不应误认为 |
|---|---|---|
| 编辑器 scoped stores | 当前 steps、connections、comments、选中、镜头、撤销历史 | 一份已经提交的执行请求 |
| Stored Workflow / 内部 Workflow 版本 | 可选择并执行的流程定义版本 | 正在运行的实例 |
| `WorkflowRunConfig` | 输入绑定、参数、目标 history、缓存和资源选项等准备结果 | 全部节点已经开始运行 |
| `WorkflowInvocation` / Invocation Step | 某次调用及其步骤的持久调度事实 | 单个 Job，或单一“完成”布尔值 |
| Job / implicit collection jobs | 实际工具执行，可能由一个步骤产生多个 Job | 与画布节点一一对应的固定数量 |
| History 数据条目与 Invocation 输出 | 数据组织、结果访问与来源关联 | 编辑器暂存对象 |
| `useInvocationStore` | 已查询的详情、摘要、metrics、错误和加载状态 | 数据库事实的替代品 |

服务选择 Workflow 版本、建立运行配置、创建调用并提交数据库事务的代码集中在 [`invoke_workflow`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/webapps/galaxy/services/workflows.py#L265)。编辑会话归属见 [`provideScopedWorkflowStores`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/composables/workflowStores.ts#L21)，运行阅读归属见 [`useInvocationStore`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/stores/invocationStore.ts#L19)。

```mermaid
flowchart LR
  E[Workflow 编辑器] --> S[Scoped stores 与撤销命令]
  S --> W[保存 Workflow 版本]
  W --> F[运行表单与输入绑定]
  F --> H[HTTP invoke 请求]
  H --> C[WorkflowRunConfig]
  C --> I[持久 WorkflowInvocation]
  I --> Q[Workflow 调度]
  Q --> J[工具 Job]
  J --> R[本地或 Pulsar runner]
  R --> D[结果数据与 Job 状态]
  I --> V[查询与摘要 API]
  D --> V
  V --> K[Invocation store]
  K --> U[运行视图与结果入口]
```

图省略了 History、权限及存储的内部细节；箭头表达本次核查的职责路径，不声称每条箭头都是直接函数调用。

## 调用链一：用户点击运行之后

### 1. 运行表单组装调用输入

[`WorkflowRunForm.onExecute`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/components/Workflow/Run/WorkflowRunForm.vue#L269) 先检查步骤表单错误，再从每步参数中排除已连线的输入。它提交 `inputs`、`parameters`、`version`、目标 history、`use_cached_job`、资源参数等。

这个路径明确设置 `batch: true`，因此前端希望得到 Invocation 列表；设置 `parameters_normalized: true`，表明工具表单提交的是已展平的参数。该表单还设置 `require_exact_tool_versions: false`。这些是此调用方的真实选择，不是所有 Galaxy 客户端的必然语义。

设计启发：**用户已确认的执行选项应出现在请求或准备结果中。** 不要靠浏览器某个隐藏全局变量决定输入匹配或版本策略。

### 2. HTTP 层把请求交给执行用例

[`invokeWorkflow`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/components/Workflow/Run/services.js#L135) 使用 Axios 调用 `POST /api/workflows/{workflow_id}/invocations`；后端 [`FastAPIWorkflows.invoke`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/webapps/galaxy/api/workflows.py#L1172) 接受类型化 payload，委托 `WorkflowsService.invoke_workflow`。

后者确定内部版本、调用 `build_workflow_run_configs`，检查 batch 与配置数量、检查所需工具，再为每份配置调用 `queue_invoke`。最后统一 `commit()` 并返回一个或多个 Invocation，而不是等待所有计算结束。

### 3. 运行配置不是未经解释的表单 JSON

[`build_workflow_run_configs`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/workflow/run_request.py#L308) 检查空流程和环，规范化参数、输入绑定，展开批量输入，并选择目标 history。这里存在多种历史输入表示和兼容逻辑，是 Galaxy 长期演化的现实，不是新项目必须引入的模式。

[`workflow_run_config_to_request`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/workflow/run_request.py#L534) 把运行配置转为 `WorkflowInvocation` 及其关联参数、输入记录；[`queue_invoke`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/workflow/run.py#L132) 填充模块状态并交给 scheduling manager。

[`WorkflowSchedulingManager.queue`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/workflow/scheduling_manager.py#L192) 保存初始状态、指定 scheduler 和 handler。它的主调度依据是持久 Invocation；源码还明确说明 Workflow scheduler 没有对应的内存队列，因此不要把方法名 `queue` 理解为“所有事实只在内存 Queue 中”。

### 4. Invocation 步骤逐步产生 Job

[`WorkflowInvoker.invoke`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/workflow/run.py#L206) 遍历剩余步骤，建立 Invocation Step，执行可推进的部分；输入或调度条件不足会保留延迟状态。批量集合使一个步骤可以有多个 Job，所以“画布节点数”不能代替实际工作量。

**Interface 的完成含义：** HTTP 成功表示此次请求产生了已提交的 Invocation；其后仍有调度、Job 执行和结果读取。任何用一个 `await run()` 表达全部过程的包装，都必须另外说明它究竟等待哪一个完成点。

## 调用链二：界面怎样知道运行状态

Galaxy 将运行阅读拆成详情、整体 Job 摘要、逐步骤 Job 摘要和 metrics。`useInvocationStore` 按 Invocation ID 分别读取：

| 读取入口 | 使用目的 |
|---|---|
| `GET /api/invocations/{id}` | steps、输入输出、消息及 Invocation 状态 |
| `GET /api/invocations/{id}/jobs_summary` | 此次调用的 Job 聚合状态 |
| `GET /api/invocations/{id}/step_jobs_summary` | 每一步或集合 Job 的状态 |
| `GET /api/invocations/{id}/metrics` | 已有 Job 的运行指标 |
| `GET /api/invocations/{id}/request` | 重建用于再次调用的请求视图 |

端点与读取实现见 [`invocationStore.ts`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/stores/invocationStore.ts#L22)。`request` 的文档明确说它是重建且可能更具体的请求，不等于逐字保存的原始 HTTP body，见[端点说明](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/webapps/galaxy/api/workflows.py#L1572)。

### 调度终态和 Job 终态分别计算

[`WorkflowInvocationState.vue`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/components/WorkflowInvocationState/WorkflowInvocationState.vue#L120) 分别计算 `invocationSchedulingTerminal` 与 `jobStatesTerminal`。`scheduled` 可以表示步骤已安排，但不能单独证明 Job 全部结束；缺少 Job summary 时也不会当作零个 Job 已完成。

页面分别轮询 Invocation 与 Job summary，当前间隔为三秒，并在卸载时清理计时器，见[轮询实现](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/components/WorkflowInvocationState/WorkflowInvocationState.vue#L274)。这是这条页面路径的机制，不能概括成 Galaxy 所有实时功能都只使用轮询。

### 缓存同时表达“已加载到哪一层”

[`useKeyedCache`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/composables/keyedCache.ts#L41) 持有数据、错误和进行中的 Promise；同一个 ID 的并发读取共享 Promise。调用者还可传 `shouldFetchHandler`，决定当前缓存是否足够。

Invocation 列表只提供 summary，详情才有 steps/inputs/outputs。store 的[详情判定](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/stores/invocationStore.ts#L132) 会升级 summary，而不是把“已有同 ID”视为完整加载。Metrics 则根据每步终止 Job 数增长重新获取，避免每个消费者维护一套失效逻辑。

这是一处很实用的 seam：**组件提出阅读意图，缓存模块拥有请求合并、错误和完整程度。** 但目前轮询时机仍留在页面，并非所有运行阅读生命周期都已被封装在一个模块内。

## 取消、错误与恢复的实际含义

| 行为 | 源码实际语义 | 借鉴时要明确什么 |
|---|---|---|
| 提交失败 | 表单读取后端 `err_data`，尝试定位步骤；其他错误沿用请求错误路径 | 错误应能关联具体参数/步骤，而不只是字符串 |
| 请求取消 | DELETE Invocation → manager 调用 `cancel()` → 保存 `CANCELLING` | 返回不代表计算进程已经停止 |
| 调度处理取消 | 非终态 Jobs 标记 `DELETING`，传播子 Workflow 取消，再标记 Invocation `CANCELLED` | 调度确认、Job 状态和外部进程停止是不同观察点 |
| 查询失败 | `useKeyedCache` 记录错误并可能返回 `undefined`；部分可重试错误由读取触发有限重试 | `await` 正常返回并不能独自证明读取成功 |
| 本地 Job 重启恢复 | `LocalJobRunner.recover` 明确将其标记 error | 持久 Invocation 不保证所有 runner 都能继续执行 |

取消链见 [manager](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/managers/workflows.py#L599)、[模型状态变化](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/model/__init__.py#L10132)和[调度处理](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/workflow/scheduling_manager.py#L559)。错误存储见 [`fetchItemById`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/composables/keyedCache.ts#L88)，本地恢复见 [`recover`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/jobs/runners/local.py#L207)。

## 编辑器 seam：命令、状态和文档

`provideScopedWorkflowStores(workflowId)` 同时提供 steps、connections、comments、工具栏、搜索和 undo/redo stores，并负责作用域结束后的释放；子组件 `useWorkflowStores` 取得同一作用域。store 按 `workflowId` 取得，因此不同 Workflow 可以隔离编辑状态与撤销栈，不能推定同一 ID 的两个组件实例自动隔离。代价是拿到 stores 的调用者拥有很宽的修改能力，scoped store 并不自动等于深模块。

[`LazyMutateStepAction`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/components/Workflow/Editor/Actions/stepActions.ts#L15) 保存起值、终值和步骤身份；等待合并期间更新当前值，undo/redo 再通过 step store 重放。`LazySetLabelAction` 还更新 report 中的标签引用，说明“改名”不是只改一个 DOM 字段。

官方[撤销模块说明](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/stores/undoRedoStore/README.md)解释了 lazy action：连续输入先实时反映，稍后作为一次动作加入历史；新动作会提交待合并动作。**即时反馈和历史提交时机可以分开设计。**

保存路径是 `saveWorkflow` → `toSimple` → PUT；[`toSimple`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/components/Workflow/Editor/modules/model.ts#L138) 保留 steps、comments、report 等，并先整理 Frame 中的关系。这是一份偏用户文档的表示，不是独立的最小执行图。这里与 ComfyUI 的双表示设计值得对照。

## 两处有真实替换者的扩展 seam

**工具描述格式 seam。** [`ToolSource`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/tool_util/parser/interface.py#L144) 描述读取输入、输出、命令、依赖等方法；[`XmlToolSource`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/tool_util/parser/xml.py#L166) 与 [`YamlToolSource`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/tool_util/parser/yaml.py#L78) 是实际实现。它隔离源格式差异，但 Interface 很宽；“实现同一父类”不等于所有格式都支持每个 feature。

**执行环境 seam。** [`BaseJobRunner`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/jobs/runners/__init__.py#L111) 管理工作线程和排队；[`LocalJobRunner`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/jobs/runners/local.py#L43) 与 [`PulsarJobRunner`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/lib/galaxy/jobs/runners/pulsar.py#L261) 提供实际运行、停止、恢复实现。部署者通过[任务配置](https://docs.galaxyproject.org/en/latest/admin/jobs.html)选择 destination/runner；UI 不负责拼本地进程或远端调度命令。

这两处 seam 的变化轴不同：前者是“工具怎样描述”，后者是“已准备的工作在哪里执行”。将两者合成一个巨型插件 Interface，会让新增格式或新增环境相互牵连。

## 类型化 API 的收益与现实限度

[`GalaxyApi`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/api/client/index.ts#L14) 使用 `openapi-fetch` 和 `GalaxyApiPaths`；[schema 入口](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/api/schema/index.ts)来自 `@galaxyproject/galaxy-api-client`。Invocation 读取因此能在编译期关联路径、参数和响应类型。

不过本次读取的 Workflow 编辑保存和运行提交仍用 Axios。源码中还有 deprecated endpoint 和旧参数解释。应借鉴类型化契约减少手写漂移的方向，不把 Galaxy 描述为已经完全统一、没有历史路径的系统。

Interface 还包含重试、取消和返回错误的方式。只复制生成的 TypeScript 类型，不会自动获得相同的请求合并、数据完整程度或运行语义。

## 测试 seam：上游实际检查了什么

| 证据 | 检查范围 | 不能据此推出 |
|---|---|---|
| [`invocationStore.test.ts`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/stores/invocationStore.test.ts#L61) | HTTP 测试替身下的共享请求、summary 升详情、保留已加载详情、metrics 失效 | 真服务器执行和模型结果正确 |
| [`Run/services.test.js`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/client/src/components/Workflow/Run/services.test.js#L18) | 请求参数配对、分页过滤、缺少工具的错误转换 | 查询对真实大规模数据的延迟 |
| [`test_workflow_invocation.py`](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/test/integration/test_workflow_invocation.py#L106) | Workflow 执行集成、可选输入、工具状态持久化、缺少工具等 | 任意 runner 均具同样恢复能力 |

这说明测试可以围绕读取 Interface、执行 Interface 和编辑命令分别建立证据；无需每次 store 变更都启动计算，也不能用 store 测试替代真实执行验证。本次只阅读这些测试，没有运行它们。

## 给我们的设计候选

### 候选 A：轻量执行会话

保留清晰的编辑模块；新增或重整一个 `ExecutionSession`，向页面提供启动回执、当前状态、结果索引和可定位诊断；实际执行支持时，提供相应的取消操作。内部统一持有当前运行的请求、读取与失效逻辑，不能由这个抽象补出 Provider 没有的远端停止能力。

这里的 `ExecutionSession` 是本文提案名称，不是 Galaxy API。它适合我们主要关注当前运行、又不希望每个页面维护轮询和事件状态的情况。它必须明确：取消是请求还是终止确认；加载失败如何表现；离开页面是否继续读取；切换运行后旧响应如何处理。

### 候选 B：持久研究执行模型

将研究设计版本、每次执行及结果关系作为可长期查询的一等对象，支持运行历史、跨次对比、从旧输入准备新运行。用户已允许重评当前范围，因此这些能力可以讨论，无需用旧 ADR 排除。

它要求回答更多问题：历史存什么、如何定位原始输入与模型、哪些运行可再次执行、失败时保留到哪一层、数据清理如何影响解释。仅增加一个历史侧栏不能完成这一设计。

**建议先比较 A/B 所需对象，避免提前复制 Galaxy 的全部 scheduler/handler/History 系统。** 如果研究旅程需要长期对比，B 有实质收益；若近期重点是单次复杂蛋白设计，A 可能先消除大部分界面耦合。

两者都可借鉴参数准备和执行实例分离、列表摘要与详情完整程度分离、取消请求与终止分离。它们不要求我们采用 Galaxy 的 XML 工具格式、隐式转换或多版本兼容路径。

## 推荐源码阅读顺序

1. `WorkflowRunForm.vue:onExecute` 与 `Run/services.js:invokeWorkflow`：先看用户操作的输入输出。
2. `api/workflows.py:invoke` → `services/workflows.py:invoke_workflow`：追版本与事务归属。
3. `workflow/run_request.py` → `workflow/run.py:queue_invoke`：追准备与持久实例的转换。
4. `WorkflowInvocationState.vue` → `invocationStore.ts` → `keyedCache.ts`：追何时读取、何时算完成。
5. `workflowStores.ts` → `stepActions.ts` → `undoRedoStore`：追编辑动作如何成为历史。
6. `ToolSource`、`LocalJobRunner`、`PulsarJobRunner`：最后研究扩展变化轴。

代码许可见固定提交的 [LICENSE.txt](https://github.com/galaxyproject/galaxy/blob/11e413dc58be6f8ddc26fdd7a997c44a184c3ec8/LICENSE.txt)：代码为 MIT，图标/图片/文档另有条款。本文分析源码机制，不复制上游视觉素材。尚未开展部署、吞吐、恢复和可用性实测；文中的性能与维护成本判断均为源码结构推断。
