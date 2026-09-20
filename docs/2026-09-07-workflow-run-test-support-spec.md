# Workflow / Run 测试辅助代码收敛

- 状态：已确认
- 日期：2026-09-07
- 领域词汇：`../CONTEXT.md`
- 前置成果：`2026-09-07-contract-test-kit-spec.md`

## 1. 范围与职责

公共 Workflow / Run 测试通过共享 module 复用提交 Workflow、启动 Run、等待终态和
读取输出的编排。请求构造、响应验证和 Typed Output 读取各自保留单一 implementation，
使用现有 public protocol bundle 与 validators。

测试拥有科学输入、Workflow 场景、预期终态、输出科学含义以及证据关系的断言。
共享 module 检查操作所需的协议响应、读取完整性和等待超时；不能把进入任意合法终态
等同于执行成功。等待允许返回 succeeded、failed、cancelled 或 interrupted。
针对错误请求或协议拒绝行为的测试继续直接调用被测 interface，观察完整响应。

runtime 与 Contract Test Kit 使用各自的 seam。Kit 已确认的单 case 生命周期与目标
Node 证据职责保持独立。生产科学行为、Workflow Commit admission、公共协议及
Run Evidence Ledger 因果规则仍由现有 owner 定义。

## 2. Interface 与资源生命周期

共享 module 接收测试已经创建好的客户端。应用、隔离存储、客户端、执行 gate 和
故障注入资源由测试持有；共享操作不隐式创建或关闭它们。

提交、启动、等待和读取均可独立调用。提交返回实际 Workflow Commit 回执，启动
返回实际 Run 回执，等待返回实际公共 projection，读取返回对应的实际输出字节及
必要的协议元数据。普通流程可以组合这些操作；取消、并发、Cache 和重启测试可以
在操作之间控制执行。request identity、Commit identity 与超时由所属调用者明确提供
或采用现有明确默认值，不隐式重写 Workflow identity、保存 Draft、重新提交或重试。

返回结果沿用现有协议表示，保留输出顺序、exact Port、value index、content identity
和 Artifact reference。公共 canonical envelope 读取与实际 Port codec 解码保持明确
区别；科学值解码使用所属契约。不能用新的结果摘要替代实际 projection 或 evidence。
读取依赖测试持有的资源仍然可用；本 module 不提供 Kit 式的自动清理后结果快照。

## 3. 两条实际使用的等待路径

进程内 TestClient adapter 保留当前等待方式：通过 runtime 等待持久化终态，再经
公共 interface 读取并验证终态 projection。此同步方式不声明验证了网络事件传输。

真实安装验收 adapter 保留 HTTP 轮询 projection 的等待方式，事件验收另通过真实
WebSocket 收集并验证消息。它只依赖公共协议和网络客户端，不导入 backend
implementation、不访问 app.state。保留现有显式超时与 loopback 网络配置。

两条路径复用公共请求、响应与输出读取 implementation，等待差异留在各自 adapter。
事件测试拥有连接、重放、游标、断线与终态的场景断言，以及消息 envelope、
事件顺序和收集终点的含义。

## 4. 共享 runtime 场景归属

`tests/fixtures/run_scenarios.py` 拥有共享的 contract、direct、pipeline、artifact
Catalog fixtures，以及配套的单 Node、独立 Nodes、artifact 和 pipeline Workflow 场景。
`tests/test_run_runtime.py` 与以下消费者使用这些 fixtures：

- `tests/test_run_cancel_derive_v2.py`
- `tests/test_result_cache_v2.py`
- `tests/test_managed_local_process_v2.py`
- `tests/test_typed_value_publication_v2.py`

execution action、factory action、Readiness、randomness、Invocation count、逐 Node
gate、失败与终结控制属于测试 seam。仅服务单个 owner 的持久化失败、丢失确认等
doubles 靠近所属测试；ledger helpers 区分完整 envelope 与内层 event 的返回形状。

## 5. 边界

公共编排由第 7 节的 support modules 提供。stress 测试拥有科学场景、断言与报告；
installed 客户端只依赖公共协议，不导入 backend implementation。
直接 runtime 等待与 codec helpers 属于其实际 seam，不增加兼容转发或重复实现。
其他领域的科学场景与 doubles 保留在各自 owner。

## 6. 验收

- 提交和启动回执、Typed Output 字节及元数据继续经过现行协议检查。
- 等待不会返回 running projection；合法失败终态可以由所属测试取得并断言。
- 取消测试仍能在 start 与 wait 之间操作 gate；Cache、进程管理、重启和持久化
  故障测试保留原有被测 seam 与有效断言。
- 真实安装验收继续经过 HTTP / WebSocket；进程内同步不代替网络验收。
- 科学断言、结果身份、事件 envelope 与顺序由所属测试覆盖，包含契约负例。
- 上述四个消费者直接使用共享 fixtures，不跨测试文件导入场景。

优先运行受影响的现有测试；新增测试仅覆盖共享行为中具有实际风险且尚无有效覆盖的
契约，不为搬移或简单转发机械增加测试。随后执行：

```bash
.venv/bin/python -m verification.backend routine
.venv/bin/python -m verification.backend deterministic-acceptance
```

按现有验证契约运行受影响的真实安装与 Provider 验收；MockTransport 不代替必需的
真实验收。最终报告区分已运行门禁与尚未运行的验收，不把默认门禁通过解释为全部
Acceptance Campaign 完成。

## 7. 实施位置

- `tests/support/public_runs.py`：调用者持有客户端的公共请求、Workflow Commit、
  Run 启动、HTTP 终态等待、Typed Output / Artifact 读取与网络事件收集。
- `tests/support/inprocess_runs.py`：TestClient 持久化终态同步，以及可选的启动后
  等待组合操作。需要控制中间时机的测试继续分步调用。
- `tests/support/runtime_results.py`：直接 runtime seam 的等待与 canonical codec
  读取；明确使用既有 runtime 和 Catalog 类型。
- `tests/fixtures/run_scenarios.py`：共享 Catalog、Workflow 场景与原有故障注入参数。
