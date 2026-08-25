# Biohub / ESM 带日期研究证据

本目录保存按日期和代码身份冻结的专项研究包。研究输出和当时的实现解释属于历史
证据；它们不会因为当前实现后来变化而被改写，也不能替代持续补充的
[runtime overlay](../observed-runtime-overlay.md) 或现行
[产品补充](../product-contract-supplement.md)。

## 2026-07-21 ESM3 generation outputs

- [研究报告](2026-07-21-esm3-generation-outputs/report.md)
- 代码身份：`d03020477beeb3949c7e42e24f17631865635115`

报告中的历史源码路径和行号只在上述提交中成立，现以代码格式保留而不作为指向当前
工作树的链接。不要把当前实现文件反向解释为当时的 Evidence。现行事实由以下文件拥有：

- [Biohub / ESM 当前产品合同](../product-contract-supplement.md)
- [当前 Protein Workbench 架构](../../protein_workbench_architecture.md)
- [`esm3` Module Package](../../../modules/esm3/package.py)、
  [Adapter](../../../modules/esm3/adapter.py) 和
  [Node Definitions](../../../modules/esm3/definitions/)

报告中“当前实现”和源码行号只描述上述提交。提交 `1972d38` 已将 Generation Result
模块化，并正式支持可选、来源封闭的 `prompt_reconstruction` 与 `sampled_structure`
Generation Structure Evidence；因此报告中“未来共享输出”或“当前丢弃 generation
structure”的实现说明已经被上述当前产品合同、架构和 Module Package 取代。报告记录的
Provider 输出事实仍是有效的历史观测。
