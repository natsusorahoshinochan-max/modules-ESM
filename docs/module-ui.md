# 模块 React 界面契约

Module Package 通过 `ModulePackageRegistration.ui_extensions` 声明浏览器入口、样式和节点编辑器。声明使用 `ModuleUiDefinition` 与 `NodeEditorDefinition`：每个编辑器提供稳定 ID、标题、适用 Node Type IDs 和组件导出名。当前每个 Node Type 接纳一个默认编辑器；重复声明在 Catalog 构建时拒绝，不按加载顺序覆盖。

官方 Selection 与外部包通过同一 `/api/v2/module-ui` 清单发现，通过 `/api/v2/module-ui/{extension_id}/assets/{resource_path}` 读取声明的包资源。资源由 `importlib.resources` 从声明的 Python package 读取。入口须是自包含浏览器 ESM，样式单独声明；不依赖载体内置组件名称表。模块未启用时不出现在当前 Catalog 的 UI 清单中。

## React 与编辑会话

共享运行时为 React 19、React DOM 19 及其 JSX runtime。入口导出 `register(host)`，返回以声明的组件名为键的 React 组件对象。`host` 提供 `React`、`ReactDOM`、`jsxRuntime`，均为载体已经加载的同一份运行时。模块不能捆绑自己的 React 副本。使用本仓库构建脚本时，React imports 被编译成共享运行时引用；外部手写 ESM 也可以直接使用 `host.React.createElement` 与 hooks。

TypeScript 契约位于 [module-ui.ts](../webui/src/module-ui.ts)。组件接收当前 `workflow`、`nodeId`、`catalog`、公共 `client`、可选版本上下文、已发布候选集合和异步 `onApply(workflow)`、`onCancel()`。宿主提供的 client 包含当前会话暂存输入，教学实例无需提前持久复制。工作流是此次 WorkspaceEditSession 的基线。取消关闭编辑器，不发布修改；确认仅把完整提案接受到载体内存，用户仍须手动保存项目。组件不能把确认操作当成持久保存。

载体拥有对话框、异步加载会话、运行锁及保存。项目切换会废弃尚未完成的编辑器打开请求；运行期间不接受新编辑。Selection 和 Prompt Studio 使用相同接口，源码分别位于 `modules/selection/ui/` 与 `modules/prompt_authoring/ui/`。Prompt 模块持有预览、矩阵、结构操作及合并来源子会话；应用不再固定加载 PromptStudio。

模块通过 `value_previews` 声明 `ValuePreviewDefinition(projection_id, port_type_id, title, describe)`，解释所属工具如何使用一个已准入的临时值。Prompt 模块收集 `protein.prompt` 的已启用投影，公共协议仅编码 `tool_projections`。ESM3 自己调用其 Adapter/Operation 解释，不由公共 codec 导入；禁用 ESM3 不影响一般 Prompt 编辑。

## 结果读取与查看器

模块通过 `ModulePackageRegistration.result_readers` 注册 `ResultReaderDefinition(port_type_id, kind, read)`。同一 Port Type 只有一个读取投影，函数接收已发布 canonical bytes，返回模块定义的 JSON object。`results:value` 按输出的实际 Port Type 分派，返回 `{kind, value}`；载体不要求自定义类型伪装为蛋白。`GET /api/v2/module-ui` 同时公布 readers 与 UI extensions，原始类型值读取不依赖专用 reader。

`ModuleUiDefinition.viewers` 接受 `ResultViewerDefinition(viewer_id, title, port_type_id, component, is_default)`。同一类型可由多个模块声明不同查看器，所有声明中恰有一个默认查看器；重复 ID、缺失 reader、缺失或重复默认值在 Catalog 构建时拒绝，不按加载顺序覆盖。查看器与节点编辑器共用 `register(host)`、React 实例、入口缓存和资源交付。查看器组件接收 `ModuleViewerProps.reading`，只决定显示，切换不会改写已发布值。

Protein I/O 为 `protein.structure` 注册默认三维查看器和结构原文查看器。载体提供选择控件和原始值入口。序列与 Prompt 轨道展示也由各自模块注册；Prompt 保留残基分页、Mask 与整条轨道缺失区别、原子坐标和功能注释。载体对没有查看器的值只提供 JSON 展示，不再固定分派序列或 Prompt。候选分页与候选结构读取由 Protein I/O 的 `protein_io.candidate_page` 和 `protein_io.candidate_structure` 只读 action 提供，经通用 `results:action` 调用；原独立 collection/structure 路由已移除。action 接收发布字节、已准入参数和已发布 Candidate references，分页沿用原身份而不重算。候选关联分数、对齐、筛选和导出由模块 Run 查看器组合呈现。新行为测试中的外部模块通过同一声明为独立 `reader_demo.temperature` 类型提供摄氏与华氏查看器，不依赖蛋白类型。读取投影的 `kind` 由模块定义；没有专用查看器的外部值采用通用 JSON 展示，不因同名 `kind` 被当作蛋白数据。

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

`PublishedResults` 只协调 Run 状态/事件和通用不可变值读取。Protein I/O 的 `CandidateResults` 订阅该会话，维护候选分页与关联索引；同一会话的候选面板、节点摘要和 Selection 编辑数据共享索引，不建立第二条事件连接。宿主结果壳不固定加载蛋白面板。模块内部可以共用 UI 设施，不要求复制结构渲染器等实现。

## 构建与分发

模块 UI 源码位于 `modules/<package>/ui/`，`module-ui.json` 声明源码入口及相对输出路径。`npm ci` 安装由 `webui/package-lock.json` 固定的构建工具，然后在 `webui/` 执行 `npm run build:module-ui`。生成的 `ui/build/` 不提交 Git。开发服务器和前端构建的前置步骤执行同一个命令。

Python wheel 构建需要 Node.js 22.12+ 和已安装的前端构建工具。`setup.py` 的 `build_py` 将同样的 JS/CSS 编译到 wheel 暂存目录；安装后的服务器读取这些资源，不需要 Node.js。sdist 包含源码、工具与 npm 锁文件；从独立 sdist 构建时先在其 `webui/` 执行 `npm ci`，或者显式设置 `PROTEIN_WORKBENCH_UI_TOOLCHAIN` 指向已有相同锁版本的 `webui/` 工具目录。构建不自动安装依赖。

Module UI source directories declare `"type": "module"` in their own
`package.json`, preserving ESM imports outside the WebUI package scope.
