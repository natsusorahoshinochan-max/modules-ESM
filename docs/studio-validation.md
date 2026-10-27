# Studio 验证

现有测试归档于 `test-archives/2026-10-27-before-studio-direct-edit/tests.tar.gz`，清单与解压步骤见同目录 README。原始研究数据保留在 `tests/fixtures/real_comparisons/`。归档不参与当前测试发现。

当前验证入口：

```sh
.venv/bin/python -m pytest tests/studio -q
node --test webui/tests/studio-*.test.mjs
npm run build --prefix modules/sequence_edit
cd webui && npx tsc -b --pretty false
```

交互验收使用独立项目或副本，从画布打开 Studio。检查序列输入与粘贴、独立轨道选区、清空、插入、划线删除、直接恢复、当前会话撤销及失败后草稿保留。完成、保存、重开后核对颜色和删除位置；读取输出包核对有效位置、五条轨道及注释区间。

三维检查覆盖四种表示、默认主体色、选中颜色、“显示修改”开关与当前轨道着色、删除残基完全不透明、残基选择与变换、缺坐标选区、确认与取消、视角操作及焦点内快捷键。已有研究文件只作为真实输入，不运行模型计算来验证界面。
