# Biohub / ESM 带日期研究证据

本目录保存按日期和代码身份冻结的专项研究包。研究输出、校验和和当时的实现解释属于历史
证据；它们不会因为当前实现后来变化而被改写，也不能替代持续补充的
[runtime overlay](../observed-runtime-overlay.md) 或现行
[产品补充](../product-contract-supplement.md)。

## 2026-07-21 ESM3 generation outputs

- [研究报告](2026-07-21-esm3-generation-outputs/report.md)
- 代码身份：`d03020477beeb3949c7e42e24f17631865635115`
- 封存完整性：包内 `checksums.json` 覆盖报告、observations 和 PDB 输出；不要在未重新封存
  整包校验和时修改这些文件。

报告中“当前实现”和源码行号只描述上述提交。提交 `1972d38` 已将 Generation Result
模块化，并正式支持可选、来源封闭的 `prompt_reconstruction` 与 `sampled_structure`
Generation Structure Evidence；因此报告中“未来共享输出”或“当前丢弃 generation
structure”的实现说明已经被现行
[functional scope](../../../functional-scope.md) 和
[scientific semantics](../../../scientific-semantics.md) 取代。报告记录的 provider 输出事实
仍是有效的历史观测。
