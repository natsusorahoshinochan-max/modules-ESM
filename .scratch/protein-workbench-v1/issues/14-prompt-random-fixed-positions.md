## Parent

> **Status: superseded historical v1; do not implement.** The v1 runtime was removed. This file is retained only as historical planning evidence and creates no current compatibility requirement.

3GB1 条件生成 → ESMFold → TM-score → ProteinMPNN 完整设计管线

## What to build

新增 `prompt.random_fixed_positions` 模块：给定序列长度和一个比例（如 0.5），随机选择 `length * fraction` 个位置作为 ProteinMPNN 的 fixed_positions，输出 `proteinmpnn.constraints` 对象。给定相同 seed 时输出可复现。

典型使用场景：在 ProteinMPNN 设计步骤前，随机固定 50% 的残基位置（保持原序列），让 ProteinMPNN 仅重设计其余 50%。该模块产出可直接接入 `proteinmpnn.design` 的 constraints 端口。

## Acceptance criteria

- [ ] 输入 length=56、fraction=0.5，输出 constraints 的 fixed_positions 恰好 28 个位置
- [ ] 选中的位置均在 [0, length) 范围内且无重复
- [ ] fraction=0 时 fixed_positions 为空列表；fraction=1 时包含所有位置
- [ ] 相同 seed 产生相同的 fixed_positions 集合
- [ ] fraction 不在 [0, 1] 范围内时抛出明确错误

## Blocked by

None — can start immediately.
