## Parent

> **Status: superseded historical v1; do not implement.** The v1 runtime was removed. This file is retained only as historical planning evidence and creates no current compatibility requirement.

3GB1 条件生成 → ESMFold → TM-score → ProteinMPNN 完整设计管线

## What to build

将现有的 `esm3.generate_sequence` 和 `esm3.generate_structure` 两个 lossy 模块统一为一个 `esm3.generate` 模块。ESM-3 的 `generate()` API 单次调用即返回完整的 `ESMProtein`（含 sequence + coordinates + pTM + pLDDT），当前两个模块各自丢弃了另一半数据。新模块一次 generate 调用同时输出 sequence candidates 和 structure candidates，二者 index 一一对应，无需两次 API 调用。

现有的 `esm3.generate_sequence` 和 `esm3.generate_structure` 保留不动（向后兼容），新模块以独立 module_id 注册（如 `esm3.generate` 或 `esm3.generate_joint`）。内部复用现有的 `esm3_adapter`。

## Acceptance criteria

- [ ] 单次 generate 调用后，`sequence_candidates` 和 `structure_candidates` 两个输出端口均有内容
- [ ] 两个 candidate collection 长度相等（等于 num_samples），同 index 的 candidate 来自同一次 generate 结果
- [ ] sequence candidates 的 item_type 为 `protein.sequence`，structure candidates 的 item_type 为 `protein.structure`
- [ ] structure candidates 的 PDB 中嵌入的 sequence 与对应 sequence candidate 一致
- [ ] 输出 scores 包含 pTM 和 pLDDT，subjects 指向 sequence candidates（或 structure candidates，二选一且一致）
- [ ] mock ESM3 client 返回含 sequence + coordinates + ptm + plddt 的 ESMProtein 时，所有输出端口正确填充

## Blocked by

None — can start immediately.
