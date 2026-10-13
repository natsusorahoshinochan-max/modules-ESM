# Interface 对照二：核心拥有编辑命令与版本投影

日期：2026-10-03。状态：独立对照设计，尚未选择或实现。[返回设计总览](README.md)。

**主张：让同一组研究编辑操作服务图、阶段表单和 Prompt Studio，由核心集中拥有文档、撤销和准备运行的语义。** 浏览器负责即时手势与渲染，收到明确版本的投影后才把编辑视为已保存。此方案优先保证多入口行为一致，接受比客户端文档方案更高的往返和协议成本。

本文的 Interface 是类型、时序、失败与成本的总和；Seam 是替换行为的位置；Adapter 是满足该 Interface 的具体实现。术语借用现有 CONTEXT，但现有契约与 ADR 不限制方案。下列类型均为提案，不是已有 API。

## 1. 三个维度分别作决定

| 维度 | 本候选的选择 | 不由此推出什么 |
|---|---|---|
| 主要编辑对象 | 研究 Workflow 文档，可用图或专用编辑器呈现 | 不要求所有用户从空白图开始；FASTA 导入不经过 ProteinPrompt |
| 编辑事实 owner | 核心 Authoring Module 持有版本、命令结果与撤销历史 | 不要求每个鼠标移动调用后端，也不需要多用户协同 |
| 即时交互 owner | 浏览器拥有尚未提交的手势、hover、镜头和局部选区 | 临时预览不是已保存条件；选区不会自动成为生成约束 |

这里的 Workflow 是 Node Instances 的研究表达，不是一个包揽历史和界面的巨大对象。Candidate、Score Observation、Run 仍有自己的身份与生命周期。专用 Prompt 编辑器修改目标 Node Instance 的条件文档；同一修改不能再在浏览器维护另一份权威数组。

## 2. 外部 Interface：有限命令，而非任意状态补丁

以下伪 TypeScript 展示必需调用约定；领域值如 `PromptEdit`、`CandidateRef` 保留其完整身份、单位、形状及缺失语义，不以任意 JSON 代替。

```ts
type Version = number; // 同一文档内单调递增；不是 Run 状态版本
type Edit =
  | { kind: "changeWorkflow"; changes: WorkflowChange[] }
  | { kind: "editPrompt"; nodeId: string; changes: PromptEdit[] }
  | { kind: "adoptResult"; nodeId: string; candidate: CandidateRef;
      tracks: TrackName[]; mapping: ResidueMapping; mode: "replace" | "addSource" }
  | { kind: "undo"; commandId: string }
  | { kind: "redo"; commandId: string };
type Command = { requestId: string; documentId: string;
  expectedVersion: Version; edit: Edit };
type CommandResult =
  | { kind: "applied"; requestId: string; commandId: string;
      version: Version; projection: EditorProjection }
  | { kind: "rejected"; requestId: string; version: Version;
      reason: "staleVersion" | "invalidEdit" | "historyMismatch" | "interrupted";
      diagnostics: Diagnostic[] };
type Prepared = { preparedId: string; documentId: string; sourceVersion: Version;
  inputs: ImmutableInputRef[]; effectiveParameters: EffectiveParameters;
  methodBindings: MethodBindingRef[]; locatorMap: LocatorMap };
type PrepareResult = { kind: "ready"; prepared: Prepared } |
  { kind: "blocked"; sourceVersion: Version; diagnostics: Diagnostic[] };
type SubmitResult = { kind: "admitted"; runId: string; preparedId: string } |
  { kind: "rejected"; preparedId: string; diagnostics: Diagnostic[] };
type CancelResult = { runId: string; stopScheduling: "requested" | "alreadyTerminal";
  attempts: { attemptId: string; stop: "unsupported" | "requested" | "confirmed" }[] };
type RequestResult = { kind: "command"; result: CommandResult } |
  { kind: "prepare"; result: PrepareResult } | { kind: "submit"; result: SubmitResult } |
  { kind: "cancel"; result: CancelResult };
type Receipt = { state: "absent" | "pending" } |
  { state: "resolved"; result: RequestResult };
interface ResearchCore {
  open(documentId: string): Promise<EditorProjection>;
  apply(command: Command): Promise<CommandResult>;
  prepare(request: { requestId: string; documentId: string;
    version: Version; scope: RunScope }): Promise<PrepareResult>;
  submit(request: { requestId: string; preparedId: string }): Promise<SubmitResult>;
  receipt(requestId: string): Promise<Receipt>;
  readRun(runId: string): Promise<RunProjection>;
  cancel(request: { requestId: string; runId: string }): Promise<CancelResult>;
}
```

`WorkflowChange` 仅含增删 Node Instance、连断 Port、改参数/Binding、改 Selection Objective 等有限操作；`PromptEdit` 仅含来源映射、轨道编辑、显式结构变换等已定义研究动作。一次数组原子应用，失败不留下半次修改；不接受脚本或任意对象路径。`undo/redo` 不能混入普通修改数组。

`adoptResult.replace` 只替换映射所覆盖的目标轨道值；`addSource` 新增可编辑来源约束而不隐式覆盖冲突值，冲突作为拒绝诊断返回。两者都保留来源 Candidate 身份；它们不是“用结果覆盖整个 Workflow”的别名。

`EditorProjection` 至少含 `documentId/version`、当前文档、静态可得的输入输出描述、可定位诊断、可撤销/重做的 `commandId`。科学值尚未知时显式显示 unknown，静态检查不偷偷调用 Provider。`Diagnostic` 带节点/字段/残基定位及可理解原因；不把所有错误压成通知字符串。

`RunScope` 明确本次目标与依赖闭包；`RunProjection` 带自己的 `runVersion`、每项工作状态、已发布 Typed Outputs、诊断及取消状态。只有已发布且可独立解释的输出可采用；网络分片、尚未闭合的数组和进度图不是 Candidate。

## 3. 调用顺序、撤销与未知结果

1. `open` 返回已持久保存的版本。输入连续变化先在本地合并为一个手势，结束时提交一条命令；prepare、离开编辑器和 undo 必须先处理待提交手势，不能暗中忽略它。
2. 每文档只保留一个在途编辑命令，后续编辑排队；核心仅接受 `expectedVersion` 对应当前版本。不自动重放到较新版本，因为残基轴或来源可能已变。拒绝时保留本地意图供用户修正。
3. `applied` 连同完整投影返回，收到它就足以更新 UI。首版不引入独立 patch 订阅；若以后需要订阅，每份消息也必须有版本，旧消息不能覆盖新投影。
4. undo 只接受当前历史栈顶的命令 ID；成功生成新版本，恢复该动作前的内容。redo 恢复同一批值与映射，不重新抽随机数。新编辑清除 redo 分支；Run 和已有输出不随撤销删除。
5. 领域拒绝以有类型结果返回；传输失败意味着“未确认”，不意味着操作失败。客户端以原 `requestId` 查询回执：pending 等待，resolved 应用结果；absent 时允许用户继续同一请求 ID 的重发，不新造一次操作。
6. 核心在受理时持久登记请求 ID 与输入摘要；重复的相同请求返回原结局，同 ID 不同内容是本地 invariant 错误。文档修改、历史游标与成功回执在同一持久提交内完成。无需通用事件平台。

重启时先按持久事实收敛 pending：已提交命令恢复原结局；未提交编辑记录 interrupted 拒绝，未完成准备记录 blocked；已建立 Run 的提交回执返回原 Run。取消意图与回执一起持久保存。外部请求结局未知记录在 Run，不自动重投，也不把 pending 永久留给客户端等待。

版本检查处理的是单用户自身的异步时序和多编辑入口，不是引入多租户或冲突合并。返回全投影的成本随文档增长；大坐标和候选数据仅返回不可变引用。交互帧率不依赖 HTTP 往返，提交反馈延迟仍须测量。

## 4. prepare 与 submit 固定哪一份事实

`prepare` 针对精确历史版本，集中完成输入解析、诊断、默认值与本次随机选择的确定，产出可阅读的有效参数和不可变输入引用。它不修改正在编辑的文档，也不调用生成 Provider；模型执行前才可得的信息不伪装成已知。重复同一 request ID 不产生另一组随机选择。

Prepared 记录保存在核心，固定源版本、目标闭包、Method/Binding、已确定的有效参数、内容引用与结果定位关系；它不是仅在浏览器有效的 token，也不是序列化的 Python Execution Plan。未能保存被引用数据或所需定义时准备不成功；不让引用随后静默漂移。

`submit` 仅接受 `preparedId`，不同时接收当前文档或临时参数覆盖。核心先原子保存 Run 与提交回执，再启动执行；继续编辑 v13 不改变从 v12 准备的 Run。环境 Readiness 在真实进入 Provider 前检查，prepare 不承诺未来可用。

同一提交 request ID 永远指向同一 Run；用户有意再运行同一 Prepared 需要新的提交 ID。这只防止 Workbench 重复受理，不能承诺第三方远端 exactly-once。若进程在外部请求后中断而结局未知，保留未知/中断事实；只有 Provider 官方支持时才能查询恢复，不自动再发生成请求。

`cancel` 首先请求停止后续调度；对在途工作逐项返回真实能力。没有官方停止接口的远端调用显示 unsupported，并允许继续记录后来得到的输出。只有收到终止事实才显示 confirmed；UI 不把“收到取消请求”显示为“全部计算已停止”。页面关闭不等于取消。

## 5. 同一任务怎样调用

```ts
const p = await core.open(documentId);                      // v10
const a = await core.apply({ requestId: "e1", documentId,
  expectedVersion: p.version, edit: { kind: "editPrompt", nodeId,
    changes: [placeSourceFragment, editTargetTrack] } });    // 成功得到 v11
const q = await core.prepare({ requestId: "p1", documentId,
  version: applied(a).version, scope: generationScope });   // Prepared -> v11
const run = await core.submit({ requestId: "r1", preparedId: ready(q).preparedId });
// 运行中仍可 apply 修改当前文档到 v12，Run 继续引用 v11。
// readRun 返回已发布 Candidate 后，以 v12 + 显式 residue mapping 采用部分轨道。
// adoptResult 成功得到 v13；undo 该 commandId 得到 v14，内容等于采用前 v12。
```

示例中的 `applied/ready` 代表调用方显式处理上述判别联合，不是忽略失败的强制转换。采用前若目标残基轴已变化，就要求新映射；不以相同数组长度推定对应。采用动作保留 Candidate 来源、轨道和映射；撤销不使 Run 消失，也不撤销此前 v12 的其他编辑。

另一条旅程是：导入 FASTA 为不可变来源 → `changeWorkflow` 建立输入、评估、折叠和筛选 Node Instances → 配置准确的 Metric/Method/Selection Objective → prepare → submit → 阅读 Candidates 与 Score Observations。它使用相同编辑/执行 Interface，无需创建虚假的 Prompt 条件文档。计算顺序由具体 Node Type 依赖确定，不能假定所有评价都可在折叠前做。

## 6. 隐藏在 Seam 后的行为与依赖策略

| 依赖类别 | 本方案隐藏的工作 | Adapter 与验证位置 |
|---|---|---|
| In-process | 研究命令、映射变更、撤销、规格推导、投影 | 直接在 Authoring Interface 检查行为，不为每个 helper 建 port |
| Local-substitutable | 文档/Prepared/Run 记录及不可变数据的持久提交 | 用实际存储实现与临时存储实例验证重开；不预设新数据库或多存储框架 |
| Remote but owned | 浏览器到本机核心的有限请求与回执 | HTTP Adapter + 直接内存调用的测试 Adapter 是拟实现的两种替换者；目前不是已存在事实 |
| True external | Provider 表示转换、调用、真实停止/查询能力 | 使用实际支持的 Provider Adapter；定向测试替身只验证协议行为，不能替代真实 Provider 验收 |

渲染器另有独立 Interface：输入结构引用、稳定残基身份、选择和显式变换，输出用户交互意图。Mol* Loci 不能成为编辑主键；也不因研究 Mol* 就提前承诺两个 renderer Adapter。来源读取、命令准备和渲染替换是不同变化轴。

持久内容包括文档版本、有限撤销历史、请求回执、Prepared、Run 和已发布输出引用；不持久保存 hover、GPU 对象、在途 Promise。采用结果所引用的数据不能因清理 Run 列表被删除。保留期及显式删除是独立产品决策；本候选不默认无限保存所有历史。

## 7. Depth、Locality 与反证

**收益：** 图、Prompt 和阶段表单通过一个 Authoring Interface 获得相同的版本、原子编辑、撤销和结果采用规则；复杂性集中于核心而非三个前端 store。删除此 Module 后，这些规则会重新散落到各入口，因此存在真实 Depth。准备与运行分离也使运行中编辑不再要求 UI 复制模型对象。

**代价：** 命令种类和投影需跨语言维护；每个新的编辑语义都涉及核心，局部预览仍需要前端代码。若为了自由度允许任意 JSON patch，校验、撤销和映射知识又会泄漏给调用者，Depth 反而下降。全投影响应可能较大，需用真实文档验证其成本。

**最强反证：** 若产品长期只有单一浏览器编辑器、所有编辑都可由纯客户端文档变换描述，且启动核心前也需要编辑，那么核心命令增加了时序却没有第二个调用者的收益；应选择客户端拥有文档的方案。若 Prompt 操作变化极快且核心命令只转发字段，Module 也会变浅。

原型应比较同一旅程的状态副本数、一次改动需触及的 owner 数、未知结果后的重复 Run 数、undo 恢复精度和大文档提交延迟；暂不以代码行数或框架名称选胜者。若接口检查发现来源映射仍需由三个视图分别补全，应退回重画 Seam。

依据来自 [KNIME 命令与投影](../2026-10-03-frontend-architecture/knime.md)、[Galaxy 持久执行](../2026-10-03-frontend-architecture/galaxy.md)、[ComfyUI 转换与事件时序](../2026-10-03-frontend-architecture/comfyui.md)、[ESM 可变对象与能力差异](../2026-10-03-frontend-architecture/esm.md)、[Mol* 选择身份](../2026-10-03-frontend-architecture/molstar.md) 和 [Vitessce 共享状态](../2026-10-03-frontend-architecture/vitessce.md)。借鉴的是职责分配，本文回执、Prepared 和命令协议是我们的设计，没有声称上游已提供同样保证。本轮只写设计文档，没有运行测试、构建或 Provider。
