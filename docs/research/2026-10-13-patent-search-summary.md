# 可扩展蛋白质设计软件：整体平台专利初步检索

项目要求以[当前有效决策](../documentation-governance-decisions.md)为准；项目实现边界见[技术事实](2026-10-13-patent-project-evidence.md)。文中外部文献事实限定于所列检索日期，文档治理未重新核查法律状态或网页变化。

- 检索日期：2026-10-13（Asia/Taipei）。
- 申请方向：中国大陆发明专利。
- 研究对象：一个允许用户自定义模块和节点，通过连接节点构建、执行自己的蛋白质设计 Workflow 的蛋白质设计软件。
- 模块开发者按接入规范实现模块；项目用户选择插件包安装并启用。该要求不等于网页填写任意 API 后即时生成节点。
- 整体发明对象：模块与节点扩展、注册接入、节点库、用户图编辑、Workflow 编译与执行共同组成的软件平台。ESM、SimpleFold 和具体数据处理机制用于说明实施，不单独替换整体发明对象。
- 本研究产物：公开文献检索、项目技术依据及技术交底主线；尚非正式申请文件、授权意见或实施自由分析。

## 1. 初步结论

专利书以**可扩展的蛋白质设计软件整体**为主线：用户能扩展框架支持的模块和节点，再根据自己的设计目标组成可执行 Workflow。需要一起描述扩展接口、模块接入、节点定义、可视化图编辑、执行框架及研究输出之间的关系。ESM、SimpleFold 是完整软件的实施例，不宜把第三方模型能力写成框架自身的发明。

这两项宽泛能力已有明确先例：KNIME 早期论文直接描述自定义节点插件及类型兼容的端口连接；BioCatalogue 和 Taverna 分别提供服务注册与研究 Workflow 组合执行。国内专利也已描述科学软件组件化和可视 Workflow，以及蛋白质计算应用的微服务集成。因此，目前不能仅凭“可扩展模块＋节点连线＋蛋白质用途”断言新颖性或创造性。需要逐项比较框架如何声明模块的科学合同、判断连接关系、编译并执行异构计算，以及保持输出的科学主体和测量含义。[KNIME 原论文](https://www.kdd.org/exploration_files/p4V11n1.pdf)、[BioCatalogue 原论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC2896129/)、[Taverna 原论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC3692062/)、[CN114464269A](https://patents.google.com/patent/CN114464269A/zh)、[CN120072027A](https://patents.google.com/patent/CN120072027A/zh)。

另一个独立问题是本项目自己的公开披露。2026-10-13 检索确认本地基线与当日获取的公开 main 的 Git tree 相同；这些现有实现已经能够从公开仓库获取。此前是否已有专利申请、首次公开时序以及具体公开内容，仍须核实。对同一已公开技术方案仅改写名称、补充用途标签或换一种描述，不能使其重新成为未公开技术。[项目仓库](https://github.com/natsusorahoshinochan-max/modules-ESM)、[专利法第22、24条](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html)。

### 整体软件的相近公开

检索覆盖整体扩展和执行链的公开，重点包括：

- [US20040056908A1，TurboWorx](https://patents.google.com/patent/US20040056908A1/en)：2004-03-25 公开。同一篇描述用户编写组件、组件库、端口连图、自动执行及用户自编组件参与的蛋白质序列分类实例；该实例属于蛋白分析，不能直接称为新蛋白设计。
- [CN119631133A，Bruker 空间生物学平台](https://patents.google.com/patent/CN119631133A/zh)：2025-03-14 公开。同一篇描述用户创建分析模块、模块库、拖拽连接及串并行执行；其具体用途是空间生物图像和组学分析。
- [US20150066383A1，Seven Bridges](https://patents.google.com/patent/US20150066383A1/en)：2015-03-05 公开。工具开发接入、节点连线和执行，以及将 Workflow 包装成可再用的新工具；具体用途是基因组分析。

与深化核读的 LION、Calici、CN114464269 一起，这些文献应作为整体软件的直接比较对象。是否公开了“用户扩展＋可视编排＋执行＋特定蛋白设计用途”的全部组合，应按同一篇文件核对，不能把多篇中的相似表述直接拼成完全相同结论。[继续检索的专利逐项对照](2026-10-13-patent-similar-software-followup.md)记录原文定位、五项能力及用途差别。

## 2. 当前项目能够支持的准确表述

项目要求以[当前有效决策](../documentation-governance-decisions.md)为准，术语见 [CONTEXT.md](../../CONTEXT.md)；实现文件仅用于确认机制和能力边界。

| 环节 | 当前机制 | 撰写时的准确表述 |
| --- | --- | --- |
| 模块接入 | Module Package 提交 `ModulePackageRegistration`，声明 Node Types、Methods、Execution Bindings、Port Type Definitions 等；现有 composition root 显式导入并列出注册对象 | 模块开发者按现有合同封装模块，当前由应用装配代码显式接入；用户插件安装要求尚待实现 |
| 服务调用 | Binding 关联科学操作、Method 与直接实现或 Adapter；Adapter 翻译具体模型、远程服务或本地运行时的输入输出 | 模块可以接入计算工具或服务；服务地址并不单独决定科学语义 |
| 自定义及可连接节点 | 自定义模块提供 Node Definition，声明输入、输出和参数；Node Instance 选择一个 Binding；Port 使用名义科学类型 | 模块开发者定义节点类型；项目用户创建节点实例、选择 Binding、设置参数并连接兼容 Ports |
| 执行准备 | 启动构造 FrozenCatalog；Workflow 编译为已解析 Execution Plan，固定合同、实现、参数及科学关系 | 用户编辑的图经过准入和编译后执行，不把任意图直接当可执行研究流程 |
| 科学输出 | Candidate、残基轴、Score Observation 和证据有各自的身份、关联及语义合同 | 跨模块数据不是无标签数组或仅按文件名、集合位置拼接的结果 |

实现依据：[bootstrap.py](../../protein_workbench_public/bootstrap.py)、[注册声明](../../core/catalog/declarations.py)、[Catalog builder](../../core/catalog/builder.py)、[Workflow compiler](../../core/workflow/compiler.py)、[ESM3 注册](../../modules/esm3/package.py)、[folding 注册](../../modules/folding/package.py)。实现位置、要求与差异见[项目技术证据](2026-10-13-patent-project-evidence.md)。

当前生产入口使用显式注册对象列表，公开 Catalog 接口提供读取能力。用户选择插件包安装启用、官方与外部模块完整接入及应用内模块设置是已确认要求；当前固定装配不能证明这些能力已经完成。技术交底须分别说明现有实现与目标要求，不能虚构安装、网页注册或热更新已经实现。

## 3. 与主构思最相关的公开文献

日期用于区分优先权、申请与公开；不能用较早优先权日期代替公众可获取日期。专利的有效状态和中国权利范围仍需官方案卷核验。同族不重复算作独立发明。

| 文献或专利族 | 日期 | 与本项目重叠的公开内容 | 本研究比较边界 |
| --- | --- | --- | --- |
| [KNIME 原论文](https://www.kdd.org/exploration_files/p4V11n1.pdf)，KNIME – The Konstanz Information Miner: Version 2.0 and Beyond | 2009 | §3.4 自定义节点 API、插件及外部工具包装；§5.2 开发者定义端口类型及不兼容端口不能连接 | 对用户封装模块和连接节点尤其直接；通用插件或类型检查本身不应直接当作区别特征 |
| [Galaxy ToolShed 原论文](https://doi.org/10.1186/gb4161) | 2014-02-20 | 自定义工具及描述、依赖和测试通过仓库安装到 Galaxy | 体现开发者式工具扩展；需区分工具安装与本项目的具体科学合同 |
| [WO2002046915A2](https://patents.google.com/patent/WO2002046915A2/en)，Workflow system | 最早列明优先权 2000-11-13；公开 2002-06-13 | 生物工具封装为独立活动，明确定义数据类型，图形编辑器组合活动；包括用户编程活动 | 是模块式生物计算与自主编排的重要早期专利；需核读具体权利要求与实施方式，不能只按标题比较 |
| [BioMOBY 原论文](https://academic.oup.com/bib/article/3/4/331/196070) | 2002-12-01 发表 | 分散的生物数据与服务在中心注册，结合对象及服务语义发现可用操作 | 已有生物服务注册思想；不能把后来的全部功能归于最早论文 |
| [Taverna 2006](https://pmc.ncbi.nlm.nih.gov/articles/PMC1538887/) / [2013](https://pmc.ncbi.nlm.nih.gov/articles/PMC3692062/) | 2006 / 2013 | 用户组合生物信息计算服务；后续套件组合本地工具与远程服务，并提供 Workflow 设计和执行 | 是用户自主研究编排的重要先例；需比较具体合同和数据关联机制 |
| [BioCatalogue](https://pmc.ncbi.nlm.nih.gov/articles/PMC2896129/) | 在线发表 2010-05-19 | 社区注册、浏览及标注生命科学服务，包括蛋白序列和结构相关服务；向 Taverna 等提供检索接口 | 正文的未来 write API 不能当作当时已完整实现的写入接口 |
| [CN114464269A/B](https://patents.google.com/patent/CN114464269A/zh)，一种虚拟药物生成方法、装置及计算机设备 | 申请 2022-04-07；A 公开 2022-05-10 | 软件池、统一输入输出组件、计算资源调用及可视组件形成 Workflow；权利要求1、2、4、7相关 | 与“工具封装＋用户构造研究图”接近；不据此认定其公开了本项目的全部科学合同 |
| [CN120072027A](https://patents.google.com/patent/CN120072027A/zh)，一种基于云计算平台的蛋白质辅助设计和分析系统及方法 | 申请 2023-11-29；公开 2025-05-30 | 蛋白质应用仓库、微服务集成和用户选择、配置、组合应用；权利要求1、4、9及实施方式相关 | 此文不能直接证明存在任意自定义模块注册和完整节点画布；独立权利要求还含云、存储加密及资源调度 |
| [WO2025023400A1](https://patents.google.com/patent/WO2025023400A1/en) / [CN119836663A](https://patents.google.com/patent/CN119836663A/zh) / HK40123392A，同族：用于挖掘新药候选物质的基于多实例 GPU 的系统 | 最早列明优先权 2023-07-26；已核读较早 [KR102708758B1](https://patents.google.com/patent/KR102708758B1/en) 公开 2024-09-24；WO 公开 2025-01-30；CN A 公开 2025-04-15 | 蛋白质数据和任务模块拖入画布、节点连线；[CN119836663B 的说明书](https://patents.google.com/patent/CN119836663B/en)描述外部功能形成额外节点及连接提示 | 非常贴近可扩展科学节点界面；独立权利要求包含 GPU 资源分配等限制，不能把说明书的某个功能直接等同完整保护范围 |

本表是检索入口，不是已经完成的新颖性或创造性对照结论。专利原文、权利要求定位、申请人、同族核验和其他候选见[Workflow 现有技术研究](2026-10-13-patent-workflow-prior-art.md)及[蛋白质现有技术研究](2026-10-13-patent-protein-prior-art.md)。

## 4. 整体平台的比较框架

以下按一个完整软件的技术过程组织，不能把其中某项单独当成本次要求申请的发明。专利比较需覆盖拟保护的整体组合、各环节关系及其共同效果，既看单篇文献的完整公开，也看既有方案的组合启示。

| 用户希望保护的能力 | 本项目可进一步描述的机制 | 需要回答的比较问题 |
| --- | --- | --- |
| 用户自定义模块和节点 | 扩展合同让用户封装工具、算法或服务，并定义节点的输入、输出、参数及执行实现 | 既有平台如何让外部开发者扩展操作？与本项目的完整接入方式有什么相同和不同？ |
| 模块接入并进入节点库 | 模块提交注册对象；应用装配后构建 FrozenCatalog，向编辑器提供可用的节点定义及能力 | 模块定义、注册准入、节点目录和编辑器之间如何协同，是否已有同样的组合？ |
| 用户构建自己的设计图 | 用户添加节点实例、选择 Binding、设置参数、连接 Ports，保存 Workflow Draft | 图编辑是否支持用户定义而非预设的设计步骤，连接判定怎样与模块声明保持一致？ |
| 编译与执行完整 Workflow | 对研究图准入、解析依赖和参数，形成执行计划；调度直接实现或经 Adapter 调用计算工具 | 新模块怎样使用既有执行框架，节点输出怎样进入后继节点，失败和结果怎样处理？ |
| 科学输出、保存和再次使用 | 输出遵守模块声明的科学合同；固定 Workflow 科学定义，保存 Candidate、观察及执行证据，并提供结果阅读和复用 | 整体平台怎样使用户设计图产生可解释的蛋白质结果；对应效果有何依据？ |

残基身份、评分语义及证据机制作为上述软件的实施细节和支持材料。后续说明书与权利要求应围绕这一个整体发明构思组织；不预先把它拆成模块注册、残基处理、评分或缓存等若干独立发明。

## 5. 可直接用于技术交底草稿的主线

### 5.1 暂定名称

**一种支持自定义模块与节点编排的蛋白质设计系统及方法**。

名称用于组织材料，不代表该宽度已经通过专利性审查。

### 5.2 技术问题

蛋白质设计目标及所需工具因用户而异。技术交底应描述一套可扩展的软件，怎样让用户把需要的能力定义为模块和节点、接入统一框架，并通过节点连接构建、保存、执行自己的设计 Workflow，得到可继续分析的研究输出。不同工具的数据和科学含义、用户编辑的图与执行实现之间的对应，是整体架构需要解决的技术问题。

### 5.3 候选处理步骤

1. 模块开发者按扩展合同封装自定义模块，并定义其提供的节点类型、输入输出、参数及执行实现；科学 Method、执行 Binding 和必要数据合同构成当前框架的具体注册内容。
2. 在应用启动装配中纳入模块注册对象，准入注册内容并构造不可变 Catalog；向节点库和编辑器提供对应节点定义及编辑能力。
3. 接收用户选取节点类型、创建 Node Instances、选定 Binding、设置参数及连接 Ports 的操作，形成和保存 Workflow Draft。
4. 对图及合同进行准入，编译生成完全解析的 Execution Plan；从同一 Plan 提取最小科学定义快照，持久发布不可变 Workflow Commit。执行查找按当前 FrozenCatalog 重编译和准入。
5. 按图的依赖关系执行节点，将输出传递至已声明的后继输入；直接 Binding 调用其实现，采用 Adapter 的 Binding 则由 Adapter 翻译工具输入、输出、错误及 provenance。
6. 按各名义 Port 合同发布设计和评价输出；Candidate-associated scientific values 用完整 Candidate Data Reference 关联主体，残基相关值保留精确布局或轴，Score Observation 固定 Metric、Method 和 Context。
7. 向用户提供 Workflow 的执行状态和研究结果，保存实际执行及输出发布事实，支持明确合同下的结果阅读和 Workflow 再次使用。

这是一项整体软件方案的技术交底结构，尚不是可直接提交的权利要求书。后续应分析这一完整组合与最接近现有技术的关系，选定能够表达整体发明构思的必要特征，并用从属权利要求和实施例展开具体实现。

### 5.4 最小实施例与附图材料

一个实施例描述现有 esm3 代码包的接入和序列生成；另一个描述 folding 模块中的 SimpleFold 执行路径。用户可将完整序列 Candidate 输入接到结构预测节点，再把对应结果与科学评价、选择节点相连。具体 Ports、Methods、Binding、随机性及 confidence 输出以注册合同和维护中的 Workflow 为准，不能因为界面上可连线而猜测语义。

可复用的项目材料：[模块注册合同](../../core/catalog/declarations.py)、[维护中的 Workflow 示例](../../examples/v2/README.md)、[canonical Workflow](../../examples/v2/canonical-3gb1.workflow.json)、[模块能力说明](../module-capabilities.md)。建议附图依次说明模块接入、节点图编辑、连接编译、异构调用及结果主体关联。

若主张自定义模块接入的完整实施方式，还需整理一个实际新增模块的完整例子：模块源码、注册对象、加入 composition root 的位置，以及用户如何把新节点连接到既有研究图。已有 ESM/SimpleFold 注册只能证明既有实现实例，不自动证明任意第三方模块都无须改动即可安装。

### 5.5 可写与尚不可写的效果

可以基于具体机制及现有证据描述：显式合同下的模块扩展、用户定义的研究图执行、科学对象精确关联及结果来源解释。若主张降低错误、减少开销或提高效率，需要对应的错误类别、基线和比较数据。

源码和示例可支持机制说明，但不能替代固定版本的真实运行材料或专利技术效果对比试验。没有相应数据时，不能声称提高蛋白质预测精度、实验成功率或性能百分比。

## 6. 本项目自己的公开证据

2026-10-13 通过 GitHub REST 和本地只读 Git 查询得到：

| 项目 | 本次观测 | 解释 |
| --- | --- | --- |
| 当前仓库可见性 | `private: false`、`visibility: public` | 当前源码为公开可获取；描述中含有 Private 字样不改变可见性 |
| GitHub 创建时间 | 2026-07-31 12:53:28，UTC+8 | 是当前仓库的创建时间，不能认定为首次技术公开时间 |
| 本地最早 root commit | `3d7688408af6f60a89d1963d18477a6fb2cea8f1`，2026-07-24 12:39:22，UTC+8 | 是 Git 历史时间，不证明当日已公开 |
| 本地检索基线 | `7577542009ad1f1b5ae0c2a7b9c69c6a881f9410` | 技术依据所对应的已跟踪源码快照 |
| 公开 main | `db0ae1354d0fd65b21b147ebe199d288124dae0a`，2026-10-13 16:28:25，UTC+8 | 2026-10-13 取得的公开 merge commit |
| 两个快照的 tree | 均为 `a62fd7f35fcffa5c94ae586498199841c405d29f` | 本地基线的已跟踪文件内容与公开 main 相同；不包含当时未跟踪的研究文件 |

来源：[仓库 REST 记录](https://api.github.com/repos/natsusorahoshinochan-max/modules-ESM)、[公开 main 提交](https://github.com/natsusorahoshinochan-max/modules-ESM/commit/db0ae1354d0fd65b21b147ebe199d288124dae0a)、[GitHub 可见性说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility)。

因此，不能把“最早公开日期未知”误当成“当前方案尚未公开”。如果在公开前没有相关申请，且公众能够从该源码和文档直接获得拟保护的完整技术方案，这会构成重要的新颖性障碍；具体结论仍取决于候选权利要求、公开内容及适用例外。中国第24条没有普通自行公开 GitHub 的一般六个月宽限期。[专利法](https://www.cnipa.gov.cn/art/2020/11/23/art_97_155167.html)。

## 7. 正式专利书前尚需补齐的事实

1. 是否在首次公开前已有相关申请；若有，整理申请日、优先权和原申请内容。
2. 仓库初建即公开，还是由私有转公开；最早能被公众获取的版本和日期。再核查演示、论文、其他仓库或产品发布。
3. 自定义模块注册、科学合同及连接执行机制中，各自然人的实际创造性贡献，以及申请权归属。
4. 与最接近专利和开源框架的逐特征对照：相同特征、真正的区别、区别解决的问题及证据。
5. 一套可实施的模块接入例子和研究 Workflow，以及必要的技术效果比较材料。

正式申请文件的组织和当前中国审查要求见[规则检索](2026-10-13-patent-cn-rules.md)。可先据本报告准备技术交底草稿；申请范围和提交判断需结合上述事实，不能以初检未发现某项特征作为授权保证。

## 8. 检索记录与覆盖限制

本研究从项目当前规格出发检索专利原文、论文原文、官方文档及官方法律。Google Patents 用于定位公开文件和阅读权利要求；其状态、申请人和同族元数据不等同官方案卷结论。可访问的官方同族公报用于补充核对。

主查询包括：

- `patent scientific workflow web services registration visual composition bioinformatics`
- `Taverna workflows bioinformatics web services service discovery`
- `BioMOBY biological web service registration datatype ontology`
- `BioCatalogue universal catalogue web services life sciences`
- `site:patents.google.com/patent 蛋白质 节点 工作流`
- `site:patents.google.com 生物信息 服务注册 工作流`
- `site:patents.google.com 蛋白质 可视化 流程 平台`
- `site:patents.google.com 生物信息 可视化 工作流`

其他检索词、模型专利和原论文记录见各分报告。部分 PMC 页面触发访问检查，本研究用其对应的 Europe PMC 官方全文接口核读 BioCatalogue 与 Taverna 2006：[BioCatalogue XML](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC2896129/fullTextXML)、[Taverna XML](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1538887/fullTextXML)。

本研究不是所有数据库的穷尽检索，未完成全部分类号、引用链、申请人组合及中国案卷法律状态检索，也不能检索尚未公开的申请。专利性研究与是否落入他人有效权利要求，是两个分别需要分析的问题。

