# 一次性原型：评价、筛选与集合交接

问题：同一对象拥有不同参考、不同区域的评价时，合并、筛选与抽取如何保留准确含义，并让独立消费者仅凭交付文件继续使用？

双击 [index.html](index.html) 即可操作。全部实际证据内嵌，交互状态留在内存。自由操作支持评价选择、阈值、排序、数量、合并与抽取；分步演习展示完整交接、切换评价和空结果。下载按钮导出包含真实文件文本的 JSON 包。

[第二轮独立演示](evidence/round2/index.html) 使用从首轮选中结果实际生成的两个 59 位结构，沿用相同主评分与筛选规则。

## 固定实例与实际调用

[plan.json](plan.json) 在取得本轮候选分数前固定：两个 58 位真实生成结构，参考原始 1PGA A 链 56 位；原生 TM-align 参考长度归一化 TM-score ≥ 0，降序，最多 1 个。附加评价为两侧独立选择 A:1–5、30–35，以及明确选择候选一为全链参考。严格阈值 ≥ 1.01 用于观察空结果。

输入来自 [结果回流原型](../../sequence_edit/prototype_result_feedback/README.md) 的 `evidence/candidates/manifest.json`。这批坐标由真实 ESM3 structure 生成和 native decoder 解码产生；比较按这些实际坐标计算。

科学调用经过已有公开入口 `modules.structure_comparison.api.compare`；固定 `tmtools==0.3.0` 的 SDK 文档及 [公开格式说明](../../structure_comparison/FORMAT.md) 定义坐标、序列、区域、原生指标和对应。首轮执行 6 次真实 TM-align。没有重跑模型来取得比较分数。

两侧不连续区域按各自当前真实编号选择，TM-align 建立对应。相同编号没有被当成原始残基血缘或强制配对。

## 结论与界限

- 同一候选的多个分数必须连同对象、参考、区域、实际方法、指标及归一化含义交付。只给 `score` 数值无法支持本例的明确选择。
- 合并按显式输入保留顺序；筛选逐对象唯一解析用户选择的评价，再进行条件、稳定排序和数量限制。用户选择显示含义，内部身份留在格式中。
- 抽取保留选中对象的序列、结构和所需评价文件；评价保留参考及原始比较内容，独立读取无需上游历史。集合模块交付这些文件，载体只负责通用复制和保存。
- 首轮原参考全链得分为 0.8263003040517922 和 0.24736964768578332，按固定规则选中 `feedback-candidate-1`。Python 直接从真实分数算出的名单与 HTML/CLI 共享 JavaScript 逻辑一致。
- 选中包实际复制到 `evidence/PROTOTYPE_WIPE_ME/selected`；`python -I` 运行的独立消费者只依赖标准库和 Gemmi，核对 58 位序列、58 位实际结构及 3 项评价，读取 15 个声明文件。这里验证复制后包的自足性；真实应用的跨项目采用仍由其自身入口验证。
- 结果回流原型读取这个实际抽取包，将选中结果编辑为 59 位模板并生成两个新序列及结构。本原型对第二轮执行 2 次相同主比较，得分分别为 0.6120604009701297 和 0.6137247185464406，选择 `feedback-round2-candidate-2`。共享筛选与独立核算一致，复制包中的 59 位序列、59 位结构和评价共 7 个文件独立读取成功。计算使用完整原值。

本原型的公开消费约定限于这一调用：`objects` 保存普通对象标识、序列及文件键；`evaluations` 保存明确主体、参考、区域、方法、原生指标、对应及比较文件；`references` 保存本次实际参考。该约定由科学模块拥有，具体字段可以随实现调整。

## 入口与证据

在仓库根目录，使用现有依赖环境运行：

```sh
python modules/filtering/prototype_evaluation_handoff/run.py
```

同一主评分规则接下一轮真实结果：

```sh
python modules/filtering/prototype_evaluation_handoff/run.py \
  --candidates modules/sequence_edit/prototype_result_feedback/evidence/round2-candidates/manifest.json \
  --output modules/filtering/prototype_evaluation_handoff/evidence/round2 \
  --primary-only
```

- `run.py`：实际比较、包整理、独立核算、CLI 回放、复制与独立消费。
- `index.html` 的 `logic` 脚本：纯合并、明确评价解析、筛选和抽取函数；`replay.cjs` 直接提取同一段执行。
- `independent_consumer.py`：无生产者导入，从复制后包中重读真实序列、结构和评价。
- `evidence/collection.json`：实际对象与全部评价。
- `evidence/primary-selection.json`：固定规则及独立计算的选中名单。
- `evidence/result.json`：共享筛选回放与独立读取结果。
- `evidence/browser-actions.json`：浏览器实际点击记录。
- `evidence/round2/`：第二轮独立的实际比较、选择与消费证据。

原型不连接应用数据库、不修改生产模块；文件写入限于本原型证据目录。
