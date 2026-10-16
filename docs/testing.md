# 测试组件职责与覆盖

更新日期：2026-10-16。

测试按职责整块重建，保留有效验证能力。当前目录、共享支持和入口已迁移，部分错误预期已按[当前有效决策](documentation-governance-decisions.md)纠正；已按本次用户授权在本机完成冻结源码的非 Provider 验证，获准的真实 Provider 验收及真实浏览器旅程已通过，本次授权范围内的测试组件治理已完成；不表示全部要求已覆盖或产品已实现。实现差异由[问题清单](2026-10-15-documentation-governance-issues.md)维护。

## 当前组织

| 归属 | 证明责任 | 入口归属 |
|---|---|---|
| [contracts](../tests/contracts/) | 公共协议、共享值、Port、模块接入与有效架构约束 | 常规后端回归 |
| [carrier](../tests/carrier/) | 项目、存储、调度、失败、取消及数据传递 | 常规后端回归 |
| [modules](../tests/modules/) | 功能行为、输入与参数翻译、对象及区域对应 | 常规后端回归；真实调用另归 Provider 门禁 |
| [journeys](../tests/journeys/) | 真实载体上的项目链和跨模块场景 | 常规回归或各专用场景入口，由选择定义决定 |
| [installed](../tests/installed/) | 发行内容、包外装配与公共服务 | installed-package |
| [providers](../tests/providers/) | 实际工具调用、精确 Binding、必要真实回归 | 安装产物 Campaign 与 provider-regressions，各自负责不同边界 |
| [前端 logic](../webui/tests/logic/) | 无服务的状态与数据逻辑 | 独立 logic 配置 |
| [前端 components](../webui/tests/components/) | 受控组件交互 | 独立组件宿主配置 |
| [前端 journeys](../webui/tests/journeys/) | 实际应用状态与隔离后端的用户操作链 | 确定性应用旅程配置 |
| [真实浏览器旅程](../webui/real-tests/) | 实际应用和 Provider 的必要组合 | WebUI 真实验收入口 |
| [verification 测试](../tests/verification/) | 选择、隔离、退出码和报告交接 | 常规回归内的最小合成探针 |

目录不是资源条件。journeys 中真实工具场景不进入无 Provider 门禁。共享工具不意味着验证责任重复：参数翻译、安装接线、真实调用及跨模块组合分别保留。

执行命令、完整门禁、资源条件及远端政策仅由[后端验证](backend-verification.md)与[WebUI 验证](../webui/README.md#verification)维护。后端门禁与 WebUI 独立；六项源码真实回归由 provider-regressions 承接，不能替代安装产物 Campaign。不把目录迁移、静态检查或部分入口通过表述为整体通过。

本次执行采用用户明确授权的本机例外，不永久修改仓库远端验证政策。禁止实际在本机运行 ESM-3、SimpleFold、ESMFold2；纯参数翻译和替身合同不加载这些模型，远端 API 调用及其他本地模型在授权范围内。真实 Provider 在完整非 Provider 门禁通过后执行，获准的 10 个完整 tier 与 5 项源码回归子集全部通过。不能宣称完整 Campaign 通过，受本次资源限制的路线也不得记为通过。

## 当前验证状态

用户已授权修复测试暴露的产品差异。运行期间修改保护、失败依赖阻断、FASTA/mmCIF 导入、独立评价、批次成功结果保留，以及前端手动保存、教学保存时机、随机残基删除、结果页动作删除和嵌套对话框修复已进入当前源码，对应非 Provider 回归通过。独立评价的真实 ProteinMPNN 验收通过；批内失败保留由受控失败回归证明，真实工具成功调用不等于线上故障注入验收。正确断言继续保留，未实现的产品接口仍按下表记录。

当前冻结源码的 16 项非 Provider 检查全部通过：定向检查 264 项、常规后端回归 1813 项，另六个后端专用门禁，以及 WebUI 类型检查、测试类型检查、lint、逻辑测试 91 项、组件测试 13 项、应用旅程 102 项、构建和真实旅程类型检查。运行前后源码未变化。当前证据位于本地 `.local/test-governance-20261016/round-07/checks/summary.json`；源码 manifest SHA-256 为 `d0ef2b166d35371b208be5ef294bd7614d5ad2dbc2d65a2f63187faa151fac00`。这些记录不证明缺失接口已实现。

同一冻结源码的真实 Provider 结果位于本地 `.local/test-governance-20261016/round-07/providers/summary.json`：七个安装产物 tier（Biohub ESMC、ESM3、ESMFold2、mkdssp、ProteinMPNN、SoluProt、Protein-Sol）和三个 fresh tier（2EMO、canonical 3GB1、5G53）全部通过；明确选择的五项源码回归（四项 ProteinMPNN 与一项远程 ESMFold2）也通过。源码保持不变。这是 10 个完整 tier 加 5 项源码子集，不是完整 19-tier Campaign，也不是完整 provider-regressions 门禁；本地 ESM-3、SimpleFold、ESMFold2 实际模型及使用这些模型的全部路线按授权限制未执行，包括四个安装产物本地模型 tier、`fresh-1pga`（依赖 SimpleFold）、全部 `fresh-local-*` 路线，以及源码回归中的本地 ESMFold2 用例，均不记为通过。

真实浏览器的六项旅程及 FASTA 报告检查全部通过，结果见本地 `.local/test-governance-20261016/round-07/real-ui/summary.json` 与同目录 `completion.json`；源码与构建产物哈希保持不变。Prompt 快速输入和内嵌控件交互的实际应用回归也通过。

## 支持、场景与资产

[tests/support](../tests/support/README.md)负责环境装配、公共操作、等待、读取及资源释放；[tests/scenarios](../tests/scenarios/README.md)拥有复用的场景输入关系、装配和预期；[tests/fixtures](../tests/fixtures/README.md)维护测试静态数据与最小模块包。

- 可收集测试使用支持库、场景及夹具，不把另一可收集测试当共享库。场景可使用支持库；通用支持不反向依赖科学场景。
- 测试拥有预期，替身只提供工具结果或已定义失败；替身不实现被测保存、批次保留或续算行为。预期不得由实际结果或同一生产算法反算。
- 组件宿主不证明持久化或完整用户链；注入 Catalog 不证明用户安装模块。安装应用不借助源码导入路径。
- 临时资源由创建者释放；原始输入、用户项目、教学结果与保留的失败材料有各自维护边界，不纳入统一删除。
- 生成工作流由现有生成源维护；真实验收不由历史归档、缓存或 mock 替代。pytest/JUnit、backend 与 Campaign 保持现有报告交接，不另建证据系统。

## 当前覆盖交接

以下区分源码承接与已取得的本地执行证据。已有测试、接口缺失、局部通过和最终验收是不同状态；未覆盖项不通过空壳测试、跳过或放宽预期计入完成。

| 要求与场景 | 主责 | 当前承接与限制 |
|---|---|---|
| Q3/Q10 原子保存、不完整草稿重开与运行准入 | carrier；前端 journeys | 有对应底层保护；不能代替手动保存旅程 |
| Q13/Q16/Q44 手动保存、退出三选项、保存并运行、教学首次保存 | 前端真实应用旅程；carrier | 手动保存、应用内退出三选项、保存并运行与教学首次保存旅程通过；浏览器关闭使用原生未保存提醒 |
| Q12 运行期间禁止修改；Q15 失败阻断依赖、独立分支继续 | carrier、项目 journeys | 项目修改锁、已连接失败依赖阻断与独立分支继续的回归通过 |
| Q14 缺模块保留与恢复 | 项目 journeys | 注入 Catalog 的保留/恢复场景本地通过；不证明正常用户模块管理链 |
| Q17 前端断开不取消后端 | carrier、前端 journeys | 保留任务生命周期及必要断连覆盖；前端关闭与用户取消分开 |
| Q11 历史列表；Q28/Q31 直接历史采用；Q33 删源后采用输入独立可用 | carrier 与前端 journeys | 列表及直接采用链尚不完整；项目复制或输入复制不能代替历史输出采用 |
| Q32 有运行源项目复制后未运行、所需输入保留 | 项目 journeys | 真实载体运行、复制、删源、重开与重新运行场景已有本地通过证据；这不等于 Q28/Q31 已实现 |
| Q7.4/Q8/Q42 空载体、用户模块管理及默认状态 | 应用 journeys、installed | 局部注册/默认清单与安装保护保留；用户管理完整链仍缺 |
| Q45–Q47 外部 React UI、多查看器、应用内配置 | 合同、前端 journeys、installed | 现有协议/配置消费覆盖不等于专用 UI 与应用设置闭环；接口和完整链仍未齐备 |
| Q19 多记录 FASTA 不拼接；Q30 PDB/mmCIF 导入 | modules/protein_io | 单条入口拒绝多记录与 mmCIF 导入回归通过；不证明选择格式导出已完成 |
| Q24 独立评价与生成来源分开 | modules/proteinmpnn、scenarios、providers | 独立评分请求及 pairwise 关系已重建，生成来源保持独立；非 Provider 契约、组合回归与真实 ProteinMPNN 安装及源码验收通过；不代表全部 Q26 参数开放已完成 |
| Q38/Q40 成功结果保留、失败停止；Q41 主动批内续算 | modules、carrier、前端 journeys | 失败停止、保留完成结果且不进入缓存/下游的受控回归通过；真实工具成功调用不替代失败路径验证；批内续算接口仍缺，节点重跑不算完成 |
| Q27 实际 logits；Q34 导出格式选择；Q35 构象选择/拆分 | 各 modules 与前端 journeys | 所需接口缺失；形状、原文保留或默认 PDB 不证明要求已满足 |
| Q2/Q6/Q20 编辑与局部采用；Q4/Q5 筛选及删除保存为流程 | modules、前端 logic/components/journeys | 保留有效编辑、筛选、导出及数据采用保护；随机残基后续编辑与结果页动作删除的模块及应用交互回归通过 |
| Q9/Q26 适用重试与参数；Q36/Q37/Q39 数据组分、参数导出、单文件输入 | modules、contracts、providers、必要前端链 | 现有局部保护保留；参数开放及完整查看/导出缺口按实现问题维护，不能扩大为新模式 |
| Q1/Q7/Q7.3/Q29/Q43 资产保护、公共模块规范、查看范围、默认教学 | 对应合同、载体、安装与前端归属 | 保留有效已有覆盖；默认教学不成为空载体必要条件，不禁止历史采用或结构比较计算 |

## 完成标准

每个职责块同时交接场景、支持、选择入口及有效覆盖，删除被替代路径。保留协议、传参、来源对应、持久写入、失败处理和真实验收能力，不以文件数或测试数下降证明治理效果。

已确认行为可调用时写正确的可执行预期，失败记录为实现差异，不使用 skip、xfail 或移出门禁制造全绿。接口尚不存在时明确记录缺口，不以测试宿主伪造功能。未决产品选择不由测试擅定。当前冻结版本已在用户授权的执行范围内完成全部适用门禁，本次测试组件治理完成。该结论不代表完整 19-tier Campaign 通过，不把明确未执行的模型路线记为通过，也不代表本表及问题清单中缺失的产品功能已经实现。
