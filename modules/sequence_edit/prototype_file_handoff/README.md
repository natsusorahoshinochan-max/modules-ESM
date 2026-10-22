# Throwaway：同一次编辑的两种完整交接

问题：原结构加附加位置映射，与完整目标 mmCIF，能否表达同一次变长编辑和相同生成条件？

双击 `index.html`，先运行三个引导演习，再使用自由操作。页面自包含、无需服务器、所有编辑只在内存中。展示原始 1PGA A 链真实序列；浏览器预览交付内容，不写结构文件或运行模型。

方案 A：`target_to_source` 长度为目标长度，元素是原始 PDB 单链内的 author number 与 insertion code，新增位置为 null。坐标留在原文件。

方案 B：`edited.cif` 的 `_entity_poly_seq` 定义完整目标，`_atom_site.label_seq_id` 对应当前目标位置。B 的请求不附带 `target_to_source`；`chain` 选择 label 链。实际 CIF 由相邻 Python 实验写出并独立读取。

两者的 `sequence_conditions` 和 `coordinate_conditions` 相同，均使用从零开始的目标下标。本次只比较明确选择的单模型、单链蛋白任务。

在原 A11 后插入三个未知位置，再删除原 A25，目标为 58 位，包含 55 个观测残基和三个无坐标位置。坐标选择独立于序列条件。操作链路只包含实际编辑与载体选择。

命令行桥接执行 HTML 中的同一段纯逻辑：

```sh
node modules/sequence_edit/prototype_file_handoff/export.cjs CASE.json OUTPUT.json
```

`CASE.json` 示例：

```json
{"actions":[{"type":"insert3"},{"type":"delete25"}]}
```

追加 `{"type":"useCif"}` 可预览 B 请求；默认导出 A 请求。实际文件和双路线编译见 `../prototype_cif_handoff/README.md`。上轮 A 的真实生成证据见 `../../esm3/prototype_file_input/README.md`。
