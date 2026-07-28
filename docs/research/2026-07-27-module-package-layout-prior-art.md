# Module Package 与 Node Definition 组织方式的外部先例调研

- 日期：2026-07-27
- 状态：调研记录，尚未形成项目决策
- 范围：Protein Workbench v2 的 Module Package、Node Definition、Python
  实现/Adapter、可选依赖与测试组织
- 来源边界：仅使用官方规范、官方文档和第一方源码

## 调研问题

本次调研回答五个问题：

1. 成熟生态把什么作为发现和加载单位？
2. 是否存在包级 manifest？
3. 一个操作或节点通常是一份定义文件、一个目录，还是在包内集中定义？
4. 声明式定义如何与 Python 或其他可执行实现绑定？
5. 可选依赖和契约测试如何组织？

## 结论摘要

不存在一个可直接照搬的、跨生态统一的“节点目录标准”。不同生态中
`plugin`、`provider`、`component`、`module` 和 `tool` 的角色并不相同；
仅按名称比较会得出错误结论。

跨生态反复出现的是以下分层，而不是某个固定目录树：

1. **发现单位通常比单个操作更粗。** PyPA/pytest 和 Airflow 以已安装
   distribution/provider package 为发现单位；一个入口可以交付多个能力。
2. **可组合操作通常有独立契约。** KFP `ComponentSpec`、CWL `Process`、
   Nextflow registry module、nf-core module 和 Galaxy tool wrapper 都把单个
   可执行操作的输入、输出及执行要求作为独立验证边界。
3. **契约粒度不等于源码粒度。** Airflow 一个 Python module 可以包含多个
   Operator；pluggy 一个插件 namespace 可以实现多个 hook；KFP 一个 Python
   文件可以声明多个 component。没有通行规则要求一份声明对应一个 Python
   文件和一个 Python package。
4. **实现绑定是显式的。** 成熟方案使用 `module:object`、provider metadata
   中的 class/module path、KFP `implementation`、CWL `run` 或 Galaxy
   `command`，而不是依赖 import side effect 或递归导入任意文件。
5. **只有在操作自带较多资产时，“一操作一目录”才显示出明显价值。**
   Nextflow/nf-core 和 Galaxy wrapper repository 会把脚本、环境、模板、
   测试数据放在操作附近；纯 Python 插件生态通常不规定这种物理布局。

因此，外部先例支持“Module Package 作为发现单位、Node Type 作为契约单位、
Adapter/实现按内聚性共享”的方向，但**不能证明“每个 Node Type 必须有独立
目录”，也不能证明“所有 Node Type 应塞进一份包级 YAML”**。

## 先对齐各生态中的角色

这是理解目录先例的前提：

| Protein Workbench 角色 | 较接近的外部角色 | 不应误认为 |
|---|---|---|
| `ModulePackage` | Python distribution、Airflow Provider、Galaxy Tool Shed repository | Nextflow/nf-core 的单个 module |
| `NodeDefinition` / Node Type | KFP ComponentSpec、CWL Process、Nextflow/nf-core module、Galaxy tool wrapper | Python distribution |
| Adapter / 实现 | KFP component implementation、CWL concrete Process、Galaxy command glue、Airflow Operator/Hook 实现 | 包发现入口本身 |

尤其是 Nextflow/nf-core：它们的“一 module 一目录”是“一可执行操作一目录”；
本项目已经接受的 `ModulePackage` 则可以包含多个 Node Type。若把两者仅因
都叫“module”而直接等同，会重新制造当前希望消除的“一节点一 Python 包”
目录膨胀。

## 横向对照

| 生态 | 发现/加载单位 | 包级 manifest | 操作定义与目录粒度 | 实现绑定 | 可选依赖与测试 |
|---|---|---|---|---|---|
| PyPA Entry Points | 已安装 distribution 中特定 group 的 entry points | `pyproject.toml`/distribution metadata 只登记 `name = module:object`；不描述插件内部所有操作 | 规范不规定插件内部文件或目录布局 | entry point 直接指向 Python module/object | 可选依赖使用 distribution extras；Entry Point 自带 extras 已不推荐；测试布局不属 Entry Point 规范 |
| pluggy / pytest | 一个 entry point 加载一个插件 namespace；namespace 可提供多个 hookimpl | 没有额外插件 manifest，复用 Python distribution metadata | 一个插件可实现一个或多个 hook；不要求每 hook 一个文件或目录 | `PluginManager.register()` 收集 namespace 上标记的函数 | pytest 提供 `pytester` 隔离运行插件测试；pluggy 做 hook 签名验证 |
| Apache Airflow Provider | 一个已安装 Provider distribution；重启后由 `apache_airflow_provider` entry point 发现 | 运行时入口返回经 schema 验证的 provider-info 字典；Apache 第一方 Provider 另维护包级 `provider.yaml` | 一个 Provider 包含许多 Operators/Hooks；一个 Python module 可包含多个 Operator；无 per-operator YAML 规则 | provider metadata 使用 module/class path；Operator 类实现 `execute()` 等契约 | Provider 声明依赖/extras；第一方包拥有 unit/system tests；不自动安装运行依赖 |
| Kubeflow Pipelines | 无启动插件扫描；component 由 Python import 或 file/URL/text 显式加载 | 没有统一 package manifest；可移植边界是 ComponentSpec/IR | YAML 形式通常一份 `component.yaml` 表示一个 component；也可由 `@dsl.component` Python 函数生成并编译，不能解释为“必须手写一节点一 YAML” | YAML 的 `implementation` 绑定 image/command/args；Python decorator 从函数生成 spec | 轻量 component 可声明 `packages_to_install`，但官方建议生产场景构建进容器；支持本地执行测试 |
| CWL 1.2 | CWL document/Process；Workflow 用 `run` 显式引用；规范还定义 XDG `commonwl/` 搜索位置 | 没有目录级 package manifest | Process 可各自成文档；`$graph` packed document 也允许一个文件装多个 Process | `Operation` 可表达抽象接口，`run`/concrete Process 明确绑定 CommandLineTool、Workflow 或 ExpressionTool | `requirements` 必须满足，`hints` 可不满足；官方有 validation 与 conformance suite |
| Nextflow 26.04 registry / nf-core | registry 中的 `namespace/name`，安装后显式 `include`；nf-core CLI 以 `tool[/subtool]` 安装 | `meta.yml` 是**操作级** spec；`.module-info`/`modules.json` 是安装来源与完整性追踪，不是另一个操作契约 | registry module 明确为一个目录、一个 `main.nf`、一个 process，并可带 resources/templates；nf-core 还带 environment 与 tests | `include` 显式绑定；`main.nf` 同时包含 process 及 container/conda 执行绑定 | 依赖紧邻 module；nf-core 每个 module 有 nf-test 与 snapshot，并运行 lint |
| Galaxy Tool wrapper / Tool Shed | 本地由 tool config 显式列出 wrapper；Tool Shed 以 repository 安装 | 单个 tool XML 是操作契约；Tool Shed repository 可有包级 `.shed.yml` 并包含多个 wrappers | 通常一个 tool wrapper XML 表示一个工具操作；有专属脚本、宏和测试数据时共同放在 repository 中 | XML `command` 把 UI/input 值转换成具体命令；`requirements` 声明依赖 | wrapper 可内嵌 functional tests；Planemo 可在隔离 Galaxy 实例中测试；依赖由 resolver 处理 |

## 各生态的直接证据

### 1. PyPA Entry Points

[PyPA Entry Points 规范](https://packaging.python.org/en/latest/specifications/entry-points/#data-model)
把 entry point 定义为 `group`、`name` 和 Python object reference。object
reference 可以是 `importable.module` 或 `importable.module:object.attr`。
消费者按 group 枚举当前环境中已安装 distribution 提供的入口，再选择并加载
对象。

[PyPA 的插件发现指南](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/#using-package-metadata)
给出的 package-metadata 方案也是让一个 distribution 在
`[project.entry-points.<group>]` 中宣布插件对象；它没有规定该对象内部必须
有几个操作，也没有规定源码目录布局。

[pyproject.toml 规范](https://packaging.python.org/en/latest/specifications/pyproject-toml/#entry-points)
说明 entry-point table 是名称到 object reference 的映射，不是插件内部所有
能力的第二份 schema。

可选依赖方面：

- `[project.optional-dependencies]` 是 distribution 的标准可选依赖声明位置；
- [Entry Points 规范](https://packaging.python.org/en/latest/specifications/entry-points/#data-model)
  明确表示在单个 entry point 上附加 extras 已不再推荐。

**边界：** PyPA 标准化的是发现和加载，不是工作流节点契约。因此它支持
“一个包级入口”，但不能单独为“一 Node 一 YAML”背书。

### 2. pluggy 与 pytest

[pluggy 官方文档](https://pluggy.readthedocs.io/en/stable/)
把插件注册单位定义为 module/class/instance 等 plugin namespace；
`PluginManager.register()` 从同一个 namespace 收集多个 hook
implementation。插件也可以通过 setuptools/PyPA entry point 自动加载。

[pytest 插件文档](https://docs.pytest.org/en/latest/how-to/writing_plugins.html#making-your-plugin-installable-by-others)
使用 `pytest11` entry point 指向插件 module，并明确一个插件可以含一个或多个
hook function。这说明成熟 Python 插件体系不会把“每个扩展点实现”强制映射为
独立 distribution、目录或 manifest。

测试方面，pytest 的
[`pytester`](https://docs.pytest.org/en/latest/how-to/writing_plugins.html#testing-plugins)
会创建隔离配置和临时测试文件、运行一个真实 pytest 进程并断言结果。这是统一
插件测试工具优于每个插件重复搭建测试脚手架的第一方先例。

pluggy 也暴露一个与本项目不同的重要边界：其 entry-point loader 直接
`load()` 并注册插件，缺少依赖导致的 import error 并不会自动变成
“已发现但 unavailable”。本项目已接受的结构化 `unavailable` 必须由自己的
ModulePackage loader/availability contract 实现，不能照搬 pluggy 的错误
语义。

### 3. Apache Airflow Provider Packages

[Airflow 自定义 Provider 官方文档](https://airflow.apache.org/docs/apache-airflow-providers/howto/create-custom-providers.html)
要求 Provider distribution 声明 `apache_airflow_provider` entry point，
指向一个返回 provider metadata 字典的 callable。安装并重启后，Airflow
按包发现其能力；它不递归扫描每个 Operator 文件。

Apache 第一方 Provider 的源码展示了运行时与源码 manifest 的区别：

- Amazon Provider 有包级
  [`provider.yaml`](https://github.com/apache/airflow/blob/eeeb6f02a88791f3c1f9b14c92e3b0b70c5d38a0/providers/amazon/provider.yaml)；
- 其
  [`pyproject.toml`](https://github.com/apache/airflow/blob/eeeb6f02a88791f3c1f9b14c92e3b0b70c5d38a0/providers/amazon/pyproject.toml#L258-L259)
  仍通过 entry point 指向
  [`get_provider_info()`](https://github.com/apache/airflow/blob/eeeb6f02a88791f3c1f9b14c92e3b0b70c5d38a0/providers/amazon/src/airflow/providers/amazon/get_provider_info.py)；
- 第三方 Provider 的正式运行时要求是 entry point 返回符合
  `provider_info.schema.json` 的字典，并不要求复制 Apache monorepo 的物理
  `provider.yaml`。

Provider metadata 可以列出 Operators、Hooks 等 Python module/class path，
但并非每个 Operator 一份 YAML。第一方
[`bedrock.py`](https://github.com/apache/airflow/blob/eeeb6f02a88791f3c1f9b14c92e3b0b70c5d38a0/providers/amazon/src/airflow/providers/amazon/aws/operators/bedrock.py)
就在一个实现文件中定义多个 Operator。Airflow 的
[Custom Operator 文档](https://airflow.apache.org/docs/apache-airflow/stable/howto/custom-operator.html)
规定类契约，而不规定一类一目录。

Provider 自己拥有
[`tests/unit`](https://github.com/apache/airflow/tree/eeeb6f02a88791f3c1f9b14c92e3b0b70c5d38a0/providers/amazon/tests/unit)
和
[`tests/system`](https://github.com/apache/airflow/tree/eeeb6f02a88791f3c1f9b14c92e3b0b70c5d38a0/providers/amazon/tests/system)；
依赖和 optional extras 属于 Provider distribution，而不是由 core 在发现时
自动安装。

**对本项目最接近的先例：** 一个内聚包通过一个显式入口被发现，同时交付多个
节点类型；节点实现文件不与节点数量一一对应。

### 4. Kubeflow Pipelines Components

[KFP Component 概览](https://www.kubeflow.org/docs/components/pipelines/concepts/component/)
给出两种主要 authoring 方式：

1. 用 `@dsl.component` 包装 Python 函数；
2. 用包含 metadata、I/O interface 和 implementation 的独立 YAML
   ComponentSpec。

[Component Specification](https://www.kubeflow.org/docs/components/pipelines/reference/component-spec/)
确实以一个 `component.yaml` 展示一个 component 的可移植契约；其
`implementation.container` 直接声明 image、command、args 和 I/O
placeholders。

但这不意味着 KFP 规定开发仓库必须“一个组件目录加一份手写 YAML”：

- [加载与共享文档](https://www.kubeflow.org/docs/components/pipelines/user-guides/components/load-and-share-components/)
  支持从 file、URL 或 text 显式加载，也说明组件库可以把多个组件发布为
  pip-installable Python package；
- [编译文档](https://www.kubeflow.org/docs/components/pipelines/user-guides/core-functions/compile-a-pipeline/)
  允许把 Python component 编译成 IR YAML；IR 也可以封装组件图或整个
  Pipeline。

因此 KFP 支持“一种操作一个独立可验证 ComponentSpec”，但不支持把它误写成
“每个节点必须有人工维护的独立目录和 Python 文件”。

依赖方面，
[Lightweight Python Components](https://www.kubeflow.org/docs/components/pipelines/user-guides/components/lightweight-python-components/#packages-to-install)
允许 `packages_to_install`，同时官方建议生产环境优先把依赖构建进
containerized component，而不是在每次执行时安装。KFP 还提供
[本地 component/pipeline 执行](https://www.kubeflow.org/docs/components/pipelines/user-guides/core-functions/execute-kfp-pipelines-locally/)
作为开发测试回路。

### 5. Common Workflow Language 1.2

CWL 是最接近“抽象科学操作与具体执行分离”的规范先例：

- [`Operation`](https://www.commonwl.org/v1.2/Workflow.html#Operation)
  可以只描述尚未绑定具体实现的输入/输出操作；
- Workflow step 的
  [`run`](https://www.commonwl.org/v1.2/Workflow.html#WorkflowStep)
  显式引用具体 `CommandLineTool`、`Workflow`、`ExpressionTool` 或兼容
  Process；
- `CommandLineTool` 用 command/input/output binding 与
  `DockerRequirement`/`SoftwareRequirement` 描述执行环境。

CWL 的文件粒度也不是唯一的：

- Workflow 可以用相对路径或 IRI 引用外部 Process；
- [packed document](https://www.commonwl.org/v1.2/CommandLineTool.html#packed-documents)
  可以通过 embedding 或 `$graph` 在一份文档中携带多个 Process；
- 规范定义
  [XDG `commonwl/` 目录中的文档发现](https://www.commonwl.org/v1.2/CommandLineTool.html#discovering-cwl-documents-on-a-local-filesystem)，
  但没有规定目录级 package manifest。

依赖语义中，
[`requirements` 与 `hints`](https://www.commonwl.org/v1.2/CommandLineTool.html#requirements-and-hints)
分别表示必须满足与可选能力；这仍不等同于本项目的 Registry
`unavailable` 状态。

CWL 官方规范仓库维护
[conformance tests](https://www.commonwl.org/v1.2/#running-the-cwl-conformance-tests)，
说明可移植契约应配套统一 validator 和跨实现测试，而不只测试某个具体工具。

### 6. Nextflow 26.04 Registry 与 nf-core Modules

Nextflow 26.04 新增的正式 module registry 是本次调研中最明确的
“一操作一目录”先例。

[Nextflow Modules 概览](https://docs.seqera.io/nextflow/modules/)
把 registry module 定义为自包含 process 加对应 spec。
[开发规范](https://docs.seqera.io/nextflow/modules/developing-modules#module-structure)
要求标准目录含：

```text
<namespace>/<module>/
├── main.nf
├── meta.yml
├── README.md
├── resources/    # optional
└── templates/    # optional
```

对 registry module，`main.nf` 必须只定义一个 process，不能定义 named
workflow；`meta.yml` 描述名称、版本、作者及 I/O。安装后 `.module-info`
记录 checksum 和 registry URL。
[使用文档](https://docs.seqera.io/nextflow/modules/using-modules)
要求通过 registry name 或相对路径显式 `include`。

值得注意的是，同一官方文档允许未发布的 local script 包含任意数量的
process、workflow 和 function，只将“一定义一 script”列为 best practice。
因此，即使在 Nextflow 内部，严格目录规则也服务于“可独立发布、安装、运行的
单操作 artifact”，不是所有内部复用代码的普遍规则。

nf-core 在此基础上形成更严格的生物信息学社区规范：

- [模块粒度规范](https://nf-co.re/docs/specifications/components/modules/general#4-module-granularity)
  通常以一个有独立功能的 command/subcommand 为 module；
- [`main.nf` 与 `meta.yml` 必须配对](https://nf-co.re/docs/specifications/components/modules/documentation)；
- 第一方
  [FastQC module 目录](https://github.com/nf-core/modules/tree/master/modules/nf-core/fastqc)
  同时包含 `environment.yml`、`main.nf`、`meta.yml` 和 `tests/`；
- [`nf-core modules test`](https://nf-co.re/docs/nf-core-tools/cli/modules/test)
  要求每个 module 用最小数据做 nf-test，并重复运行检查 snapshot 稳定性。

**边界：** Nextflow/nf-core 的 module 在角色上对应本项目的 Node Type。
它证明节点有大量专属执行资产时独立目录很合理，却不能推出本项目的
ModulePackage 也应退化为“一包一节点”。

### 7. Galaxy Tool XML 与 Tool Shed

Galaxy 提供了另一个很接近生物信息学 Workbench 的先例。
[Galaxy Tool XML schema](https://docs.galaxyproject.org/en/latest/dev/schema.html)
说明一个 tool wrapper 同时描述：

- 用户界面与输入参数；
- 输出；
- Galaxy 调用程序的 command glue；
- requirements、help、citations；
- functional tests。

这通常形成“一工具操作一 wrapper XML”的独立契约。wrapper 可以调用同目录
脚本，并引用测试数据或共享 macros。

另一方面，安装与聚合单位可以更粗：

- [Tool Panel 管理文档](https://docs.galaxyproject.org/en/latest/admin/tool_panel.html)
  说明本地和 Tool Shed tools 由 tool configuration 显式列出，不依赖任意
  wrapper 的递归导入；
- Galaxy 官方培训资料说明
  [一个 Tool Shed repository 可包含一个或多个 wrapper](https://training.galaxyproject.org/training-material/topics/admin/tutorials/tool-management/slides-plain.html)，
  repository 的 `.shed.yml` 保存包级发布 metadata；
- [Planemo test](https://planemo.readthedocs.io/en/stable/commands/test.html)
  可以对指定 wrapper 或目录中的 wrappers 启动隔离 Galaxy 实例并运行测试。

Galaxy 因而明确展示了“包级 repository 聚合多个操作、每个操作有独立声明、
实现资产按需要相邻放置”的组合，而不是在二者之间二选一。

## 对 Protein Workbench v2 的设计含义

以下是调研支持的**建议**，不是已接受决定。

### 建议 1：保持 Module Package 为唯一发现单位

继续采用一个一级目录代表一个 `ModulePackage`，只暴露一个轻量、显式的
`ModulePackage` 注册对象。它负责列出：

- Node Definitions；
- Python factory/implementation/Adapters；
- Metric Definitions；
- availability probes。

启动时不递归寻找任意 YAML，也不依赖 import side effect。未来 Python entry
point 只需返回同一种对象。

这是 PyPA、pytest 和 Airflow 的共同模式，也符合已经确定的“新增节点不修改
core、启动时发现、未来可接 entry points”边界。

### 建议 2：每个 Node Type 一份 YAML，但把它限定为契约粒度

推荐每个 Node Type 有一份独立 YAML，以获得独立 ID/version、schema
validation、diff、错误定位和契约测试；不推荐把整个 ModulePackage 的全部
Node 塞进一份大型 YAML。

必须同时写清楚：

- 一份 Node YAML **不要求**一个对应的 Python package；
- 一份 Node YAML **不要求**一个对应的 `module.py`；
- 多个 Node 可以共享一个 Adapter、实现文件和测试 fixture；
- “每 Node 一份 YAML”是项目基于多生态共同分层做出的政策选择，不是 PyPA、
  KFP、CWL 等共同规定的物理文件标准。

### 建议 3：默认平铺 Definition，专属资产使用显式资源目录

建议默认目录为：

```text
modules/
└── <module_package>/
    ├── package.py
    ├── definitions/
    │   ├── <node-a>.yaml
    │   └── <node-b>.yaml
    ├── adapters/
    ├── implementations/
    ├── resources/
    │   └── <node-id>/          # optional
    └── tests/
```

`definitions/` 默认平铺，使 Node Definition 容易枚举和审阅。只有节点确实有
专属模板、脚本、golden files 或大型 fixtures 时，才创建
`resources/<node-id>/` 或相应测试子目录；不要为每个简单节点预先生成空目录、
`__init__.py` 和 `module.py`。

这吸收了：

- KFP/CWL/Galaxy 的“操作契约独立”；
- Airflow/pluggy 的“实现可按内聚性聚合”；
- Nextflow/nf-core 的“专属执行资产靠近操作边界”。

### 建议 4：不新增重复的 `package.yaml`

当前 v2 只要求仓库内维护者扩展，不需要第三方安装市场或 import-free catalog。
因此建议暂不新增会复制 Node 端口、参数或 Metric 信息的 `package.yaml`。

包级信息由 import-safe 的 `package.py:PACKAGE` 聚合；Node 的公共合同仍只存在
于各自 YAML。若未来确实需要“不导入 Python 就浏览第三方包”，可在不改变
`ModulePackage` 契约的前提下增加 entry-point metadata 或生成式 catalog。

Airflow 的经验尤其说明：源码中存在包级 YAML 不代表运行时必须维护两份相同
合同；关键是只有一个受 schema 约束的正式入口。

### 建议 5：绑定必须显式，且包入口必须轻量

`PACKAGE` 应显式把 Node ID/Definition 绑定到 factory 或 Adapter，而不是：

- 根据同名 Python 文件猜测；
- 导入整个子目录触发 `register()`；
- 递归扫描后自动配对 YAML 与类。

模型框架、GPU runtime、SDK 和模型权重不得在导入 `package.py` 时成为硬前提。
重型/可选依赖在 availability probe 或 Adapter 执行边界延迟检查。

外部生态通常会让缺依赖直接安装失败或 import 失败；本项目已经接受
“Node 被发现但结构化 unavailable”，因此需要自己的显式错误转换和测试，
不能声称这是 pluggy、KFP 或 CWL 已提供的标准行为。

### 建议 6：统一测试工具按 Definition 参数化，而非复制脚手架

统一测试工具应：

1. 在隔离 Registry 中加载一个 `ModulePackage`；
2. 遍历其显式列出的全部 Definitions；
3. 验证 YAML schema、唯一 ID、ports/types、MetricDefinition 和绑定完整性；
4. 验证重复 ID/冲突时包级注册原子失败；
5. 验证缺少可选 runtime 时返回结构化 `unavailable`；
6. 对可执行 Node 运行统一的最小输入/输出契约；
7. 允许 Adapter 另有单元测试和少量真实运行/系统测试。

这综合了 pytest `pytester`、CWL conformance suite、nf-core module tests、
KFP local execution 与 Galaxy Planemo 的共同方向。

## 对当前待决问题的修正版建议

原问题是是否接受：

> 每个 Node Type 一份 YAML，但不再为每个节点建立独立目录。

基于以上先例，建议改成更精确的版本：

> 每个 Node Type 维护一份独立 YAML Definition，默认平铺于
> `ModulePackage/definitions/`；Node Definition、Python 实现与目录不做
> 一一对应。多个 Node 可以共享实现、Adapter 和测试设施。只有节点拥有确实
> 专属的模板、脚本、资源或大型 fixtures 时，才创建按 Node ID 命名的资源/
> 测试子目录。ModulePackage 仍是唯一启动发现和原子注册单位。

推荐接受这个**带默认规则和明确例外**的版本，而不是绝对禁止节点专属目录。

## 仍需后续决定

本调研没有替项目决定以下实现细节：

- `package.py`、`PACKAGE` 是否是最终文件名/符号名；
- `PACKAGE` 是逐项显式列出 Definition path，还是调用只扫描一层
  `definitions/*.yaml` 的受控 helper；
- Node-specific resources 的路径命名规则；
- 测试工具要求每个 Node 都有真实 smoke fixture，还是允许仅做契约验证；
- package-level availability 与 adapter-level availability 的合并规则。

这些应在接受文件粒度原则后逐项讨论，不应从任一外部生态的目录名称机械推导。
