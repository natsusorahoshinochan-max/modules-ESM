# ESM-3 conditioning identity 的 Adapter ownership

- 状态：已确认
- 日期：2026-09-06
- 领域词汇：`CONTEXT.md`
- 科学约束：`2026-09-02-clean-scientific-data-flow-refactor-spec.md` §§5–7

## 职责与 interface

ESM-3 Operation 拥有样本数量与顺序、生成模式、Node 前置条件、Candidate lineage、
Prediction Residue Axis、confidence association 和输出组装。它将 runtime 已解析的
基础随机性与样本序号交给 Adapter，不计算或传递 functional-input digest 或派生 call seed。

现有 ESM-3 Adapter module 保留三个入口：`generate_sequence`、`generate_structure`、
`generate_pair`。每个入口接收 `ProteinPrompt` 和以下 keyword parameters：

```python
parameters: ESM3CallParameters
base_seed: int | None
sample_index: int
```

返回值保留原有科学结果、实际生效的 call seed 和 generation steps，供 Operation 记录
provenance。生成轨道由明确的入口与 paired 子调用决定。

## Adapter 内部 implementation

每个入口从 ProteinPrompt 构造一次不可变 conditioning projection。它是 Adapter 的私有
implementation，不穿过其对外 seam，也不成为新的 Port Type 或通用 residue carrier。

同一 projection 产生 functional-input digest 编码和实际 SDK 输入编码。共享内容包括：

- Provider-visible sequence 与 secondary structure；
- absolute SASA；
- 按 admitted 顺序保留的 annotation label 与一基、闭区间位置；
- 经过 atom37 筛选、按 residue position 和 atom index 排序的坐标。

两种编码保留各自形式：digest 使用 float32 坐标位模式、float64 SASA 位模式和空注释
`[]`；SDK 使用 `[L, 37, 3]` float32 tensor、缺失坐标 NaN、Python float SASA 和空注释
`None`。不存在支持的坐标时，两者均无可用 coordinates。absent 与 present all-null
secondary structure/SASA 保持区别。SDK 的可变值从 immutable projection 新建。

paired 父调用使用原 projection；取得已 admitted 的生成 sequence 后，仅替换 projection
的 sequence，生成子调用的输入与 seed。其余 conditioning 保持原值。

## 随机性和 evidence

保留已确认的现有 digest 编码与随机流。call seed 是下列 ASCII 内容的 SHA-256 前六字节
按 big-endian 解释的整数；缺少 base seed 时不产生派生 seed：

```text
protein-workbench-esm3-call-seed/v2:{base_seed}:{functional_digest}:{sample_index}:{track}
```

本地 Adapter 继续精确应用派生 seed；Biohub Adapter 继续记录 `provider_uncontrolled`，
不声称远端应用了 seed。实际 Engine Invocation 的开始、终止、paired 父子关系与错误归属
保持不变。该重构不改变 Method、Result Identity、Cache identity 或 Candidate metadata 合同。

## 验证

测试通过现有 Adapter interface 将 conditioning、实际 Provider 输入、实际应用的 seed、
返回的科学结果与 Invocation provenance 连接起来。受控 Provider client 只用于 focused
行为测试，不能替代真实 Provider 验收。

固定数值测试覆盖重构前的随机流，包括 atom37 过滤、float32 rounding/signed zero、SASA
float64 精度、absent/all-null、annotation label/位置、样本序号和 paired 子调用。
删除被这些 interface 测试替代的 helper mechanics 测试，保留 Node 前置条件、lineage、
confidence、Result Identity 与运行证据的现有科学断言。

实施验证包括 focused tests、`verification.backend routine`、
`verification.backend deterministic-acceptance`、`installed-biohub-esm3` 和
`installed-local-esm3`。真实 Provider 环境不可用时明确记录未完成的验收，不以模拟结果代替。
