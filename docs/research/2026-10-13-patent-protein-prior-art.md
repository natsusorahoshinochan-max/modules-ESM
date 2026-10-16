# 蛋白质计算模块接入与可视 Workflow：专利和论文初步检索

项目要求以[当前有效决策](../documentation-governance-decisions.md)为准；项目实现边界见[技术事实](2026-10-13-patent-project-evidence.md)。文中外部文献事实限定于所列检索日期，文档治理未重新核查法律状态或网页变化。

检索日：2026-10-13。用途：中国大陆发明专利的技术交底准备。检索重心是**模块开发者封装计算能力，项目用户安装启用模块后连接节点，构建和执行蛋白质研究 Workflow 的整体软件**。这里的注册不是在网页填写任意 API 地址，也不预设热加载。上游蛋白质模型的专利与论文仅作为应用背景。

项目科学词义依据 [GLOSSARY.md](../../GLOSSARY.md) 与 [README.md](../../README.md)。Node Type、Module Package、Adapter、Execution Binding、Workflow 是不同对象；不能把调用某个模型、模型训练和扩展框架混成一项发明。本文不从代码推断科学语义，也不替代项目实现核查。

## 初步结论

“蛋白质/药物计算工具组件化＋统一输入输出＋可视方式编排计算流程”已有明确公开。尤其 **CN114464269A/B** 同时披露 AlphaFold 等软件池、组件封装、计算接口以及拖拽方块生成工作流。其范围、完整步骤与本项目仍需逐项比较，不能仅因本项目调用 ESM 或 SimpleFold 就认定新颖。[CN114464269A 原文](https://patents.google.com/patent/CN114464269A/zh)

更贴近用户扩展方式的现有产品资料包括 Salpa 的自定义 Python 节点包导入与注册，以及 VERA 的插件注册 API；ProtXplain 明确宣传将 AlphaFold、ProteinMPNN、ESM-2 和自定义工具连成节点流程。**这些现行网页的最早公开时间尚未取证**，因此先列为需追踪的技术对照，不能直接认定其早于项目公开或某个申请日。[Salpa 自定义节点文档](https://salpa.app/docs/custom-nodes)、[VERA 原始仓库](https://github.com/Arifmaulanaazis/vera/)、[ProtXplain 官网](https://www.protxplain.com/en/)

专利书仍可围绕用户指定的“模块接入与 Workflow”方向准备，但须写出模块接入的具体契约、注册时建立的关系、节点连接的判定与执行机制及其可验证技术效果，再与既有平台逐项比较。本文未完成这一组合的新颖性或创造性评价，亦不提供授权保证。

## 阅读与日期口径

- 下面六组专利候选按公开文本和同族关系归并，未把 A/B 两种文本计成两项发明。
- 已阅读下列指定权利要求和说明书定位，检索片段没有替代权利要求阅读。Google Patents 是专利原文的检索/全文镜像，不是法律状态登记机关。
- 优先权日与公众可得日分开列示。最早优先权日不能自动等同于公开日。是否构成中国申请的现有技术、抵触申请或其他法律障碍，仍须结合拟申请日、优先权链、具体公开内容和中国申请记录判断。
- 各组**当前有效性、权利人变更、缴费和中国国家阶段状态均标为未知**；“已发现 B 公报”仅说明找到授权公开文本，不确认今天仍有效。

## 六组专利候选

### P1．最接近本研究方向：组件化工具与可视科学流程

| 项目 | 已核信息 |
| --- | --- |
| 题名 | 一种虚拟药物生成方法、装置及计算机设备 |
| 同族/版本 | [CN114464269A](https://patents.google.com/patent/CN114464269A/zh)；[CN114464269B](https://patents.google.com/patent/CN114464269B/zh)，同一申请 CN202210359239.2 |
| 申请人 | 国家超级计算天津中心；已由 [A 公报首页](https://patentimages.storage.googleapis.com/42/c2/35/b9595531a751d8/CN114464269A.pdf) 核实 |
| 最早申请/优先权 | 2022-04-07 |
| 公开日 | A：2022-05-10；B：2022-07-08 |
| 当前法律状态 | 未核实 |

**定位与重叠。** A 权利要求 1–4 涉及按 Workflow 选取工具、组件化、输入输出封装及计算接口；权利要求 7 涉及可视组件生成流程。说明书 [0020]、[0022]、[0025]–[0026]、[0029] 包含 AlphaFold 软件池、接口及拖拽流程。这覆盖用户目标的多项一般构成。[A 公报全文](https://patentimages.storage.googleapis.com/42/c2/35/b9595531a751d8/CN114464269A.pdf)

**尚待比较。** 未在上述定位看到用户自编适配模块的注册协议，也未完成与 Workbench Node Definition/Execution Binding 分离机制的全要素比较。其云与超算融合等限定不能忽略。侵权范围须另外阅读当前有效权利要求，不能直接以 A 文本判断。

### P2．多轨蛋白质模型本身

| 项目 | 已核信息 |
| --- | --- |
| 题名 | Biological language reasoning |
| 同族候选 | [US20250378914A1](https://patents.google.com/patent/US20250378914A1/en)；[WO2025254811A1](https://patents.google.com/patent/WO2025254811A1/en)；WO 文本还列出 US18/734,907 优先权，相关 US 文本未逐项核读 |
| 公开申请人 | EvolutionaryScale, PBC，按 US/WO 公开书目记载；现权利人未知 |
| 最早优先权 | 2024-06-05 |
| 已核公开日 | US 与 WO：2025-12-11 |
| 当前法律状态/中国成员 | 未核实 |

**定位与重叠。** US 权利要求 1 涉及序列/局部结构 token、几何损失训练、掩码多轨训练及生成新蛋白质；说明书图 1–5、图 10–11 的相关描述披露序列、结构、功能、二级结构、SASA 条件与可视提示界面。因此多轨条件生成属于重要上游公开背景。[US 原文](https://patents.google.com/patent/US20250378914A1/en)

**本研究意义。** 该文献重点是模型和生成，不能当成“用户注册自定义计算模块”的完整公开，也不能把 ESM3 自身算法写成项目原创。

### P3．跨轨反复预测与优化

| 项目 | 已核信息 |
| --- | --- |
| 题名 | Protein refinement and joint optimization |
| 同族候选 | [US20250378901A1](https://patents.google.com/patent/US20250378901A1/en)；[WO2025255489A1](https://patents.google.com/patent/WO2025255489A1/en) |
| 申请人记载 | WO 公开书目为 EvolutionaryScale, PBC；US 网页 Original Assignee 为 Chan Zuckerberg Initiative LLC、Current Assignee 为 Biohub，存在成员/时点差异；未核官方转让链 |
| 最早优先权 | 2024-06-07；说明书还声明 2024-06-20 的另一临时申请 |
| 已核公开日 | US 与 WO：2025-12-11 |
| 当前法律状态/中国成员 | 未核实 |

**定位与重叠。** US 权利要求 1–10 披露在多个蛋白质轨道间交替设定条件与预测，可包含序列、结构、功能、二级结构、SASA 及评价指标。它直接相关于设计—折叠—评价的反复组合。[US 权利要求](https://patents.google.com/patent/US20250378901A1/en)

**尚待比较。** 未在上述权利要求中看到用户适配模块安装/注册与可自由连接框架的完整机制；模型交替推理不等同于通用模块接入。[WO 书目与原文](https://patents.google.com/patent/WO2025255489A1/en)

### P4．候选生成、评价、选择与反馈

| 项目 | 已核信息 |
| --- | --- |
| 题名 | Protein binder search |
| 同族/相关继续申请 | [US12367329B1](https://patents.google.com/patent/US12367329B1/en)；[US20260161853A1](https://patents.google.com/patent/US20260161853A1/en) 是网页所列继续申请候选，后者未逐项核读 |
| 原始申请人 | EvolutionaryScale, PBC；现权利人未知 |
| 最早优先权 | 2024-06-06 |
| 本研究已核最早公开 | B1：2025-07-22；尚未穷尽其他地区更早公开 |
| 当前法律状态/中国成员 | 未核实 |

**定位与重叠。** B1 权利要求 1 为靶蛋白/结合位点条件下的候选预测、结合质量评价、选择与反馈；权利要求 2–9涉及序列或结构 token、位置选择和原子距离评价。说明书图 25–31 涉及搜索、候选评价与迭代。[B1 原文](https://patents.google.com/patent/US12367329B1/en)

**本研究意义。** 这是蛋白质研究操作组合的背景；未在所读权利要求中见用户安装适配模块注册平台的完整步骤。

### P5．RFdiffusion 与结构—序列设计组合

| 项目 | 已核信息 |
| --- | --- |
| 题名 | Generative protein design via noise diffusion |
| 同族/版本 | [WO2024158466A2](https://patents.google.com/patent/WO2024158466A2/en)；WO2024158466A3 为同一 PCT 的后续公开版本，不算第二组 |
| 申请人 | University of Washington，按公开书目记载 |
| 最早优先权 | 2022-11-30；PCT 申请日 2023-11-29 |
| 已核公开日 | A2：2024-08-02；A3：2024-10-17 |
| 当前法律状态/国家阶段成员 | 未核实；不把 Google 的“Ceased”解释为各国权利均消失 |

**定位与重叠。** 权利要求 1 为结构加噪训练；权利要求 9 起涉及迭代结构生成；权利要求 18–26 涉及 motif、靶蛋白条件及第二模型设计序列。说明书 [0088] 明确将 ProteinMPNN 与 AF2 评价/选择组合。[WO 原文](https://patents.google.com/patent/WO2024158466A2/en)

**本研究意义。** 直接说明把结构生成、序列设计、结构预测和筛选串联已有技术背景；它不披露本项目模块注册框架的全部实现。

### P6．中国多属性打分与蛋白质设计筛选

| 项目 | 已核信息 |
| --- | --- |
| 题名 | 一种多模态蛋白质设计方法、装置、系统及其存储介质 |
| 同族/版本 | [CN119943206A](https://patents.google.com/patent/CN119943206A/zh)；[CN119943206B](https://patents.google.com/patent/CN119943206B/zh)，同一申请 CN202510413097.7 |
| 申请人 | Google 原文书目：Baitu Shengke Beijing Intelligent Technology Co ltd；中文正式名称未由公报首页进一步核实 |
| 最早申请/优先权 | 2025-04-03 |
| 公开日 | A：2025-05-06；B：2025-07-22 |
| 当前法律状态 | 未核实 |

**定位与重叠。** A 权利要求 1、4–7 涉及候选区域、突变库、多属性评分、多目标优化与筛选。B 权利要求 1 还整合实验数据训练及迭代更新；A 与 B 限定不同，不能混读。[A 权利要求](https://patents.google.com/patent/CN119943206A/zh)、[B 权利要求](https://patents.google.com/patent/CN119943206B/zh)

**本研究意义。** 属于蛋白质设计—评价—筛选公开背景；未在所读权利要求中见用户适配模块注册和节点连接平台的完整机制。

## 更贴近“用户模块注册＋节点连接”的技术对照

这些来源是产品/作者原始资料，功能是资料所述，未运行产品。所标日期只表示能证明的公开日期；当前页面内容不能倒推到其项目创建日。

| 原始来源 | 与用户目标相关的明确资料 | 日期证据与限制 |
| --- | --- | --- |
| [Salpa 首页](https://salpa.app/)、[Build Custom Nodes](https://salpa.app/docs/custom-nodes) | 科学计算画布连接节点，支持本地/集群和云节点；开发者用 manifest 与 Python 类编写节点，定义参数和执行入口，可从本地目录或 GitHub 导入，安装后进入 Node Library；支持注册本地/远端包源。**非常接近用户封装和安装模块后接入框架的解释。** | 2026-10-13 本研究已见；具体功能最早公开日期未知。文档含未来版本规划，不能把所有当前表述视为早期已实现。 |
| [VERA 仓库 README：Plugin Architecture](https://github.com/Arifmaulanaazis/vera/#plugin-architecture) | 科学计算可视 DAG、端口类型、插件 manifest、`register(api)`/`api.register_node(...)`、插件节点库扩展与刷新；包含蛋白质结构检索、对接和分子动力学。 | README 自报预印本 2026-04-24；[ChemRxiv DOI](https://doi.org/10.26434/chemrxiv.15002367/v1) 与 PDF 本研究访问失败，故该日期尚未由预印本原站核实。README 的现行插件功能公开日期也未知。 |
| [ProtXplain：ProtFlow](https://www.protxplain.com/en/) | 明确宣传可拖拽并连接 AlphaFold、ProteinMPNN、ESM-2 与 custom tools，面向蛋白质设计、折叠、对接和验证，并提供执行日志。 | 页面显示 2026 版权，仅能确认本研究可访问；未见版本化自定义模块注册协议，不把“custom tools”直接等同于 Workbench 的注册合同。 |

与通用生物信息学平台 Galaxy、KNIME 的进一步比较可接续仓库已有 [Galaxy 研读](frontend-reference-galaxy.md) 和 [KNIME 研读](frontend-reference-knime.md)。这些技术参考用于定位固定源码；专利证据仍应回到其中引用的原始论文、版本文档和可证明公开时间的材料。

## 核心蛋白质论文背景

1. **ESM3：Hayes 等，Simulating 500 million years of evolution with a language model。** [bioRxiv v1](https://www.biorxiv.org/content/10.1101/2024.07.01.600583v1) 页面索引记载 Posted July 02, 2024；[Science DOI](https://doi.org/10.1126/science.ads0018)。原始团队 [现 Biohub 公告](https://biohub.org/blog/esm3-simulating-evolution/) 标注 2024-06-24，披露序列、结构、功能的掩码多模态生成和条件组合。日期必须按各来源分别记录。bioRxiv/Science 正文在本研究工具中未成功获取，故不将论文摘要当作全部轨道细节的证明；上面专利原文另有多轨条件披露。

2. **RFdiffusion：Watson 等，De novo design of protein structure and function with RFdiffusion。** Nature 原站索引及 [PMC 作者全文](https://pmc.ncbi.nlm.nih.gov/articles/PMC10468394/) 记载 2023-07-11；DOI [10.1038/s41586-023-06415-8](https://doi.org/10.1038/s41586-023-06415-8)。已阅读正文模型与验证部分：结构生成后用 ProteinMPNN 设计序列，再用 AF2 与结构指标评价；可加入部分序列、折叠和功能 motif 条件。证明一般多工具研究流程早有公开，不证明用户模块注册协议。

3. **ProteinMPNN：Dauparas 等，Robust deep learning based protein sequence design using ProteinMPNN。** [bioRxiv v1](https://www.biorxiv.org/content/10.1101/2022.06.03.494563v1)、[PMC 作者稿](https://pmc.ncbi.nlm.nih.gov/articles/PMC9997061/)、[Science DOI 10.1126/science.add2187](https://doi.org/10.1126/science.add2187)。PMC 索引记载线上日期 2022-09-15、期刊期次日期 2022-10-07；预印本具体 Posted 日期本研究未核。该研究针对给定骨架的序列设计以及链/位点约束，属于计算模块的上游科学能力。本研究 PMC/bioRxiv 正文访问被验证码或访问限制阻挡，未宣称全文核读。

## 可复用检索式

中文：

```text
蛋白质 可视化 工作流 自定义模块 注册
蛋白质 计算服务 适配器 节点 编排
蛋白质结构预测 软件池 组件化 输入输出标准 工作流
多模态蛋白质设计 多目标优化 筛选
序列 结构 二级结构 溶剂可及表面积 功能 掩码
```

英文：

```text
protein design visual node-based workflow custom tools
protein workflow register module plugin computational service
protein design graphical workflow ESM ProteinMPNN
site:patents.google.com EvolutionaryScale biological language reasoning
site:patents.google.com "protein refinement and joint optimization"
site:patents.google.com "RFdiffusion" "Claims"
site:patents.google.com "protein" "workflow" "screening" "design"
"Generative protein design via noise diffusion"
```

检索入口：Google Patents 原文、同族/引用链和公开 PDF；WIPO PATENTSCOPE 具体公开号入口；作者原始仓库和产品官方文档；Nature、Science、bioRxiv、PMC 原文入口。可继续用 G16B15/20、G16B40/20、G16C20/50 等分类扩展，本研究未穷尽分类检索。

## 覆盖限制与待核实材料

- 尚未在 CNIPA 完成逐申请检索、法律状态核验、中国国家阶段与权利人链核验。PATENTSCOPE 的部分页面仅返回动态加载框架或拒绝访问；不能据此说不存在相关申请。
- 同族分组依据本研究公开书目及优先权/相关申请栏，未完成所有继续申请、分案和国家阶段的完整链核验。中国 B 公报须在准备实施/侵权分析时另行按当时有效文本阅读。
- 未检索全部未公开申请，也未穷尽无专利产品、教材、学术软件、GitHub 历史快照或其它语言关键词。初步检索不能证明“未找到之处”新颖。
- Salpa、VERA、ProtXplain 必须补足具体功能首次公开日期和可复核快照；不要用 copyright 年、网页抓取时间或仓库创建时间代替功能公开时间。
- 本项目自身公开仓库及具体模块接入功能的最早公开日期由另一研究项核查。任何最终对比表都应列出拟申请技术的逐项特征及每项首次公开证据。
- 尚待完成的整体比较：自定义 Module Package 提供什么；注册时验证/固定什么；Node Type 与 Method/Execution Binding 如何关联；哪些 Port 可以连接；适配输出如何交给后继操作；这些步骤共同解决了哪项具体技术问题。残基轴、对象关联或证据仅在与这一模块接入流程发生必要技术联系时作为限定，不替换用户确定的发明重心。

本文未执行本地测试、构建或 Provider，也未改动实现代码。
