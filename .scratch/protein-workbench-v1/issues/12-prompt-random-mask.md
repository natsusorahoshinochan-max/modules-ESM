## Parent

3GB1 条件生成 → ESMFold → TM-score → ProteinMPNN 完整设计管线

## What to build

新增 `prompt.random_mask` 模块：在 residue track 上随机选择恰好 N 个非 sentinel 位置，将其值设为 sentinel（mask），其余位置不变。输出 track 长度与输入一致。给定相同 seed 时输出可复现。

模块在 workflow DAG 中可组合使用——先通过 `prompt.apply_residue_edits` 获取 sequence track 或 structure track，再接入此模块进行随机掩码，最后送入 `prompt.assemble_protein_prompt`。

## Acceptance criteria

- [ ] 输入 56 位置的 track（全部非 sentinel），count=20，输出 track 恰好 20 个位置为 sentinel，其余 36 个保持不变
- [ ] 输入 track 中已有部分 sentinel 位置时，只从非 sentinel 位置中随机选择
- [ ] 相同 seed 产生相同的掩码位置集合；不同 seed 大概率产生不同集合
- [ ] count 超过非 sentinel 位置数时抛出明确错误
- [ ] 输入 track 为 None 时抛出明确错误

## Blocked by

None — can start immediately.
