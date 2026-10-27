# 归档测试

`tests.tar.gz` 保存归档时的 Python 与前端测试、辅助代码和数据，包含当时未提交的修改。`manifest.json` 列出归档文件和已移出测试入口的代码。`tests/fixtures/sequence_conditions.py` 取自清单注明的 Git 提交。原始研究数据仍保留在 `tests/fixtures/real_comparisons/`。

归档内容不作为当前行为规范，也不参与测试发现。本轮验证使用依据 `docs/requirements.md` 新建的测试。需要查看归档时，解压到测试目录以外的位置：

```sh
mkdir -p /tmp/protein-workbench-archived-tests
tar -xzf test-archives/2026-10-27-before-studio-direct-edit/tests.tar.gz -C /tmp/protein-workbench-archived-tests
```
