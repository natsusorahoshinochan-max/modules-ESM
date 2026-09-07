# Residue Track element admission 的共享规则

- 状态：已确认
- 日期：2026-09-06
- 领域词汇：`CONTEXT.md`
- 科学约束：`2026-09-02-clean-scientific-data-flow-refactor-spec.md` §§4.4–7、13

## 所有权与 interface

`modules/residue_data/elements.py` 拥有共同的 nullable residue element 规则、
氨基酸与 canonical SS8 字母表，以及已有的 absolute SASA quantity contract。
ProteinPrompt、Conditioning Port Types 和 Observed Port Types 直接调用以下 interface：

- `validate_sequence_elements`
- `validate_coordinate_elements`
- `validate_secondary_structure_elements`
- `validate_sasa_elements`

每个函数接收 `values: Sequence[object]` 和 keyword-only `subject: str`。
`subject` 是错误定位名称，不是 Candidate subject。成功返回 `None`；失败抛出带有
名称和从零开始的元素位置的 `ValueError`。函数不转换、修复或重建值，不接收 Layout、
Candidate Data Reference 或 nominal Port Type ID。

每种元素都允许 `None`。非空元素分别要求：精确 `str` 类型的单字符既定氨基酸代码；
精确 `NamedAtomCoordinates` 类型；精确 `str` 类型的 canonical SS8 状态；或精确
`float` 类型的有限、非负 absolute SASA，单位为平方埃。SASA 不设额外上界。
NamedAtomCoordinates 自身拥有原子名唯一性和有限 Cartesian 3-vector 约束；
元素检查不限制 Provider 原子词汇。

## 完整科学值的 admission

现有 owning admission 入口和调用时机保留。各 owner 继续负责 carrier 类型、Layout
合法性、Candidate subject 和 aggregate 缺失语义。ResidueTrack 与 ProteinPrompt
构造器已经闭合轨道长度；元素规则不再接收或重复比较 Layout 长度。

Conditioning 的 null 表示未指定条件，Observed 的 null 表示不可获得；Observed
仍须关联 `protein.structure` Candidate。ProteinPrompt 保留 optional track 缺席与
present all-null 的区别，其 Function Annotations 继续独立 admission。
共享元素规则不改变 exact nominal Port compatibility。

SASA wire 整数转浮点由各 nominal codec 保留。Prompt 来源的 SS8 normalization、
DSSP token translation 和 ESM3 atom37 projection 继续由原 owner 负责。
删除被替代的重复循环、旧 kind 分派及其无调用的包装函数，不保留兼容路径。
本次不调整运行时 admission 次数，不扩展为 validation framework。

## 验证

共享 interface 测试覆盖字母表、nullable 值、精确类型、finite/non-negative SASA、
Provider-independent named atoms、不转换值和错误位置。完整科学值 interface 测试
验证 Prompt、Conditioning 和 Observed 接入相同规则；既有合同测试继续覆盖 Layout、
subject、Function Annotations、wire normalization 以及 absent/all-null 区别。
运行 focused tests、backend routine 和 deterministic-acceptance。
