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

测试通过公共 HTTP 准备项目和运行，再操作完整应用 UI。覆盖外部温度值、官方结构的默认展示和切换、原始值不变、重开，以及外部同名读取 kind 不被误解为蛋白类型。无全局配置、后台矩阵或旧夹具。该入口不覆盖 Provider 计算；候选分页和组合展示见下方官方查看器切片。

## 模块设置

在仓库根目录执行公共 API 切片：

```sh
.venv/bin/python -m unittest discover -s tests -p test_module_settings.py
```

界面测试使用启用官方模块的正常应用及独立临时数据目录，不使用上面的 `reader_demo` 清单。启动正常后端和前端后，在 `webui/` 运行：

```sh
WORKBENCH_TEST_URL=http://127.0.0.1:5188 npx playwright test tests/module-settings.spec.ts --workers=1 --reporter=line --output=/tmp/workbench-settings-test-results
```

覆盖设置保存、重开、实际调用取值及缺少配置时阻止 Provider 执行；界面操作不替代 Provider 行为证明。

## ESMFold2 主动续算

在仓库根目录执行公共 Run 与官方 SDK 调用边界的受控失败切片：

```sh
.venv/bin/python -m unittest discover -s tests -p test_esmfold2_continuation.py
```

覆盖批内失败保留结果、下游阻断、独立分支、服务重开继续、首请求及再次失败、候选与置信度身份保持、改参后新计算。SDK 返回受控响应，不运行模型或请求真实 Biohub。

续算界面测试使用单场景服务替换 SDK 边界，应用本身与公共设置、项目、Run 接口保持正常。每次执行该界面测试前重新启动该服务，以重置受控失败序列；使用独立临时数据目录，不使用 `reader_demo` 清单：

```sh
PROTEIN_WORKBENCH_DATA_ROOT="$(mktemp -d)" PYTHONPATH=. .venv/bin/python tests/serve_continuation.py
```

等后端显示启动完成，再在另一个终端启动前端：

```sh
cd webui
PROTEIN_WORKBENCH_BACKEND_URL=http://127.0.0.1:8191 npm run dev -- --port 5191 --host 127.0.0.1
```

在 `webui/` 执行：

```sh
WORKBENCH_TEST_URL=http://127.0.0.1:5191 npx playwright test tests/continue-batch.spec.ts --workers=1 --reporter=line --output=/tmp/workbench-continuation-test-results
```

覆盖用户主动继续原 Run、保留未保存的画布布局、无自动保存及完成后移除继续入口。受控 SDK 测试不能证明真实线上调用或模型结果质量。

## 历史结果采用

采用界面测试使用启用官方模块的正常应用和独立临时数据目录；后端与前端启动方式同模块设置，地址通过 `WORKBENCH_TEST_URL` 指定。在 `webui/` 执行：

```sh
WORKBENCH_TEST_URL=http://127.0.0.1:5193 npx playwright test tests/result-adoption.spec.ts --workers=1 --reporter=line --output=/tmp/workbench-adoption-test-results
```

通过公共 API 准备一个真实序列导入结果，再操作应用选择来源项目、历史运行与结果值。覆盖采用后只添加未保存来源节点、不自动连线，以及手动保存后重新打开；不调用模型。另一个界面切片永久删除来源项目后运行已采用输入，实际下载 ZIP 并核对原始计算参数，防止把采用节点的输入引用误写成原计算；同一结果页加载后再禁用来源模块也覆盖该导出行为。采用 API 测试还用确定性结构导入、残基轴、比对与 TM-score 路径覆盖真实 pairwise 依赖：永久删除来源后重开，保留两侧轴与原比对值，直接下游排序且 Candidate 身份不变。

## 未保存编辑提醒

启用官方模块的正常应用使用独立临时数据目录，启动后在 `webui/` 执行：

```sh
WORKBENCH_TEST_URL=http://127.0.0.1:5194 npx playwright test tests/unsaved-exit.spec.ts --workers=1 --reporter=line --output=/tmp/workbench-exit-test-results
```

覆盖未保存布局切换项目时仅放弃或取消；取消保留编辑，放弃后原保存内容不被改写。使用公共 API 准备未完成流程，不调用模型。浏览器原生提醒的触发条件由浏览器控制。

## 官方序列与 Prompt 查看器

使用启用默认官方模块的独立临时应用目录（不用 reader_demo 清单），正常启动后端和前端；在 `webui/` 运行：

```sh
WORKBENCH_TEST_URL=http://127.0.0.1:5199 npx playwright test tests/official-readers.spec.ts --workers=1 --reporter=line --output=/tmp/workbench-official-readers
```

通过公共接口导入序列或创建空白 Prompt 后执行，完整应用中打开模块查看器并重新打开项目。检查序列原值不变及 Prompt 残基分页、Mask 和整轨缺失区别；候选面板跨页勾选、比较与 Workflow 往返；确定性结构对齐和 RMSD 结果的角色、单位、变换、来源及重开。只运行确定性模块，不调用 Provider。

候选读取公共 action 的应用重开、分页顺序/引用及结构原文切片：

```sh
.venv/bin/python -m unittest discover -s tests -p test_candidate_reading.py
```

## ESMC 可选数值

`.venv/bin/python -m unittest discover -s tests -p test_esmc_values.py` 通过公共 Run 和受控官方 SDK 边界覆盖 embedding-only、logits-only、both 的请求选择、CLS/EOS 去除、持久值重开读取及传入外部下游模块。受控数值不证明模型质量。

应用界面切片使用 `PYTHONPATH=. PROTEIN_WORKBENCH_DATA_ROOT="$(mktemp -d)" .venv/bin/python tests/serve_esmc.py` 启动独立受控 SDK 场景（8196）。前端以 `PROTEIN_WORKBENCH_BACKEND_URL=http://127.0.0.1:8196 npm run dev -- --port 5196 --host 127.0.0.1` 启动；在 `webui/` 执行 `WORKBENCH_TEST_URL=http://127.0.0.1:5196 npx playwright test tests/esmc-values.spec.ts --workers=1 --reporter=line --output=/tmp/esmc-viewer-results`。覆盖查看实际数值、切换残基位置和刷新重开；不会调用真实 Provider。

## ESM3 批内继续

```sh
.venv/bin/python -m unittest discover -s tests -p test_esm3_continuation.py
```

通过公共 Run API 与受控官方 SDK 响应覆盖序列、结构、联合生成的主动继续、重开、首请求失败、再次失败、重建结构与置信度保留、下游阻断和参数变化后的新计算。不加载本地模型，不向线上服务注入故障。

## 结构构象选择与拆分

`.venv/bin/python -m unittest discover -s tests -p test_structure_conformers.py` 覆盖公共输入检查、PDB/mmCIF 选择和拆分、来源身份、重开、拒绝未选/不存在的模型，以及真实残基轴下游对单构象的读取。不调用模型。

使用独立临时数据目录启动正常应用后端及前端（启用默认模块），在 `webui/` 执行 `WORKBENCH_TEST_URL=http://127.0.0.1:5206 npx playwright test tests/structure-conformers.spec.ts --workers=1 --reporter=line --output=/tmp/conformers-results`。覆盖完整来源界面的单文件上传、构象勾选、保存重开，以及 Prompt 来源构象与链的对应。

## SimpleFold 定义失败与批内续算

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_simplefold_*.py'
```

不启动本地模型。`test_simplefold_failures.py` 用受控官方 `run_inference` 调用验证明确的 Torch 内存异常分类及普通程序错误原样传播。`simplefold_controlled.py` 是显式测试模块：装配生产 SimpleFold Operation 和受控 Adapter，仅证明公共 Run 的失败停止、完成请求保存、重开续算、首请求与重复失败、候选身份与 seed 保持；它不证明真实 LocalAdapter 激活、资产加载或模型结果。

## 可组合 Top-k 范围

`.venv/bin/python -m pytest tests/test_topk_scopes.py -q` 通过公共 API 执行整批及按骨架范围的 Top-k。独立导入序列与结构，使用普通关系操作表达评价对象；显式外部测试模块提供四个已知评分，不调用 Provider。覆盖完整 Candidate 和骨架关联保持、同一评分源复用，以及缺少本范围必需评分时对应筛选失败、已评分分支仍成功。

## Provider 参数传递

```sh
.venv/bin/python -m unittest discover -s tests -p test_provider_parameters.py
```

仅使用现有 Python 3.12、httpx、Torch 和固定 ESM/SimpleFold SDK。覆盖 Biohub ESM3 两阶段各自的非默认生成设置、远程 ESMFold2 六项推理参数、本地 ESMFold2 builder 的路线参数与 null 值，以及 SimpleFold wrapper 的 tau 和大于50的步数。公共 Catalog 同时确认独立 confidence 不声明采样参数。

远程调用用官方 SDK 边界替身；本地 ESMFold2 的模型/CCD 加载由外部边界替代，SimpleFold 在 wrapper 构造入口记录参数后立即停止。不会加载重模型或发送网络请求，不表示本地 ESM-3、ESMFold2、SimpleFold 真实模型已运行，也不覆盖完整界面编辑链。
