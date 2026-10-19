# 模块接入与文件交付

行为范围见 [需求](requirements.md)，职责与文件交接见 [架构](architecture.md)。Python 作者入口为 `protein_workbench_public.module_api`，该入口只依赖标准库。

## Python 声明

模块提供一个无参数工厂，返回 `Module`。工厂声明节点、配置字段和可选的浏览器入口；配置保存在应用数据目录中，与节点计算参数分开。一个模块的 `nodes` 可声明多个节点。

用户在应用中选择 wheel 文件并填写 `包名.模块名:工厂名`，点击 `Install package`。应用使用后端 Python 将所选 wheel 离线安装到数据目录的独立包目录，只安装该包；其 `Requires-Dist` 中的依赖须已由部署者装入后端环境。已有环境包可用 `Register module` 登记同一公共工厂。安装成功后默认启用。禁用保留设置；卸载删除登记及应用拥有的包目录。随载体发行的官方模块可重新登记其公开入口。安装失败清理本次目录并报告具体原因。HTTP 客户端上传使用 `POST /api/module-packages?filename=所选文件名&entry_point=公开工厂`，携带 `Content-Type: application/octet-stream` 和 `X-Workbench-Module-Package: wheel`；应用界面自动填写。登记已有环境包的 `POST /api/modules` 使用 `application/json`。

模块声明的环境字段是凭据、已有模型路径、服务地址或程序位置等字符串。`Module.settings` 以字段名映射说明文字，或映射 `{ "type": "string", "title": "显示名称", "secret": true }`；`secret` 字段在界面中遮蔽显示。载体按声明展示并保存用户值，通过 `Call.settings` 及工具的构造入口提供给所属模块。

```python
from shutil import copyfileobj

from protein_workbench_public.module_api import (
    Delivery, InputPort, Module, Node, Outcome, OutputPort,
)


def execute(call, runtime):
    source = call.inputs["source"][0]
    output = runtime.workdir / "output.bin"
    with source.open(source.entry) as reader, output.open("wb") as writer:
        copyfileobj(reader, writer, length=1024 * 1024)
    return Outcome(outputs={
        "result": [Delivery(
            format="my_lab.binary",
            entry="data",
            files={"data": "output.bin"},
        )],
    })


def module():
    return Module(
        id="my_lab.copy",
        name="Binary copy",
        nodes=(Node(
            id="my_lab.copy_file",
            name="Copy file",
            execute=execute,
            inputs={"source": InputPort(accepts=("my_lab.binary",))},
            outputs={"result": OutputPort(format="my_lab.binary")},
        ),),
    )
```

`Call.inputs` 按端口提供有序数据包，`parameters` 提供节点参数，`settings` 提供模块部署配置。输入包通过 `format`、`entry`、`files` 描述内容，用 `open(文件键)` 获取只读二进制流。模块在自己的公开格式文档中说明文件内容、对应关系与样例，独立消费者据此读取。

## 交付文件

将输出写入 `runtime.workdir`，完成写入并关闭后返回 `Outcome`。`Delivery.files` 的键供包内读取使用，值为该工作目录内的相对来源路径；`entry` 选择其中一个键，可以指向二进制文件。返回后由载体接收文件，模块放弃写权。

大文件使用流读取和写入。浏览器上传实际文件后提交交付描述，下载通过文件入口；文件内容不嵌入计算请求或结果 JSON。

通用 HTTP 包操作为 `POST /api/projects/{target}/adoptions`，正文 `{ "package_id": "所选包 ID" }`，返回目标项目的新包记录；`GET /api/packages/{id}/export.zip` 下载完整 ZIP。归档的 `package.json` 提供 `format`、`entry` 及按包内顺序排列的 `files: [{key, member}]`，原始文件键通过该索引对应 `files/000000` 等安全成员名。所有模块格式均使用这些入口。

操作不能完成时，返回 `failed` 和具体 `diagnostics`，或者抛出包含具体原因的异常。已接收的数据包通过应用的包入口重新读取，接收者只使用包内键。

## 后端运行

`Workbench.start(project_id)` 与 `POST /api/projects/{project_id}/runs` 返回已创建的运行记录，初始状态为 `running`。用 `Workbench.get_run(run_id)`、`GET /api/runs/{run_id}` 或项目运行列表查询后续状态；浏览器断开后后端继续执行。`Workbench.cancel_run(run_id)` 与 `POST /api/runs/{run_id}/cancel` 请求取消，模块通过 `runtime.cancelled` 观察信号；任务退出并释放项目租约后恢复编辑。

运行记录的 `groups` 保存连通组成员及配置诊断。`configuration_blocked` 表示组内公开配置不完整或连接不合格；`failed` 表示节点执行或文件交付失败；`blocked` 表示依赖未成功而未执行。`Outcome` 的部分输出在接收成功后仍可查看，失败节点的输出不驱动下游。节点状态、输出包与续算内容在同一次提交后可见。查询发现运行租约已结束而终态未提交时，报告失败并保留已持久接收内容。

## React 界面

公共类型以 npm 包 `@protein-workbench/module-ui` 分发，包文件随 Python wheel 安装在 `protein_workbench_public/module_ui/`。先安装 `protein-workbench` wheel 并激活其 Python 环境，再在作者项目目录执行：

```bash
SDK_DIR="$(python -I -c 'from importlib.resources import files; print(files("protein_workbench_public").joinpath("module_ui"))')"
npm pack "$SDK_DIR" --pack-destination .
npm install ./protein-workbench-module-ui-0.1.0.tgz react@^19
npm install --save-dev typescript@~5.8.3 @types/react@^19
```

作者使用包名导入类型：

```typescript
import type { ModuleEntry, ModuleActionProps, EditorProps, ViewerProps } from '@protein-workbench/module-ui'
```

类型文件通过作者项目的 `node_modules` 解析；React 19 与 `@types/react` 19 是该包的 peer dependencies。完整作者样例见 `examples/typescript_module/`，其 `tsconfig.json` 使用标准 NodeNext 解析及严格类型检查。编译后仅保留模块自身代码，类型导入被移除。

仓库前端也使用这个 npm 包；`webui/.npmrc` 的 `install-links=true` 将本地包复制到前端的 `node_modules`，公共声明集中维护在包内的 `index.d.ts`。

`Module.ui` 指向模块包附带的浏览器 ES 模块文件。该文件导出 `runtime = { react: 19 }` 和 `register({ React })`，返回操作入口 `actions`、节点参数编辑器 `editors` 或格式查看器 `viewers`。

模块记录的 `installation_id` 标识当前这次安装；启停和设置保留它，卸载重装重新分配。`GET /api/catalog` 返回当前 `ui_url`，载体通过该地址装载界面。入口按当前安装核对，与当前身份不符的地址返回 409。模块入口为单文件 bundle；其依赖沿下述共享和打包约定提供。

载体传入自己安装的 React 19 实例。模块使用这个实例创建元素和调用 hooks；构建模块时将 React 作为共享依赖，产物只保留传入的运行时引用。其他浏览器依赖由模块打包进自己的入口文件。

操作入口通过 `host.createInput` 上传文件并创建输入包，使用 `host.addNode` 和 `host.connect` 编辑流程。查看器通过 `host.readFile` 读取包内文件。同一格式可声明多个具有唯一 `id` 的查看器；载体按查看器 ID 排序，默认使用第一项，用户可手动切换。打开另一包时恢复默认；当前查看器被禁用或卸载时使用剩余默认项，切换只影响展示。编辑器接收节点参数及 `onChange`；界面遵守 `readOnly` 状态。各接口的参数以公共类型声明为准。

操作绑定发起时的项目会话；切换项目后，旧操作的编辑请求会拒绝。`await host.addNode(...)` 完成后，后续 `addNode` 或 `connect` 调用可立即使用已添加的节点。

## 安装并运行外部样例

在已安装本项目的 Python 3.12 环境中，从仓库根目录执行：

```bash
.venv/bin/python -m pip install --no-build-isolation --no-deps ./examples/external_module
.venv/bin/python -m pip install --no-build-isolation --no-deps ./examples/independent_consumer
```

按 [README](../README.md) 启动后端和前端。创建项目，在模块管理中分别登记：

```text
workbench_notes:module
workbench_note_consumer:module
```

使用 `New note` 操作输入文本并添加 `Uppercase note` 节点，再添加 `Count note characters` 节点。在端口连接区将前者的 `note` 输出连到后者的 `note` 输入，保存并运行。结果包可通过查看器或文件下载入口读取，重开项目后仍可访问。

生产者发行包为 `workbench-notes-producer`，消费者发行包为 `workbench-note-consumer`。消费者仅依赖载体公共接口，依据生产者公开的 `example.note` 格式独立解析输入。两者的格式说明和样例分别位于 `examples/external_module/src/workbench_notes/` 与 `examples/independent_consumer/src/workbench_note_consumer/` 下的 `FORMAT.md`、`sample/`。

模块包使用标准 Python 构建配置将工厂代码、浏览器入口及格式资源一并安装。登记和设置保存在应用数据目录，重启应用后继续读取。

## 发行包隔离验证

运行实际分发包的接入验证：

```bash
.venv/bin/python -m pytest tests/test_installed_modules.py -q
```

测试需要 Python 构建工具、Node.js、npm 及依赖源访问。它在临时副本中构建载体和两个独立模块的 wheel，将正常依赖下载到 wheelhouse 后，在全新虚拟环境中离线安装，并执行 `pip check`。子进程使用 `python -I` 隔离源码导入。

生产者交付数据后，测试注销并卸载生产者，删除构建源码及执行工作目录，再安装消费者，验证已有包的读取、计算、保存和重新打开。 官方预测与比较的隔离测试保留单体载体发行包，在临时安装环境中仅移除预测生产模块目录，再用全新的 `python -I` 进程检查生产模块无法导入，并验证采用、ZIP 与两种比较路径。类型验证从已安装的载体 wheel 打包 npm 包，在仓库外的独立 TypeScript 作者项目中安装；删除 Python 安装环境和原始 tarball 后执行严格编译。

## 工具插槽

节点通过 `Node.tools={"位置名称": ToolSlot("作者定义的约定 ID", "显示名称")}` 公开调用位置。实现模块声明 `Module.tools=(Tool(id=..., name=..., slot=..., create=...),)`；`create(settings)` 接收实现所属模块的部署配置并返回可调用对象。`Tool.parameters` 和 `capabilities` 是面向用户的参数与能力声明，载体只保存和展示。

流程节点的 `tools` 按位置名称保存所选实现 ID；`tool_parameters` 按相同位置保存参数字典。载体检查所选实现仍存在且声明相同约定 ID，将可调用对象注入 `Call.tools`，把选择 ID 提供给 `Call.tool_choices`。未安装或已禁用的实现不能执行；保存的选择仍保留。节点通过自己的公开约定解释请求、结果、错误及取消和续算，不枚举实现。

独立结构比较入口为 `modules.structure_comparison:module`；参考输入、结果包和明确复用接口见 [比较格式](../modules/structure_comparison/FORMAT.md)。该消费者直接读取预测格式，查看叠合只需要结果包内的双方完整结构、对齐和全部原子坐标。

完整实例为 `modules.folding:module`：调用约定见 [预测工具插槽](../modules/folding/TOOL.md)，独立数据读取说明与样例见 [预测格式](../modules/folding/FORMAT.md)。

显式转换及独立目标格式消费者见 `modules.structure_conversion:module` 的 [格式与接入说明](../modules/structure_conversion/FORMAT.md)，其比较执行明确依赖 `protein-workbench` 分发包提供的比较公共入口。

## 本地子进程工具

需要机器资源互斥的本地 Adapter 可调用仅依赖标准库的公共入口 `protein_workbench_public.worker_process.run_worker(command, *, cwd, log_path, cancelled, label)`。`command` 为可执行文件及参数列表，`cancelled` 为读取取消状态的无参数函数，`label` 用于错误显示。正常退出后返回；非零退出时报告退出码及日志末尾的具体原因，取消时等待进程清理后报告错误。模块自行准备配置文件并读取结果文件；资源与进程约束见 [本地模型](local-models.md)。
