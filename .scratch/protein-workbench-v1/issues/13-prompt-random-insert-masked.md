## Parent

3GB1 条件生成 → ESMFold → TM-score → ProteinMPNN 完整设计管线

## What to build

新增 `prompt.random_insert_masked` 模块：在 residue track 上随机选择 N 个位置，每个位置插入一个 sentinel（masked）值，同时更新对应的 residue layout（长度 + N）。给定相同 seed 时输出可复现。

典型使用场景：在 sequence track 中随机插入 masked 残基以增加 ESM-3 的生成自由度，或扩展结构 track 以引入新的坐标位置。

## Acceptance criteria

- [ ] 输入 56 位置的 track + 对应 layout，count=15，输出 track 长度为 71（56 + 15），layout 同步更新为长度 71
- [ ] 插入的 15 个位置值均为 sentinel，原有值保持相对顺序
- [ ] 相同 seed 产生相同的插入位置集合
- [ ] count=0 时输出与输入完全一致
- [ ] 输入 track 为 None 或 layout 为 None 时抛出明确错误

## Blocked by

None — can start immediately.
