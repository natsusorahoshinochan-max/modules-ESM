# Protein Workbench

通过画布组合模块，完成蛋白数据编辑、生成、预测、比较和筛选等研究任务。

项目正在进行大规模重构。已确认的需求与目标设计见下列入口，现有代码尚未完成替换。

- 开发或审查前读 [AGENTS.md](AGENTS.md)。
- 核对行为范围读 [需求](docs/requirements.md)。
- 设计模块、数据交接和保存读 [架构](docs/architecture.md)。
- 查阅概念读 [术语](GLOSSARY.md)。

后续开发按确认需求与公共接口开展 TDD。

外部模块的声明、React 接口及可安装样例见 [模块接入与文件交付](docs/module-authoring.md)。

## 安装

需要 Python 3.12、uv、Node.js 和 npm。以下命令在仓库根目录执行。

```bash
npm ci --prefix webui
PROTEIN_WORKBENCH_UI_TOOLCHAIN="$PWD/webui" uv sync --locked --extra dev --extra providers
```

本地模型位置见 [本地模型路径](docs/local-models.md)。

## 启动

后端：

```bash
PROTEIN_WORKBENCH_DATA_ROOT="$HOME/.local/share/protein-workbench" \
  .venv/bin/protein-workbench-server --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```bash
npm --prefix webui run dev -- --host 127.0.0.1
```

打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。

## 构建

前端：

```bash
npm --prefix webui run build
```

Python 源码包和 wheel：

```bash
PROTEIN_WORKBENCH_UI_TOOLCHAIN="$PWD/webui" .venv/bin/python -m build --no-isolation
```

产物分别位于 `webui/dist/` 和 `dist/`。

## 验证

公共应用、HTTP 文件交付及轻量模型资源锁测试：

```bash
.venv/bin/python -m pytest tests -q
```

真实模型验证统一使用 [模型验证入口](docs/local-models.md)，所有 worktree 共用机器级资源锁。
