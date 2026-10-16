# 模块 React 界面契约

Module Package 通过 `ModulePackageRegistration.ui_extensions` 声明浏览器入口、样式和节点编辑器。声明使用 `ModuleUiDefinition` 与 `NodeEditorDefinition`：每个编辑器提供稳定 ID、标题、适用 Node Type IDs 和组件导出名。当前每个 Node Type 接纳一个默认编辑器；重复声明在 Catalog 构建时拒绝，不按加载顺序覆盖。

官方 Selection 与外部包通过同一 `/api/v2/module-ui` 清单发现，通过 `/api/v2/module-ui/{extension_id}/assets/{resource_path}` 读取声明的包资源。资源由 `importlib.resources` 从声明的 Python package 读取。入口须是自包含浏览器 ESM，样式单独声明；不依赖载体内置组件名称表。模块未启用时不出现在当前 Catalog 的 UI 清单中。

## React 与编辑会话

共享运行时为 React 19、React DOM 19 及其 JSX runtime。入口导出 `register(host)`，返回以声明的组件名为键的 React 组件对象。`host` 提供 `React`、`ReactDOM`、`jsxRuntime`，均为载体已经加载的同一份运行时。模块不能捆绑自己的 React 副本。使用本仓库构建脚本时，React imports 被编译成共享运行时引用；外部手写 ESM 也可以直接使用 `host.React.createElement` 与 hooks。

TypeScript 契约位于 [module-ui.ts](../webui/src/module-ui.ts)。组件接收当前 `workflow`、`nodeId`、`catalog`、公共 `client`、可选版本上下文、通用结果阅读会话和异步 `onApply(workflow)`、`onCancel()`。宿主提供的 client 包含当前会话暂存输入，教学实例无需提前持久复制。工作流是此次 WorkspaceEditSession 的基线。取消关闭编辑器，不发布修改；确认仅把完整提案接受到载体内存，用户仍须手动保存项目。组件不能把确认操作当成持久保存。组件等待 onApply 完成后才视为采用；拒绝时显示错误并保留编辑内容，允许用户重试。

模块内的嵌套弹窗使用 `host.InteractionDialog`，与载体复用同一个焦点和弹窗层级实现；外部模块通过 `register(host)` 取得该 React 组件。组件接收 `title`、`children`、`onClose`，以及可选的 `className`、`busy` 和 `onRestoreFocus`，类型见 [InteractionDialog](../webui/src/InteractionDialog.tsx)。本仓库构建脚本将对该源组件的导入转换为宿主引用，不在模块包内另行捆绑其 Radix 实现。

载体拥有对话框、异步加载会话、运行锁及保存。项目切换会废弃尚未完成的编辑器打开请求；运行期间不接受新编辑。Selection 自己通过通用结果会话及公共 client 读取候选，复用模块内共享阅读缓存；完整读取前不开放候选编辑，读取失败显示错误，用户可主动重新读取。重试先刷新读取状态再补全分页，避免把部分集合当作完整集合。宿主不向编辑器传递候选专用投影。Selection 和 Prompt Studio 使用相同接口，源码分别位于 `modules/selection/ui/` 与 `modules/prompt_authoring/ui/`。Prompt 模块持有预览、矩阵、结构操作及合并来源子会话；应用不再固定加载 PromptStudio。

`WorkflowEdge.target_slot` 为目标节点内稳定的输入槽身份，模块可在节点参数中引用该槽；来源节点与输出端口只保存在普通连线中。画布建立或更换来源时生成新槽，删除连线保留节点参数；模块不能因此改用另一条输入。片段复制保留节点参数及内部连线的槽，副本的参数可独立编辑。来源未连接的配置仍可手动保存，是否满足运行要求由模块与通用编译边界判断。Selection 原值排序和 top-k 使用这一公共机制，将评价选择、方向和数量保存为节点参数，不读取 Workflow 全局筛选规则。

指标模块通过同一 `ModulePackageRegistration.utility_transforms` 声明评分方式。`UtilityTransformDefinition` 必须给出 `title`、`meaning`、`applicability`、非空 `limitations`，以及精确 Metric、Method、Context Profile 的 `compatible_input_contract`、参数默认值、Behavior 与 callable。公共 Catalog 完整投影这些声明；Selection 编辑器仅呈现与已选评价匹配且无需用户补填必需转换参数的方式。无适用方式时明确显示加权不可用，仍允许编辑和保存；已保存但失配的选择保留并标明，不自动换成另一方式。标题是展示内容，含义、适用性与限制仍属于定义事实。

模块通过 `value_previews` 声明 `ValuePreviewDefinition(projection_id, port_type_id, title, describe)`，解释所属工具如何使用一个已准入的临时值。Prompt 模块收集 `protein.prompt` 的已启用投影，公共协议仅编码 `tool_projections`。ESM3 自己调用其 Adapter/Operation 解释，不由公共 codec 导入；禁用 ESM3 不影响一般 Prompt 编辑。

## 未发布输入检查与编辑预览

模块通过 `ModulePackageRegistration.authoring_actions` 声明 `AuthoringActionDefinition(action_id, apply)`；`GET /api/v2/module-ui` 的 `authoring_actions` 公布当前启用的 action IDs。`POST /api/v2/projects/{project_id}/authoring-actions/{action_id}` 接收 `{parameters, prospective_inputs?}`，返回模块定义的 JSON object。未声明或已禁用的 action 返回 404。

handler 接收 `AuthoringActionContext` 和模块参数。上下文提供当前项目、Workflow authoring、Catalog 与 `read_input(reference)`；后者先取本次请求的暂存输入，再读取项目已保存输入。暂存输入不发布，不修改项目；模块负责参数准入和结果编码。只读 action 用于来源检查及确定性编辑预览，不能发布 Run、保存编辑或调用科学 Provider；真正采用、保存与计算仍由用户明确触发。

Protein I/O 的 `protein_io.inspect_input` 与 Prompt 的 `prompt_authoring.open`、`prompt_authoring.preview` 使用同一声明和入口，其 schema/codec 在所属模块内。Prompt 继续接收 prospective Workflow 和 version context，只解析已支持来源，不执行任意上游节点。前端模块调用 `client.authoringAction(projectId, actionId, parameters)`；宿主提供的编辑 client 自动带上当前会话暂存输入。已有 `inspectProjectInput`、`openPrompt`、`previewPrompt` 是同一入口的类型化方便方法。

外部模块最小声明示例：

```python
from core.catalog.authoring_actions import AuthoringActionDefinition
from core.catalog.declarations import ModulePackageRegistration


def inspect_reading(context, parameters):
    descriptor, payload = context.read_input(parameters["project_input_ref"])
    return {"filename": descriptor.filename, "reading": float(payload)}


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="meter", package_module=__name__,
    authoring_actions=(AuthoringActionDefinition("meter.inspect", inspect_reading),),
)
```

模块可使用自己的参数解析器，或通过 `validate_schema(..., definitions=...)` 复用公共 JSON schema 解析器；自己的 schema 可引用共享的项目、Workflow 和 JSON 类型，不要求伪装为 ProteinPrompt 或蛋白输入。

## 结果读取与查看器

模块通过 `ModulePackageRegistration.result_readers` 注册 `ResultReaderDefinition(port_type_id, kind, read)`。同一 Port Type 只有一个读取投影，函数接收已发布 canonical bytes，返回模块定义的 JSON object。`results:value` 按输出的实际 Port Type 分派，返回 `{kind, value}`；载体不要求自定义类型伪装为蛋白。`GET /api/v2/module-ui` 同时公布 readers 与 UI extensions，原始类型值读取不依赖专用 reader。

`ModuleUiDefinition.viewers` 接受 `ResultViewerDefinition(viewer_id, title, port_type_id, component, is_default)`。同一类型可由多个模块声明不同查看器，所有声明中恰有一个默认查看器；重复 ID、缺失 reader、缺失或重复默认值在 Catalog 构建时拒绝，不按加载顺序覆盖。查看器与节点编辑器共用 `register(host)`、React 实例、入口缓存和资源交付。查看器组件接收 `ModuleViewerProps.reading`，只决定显示，切换不会改写已发布值。

Protein I/O 为 `protein.structure` 注册默认三维查看器和结构原文查看器。载体提供选择控件和原始值入口。序列与 Prompt 轨道展示也由各自模块注册；Prompt 保留残基分页、Mask 与整条轨道缺失区别、原子坐标和功能注释。载体对没有查看器的值只提供 JSON 展示，不再固定分派序列或 Prompt。候选分页与候选结构读取由 Protein I/O 的 `protein_io.candidate_page` 和 `protein_io.candidate_structure` 只读 action 提供，经通用 `results:action` 调用；原独立 collection/structure 路由已移除。action 接收发布字节、已准入参数和已发布 Candidate references，分页沿用原身份而不重算。候选关联分数、对齐、筛选和导出由模块 Run 查看器组合呈现。外部模块可通过同一声明为自定义类型提供查看器，不依赖蛋白类型。读取投影的 `kind` 由模块定义；没有专用查看器的外部值采用通用 JSON 展示，不因同名 `kind` 被当作蛋白数据。

## 历史值采用声明

模块通过 `ModulePackageRegistration.result_sources` 声明 `ResultSourceDefinition(port_type_id, node_type_id, binding_id, output_port)`；来源节点使用普通 Project Input 参数与类型化输出。`GET /api/v2/result-sources` 供采用界面发现兼容值，`POST /api/v2/projects/{project_id}/inputs:adopt` 接收精确的来源项目、Run、节点、端口和值序号，独立保存输入后返回来源节点参数。该请求不修改或保存 Workflow。

共享 `AdoptedInputOperation` 读取声明的 `project_input_ref`，以 `RestoredOutput` 交给既有输出准入恢复原始 canonical 值和 Candidate references；不按新生成候选分配身份。模块可提供 `observations` 与 `dependencies` 回调，投影原值的评价能力并选择必要依赖。官方 Candidate 来源由 Protein I/O 提供，Score 来源由 Selection 提供；外部包使用同一声明。来源节点的 `restored_output_port` 标记保存在 Commit，原参数读取不依赖当前模块是否启用。

不需要附加输出或依赖的来源节点可复用 `core.catalog.adopted_sources.with_adopted_sources`。模块显式列出 `(本地节点名, Port Type ID)`，并提供 `definitions/<本地节点名>.yaml`：无输入、一个名为 `value` 的目标类型输出，以及必填的 `project_input_ref` Project Input 参数。辅助函数仅补齐同一恢复操作的 Method、Binding 和 `result_sources` 声明，不扫描或自动启用其他类型。

```python
from core.catalog.adopted_sources import with_adopted_sources

MODULE_PACKAGE = with_adopted_sources(MODULE_PACKAGE, (
    ("adopt_temperature", "example.temperature"),
))
```

官方模块以此声明 Prompt、单序列、单结构、条件轨道、残基轴、结构注释、评价关系、比对数据、置信度事实、ProteinMPNN 条件与 ESMC 表征；外部温度模块使用同一入口。采用数据保留为目标项目自己的 canonical 值，不依赖来源项目继续存在。需要评价定义、依赖或额外输出的 Score 来源仍通过上述完整声明提供。

## 同一次 Run 的跨输出查看

`ModuleUiDefinition.run_viewers` 声明 `RunViewerDefinition(viewer_id, title, port_type_ids, component)`。Run 包含声明类型中的任一输出时，载体显示该面板入口；多个入口按稳定 viewer ID 排序，用户可切换，不按模块加载顺序覆盖。它与单值查看器共用 `register(host)`、资源与 React 实例。

`ModuleRunViewerProps` 只提供 Run、通用结果阅读会话、公共客户端、当前工作区查看状态和节点定位回调。外部模块可用相同的值读取与 action 接口关联多个输出，不需要接收载体定义的蛋白、分数或对齐对象。查看状态仅保留在浏览器会话内，不保存项目。

| 现有展示 | 读取与界面 owner |
|---|---|
| 序列、结构三维与原文 | Protein I/O 单值 reader/viewer |
| Prompt 残基轨道、坐标、Mask、注释和分页 | Prompt authoring 单值 reader/viewer |
| 候选分页、元信息、完整引用和所有 parents | Protein I/O candidate actions 与 Run 面板 |
| 关联分数的 Metric、Method、Context、单位、残基轴及来源 | Selection reader；Protein I/O Run 面板组合 |
| 已发布轴及候选序列关联 | Structure transform reader；原值与候选面板 |
| 对齐角色、刚体变换、RMSD、coverage、三维叠加 | Structure comparison reader；Protein I/O Run 面板组合 |
| 搜索、临时筛选/排序、导出勾选、四位置比较、ZIP及参数 | Protein I/O Run 面板及模块读取会话 |
| 所有类型原值、输出身份、附件与 Run 控制 | 载体通用结果壳 |

`PublishedResults` 协调 Run 状态/事件、通用不可变值读取及结果下载打包。模块运行查看器通过同一 `results.exportBundle(files, details)` 接口提交文件名到 `Uint8Array` 的映射和模块自己的选择说明，取得 ZIP 字节；载体附带现有参数读取器取得的 `computation-parameters.json`（类型值与附件均关联原生产 Run 的节点参数及已保存 admitted 参数；附带的 `publishing_workflow` 只表示本次发布 Run 的 Workflow），并写入 `export-details.json`，不解释蛋白或组分语义。会话切换后未完成的打包返回 `undefined`，模块不触发下载。附件下载通过 `results.exportArtifact(artifact)` 读取并打包，整个异步过程使用开始时的阅读会话；已发布 Artifact 的媒体与内容不变。附件公开投影携带已有结果身份与生产 Run，缓存重放不会将当前节点参数冒充原生产参数。Protein I/O 的 `CandidateResults` 订阅该会话，维护候选分页与关联索引；同一会话的候选面板、节点摘要和 Selection 编辑数据共享索引，不建立第二条事件连接。宿主结果壳不固定加载蛋白面板。模块内部可以共用 UI 设施，不要求复制结构渲染器等实现。

## 构建与分发

模块 UI 源码位于 `modules/<package>/ui/`，`module-ui.json` 声明源码入口及相对输出路径。`npm ci` 安装由 `webui/package-lock.json` 固定的构建工具，然后在 `webui/` 执行 `npm run build:module-ui`。生成的 `ui/build/` 不提交 Git。开发服务器和前端构建的前置步骤执行同一个命令。

Python wheel 构建需要 Node.js 22.12+ 和已安装的前端构建工具。`setup.py` 的 `build_py` 将同样的 JS/CSS 编译到 wheel 暂存目录；安装后的服务器读取这些资源，不需要 Node.js。sdist 包含源码、工具与 npm 锁文件；从独立 sdist 构建时先在其 `webui/` 执行 `npm ci`，或者显式设置 `PROTEIN_WORKBENCH_UI_TOOLCHAIN` 指向已有相同锁版本的 `webui/` 工具目录。构建不自动安装依赖。

Module UI source directories declare `"type": "module"` in their own
`package.json`, preserving ESM imports outside the WebUI package scope.

区域比较、提取和已有指标统计由各自模块注册编辑器，共用自然位置编辑组件；对齐和统计结果通过模块单值查看器显示。
