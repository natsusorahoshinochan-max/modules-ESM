# 候选 B / Interface 对照三：以蛋白质设计文档为主要编辑对象

[返回设计总览](README.md)。

日期：2026-10-03。状态：独立候选，尚未选定；不是现行契约，也不是已接受 ADR。

**本方案优化的调用者是反复修改条件、生成或分析候选、比较结果并继续设计的研究者。** 默认入口是可理解的输入与条件，而 Workflow 是完整可见、可编辑的执行方式。若实际主要任务是任意图编排，本方案可能输给 Workflow 中心方案；目前不能把精细设计认定为已确认的首要旅程。

使用现有词汇 `Workflow`、`Run`、`Candidate`、`Method`、`Score Observation`；不把 Run 改称 Session。下文 `Design Document`、`Design Revision`、`Prepared Design` 和具名 Workflow 输入是**提案术语**。当前 [CONTEXT.md](../../../CONTEXT.md) 的科学细节、文档归属和版本规则都可重设；这里仅保留可供讨论的名称。

## 1. 用户看到的产品结构

- 左侧是输入素材、条件版本与关联 Run；中部是条件矩阵／序列／结构，或没有条件编辑时的 Candidate 表；右侧是当前操作、Method 与参数。
- “执行方式”展开 Workflow 编辑器。普通用户可以选现成 Workflow 并调整暴露参数；高级用户能增删 Node Instance、分支、连接及输出目标。
- Run 面板同时提供目标结果和逐 Node Instance 的已发布中间输出。只打开阶段摘要不会隐藏数据来源；完整 Workflow 始终可进入。
- 当前查看、加入比较、临时残基选区、下一次输入分别显示；拖动镜头或高亮不会自动改生成条件。采用结果需要明确动作及范围。
- “下一轮”是从当前文档或结果创建新版／分支的操作，不先增加一个独立 Round 持久实体；是否需要命名轮次由使用实验决定。

FASTA 批分析不要求创建空 Prompt。导入后直接显示 Candidate Collection 表，执行方式可以是“多个 Method 评分＋折叠＋筛选”；缺少三维结构时不显示无用的空 3D 主面板。

## 2. 对象与 ownership：不维护两份相同的科学参数

| 对象 | 拥有事实 | 不拥有的事实 |
|---|---|---|
| Design Document（提案） | 输入槽中的条件文档或精确 Candidate 引用；选择的 Workflow 版本、具名输入绑定；用户暴露的运行参数绑定 | SDK tensor、Provider 队列、计算输出、镜头 |
| Workflow | Node Instance、连接、Node 参数及目标 Port；供外部输入和参数绑定的明确位置 | 另一份自动同步的条件文档 |
| Prepared Design（提案） | 一份 Design Revision 的输入快照、解析后的 Workflow、有效参数与接纳诊断 | 可继续编辑的控件值、执行成功承诺 |
| Run／输出记录 | 实际执行与失败、已发布输出、所用准备记录；保留可解释结果所需来源 | 新版文档的当前编辑意图 |
| 显示状态 | 当前 Candidate、比较成员、各视图选择／镜头／布局 | 跨 Candidate 的科学对应关系 |

这是与“Workflow 是唯一作者文档”的实质差异：**条件文档可以独立存在、换用执行方式、在多个输入位置复用；它不再必须是一个 author Node 的 parameter。** 采用这一点要改写当前 Prompt Authoring Document 的归属，而不是偷偷在现有参数旁建立第二份 owner。

绑定只记录来源与目的位置。Workflow 内被外部绑定的参数显示只读引用，编辑动作回到唯一来源；解除绑定后才能成为 Workflow 自有字面值。更改图的输入契约导致绑定失效时，返回定位诊断，不能自动猜线或静默丢条件。

任意 Workflow 不保证可还原成简化表单。图编辑保存新的 Workflow 版本，Design Document 显式引用它；保持相同具名输入契约才可直接沿用输入，超出专用编辑器能力的部分继续用图编辑。这避免设计一个不可能完整往返的“图 ↔ Prompt”转换器。

## 3. Interface 草图

以下是说明调用责任的类型草图，不是可执行 TypeScript。`Readonly` 表示调用方不得原地修改；精确科学字段需在后续规范中定义。

```typescript
type DesignInput =
  | { kind: 'conditions'; document: PromptAuthoringDocument }
  | { kind: 'candidates'; references: readonly CandidateDataReference[] };

type DesignRevision = Readonly<{
  documentId: string; revision: string;
  inputs: Record<string, DesignInput>;
  parameters: Record<string, BoundParameterValue>;
  workflow: WorkflowRevisionRef;
  bindings: readonly ExplicitInputOrParameterBinding[];
}>;
type Location = InputPath | ParameterPath | NodeInstancePortLocator;
type Preparation =
  | { kind: 'ready'; preparedId: string; revision: string;
      summary: EffectiveInputsAndParameters; targets: readonly PortRef[] }
  | { kind: 'invalid'; issues: readonly { at: Location; reason: string }[] };

interface DesignEditor { // 浏览器内 Module；组件与测试跨同一 Interface
  read(): DesignRevision;
  apply(action: DesignAction): EditResult; // 包括采用、绑定、撤销、重做
  save(): Promise<SavedRevision>;        // 后端原子保存，不启动计算
}
interface DesignPreparation { // 核心拥有规范化和科学接纳
  preview(revision: DesignRevision): Promise<AuthoringPreview>;
  prepare(saved: SavedRevision, targets: readonly PortRef[]): Promise<Preparation>;
}
interface Runs {
  submit(preparedId: string, submissionId: string): Promise<RunReceipt>;
  read(runId: string): Promise<RunSnapshot>;
  lookupSubmission(submissionId: string): Promise<SubmissionStatus>;
  observe(runId: string, onChange: (s: RunSnapshot) => void): Unsubscribe;
  requestCancel(runId: string): Promise<CancellationDisposition>;
}
```

`DesignAction` 是少量完整意图，例如“将精确 Candidate 的指定轨道按显式对应关系采用为输入”，不是组件各自写十个字段的公开 JSON patch。一次动作同时更新来源、条件和撤销记录；hover 与镜头不进入此动作历史。

编辑 Module 内保留尚未保存的可撤销版本；保存返回确切版本后才成为已保存事实。允许保存不完整文档；可执行性由 prepare 判定。保存失败不清空本地编辑，不显示为已保存。

## 4. 必须写进 Interface 的时序、错误与成本

1. **预览不执行。** preview 只做明确声明的条件解释与投影，不暗中调用生成 Provider；需要模型的变换必须作为可见执行操作。预览有输入版本，迟到的旧结果不能覆盖新版本。
2. **提交不再读 UI。** prepare 固定条件、来源数据、Workflow、目标及能预先确定的有效参数；成功后返回已保留的 `preparedId`。用户继续编辑不改变它，提交按钮清楚显示它来自哪版。
3. **不伪造随机确定性。** 可控且已实现的随机选择由对应科学 owner 固定并记录；Provider 不能提供的随机状态保持未知。参数归一化与实际执行报告分开，UI 不凭 seed 字段宣称复现。
4. **所有请求目标先接纳。** 默认任一所请求目标不合法即 prepare invalid；用户可明确删去目标后重试。不沿用 ComfyUI 的隐式有效子集接纳。运行中的部分失败仍保留成功输出。
5. **提交回执只代表 Run 已接纳。** `submissionId` 由一次用户提交动作生成并保留；结果未知时按该 ID 查询。重复同 ID 只返回原接纳结果，不建立新 Run，也不自动重新调用 Provider。
6. **传输失败与研究失败分开。** 输入问题是带位置的 invalid；读取失败是传输错误，不改写 Run 状态；真实执行失败由 RunSnapshot 的 Node 结论和诊断表达。局部 invariant 违反直接抛错。
7. **取消是请求。** 返回明确的已请求／已终态／无可中止能力及其适用范围；页面等待后端事实，不把点击当 cancelled。停止后续调度与中止已在 Provider 内的工作分开报告。
8. **终态不删除成果。** 已发布的 Typed Output 与诊断可继续查看；请求取消后的迟到结果如何收录由执行契约明确定义，前端不自行丢弃或升级成功。
9. **关闭视图不取消 Run。** observe 返回退订函数，生命周期结束清理订阅与视图资源；Run 继续。read 是完整状态入口，通知仅触发更新，不要求事件日志重放才能恢复当前显示。
10. **深接口也有数据成本。** RunSnapshot 只含状态和输出描述，坐标、矩阵按引用按需读取；长集合分页。prepare 不随每次鼠标移动运行。延迟与内存预算由代表性数据实验确定，不在本稿宣称性能。

## 5. 三条场景怎样穿过同一 Seam

**精细设计。** 导入结构 → 选目标残基并显式建立来源对应 → apply 固定条件 → preview 查看轨道和坐标 → save → prepare → 展示真实参数 → submit。结果采用是 `apply(adoptCandidateTrack)`，得到新编辑版本；撤销后重新 prepare 应回到之前输入含义，原 Run 与 Candidate 不变。

**FASTA → 多模型评分／折叠 → 筛选。** FASTA 导入后由科学 owner 建立 Candidate；DesignInput 使用 Candidate 引用，Workflow 执行多分支。结果表每列保留 Metric Definition、Method、单位、Observation Context，不能因同一可读名称合并。只改排序是显示操作；保存研究筛选规则或候选集合是明确动作，缺值策略不能由表格默认值代替。

**使用中间结果继续。** 打开失败 Run 中已发布的折叠输出 → 确定该 Port 的 Candidate Collection → 用所选精确引用建立文档分支 → 换执行方式重新评分。重用未变 Candidate 不因为“新一轮”而虚构新的 Candidate 身份或转换 lineage。输入究竟是未变值还是新变换产物，由科学操作定义。

## 6. Implementation 隐藏什么，在哪里需要 Adapter

调用者不处理来源切片、参数归一化、绑定解析、SDK 可变对象复制、残基身份到渲染索引的映射、过时预览淘汰或重复提交。删除这些 Module 后，这些复杂度会重新散落到条件矩阵、3D、运行对话框与结果表，因而具备可检验的 Depth 与 Leverage。

| 依赖类别 | 策略与真实变化压力 | 不能推导的承诺 |
|---|---|---|
| in-process | 编辑动作、撤销、绑定检查集中在 Module；用真实函数跨 Interface 验证 | 不给每个 reducer 建 Adapter |
| local-substitutable | 文档与准备记录持久化采用项目真实存储；临时目录验证原子保存及失败保留 | 存储保存不能代替科学接纳 |
| remote but owned | 前端到本地核心使用实际 HTTP Adapter；确定性内存 Adapter 验证编辑时序与未知回执 | 内存 Adapter 不证明真实协议、存储或 Provider 正确 |
| true external | 生物模型差异保留在对应 Adapter，声明实际参数、错误、取消能力 | 相同函数名不证明本地／远端模型科学等价；mock 不替代真实 Provider 验收 |
| renderer 依赖 | 先以结构 Module 集中 selection、加载与释放；只有比较 3Dmol/Mol* 的真实实现时才建立可替换 Seam | 不为未来任意 renderer 预造插件框架 |

不引入多租户、权限系统、分布式编辑或通用事件溯源。单用户也会同时发生保存、预览和提交；版本与回执机制解决的是这些真实时序以及重复计算，不是托管服务防御。

## 7. 借鉴与代价

| 来源 | 本方案借鉴 | 刻意需要重新定义的行为 |
|---|---|---|
| [ESM](../2026-10-03-frontend-architecture/esm.md) | 直接围绕来源、轨道、生成与采用 | 采用写回编辑文档；不修改已编译 SDK 对象作为事实来源 |
| [ComfyUI](../2026-10-03-frontend-architecture/comfyui.md) | 编辑表示与执行请求分离 | prepare 不读可变 widget、不隐式提交有效子集 |
| [Galaxy](../2026-10-03-frontend-architecture/galaxy.md) | Run、实际执行、输出读取分开 | 保留必要研究历史，不复制全部调度和 History 体系 |
| [KNIME](../2026-10-03-frontend-architecture/knime.md) | 早期可解释诊断，执行生命周期单独拥有 | 静态检查不冒充对实际科学输出的预言 |
| [Mol*](../2026-10-03-frontend-architecture/molstar.md) | 结构状态、选择、镜头、释放集中处理 | renderer 选择不能决定科学残基对应 |
| [Vitessce](../2026-10-03-frontend-architecture/vitessce.md) | 视图只共享指定状态 | 一次采用／建立集合原子完成，不以连续 setter 构造研究事实 |

优点：默认调用者一次动作即可修改完整设计意图；来源与采用的逻辑维护在一处；更换执行方式不用重建条件。代价：Design Document 和 Workflow 两种文档需要明确绑定与版本关系；开放任意 Workflow 时，简化编辑器能力必然有限；批分析用户可能觉得额外文档只是一层包装。

**本候选的推荐条件：** 精细条件编辑与多轮候选采用确实是高频工作，并且同一组输入需要换用执行方式。届时选这一方案，把 Workflow 编辑作为一等入口。尚未取得这些证据时，不将它升级为整个产品的唯一模型。

## 8. 反证与淘汰条件

- 同一条 FASTA 批分析任务若必须制造无意义 Prompt、反复切换编辑器，或无法从任意已发布中间输出继续，淘汰当前设计结构；不能以“高级场景以后再做”掩盖。
- 同一条件分别运行两个 Workflow 后，用户无法解释哪个文档拥有有效参数，说明 binding Interface 不够深；应减少绑定自由度或改为 Workflow 中心。
- 对任意图编辑都必须反向生成条件文档，说明引入了双向科学编译器，应放弃该同步目标。
- 若实测大部分任务围绕节点、分支和共享子图，设计文档只是多余一次打开，则 Workflow 中心更直接；保留其专用条件编辑器即可。
- 首个原型应验证采用→撤销→再准备、同输入换 Workflow、FASTA 双 Method 比较和失败 Run 中间输出续用。只做“漂亮的生成页面”无法支持本候选。

本稿仅提出设计与判别实验，未更改产品代码、CONTEXT 或 ADR；未运行测试、构建、Provider 或性能测量。后续验证依项目远端执行政策进行。
