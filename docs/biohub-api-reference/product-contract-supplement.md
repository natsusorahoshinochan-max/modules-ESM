# Biohub / ESM 接入说明

本文区分现有接入与已确认要求。目标行为以[当前决策](../documentation-governance-decisions.md)为准；参数与输出的已知差异见[参数审查](../tool-parameter-exposure-audit.md)和[治理问题清单](../2026-10-15-documentation-governance-issues.md)。

## 官方接口与项目职责

Biohub 官方 API 和固定官方 SDK 定义 Provider 的请求、响应表示及处理结果。[v1 快照](v1/README.md)保存其抓取时公开的请求字段，不包含完整响应 schema。Adapter 按官方接口将用户指定的输入与参数正确传入，并接回所需结果。

模块声明描述当前软件提供哪些功能；现有声明不是冻结错误参数范围或隐藏适用参数的理由。现有功能中，官方支持、适用且影响结果的输入与参数须按 Q26 允许配置，默认值及限制有明确依据；这不自动新增其他工具模式。

Adapter 信任符合约定的响应，只做确定的格式和单位翻译。官方未发布的 schema 不从表格展示标签或观测值反推，不增加响应修复、交叉验证、兼容分支或备用端点。程序不变量错误立即失败；已定义的运行失败遵守[执行规则](../execution.md)。

## 现有远程路线

| 当前代码包 | Biohub 模型 | 已接入操作 |
|---|---|---|
| `esm3` | `esmc-600m-2024-12` | encode 与 logits，构成序列表征操作。 |
| `esm3` | `esm3-medium-2024-08`、`esm3-open-2024-03` | sequence、structure、paired generation。 |
| `folding` | `esmfold2-fast-2026-05` | 单链 `/fold`。 |

精确注册、参数和输出见 [`esm3/package.py`](../../modules/esm3/package.py)、[`folding/package.py`](../../modules/folding/package.py)及各自 `definitions/`。这些代码包名称不预定最终功能模块划分；职责见[模块能力](../module-capabilities.md)。

当前 ESMFold2 路线不调用 `/fold_all_atom`。快照中 `all_atom_input.sequences[].ProteinInput` 等名称可能是联合类型分支标签，不能据此认定它们是实际 JSON 键并多包一层对象。本地材料不足以裁决这个展示问题；新增或修改相关路线前必须核对官方原始定义，不能猜测。当前产品未因快照包含该端点而自动接入复合物折叠。

## 输入、参数与随机性

ESM-3 条件翻译的 atom37、绝对 SASA、功能注释及缺值规则见[模块能力中的 ESM-3 条件翻译](../module-capabilities.md#esm-3-条件翻译)。翻译属于该工具 Adapter，不限制通用 Prompt 或其他模块的数据表达。

ESM-3 的三种生成当前共用采样参数声明；paired 先生成序列，再据该序列生成结构。`condition_on_coordinates_only` 当前固定为 true，`invalid_ids` 当前未开放；ESMFold2 的步数、循环、dropout 和 masking 等也固定在调用中。这些是尚未对齐 Q26 的实现状态，不能继续作为禁止用户配置的要求。对应路线的范围、默认值和限制见[参数审查](../tool-parameter-exposure-audit.md)。

项目当前使用的固定 SDK 生成与折叠调用未传入 seed，Adapter 将远程随机性记录为 Provider 控制；不能因节点显示 seed 就宣称远端采用了它。这个结论描述固定调用路线，不推断当前线上全部接口。本地 ESM-3 的派生 seed 与实际输入由同一 Adapter 条件投影计算，具体公式见[模块能力](../module-capabilities.md#esm-3-条件翻译)。

ESM-3 与 ESMFold2 使用固定 SDK 的现有适用重试，默认总计最多五次尝试，仅重试 SDK 指定错误；不在外层叠加重试。一次 Engine Invocation 可以包含 SDK 的多次尝试，不等于一次 HTTP 请求。Q9 不把这一次数变成所有模块的统一规则；实现见[SDK 重试](../../repositories/esm/esm/sdk/retry.py)。

## 输出含义与实现差异

- ESM-3 structure-track 采样输出标记为 `sampled_structure`；坐标条件下 sequence-track 返回的条件结构重建标记为 `prompt_reconstruction`。二者不冒充独立折叠验证结果。纯序列结果不补造结构或置信度。
- ESM-3 结构附带的 PAE 当前允许缺失；存在时保留与相应预测残基轴一致的完整矩阵，单位为 Å，不补零或借用另一预测的值。
- ESMFold2 当前明确请求 `include_pae=true`、`include_embeddings=false`，同时保留该次预测的结构、pLDDT、pTM 与 PAE。与已承诺输出对应的必需开关，不直接视为需要新增关闭选项的证据；也不自动接入其他输出模式。
- ESMC 当前只保存整序列 mean embedding 和 logits 的形状。Q27 已确认整条序列 embedding 和实际逐位置 logits 均应作为可选输出，供查看与后续计算；该要求尚未对齐。logits 不是概率。

工具自然产生且属于所需功能的分数随结果保留；不因功能模块拆分而要求用户重算。评价对象与参考对象独立于生成来源，不通过改写来源关系绑定评分。

配置说明见[Provider 配置](../provider-configuration.md)。原始研究数据不证明当前实现已经满足产品要求。
