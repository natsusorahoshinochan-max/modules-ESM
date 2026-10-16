# 新业务行为测试

这里的测试依据当前需求重新编写，不继承已废弃的测试体系或门禁。每个业务切片只运行相关的新测试；不将测试通过等同于整个规格完成。

## 模块结果读取

仓库根目录，使用已安装应用依赖及 httpx 的 Python 3.12 环境：

```sh
.venv/bin/python -m unittest discover -s tests -p test_result_readers.py
```

覆盖公共 HTTP 的自定义值执行、应用重开、注册读取、原值保持和默认查看器声明。测试使用临时数据目录，不调用 Provider。

## 模块查看器

安装 `webui/package-lock.json` 的依赖和 Playwright Chromium（首次需要）：

```sh
cd webui
npm ci
npx playwright install chromium
npm run build:module-ui
```

在仓库根目录准备独立临时应用目录；不要指向用户项目目录：

```sh
export WORKBENCH_TEST_DATA=$(mktemp -d)
.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
root = Path(os.environ['WORKBENCH_TEST_DATA'])
root.joinpath('modules.json').write_text(json.dumps({'packages': [
    {'package_id': 'reader_demo', 'package_module': 'reader_module',
     'enabled': True, 'source_root': str(Path('tests').resolve())},
    {'package_id': 'protein_io', 'package_module': 'modules.protein_io.package',
     'enabled': True, 'source_root': None},
]}))
PY
PROTEIN_WORKBENCH_DATA_ROOT="$WORKBENCH_TEST_DATA" .venv/bin/python -m uvicorn protein_workbench_public.bootstrap:create_application --factory --port 8188
```

另一个终端启动正常应用前端：

```sh
cd webui
PROTEIN_WORKBENCH_BACKEND_URL=http://127.0.0.1:8188 npm run dev -- --port 5188 --host 127.0.0.1
```

在 `webui/` 执行当前结果查看器切片：

```sh
WORKBENCH_TEST_URL=http://127.0.0.1:5188 npx playwright test tests/result-viewers.spec.ts --workers=1 --reporter=line --output=/tmp/workbench-reader-test-results
```

测试通过公共 HTTP 准备项目和运行，再操作完整应用 UI。覆盖外部温度值、官方结构的默认展示和切换、原始值不变、重开，以及外部同名读取 kind 不被误解为蛋白类型。无全局配置、后台矩阵或旧夹具。该入口不覆盖 Provider 计算、候选分页迁移或其他业务切片。
