# Interface 对照一：用三个操作完成一次研究迭代

日期：2026-10-03。状态：独立候选提案，尚未采纳或实现。[返回设计收敛总览](README.md)。

本方案把“Workflow Draft → 准备 → Run → 采用 Candidate”集中在一个 deep Module，优先减少普通调用者需要掌握的生命周期。主要编辑对象是研究 Workflow；Prompt Studio 是其中一个 Node Instance 的专用编辑视图。既有契约与 ADR 是背景材料，不用于限制候选方案。

**推荐条件：** 用户主要进行“修改一份 Workflow，运行，检查结果，再修改”的串行研究。**核心限制：** 一份准备记录最多接纳一个 Run；再次执行需要重新准备。这个限制是真实产品取舍，不以一个万能 `dispatch(string, payload)` 掩盖更大的 Interface。

## 1. Module 的范围与事实归属

核心拥有已确认的 Workflow Draft、准备记录、Run 与结果事实；浏览器拥有拖拽、滑块、悬停和镜头等即时预览。选择核心作为 owner，是为了让采用结果、来源关联、版本发布与撤销进入同一编辑事务，避免每个视图分别拼装和保存这些变化。

本 Module 负责一次研究迭代的三个转换，**不冒充完整图编辑器 Interface**。普通节点增删、连接和参数编辑由 authoring owner 提供；布局和镜头不经本 Module。调用 `prepare` 前，调用者必须拿到 authoring owner 确认的 Draft revision；仅存在于输入框或拖拽预览中的值不参与运行。

这是一个跨前后端的 Module，不要求独立服务。浏览器调用 facade，核心保存事实，传输 Adapter 隐藏 HTTP 与观察连接。科学 Node Type、Method、Candidate 与 Run 的含义沿用项目词汇；下文 `Preparation`、`RunView`、`Adoption` 均为待评估的新增提案。

## 2. 三个入口与数据形状

下面是概念 Interface，不是生产 TypeScript 声明；省略的领域类型需要在选定方案后逐项定义。

```typescript
prepare(draft: DraftRef, targets: readonly OutputPortRef[]): Promise<PrepareResult>
run(preparation: PreparationRef, signals: RunSignals): AsyncIterable<RunView>
adopt(base: DraftRef, adoption: Adoption): Promise<AdoptResult>

type DraftRef = { workflowId: WorkflowId; revision: DraftRevision }
type PrepareResult =
  | { kind: 'ready'; preparation: PreparationRef; review: PreparedReview }
  | { kind: 'invalid'; diagnostics: readonly Diagnostic[] }
type RunSignals = {
  stopObserving: AbortSignal
  requestCancellation: AbortSignal
}
type Adoption =
  | { kind: 'source'; candidates: readonly CandidateDataReference[];
      destination: SourcePortTarget }
  | { kind: 'prompt-tracks'; candidate: CandidateDataReference;
      destination: PromptNodeTarget; edits: readonly MappedTrackAdoption[] }
type AdoptResult =
  | { kind: 'published'; draft: DraftRef; change: AdoptionSummary }
  | { kind: 'stale'; current: DraftRef }
  | { kind: 'invalid'; diagnostics: readonly Diagnostic[] }
```

`PreparationRef` 是核心保存的准备记录标识，不能只指向浏览器内存。`PreparedReview` 含精确 Draft revision、目标输出、已解析的 Node Type / Method / Execution Binding、输入内容引用、有效参数、随机性说明及定位诊断。它不向前端暴露 SDK 对象、张量或可变 Execution Plan。

`RunView` 是某个 Run 的完整可显示投影，至少含 `runId`、单调 `revision`、当前运行状态、Node Instance 状态、已发布 Typed Output 引用、失败定位、取消请求状态和终态。订阅首先给出最新投影，随后给出更新；进度未知就明确未知，不按请求耗时猜百分比。

`SourcePortTarget` 明确采用到哪个 Node Instance 的哪个输入；核心在该次编辑中建立显式来源节点与连接。`MappedTrackAdoption` 必须逐项指定目标轨道、来源 Candidate 内容引用、来源/目标残基身份对应及写入范围；只替换明确指定的范围，禁止按数组位置或运行时 renderer 索引推断对应。

这两个采用变体是有限的领域操作，不接受任意 patch 或插件函数。新增第三种采用语义必须评审 Interface，而不是悄悄增加隐藏 hook。

## 3. 时序、版本与完成语义

1. `prepare` 读取精确 Draft revision，完成科学输入准备与执行可行性检查，固定内容引用和有效参数。用户可读的诊断返回 `invalid`，整个目标集合不接纳；不悄悄运行其中有效的部分。
2. 成功准备记录不可变，保留其解释需要的定义信息；不创建 Run，不调用生成 Provider。浏览器继续编辑 Draft 不会改变该记录，纯布局变化也不改变其科学内容。
3. `run` 第一次使用某个 Preparation 时，核心原子接纳并绑定一个 Run；以后使用同一个标识只观察这个 Run。断线重连不重新调用 Provider，重连也不是恢复已经中断的计算。
4. 真正执行前仍可能遇到 Binding 不可用或外部操作失败；这些成为实际 Run/Node outcome，不改写准备快照。不能把准备成功展示为 Provider 一定能完成。
5. `adopt` 在核心比较 `base.revision` 与当前 Draft。相同才发布新 revision；不同时返回 `stale`，不自动合并、不重放用户动作。来源、轨道变化与撤销信息一起发布。
6. 采用引用已经发布且可读取的 Typed Output / Candidate；整体 Run 失败不必抹去已经发布的有效结果。采用只产生新的编辑事实，不凭空产生已执行的 Candidate，也不修改旧 Candidate。

准备记录的身份与其内容摘要分开：对同一 Draft 再次 `prepare` 可以得到另一份准备记录，随后产生另一个 Run。随机性是否重新实现、能否提供 seed、哪些条件由 Provider 控制，应在 `PreparedReview` 明示；不假定不同 Method 具有相同随机性承诺。

调用方只在收到确认的投影后显示“已接纳”“已停止”或“采用已保存”。作者预览与核心确认可以同时显示，但必须有明确区别；一次命令响应不是所有独立视图已渲染完成的证明。

## 4. 错误、取消与资源

| 情况 | Interface 约定 | 调用者应做什么 |
|---|---|---|
| 参数、Port 或残基映射不成立 | 返回可定位的领域诊断 | 回到相应 Node Instance / 字段 / 残基范围修正 |
| 本地不变量被破坏 | 立即抛出编程错误，不包装为普通诊断 | 报错并修复；不静默修补输入 |
| 观察连接失败 | 抛出传输错误，已接纳 Run 保持自身状态 | 显示“状态连接断开”；使用同一 Preparation 重连 |
| Node 执行失败 | `RunView` 保留确切 Node outcome 与已发布结果 | 解释失败范围，不把传输成功等同计算成功 |
| `stopObserving` 或 iterator 释放 | 仅关闭该订阅和浏览器资源 | 关闭面板不会默认停止 Run |
| `requestCancellation` | 发送明确取消请求；以投影确认是否接纳及实际停止 | 请求发出、请求接纳、实际终止分别显示 |

取消先停止后续调度，再按具体 Adapter 已声明的能力处理在途操作。若外部 Provider 不支持停止，界面保留“已请求停止，仍等待在途操作结束”的事实；不伪造远端已取消。已发布结果保留，取消与完成竞态由核心决定最终事实。

取消信号本身不证明送达；连接中断时只能显示“送达未知”。重新观察同一 Preparation 时可以再次发送同一语义请求；核心对已终态 Run 返回终态，对已接纳取消保持原结论，不重复启动任何操作。

核心拥有准备记录、结果引用和运行证据的寿命，浏览器缓存不是持久记录。关闭订阅不删除记录；清理保存空间属于独立、显式的数据管理动作，不能作为 iterator 的析构副作用。启动进程重启后的旧 Run 可以显示 `interrupted`；本方案不承诺复原 Provider 的内部过程。

## 5. 一次完整使用场景

用户在 Workflow 的 Prompt Node Instance 中修改来源片段。authoring owner 确认 Draft `d18` 后，“准备运行”调用 `prepare(d18, [generation.output])`；界面显示来源版本、Method、有效长度及随机性说明。这里显示的是准备结果，尚没有 Run。

确认后，界面观察 `run(p7, signals)`，第一份投影给出 Run `r4`。用户可以继续编辑为 `d19`；`r4` 仍执行 `d18`。关闭结果面板仅释放观察；再次打开时用持久保存的 `p7` 恢复观察，既不产生第二个 Run，也不从浏览器缓存猜进度。

`r4` 发布 Candidate `c8` 后，用户选择其序列轨道和明确的残基对应，向当前 `d19` 发起 `adopt`。核心原子发布 `d20`，保留 `c8` 的来源引用及采用范围。一次撤销恢复采用之前的编辑内容，并发布新的 Draft revision；不删除 `r4` 或 `c8`。

若期间另一个已确认动作将 Draft 改为 `d21`，采用返回 `stale`；界面展示目标已变化，用户重新检查后再采用。重新准备的新记录必须从已确认 Draft 构造，不能从旧准备产物或渲染器状态反推。

## 6. Implementation 隐藏什么；依赖如何处理

删除这个 Module 后，目标遍历、输入固定、参数实现、接纳去重、观察重连、取消状态、结果来源与采用事务会重新散落在运行对话框、结果工作台和 Prompt Studio 中。这些是它提供 Depth 的主要内容；单纯把 HTTP 请求转发三次不够。

| 依赖类别 | 本方案处理 | Adapter 的真实性与验证责任 |
|---|---|---|
| 进程内 | 图解析、有效参数、结果映射与采用计算集中在内部 | 不为纯函数制造 port；通过三个操作验证可见结果 |
| 本地可替换 | 核心持久存储、原子接纳和 Draft 发布 | 优先使用真实临时存储做集成验证；不假称已有两套数据库实现 |
| 远端但自有 | 浏览器到 loopback 核心的提交与观察 | 拟实现 HTTP Adapter 与确定性内存 Adapter，二者必须经过同一 Interface 用例；目前是待验证的 seam |
| 真正外部 | 科学执行的 Provider | 使用既有实际 Adapter；其输入、错误、取消能力逐一核查，不能从相同基类推断等价 |

内存 Adapter 能验证重连、版本与取消竞态，但不能证明持久写入或真实 Provider 行为。后续运行验证必须遵循项目远端验证政策，真实 Provider 验收仍独立进行。本文件未运行代码、测试、构建或 Provider。

## 7. 取舍与最容易推翻本方案的场景

优点是 UI 只组织三次领域转换，版本、接纳、结果采用和错误在同一个 Seam 后闭合；通过相同 Interface 可以覆盖完整研究迭代。限制是一份准备记录绑定一个 Run，历史读取依赖其保存的关联，且核心拥有编辑事务会增加拖拽预览与确认状态的协调成本。

Interface 仍然包含两个信号、有限采用变体和完整投影，不能仅凭“三个函数”宣称简单。若调用者反复绕过它处理部分执行、单独订阅或逐字段采用，它的 Depth 已经下降，应扩大或重新划分 Seam。

**最容易推翻它的任务：** 用户固定同一个输入快照，按多个 Method 与随机条件批量提交、比较、取消部分 Run，并从任意历史结果分支编辑。这会让 Preparation 同时承担请求身份与提交身份，迫使调用者制造没有编辑意义的新准备记录。此时应拆开“准备值”“Run 接纳”“观察/取消”，明确增加 Interface，而不是继续塞入 `run` 的参数变体。

另一个推翻条件是浏览器需要离线编辑或长期保存多个未确认分支；届时客户端文档 owner 可能更合适。多用户、权限、集群和可插拔存储平台不在这个可信单用户产品的目标内，不为它们增加抽象。

本方案借鉴 [ComfyUI 的编辑/执行区分](../2026-10-03-frontend-architecture/comfyui.md)、[KNIME 的核心确认与投影](../2026-10-03-frontend-architecture/knime.md)、[Galaxy 的运行与结果寿命](../2026-10-03-frontend-architecture/galaxy.md)，并针对 [ESM 的可变配置和转换差异](../2026-10-03-frontend-architecture/esm.md)收拢准备逻辑。三个入口及其行为均是本项目提案，不是上述项目现成提供的 Interface。
