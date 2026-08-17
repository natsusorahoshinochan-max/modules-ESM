计划确定：采用替换式迁移，不保留旧 Evidence schema、兼容层、第三种 writer 或新的通用状态机。Annotation 1

## 阶段 1：先建立 RED 合同

修改 [test_acceptance_evidence_contract.py](/Users/sorachan/Documents/modules-ESM/tests/test_acceptance_evidence_contract.py)：

- Service projection/event 未通过公共 validator 时，必须在写文件前失败。
- REST client 验证后的 metadata 必须逐字段原样保存。
- 全部 15 个 acceptance tiers 必须声明非空 Run labels。
- 四个 fresh tiers 必须使用与 installed tiers 相同的最小目录结构。
- 旧 root-level bundle、manifest、run-index 或 checksum 出现时失败。
- 核心 suite 继续保持 5 秒以内。

## 阶段 2：修复 validate-once 链

修改：

- [public_protocol_acceptance_client.py](/Users/sorachan/Documents/modules-ESM/tests/public_protocol_acceptance_client.py)
- [retained_evidence.py](/Users/sorachan/Documents/modules-ESM/tests/acceptance/retained_evidence.py)
- 7 个 Service acceptance 文件中的 13 个调用点

具体做法：

1. `PublicProtocolAcceptanceClient.typed_value()` 返回已经验证的 metadata 与 payload，不再只返回 bytes。
2. `retain_rest_run()` 原样保存该 metadata，删除 `_digest()` 和 descriptor 重建。
3. `retain_service_run()` 在 Adapter seam 使用现有公共 validator 对 projection/events 验证一次，然后交给内部 writer。
4. `_retain_run()` 只写文件，不导入 validator、不解释协议、不计算协议 digest。
5. 所有调用继续放在科学断言之后。

不新增 `ValidatedRunManager`、通用 port、策略对象或兼容签名。

## 阶段 3：收紧 tier contract

修改 [acceptance_verification.py](/Users/sorachan/Documents/modules-ESM/modules/acceptance_verification.py)：

- 删除 `required_run_labels=()` 默认值。
- 15 个 tiers 全部显式声明 labels。
- Fresh labels 固定为：

  - `fresh-1pga`
  - `fresh-2emo`
  - `fresh-canonical-3gb1`
  - `fresh-5g53`

- 将 `require_installed_evidence()` 重命名为适用于所有 tiers 的 `require_retained_evidence()`。
- 快速测试不再使用 `startswith("installed-")` 过滤。

## 阶段 4：迁移四个 source-bound tiers

目标路径统一为：

```text
evidence/
  catalog-snapshot.json
  public-protocol.json
  runs/<tier-label>/
    projection.json
    events.json
    typed-values.json
    artifacts.json
    values/*
    artifacts/*
  model-lifecycle.json
  tier-result.json
```

实施顺序：

1. 将 source-bound 运行驱动迁入现有 installed external-test harness。
2. 公共协议验证完成后执行原有科学断言。
3. 科学断言全部通过后调用同一个 `retain_service_run()` 或 `retain_rest_run()`。
4. Campaign 已冻结 source revision、Workflow digest、Profile 和 artifacts，因此不再保留：

   - `source-bound-receipt.json`
   - `source-receipt.json`
   - `workflow.json`
   - `workflow-commit.json`
   - `run-admission.json`
   - `manifest.json`
   - `run-index.json`
   - `verification.json`

5. 2EMO 只保留三项 lifecycle receipt。观察逻辑放入 pytest-scoped fixture，用 `monkeypatch` 自动恢复；不增加生产 observer Interface。

## 阶段 5：删除旧实现

迁移完成后直接删除或清空其旧 Evidence 职责：

- [fresh_source_bound.py](/Users/sorachan/Documents/modules-ESM/scripts/fresh_source_bound.py)
- [fresh_remote_3gb1.py](/Users/sorachan/Documents/modules-ESM/scripts/fresh_remote_3gb1.py)

同步删除：

- checksum writer/validator
- symlink/path扫描
- protocol、Catalog、event closure 二次验证
- 旧 bundle validator 测试
- 针对旧 manifest/run-index 的测试
- [test_installed_backend_v2.py](/Users/sorachan/Documents/modules-ESM/tests/test_installed_backend_v2.py:445) 中的 AST import-shape 测试

必要的科学断言保留并迁移，不因删除 Evidence validator 而删除科学验收。

## 阶段 6：保持不变的部分

不修改：

- `scripts/verify_backend.py`
- Campaign 状态机和目录 digest
- Execution Profile 格式
- ProteinMPNN installed gate-wide cache
- ProteinMPNN `close()` 成功/异常语义
- installed Certification selector
- 凭据脱敏和 durable write

## 验证顺序

1. 新 RED/GREEN Evidence tests，要求低于 5 秒
2. affected provider-free acceptance tests
3. ProteinMPNN implementation/Adapter tests
4. routine
5. examples-v2
6. deterministic-acceptance
7. scientific-repro
8. local-esmfold2-v2-contract
9. installed-package
10. profile-backed provider-isolation
11. security-failure
12. frontend lint/build
13. compileall、diff check、旧 schema 残留搜索
14. 使用 Execution Profile 运行全部 15 个真实 Qualification tiers
15. 全部 Qualification 通过后，才允许开始新的 Certification generation

退出条件是：仓库只剩一个 Evidence schema、一个内部 writer、两种真实 Adapter、一个 Campaign digest，且不存在旧 checksum、manifest、run-index、二次协议 validator 或 AST 结构测试。
