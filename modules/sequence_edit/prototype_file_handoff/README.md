# Throwaway：结构文件与最少任务参数

问题：原始结构文件保持不变时，如何交付变长编辑后的目标顺序，以及彼此独立的序列和坐标条件？

双击 `index.html`，先运行四个引导演习，再使用自由操作。页面自包含、无需服务器、所有编辑只在内存中。展示原始 1PGA A 链真实序列；浏览器不解析结构或运行模型。

`target_to_source` 的长度为目标长度，元素为本次选择的单模型、单链内的 author number 与 insertion code，新增位置为 null。`sequence_conditions` 和 `coordinate_conditions` 使用从零开始的目标下标。原子坐标保留在文件中。此请求只供本次单链实验使用，多模型、多个链及其他条件须由实际任务明确表达。

在原 A11 后插入三个未知位置，再删除原 A25，目标为 58 位，包含 55 个来源对应和三个新位置。坐标选择独立于序列条件；纯逻辑拒绝从没有来源的新位置采用原始坐标。文件身份、解析能力与坐标实际存在性由接收工具验证。

命令行桥接执行 HTML 中的同一段纯逻辑：

```sh
node modules/sequence_edit/prototype_file_handoff/export.cjs CASE.json OUTPUT.json
```

`CASE.json` 示例：

```json
{"actions":[{"type":"insert3"},{"type":"delete25"}]}
```

ESM 实验见 `../../esm3/prototype_file_input/README.md`；格式与解析实验见 `../../structure_io/prototype_file_transport/README.md`。标准文件中的来源信息和任务指定的目标位置共同决定实际工具输入；载体只传递文件和参数。
