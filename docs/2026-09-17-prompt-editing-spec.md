# Prompt 编辑与合并的科学合同

本规格实现 [完整 WebUI 集成计划](2026-09-17-webui-full-integration-plan.md) P4/P5 的已确认决策。`modules/prompt_authoring/recipe.py` 是预览和执行共同的科学 owner；浏览器只组装意图，不产生随机结果、不推断残基对应。

## 文档执行顺序

依次采用主来源/blank chains、显式 target layout、按 document 顺序的随机插入、按列表顺序的 source merges、普通 track edits、按列表顺序的 rigid transforms、随机 Mask、完整 Function tuples。每个刚体变换读取前一个变换的坐标结果；不会再次从最初来源取坐标。合并建立编辑基线，随后本节点的显式轨道、坐标和 Function 编辑作用于合并结果。所有预览显示该顺序。

## 刚体变换

世界坐标，列向量约定 `x' = R (x − origin) + origin + translation`，距离 Å，UI 角度 °，右手旋转。UI 的 G 默认沿操作开始时的视平面移动，R 默认绕当时视线旋转；X/Y/Z 切换世界轴约束，再按同轴解除。镜头基向量只确定本次操作方向，最终生成已有的精确 3×3 `rotation_matrix`、三维 `origin`、三维 `translation` 和 `residue_ids`。

默认中心是选区中全部现有原子坐标的算术平均；不按残基平均，也不只取 CA。选择“残基位置”时，用户明确选择残基及该残基的一个现有 named atom，默认候选为 CA（有 CA 时）；不会猜测或补造坐标。自定义中心直接指定世界坐标 Å。中心标记和数值与提交的 origin 一致。选区允许不连续，但每个参与变换的残基必须有坐标；Mask 残基须从变换选区排除。旋转/位移不会改变未选择残基。镜头操作不写入 document。

同链相邻的一个选中、一个未选中残基构成变换边界；UI 列明其精确 residue identities 并提示可能改变边界几何，不设置猜测的键长阈值，不自动移动邻居或最小化。这是提示，不是新的科学 admission。

三维选择与镜头导航不改变科学坐标。中键旋转视角，Shift＋中键平移，滚轮缩放；只有初载或主动聚焦重新适配镜头。B 穿透框选显示选择标记：每个残基优先取现有 CA，否则取现有原子的几何中心，按标记的屏幕投影是否落入框判断。这个选择标记不同于刚体变换的全原子旋转中心。保留可见点选；本轮不提供可见框选。G/R 中鼠标、数字和轴键属于同一持续操作，Enter／左键确认、Escape／右键取消；自由移动的数字沿已建立的鼠标方向，无方向时明确要求先移动鼠标或选择轴。轴与视线接近而无法可靠求鼠标位移时，保留数值输入并显示提示。

当前结构显示仍使用 3Dmol。G/R 拖动通过 90 ms debounce 请求后端 preview，再以返回的 PDB 清除并重载模型，同时恢复镜头。该路径尚未达到用户要求的流畅实时预览；2026-09-29 交互阶段性通过不代表此问题已解决。后续需优化拖动显示反馈，当前未更换 renderer，也未实现逐帧本地坐标预览。

## Function tuples

端点编辑替换精确的 `(label, start_residue_id, end_residue_id)`。拆分点是左区间最后一个残基；生成 `[start, split]` 和 `[next, end]` 两个 tuple。仍由现行 owner 检查同链连续区间、允许重叠和禁止完全重复。任何删除或合并都不自动截短 annotation。

## 显式区域合并

`source_merges` 每项为 `{source_index, correspondence, track_adoptions, adopt_annotations, remove_annotations}`。这是唯一当前合同，替换旧的整轨 adopt/preserve。

- source_index 对应有序 `merge_sources` 输入。来源 identity/digest、全部有序残基和轨道投影由后端 open 返回；不把来源内容写进 document。
- correspondence 必须将每个来源残基和每个原目标残基按各自顺序恰好表达一次。`match` 同时消费一个来源与一个原目标；`source_gap` 只消费来源；`target_gap` 只消费目标；`insert` 消费来源并显式创建新的目标 identity，位置由表中顺序确定。insert 要求用户给出目标 identity，不使用数组下标猜对应。现有 layout owner 检查 chain 和 identity。
- `track_adoptions` 是 `{track, source_residue_ids, mask_policy}` 列表。选择细到来源残基 × 轨道；未选值保留目标。`mask_policy` 必填，`preserve` 保留来源 Mask 对应的目标旧值，`adopt` 明确允许来源 Mask 清除目标。采用 whole-track absent 是错误，不能把 absent 冒充 Mask。每个轨道只能出现一次，每个被采用残基必须有 match/insert。
- `adopt_annotations` 精确列出来源完整 tuples；`remove_annotations` 精确列出待移除目标 tuples。移除发生在 target layout 扩展前，以便用户明确解决插入打断原区间的后果。来源 tuple 只有完整、连续、同链映射时才能采用，失败不截短。不采用/不移除的目标 tuple 保留；完全重复仍由现行 annotation owner 拒绝。
- 新残基先全 Mask；仅采用被选择的来源轨道。预览分别列明新增 identity、轨道采用、Mask 处理和 annotation 采用/移除。重复来源按列表顺序作用，后项读取前项结果。

手动表格从空对应开始，不自动序列比对或位置匹配。用户可显式增加、调整和移除每行，填写 gaps，逐轨勾选采用范围。应用前始终经过同一后端 recipe 预览。

## 编辑会话

blank 默认布局，其他来源默认条件。桌面主工作区为结构视图与 AG Grid Community 残基矩阵两栏，可调整宽度；窄屏通过结构／矩阵页签切换。矩阵以残基为列、五条轨道为行。常用选择、指定值和清除操作位于矩阵工具栏；插入／删除、批量修改、随机操作、Function、精确结构参数、合并和条件详情按需打开对话框，不再常驻第三栏。三维点选同步矩阵位置但保留视口键盘焦点；主动定位矩阵和撤销／重做按各自工作上下文恢复焦点。

矩阵单击选择，键入替换，F2／双击编辑现值；Enter 接受并移到下一轨道，Tab 接受并移到下一残基，Shift 反向，Escape 取消当前输入。Shift 连选保持最初锚点，Ctrl／⌘ 追加或移除单元格。Sequence、SS8、SASA 原位输入，Coordinates 和 Function 使用专用编辑入口。输入框显示当前选值；混合选值和 Mask 不伪装为默认氨基酸。非法输入保留在编辑器中，输入法组合确认不提前提交。

复制按残基列序和可见轨道顺序生成 TSV；一次粘贴先验证整个范围，非法或不匹配的内容不修改任何单元格。原生输入框内的复制粘贴只作用于输入文本。单格确认与一次有效粘贴分别形成一次内容编辑；快速连续输入按次序请求预览并保留各自撤销记录，失败保留输入和选区。显式批量、布局、随机、Function、合并与精确参数操作继续经过预览／应用；一次完整 G/R 变换形成一次编辑。Ctrl／⌘ Z 撤销、Ctrl／⌘ Shift Z 重做遵守当前焦点与模态范围，恢复对应内容并保留镜头与工作位置。清除选择不取消编辑。

顶部保存直接写回整份会话，无需第二次保存确认或重复接受已完成的单格操作。最终写回使用已确认的规范化预览；文档、来源或版本改变后才重新预览。

随机控件记录 seed/count/eligible scope。换 seed 只是修改明确 seed 后请求 owner；真实选择只展示后端 trace。已生成随机残基可以编辑值，不能独立删除或作为普通插入锚点。轨道摘要区分 absent 与 present/all-Mask。页面离开使用浏览器 beforeunload 保护未保存编辑。

## 验证

测试仅在远端服务器执行。覆盖组合 track preview、seed 重抽、端点/拆分、连续刚体变换、未选坐标不变、逐区域采用与 Mask policy、显式插入与 annotation 后果、预览/执行一致，以及无来源结构时的空状态。新增连接的原子 graph+document 提交由公共 authoring 接口共同实现，不能用前端先保存连接再取消作为替代。

## Prospective Workflow 的原子写回

open/preview 请求可携带完整 `workflow`。它是本次会话待采用的普通 Workflow document（新增 I/O/author Nodes、边及目标 author Node 均在其中），不创建第二套 graph model。省略时使用当前已保存 Draft。open/preview 只解析候选，不写 Draft；因此取消没有 graph 修改。已发布但未引用的 immutable Input 仍按 Input 生命周期处理。

open 返回当前工作区的 `draft_revision`。WorkspaceEditor 将已确认的 normalized document 放入本会话的完整候选 Workflow，再统一提交；不重新求值、规范化或生成／比较哈希。Prompt 专用 apply route/request/result/codec 已删除。普通保存携带打开编辑时的 `expected_draft_revision`，由 Workflow 持久化 owner 与当前工作区的 Draft revision 比较一次，防止覆盖后续编辑。历史最大 revision 仅用于分配新记录编号。新项目无 Draft 时基线为 0。冲突不自动合并或重试。其他未完成 Nodes 不被强制编译。

旧版本预览携带版本上下文，使科学变更基线仍来自被查看的版本。确认后由 WorkspaceEditor 以最终候选 Workflow 和当时的 desired UI 调用 `fork_version`；普通编辑调用 `save_workspace`。整个确认只有一次工作区发布，返回完整 ProjectWorkspace；不能先 fork 再保存，也不能先覆盖当前工作再另行 fork。旧版本与打开前的当前工作均保持可返回。长会话需要改变布局时提供作用于最新 UI 的明确操作，不携带旧完整 UI 覆盖后来布局。

## ESM3 有效条件的权威视图

公共 authoring codec 取得 recipe 已求得的实际 `ProteinPrompt`，调用 ESM3 Adapter 的只读 `describe_conditioning` 和 Operation 的 `describe_generation_compatibility`。不从矩阵/PDB文本反建科学数据，不调用 Provider，不查询运行准备状态。Adapter 内部 `_ConditioningProjection` 仍私有，不建立新 Port Type。

投影列出实际 sequence Mask `_`、absent/present SS8 与 SASA、已解析的一基闭区间 Function annotations、functional-input digest，以及有序 atom37 entries。每项包含原 residue identity、atom name/index、实际 float32 坐标与位模式。没有可用 atom37 坐标时 coordinates 表示 absent；科学 Prompt 中非 atom37 named atoms 单独列明遗漏但保持原值。UI 同时显示实际结构形状 `[L,37,3]`、Å 和 NaN 缺失表示。

科学合法的多链 Prompt 等 SDK 无法表示的内容显示 `unsupported` 原因，不阻止保存。Node 模式前提单独显示，来自运行时现有 sequence Mask / complete sequence 检查；条件投影兼容不代表模型已安装、Provider可达或本次 Run 已 Ready。只捕获明确的模型不可表示结果；科学内部不变量仍 fail fast。

### 手动合并的证据与阶段投影

Open/Preview 的 `merge_targets` 由同一 recipe owner 记录：元素 i 是执行第 i 个 `source_merges` 前的目标科学值；最后一个元素是全部来源合并之后、普通轨道覆盖、刚体变换、随机 Mask 和最终 Function 替换之前的值。没有合并时仍有一个初始目标。对应表、原目标身份与 annotation 删除选择引用此阶段，不能引用本次合并自己的输出。无效预览没有有效阶段投影；UI 若继续显示上次有效阶段，明确说明其不是当前无效预览的结果。

证据分屏提供独立的来源与目标三维视图和有序残基带。选择既有明确 Match 时同步选中；未对应的位置保持可独立选择，用户明确创建 Match。Ctrl/⌘ 可多选、Shift 可取区间；首端、尾端与任意已选行之后均可显式添加 gap。新增目标身份由用户填写。来源区域采用范围可精确到所选残基 × 轨道，Mask 决策必须显式提供；影响表展示后端阶段目标旧值、来源值、采用/保留/清除意图、新增身份及完整 annotation 后果。分屏不计算对应、不自动对齐、不改变镜头之外的科学坐标。

新增来源入口保持 Studio 实例及当前未确认 document。来源选择向 App 返回完整 prospective Workflow，成功后更新可选来源；取消来源选择维持原会话。最终确认通过 WorkspaceEditor 使用相同完整 Workflow 与 document 一次持久化，关闭整个会话丢弃未提交的图与 document。已上传且取消后未使用的 Input 遵循项目 Input 保留合同。

当同时修改目标 layout、来源合并和最终 Function 列表时，layout 阶段保留仍完整连续的继承 tuple，供后续明确 remove_annotations 引用。显式最终 Function 替换只允许丢弃已被 layout 破坏的旧 tuple，不截断或自动扩展；最终列表仍在全部合并后整体替换。与目标扩展无关的 tuple 不提前抹去。

旧版本编辑的变更预览基线来自 `version_context.version_id` 对应的不可变命名版本，不能以打开前的另一份当前工作来标记本次变化。确认时沿用工作区 owner 的返回点保护和原子 fork。

### 合并后的普通布局编辑

不新增隐式执行阶段。普通布局始终修改 merge 前的 `target_residues`；生成该列表时只使用 owner 的首个 `merge_targets` 轴，排除随机插入，不把后续 merge 的 insert identity 声称为原始 source。

用户明确删除目标残基时，同步每个已声明对应表：该目标的 Match/Insert 转为原来源的 Source gap，Target gap 删除，并只移除这些来源残基的轨道 adoption 及被删除目标的普通 track edits/刚体选区引用。其余对应和采用范围保留；annotations 不裁剪、不自动删除，不能继续满足完整区间的意图由 owner 诊断，等待用户明确修改。

用户普通插入的新身份在 merge 前创建，并在每个已声明 merge 的适当位置加 Target gap，不建立任何新的来源 Match。位置依照用户所选锚点在后端最终轴上的先后关系、各表中已有的精确目标身份确定。因此也可以在 merge 创建的身份之后插入：较早阶段放在当时仍存在的最近前驱后，产生锚点的阶段放在其 Insert 行后。最终仍由 owner 核对全源/全目标顺序与 annotation 完整性。改数量时先移除同一 pending 插入的旧身份与它们的 gap，再提出新身份。随机插入的独立布局限制保持不变。

可插入的目标 chain 集合固定取本次 recipe 初始主来源的实际 chains，或显式 blank declarations，并贯穿 target layout 与全部来源合并。删除某链的旧残基不会撤销这个已经明确的范围，因此允许显式用 merge insert 全部替换原链残基；多链中也可仅保留某链的新合并残基。来源合并不能凭来源 chain 自动扩大目标 chain 范围，未声明的目标 chain 仍拒绝。该范围只用于 recipe admission；最终 ProteinPrompt 的 layout 仅记录实际输出残基，不存幽灵残基或独立空链，也不新增执行阶段。

## 画布修改合并来源

`source_merges` 非空且被保留的 Prompt 节点，其现有 `merge_sources` 有序来源
必须保持为修改后来源列表的完整前缀。画布允许无操作重连和末尾追加，拒绝替换、
删除、移出或重排现有来源；删除直接来源节点同样适用。批量操作同时删除该 Prompt
时不保护其已删除的配置，但仍检查其他保留的 Prompt；整个操作一次接纳或全部保留。

拒绝时保留原 Workflow，定位受影响 Prompt 并提供打开 Studio 的入口。用户先通过
现有 Preview 编辑、清除合并操作并保存，再修改连接；画布不自动清除文档其他编辑、
重映射 source_index、猜测对应关系或增加来源 digest 合同。本规则只保护直接连接
变更，不建立上游内容追踪机制。三个主来源仍明确展示为“最多选择一个，全部不选
表示空白”，与 ordered many 合并来源分别呈现。
