# 条件表示比较原型

一次性逻辑原型；所有坐标与评分均为合成夹具，无模型推理、无持久化。

## 问题

每个位置的条件随行保存，与有序位置加独立条件轨道，能否在增删、突变和重排后保留相同科学含义？跨位置区域和成对约束需要哪些交接内容？

两个方案都使用普通稳定位置 ID；区域使用明确成员列表。观察值与实际选择的条件分开。新位置缺少来源和坐标。来源结构与其评价独立保留。

## 运行

双击 `index.html`，使用自由操作或四组引导演练。页面完整显示当前位置、条件、来源、引用及原对象评价，折叠区域提供内存表示和交付内容。

用户明确要求测试，执行：

```sh
node --test modules/sequence_edit/prototype_conditions/contract.test.cjs
```

测试提取 HTML 中纯逻辑脚本，通过 Node 内置 VM 运行，无额外依赖。

实际结构夹具可通过同一纯逻辑处理，再交给原生工具验证：

```sh
node modules/sequence_edit/prototype_conditions/export.cjs INPUT.json OUTPUT.json
```

输入为 `{seed: {objectId, positions, regions, pairs}, actions}`；`positions` 使用页面交付中的行字段，位置 ID 在此原型中采用 `p` 加正整数。输出为 `{request, representationsEqual: true}`，仅在两个表示的完整交付相等时写入。真实结构文件的解析由调用方负责。

## 原型接口职责

- `initial(kind)`：创建行表示或独立轨道表示。
- `fromSeed(kind, seed)`：从明确位置、观察和条件建立同一逻辑状态，用于实际结构夹具交接。
- `apply(state, action)`：纯编辑操作；失败保留原输入。位置删除采用明确的拒绝或清理引用操作。
- `exportRequest(state)`：交付当前对象、按顺序排列的位置、来源观察、选择的条件、区域成员和成对约束。原对象评分不进入新对象交付。
- `validate(state)`：检查本原型的内部引用与轨道一致性。
- 独立坐标输入需要显式一对一映射。原型不执行自动对齐；部分输入需先明确选择区域。
- 工具 Adapter 在此交付之后负责模型原生布局、掩码和特殊 token；本原型不调用工具。

两个替代实现仅用于比较，全部位于此一次性目录，生产模块没有增加接口或兼容路径。
