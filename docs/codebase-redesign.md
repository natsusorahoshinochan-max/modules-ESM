不可妥协原则
科学合同、单位、形状、残基映射、随机性、lineage、provenance 和 Evidence 语义保持不变。
只验证明确合同，不重复验证公共协议和科学结论。
假设用户和开发者按预期使用；不实现攻击者、路径穿越、symlink、object-address 等防御。
保留必要的凭据脱敏、durable write 和防止意外数据丢失。
不增加兼容层、旧 schema、fallback 或双路径。
阶段 1：冻结最小 Evidence 合同
确定唯一保留结构：
evidence/
  catalog-snapshot.json
  public-protocol.json
  runs/
    <run-label>/
      projection.json
      events.json
      typed-values.json
      artifacts.json
      values/*
      artifacts/*
  model-lifecycle.json   # 仅确实需要的 tier
  tier-result.json
规则：
projection、events、Typed Values、Artifacts 来自已经通过公共协议验证的 acceptance client。
Campaign 的目录 digest 是唯一完整性 digest。
不增加 per-file manifest、二次 checksum 或事件因果验证器。
tier contract 只声明预期 Run labels 和是否需要 lifecycle receipt。
阶段 2：删除浅层和防御性实现
删除以下 11 个原型文件：
modules/_acceptance_evidence_safety.py
modules/_acceptance_installed_evidence.py
modules/_acceptance_installed_validation.py
modules/_acceptance_public_provenance.py
modules/_acceptance_resident_lifecycle.py
modules/_acceptance_resident_validation.py
modules/_acceptance_retained_runs.py
modules/_acceptance_tier_contracts.py
modules/_verification_process_control.py
modules/_verification_result_retention.py
modules/_verification_run_stages.py
将 tier inventory 直接收回 [acceptance_verification.py](/Users/sorachan/Documents/modules-ESM/modules/acceptance_verification.py)，其 Interface 仅包含：
pytest selector；
timeout；
required Run labels；
是否需要 lifecycle receipt。
同时删除原型的安全扫描、resident 状态机和 verifier 内部结构测试。
阶段 3：实现一个 test-only Evidence writer
新增一个文件：
tests/acceptance/retained_evidence.py
只提供两个真实 Adapter：
retain_service_run(...)
retain_rest_run(...)
二者共享一个内部 writer，负责：
写入已经验证的 projection/events；
通过现有 retrieval Interface 保存 Typed Values；
保存 Artifacts；
更新确定性的 Run label inventory。
writer 不加载模型、不解释 Catalog、不判断科学阈值、不验证事件 closure。
更新这些 acceptance tests，在现有科学断言全部通过后调用 writer：
Biohub ESMC/ESM-3/ESMFold2
local ESM-3/ESMFold2
ProteinMPNN public Runs
mkdssp
SimpleFold
SoluProt
Protein-Sol
阶段 4：缩减 resident-model 证明
删除通用 ResidentModelLifecycleObserver。
只记录无法由 public events 推导的事实：
{
  "model": "proteinmpnn",
  "load_count": 1,
  "release": "before-protein-sol"
}
策略：
多次 Engine Invocation 已由 public events 证明。
load_count == 1 加上多次 Invocation，即证明复用。
gate 之间的释放由 nested child exit 和 Campaign 串行执行证明。
2EMO 单独记录 ProteinMPNN release 早于 Protein-Sol 进入。
不记录对象 ID、run-to-object mapping、release policy enum 或通用 ordinal 状态机。
保留并收紧：
[ProteinMPNN implementation close (line 276)](/Users/sorachan/Documents/modules-ESM/modules/proteinmpnn/implementation.py:276)
[ProteinMPNN Adapter close (line 540)](/Users/sorachan/Documents/modules-ESM/modules/proteinmpnn/adapter.py:540)
补充小型测试，覆盖成功和异常路径都执行 close()。
阶段 5：修正 ProteinMPNN Certification selector
权威 installed ProteinMPNN tier 只运行产生公共 Run 的测试：
design Run
score Run
native-score Run
sibling-design Run
这些 direct Adapter edge-case tests 移出 Certification selector，但继续保留为非权威 Provider regression：
reversed chain layout
CSH missing-backbone case
signed insertion/gap axis
如果将来某个 edge case 必须成为 Certification criterion，应改写成公共 Run，而不是向 direct test 添加伪造 run_id。
阶段 6：恢复轻量 verifier
将 [verify_backend.py](/Users/sorachan/Documents/modules-ESM/scripts/verify_backend.py)恢复为单文件 owner，只增加必要接线：
创建 evidence staging directory；
向 pytest child 注入路径和 tier 名称；
运行 child；
记录 JUnit、exit、console；
将 evidence 原样复制到结果目录。
它不读取或重新验证 public Evidence。
Campaign 继续唯一拥有：
Execution Profile；
严格串行；
Qualification/Certification 状态；
最终目录 digest；
child lifecycle。
阶段 7：消除 ambient profile 依赖
保留现有 ExecutionProfile，不创建第二种配置格式。
在 [acceptance_campaign.py](/Users/sorachan/Documents/modules-ESM/scripts/acceptance_campaign.py)增加一个很薄的 profile-backed repository verification 命令，用 profile.environment() 串行启动最终 matrix。
这样 provider-isolation 不再从操作员 shell 继承 SoluProt 等路径，也不改变既有 Campaign 状态机。
阶段 8：替换测试，而非叠加测试
删除当前五组通用 evidence/lifecycle 测试和 unsafe probes，替换为：
tests/test_acceptance_evidence_contract.py
tests/test_proteinmpnn_operation_lifecycle.py
秒级合同测试必须覆盖：
完整 fixture：GREEN；
generic pytest-only bundle：RED；
缺 Run：RED；
缺 Typed Value：RED；
缺 Artifact：RED；
需要 lifecycle 但缺 receipt：RED；
2EMO release 顺序错误：RED。
不测试：
symlink；
traversal；
object address；
secret pattern fuzzing；
函数行数；
内部调用结构；
私有 helper 数量。
目标：核心 fixture suite 在 5 秒内完成，而不是当前的 93.86 秒。
验证顺序
实现后严格按以下顺序验证：
新的秒级 evidence/lifecycle tests；
affected acceptance provider-free tests；
ProteinMPNN implementation/Adapter tests；
routine；
examples-v2；
deterministic-acceptance；
scientific-repro；
local-esmfold2-v2-contract；
installed-package；
profile-backed provider-isolation；
security-failure；
frontend lint/build；
compileall 和 git diff --check。