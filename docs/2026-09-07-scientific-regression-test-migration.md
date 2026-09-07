# 科学回归测试迁移记录

依据：`2026-09-07-scientific-regression-test-ownership-spec.md`。以下按原用例记录去向；参数化输入随用例迁移，未以测试数量减少作为验收指标。

## test_workflow_usability_repairs_v2.py

| 原用例 | 当前 owner / 用例 | 处理 |
|---|---|---|
| `test_2emo_csh_normalization_preserves_parent_span_and_builds_prompt` | `test_prompt_structure_source_v2.py` / `test_2emo_csh_normalization_preserves_parent_span_and_builds_prompt` | 迁移；axis 细节由现有 residue-axis owner 集中覆盖，见下文 |
| `test_2emo_raw_modified_polymer_is_rejected_at_residue_axis_seam` | `test_prompt_structure_source_v2.py` / `test_2emo_raw_modified_polymer_is_rejected_at_residue_axis_seam` | 迁移，保留科学输入与断言 |
| `test_5g53_identity_insertions_preserve_every_modeled_residue_and_track` | `test_prompt_structure_source_v2.py` / `test_5g53_identity_insertions_preserve_every_modeled_residue_and_track` | 迁移，保留科学输入与断言 |

## test_prompt_authoring_contract_repairs_v2.py

| 原用例 | 当前 owner / 用例 | 处理 |
|---|---|---|
| `test_public_and_catalog_authoring_documents_share_nested_contracts` | `test_prompt_authoring_document_v2.py` / `test_public_and_catalog_authoring_documents_share_nested_contracts` | 迁移，保留科学输入与断言 |
| `test_primary_source_is_optional_but_never_ambiguous` | `test_prompt_authoring_recipe_v2.py` / `test_primary_source_is_optional_but_never_ambiguous` | 迁移，保留科学输入与断言 |
| `test_sequence_source_uses_document_chains_without_fasta_header_identity` | `test_prompt_authoring_recipe_v2.py` / `test_sequence_source_uses_document_chains_without_fasta_header_identity` | 迁移，保留科学输入与断言 |
| `test_fasta_parser_leaves_empty_sequence_rejection_to_port_admission` | `test_protein_io_v2.py` / `test_fasta_parser_leaves_empty_sequence_rejection_to_port_admission` | 迁移，保留科学输入与断言 |
| `test_sequence_source_preserves_existing_identity_and_checks_chain_layout` | `test_prompt_authoring_recipe_v2.py` / `test_sequence_source_preserves_existing_identity_and_checks_chain_layout` | 迁移，保留科学输入与断言 |
| `test_target_layout_can_delete_or_insert_but_cannot_reorder_source` | `test_prompt_authoring_recipe_v2.py` / `test_target_layout_can_delete_or_insert_but_cannot_reorder_source` | 迁移，保留科学输入与断言 |
| `test_optional_track_clear_preserves_present_all_null_state` | `test_prompt_authoring_recipe_v2.py` / `test_optional_track_clear_preserves_present_all_null_state` | 迁移，保留科学输入与断言 |
| `test_annotations_use_layout_order_and_explicit_empty_replaces` | `test_prompt_authoring_recipe_v2.py` / `test_annotations_use_layout_order_and_explicit_empty_replaces` | 迁移，保留科学输入与断言 |
| `test_merge_requires_complete_monotone_correspondence_and_keeps_target_gaps` | `test_prompt_authoring_recipe_v2.py` / `test_merge_requires_complete_monotone_correspondence_and_keeps_target_gaps` | 迁移，保留科学输入与断言 |
| `test_merge_rejects_absent_adopt_and_partial_annotation_mapping` | `test_prompt_authoring_recipe_v2.py` / `test_merge_rejects_absent_adopt_and_partial_annotation_mapping` | 迁移，保留科学输入与断言 |
| `test_protein_prompt_codec_normalizes_only_sasa_json_integers` | `test_residue_track_closure_v2.py` / `test_protein_prompt_codec_normalizes_only_sasa_json_integers` | 迁移，保留科学输入与断言 |
| `test_random_insert_identity_and_trace_include_operation_index` | `test_prompt_authoring_public_v2.py` / `test_open_random_trace_matches_preview` | same-seed-successive-insertions：链长 2，两次 seed 5；以实际 trace 替代 ID 格式 |
| `test_observed_annotation_subject_must_reference_structure` | `test_structure_annotation_v2.py` / `test_observed_annotation_subject_must_reference_structure` | 保留非法 protein.sequence subject；通过实际 owning Port codec admission 验证 |

## test_prompt_authoring_review_regressions_v2.py

| 原用例 | 当前 owner / 用例 | 处理 |
|---|---|---|
| `test_matching_assembly_control` | `test_prompt_authoring_public_v2.py` / `test_matching_assembly_control` | 迁移，保留科学输入与断言 |
| `test_preview_accepts_repositioned_explicit_insertion` | `test_prompt_authoring_public_v2.py` / `test_preview_accepts_repositioned_explicit_insertion` | 迁移，保留科学输入与断言 |
| `test_preview_rejects_annotation_layout_mismatch_like_runtime` | `test_prompt_authoring_public_v2.py` / `test_preview_rejects_annotation_layout_mismatch_like_runtime` | 迁移并固定来源 HTTP 400；删除私有 assembly 重复控制，保留实际 Run 拒绝，新增 Apply 不写入 |
| `test_preview_preserves_connected_absent_optional_tracks` | `test_prompt_authoring_public_v2.py` / `test_preview_preserves_connected_absent_optional_tracks` | 迁移；删除私有 assembly 控制，改读实际 assemble/edit Typed Outputs 的两个 absent tracks |
| `test_preview_can_repair_stale_sequence_chain_declaration` | `test_prompt_authoring_public_v2.py` / `test_preview_can_repair_stale_sequence_chain_declaration` | 迁移，保留科学输入与断言 |
| `test_fasta_source_must_be_admitted_before_overrides` | `test_prompt_authoring_public_v2.py` / `test_fasta_source_must_be_admitted_before_overrides` | 迁移并固定来源 HTTP 400；保留 source Run 失败，新增 Apply 不写入 |
| `test_other_assembly_layout_mismatches_are_diagnosed` | `test_prompt_authoring_public_v2.py` / `test_other_assembly_layout_mismatches_are_diagnosed` | 保留 coordinates/secondary_structure/SASA 三组输入，固定 Layout 错误 HTTP 400 并检查 Apply 不写入 |
| `test_present_all_null_assembly_control` | `test_prompt_authoring_public_v2.py` / `test_present_all_null_assembly_control` | 迁移，保留科学输入与断言 |
| `test_random_insert_axis_change_variant` | `test_prompt_authoring_public_v2.py` / `test_random_insert_axis_change_variant` | 迁移，保留科学输入与断言 |
| `test_merge_order_and_digest_control` | `test_prompt_authoring_public_v2.py` / `test_merge_order_and_digest_control` | 迁移，保留科学输入与断言 |
| `test_overlapping_annotations_across_sources` | `test_prompt_authoring_public_v2.py` / `test_annotation_contract_has_no_overlap_policy` | touching × explicit/inherited/merged；保留原输入和来源连接，并执行 Apply → Run |
| `test_upstream_author_document_uses_owning_schema` | `test_prompt_authoring_public_v2.py` / `test_upstream_author_document_uses_owning_schema` | 保留 composition_id schema 拒绝与 Commit 422，错误指向 source Document 字段 |
| `test_projection_axis_obeys_candidate_order` | `test_prompt_authoring_public_v2.py` / `test_projection_axis_obeys_candidate_order` | 改写为真实 Preview，完整保留四组 before/after/expected 与 tombstone 断言 |
| `test_order_change_and_apply_preserve_identity` | `test_prompt_authoring_public_v2.py` / `test_order_change_and_apply_preserve_identity` | 迁移，保留科学输入与断言 |
| `test_ordinary_deletion_does_not_report_order_change` | `test_prompt_authoring_public_v2.py` / `test_ordinary_deletion_does_not_report_order_change` | 迁移，保留科学输入与断言 |
| `test_annotation_contract_has_no_overlap_policy` | `test_prompt_authoring_public_v2.py` / `test_annotation_contract_has_no_overlap_policy` | nested × explicit/inherited/merged；与 touching 组共享 setup，保留 blank explicit 场景 |
| `test_duplicate_annotation_is_rejected_without_deduplication` | `test_prompt_authoring_public_v2.py` / `test_duplicate_annotation_is_rejected_without_deduplication` | 迁移，保留科学输入与断言 |
| `test_deleted_overlap_policy_is_not_admitted` | `test_prompt_authoring_public_v2.py` / `test_deleted_overlap_policy_is_not_admitted` | 迁移，保留科学输入与断言 |
| `test_open_random_trace_matches_preview` | `test_prompt_authoring_public_v2.py` / `test_open_random_trace_matches_preview` | 保留 single-insertion（链长 3、seed 42），并接收双操作场景 |

## 删除与集中覆盖的依据

- 2EMO journey 中的 224-residue layout、单 A segment、精确 A:64–A:68 顺序、SHG、
  CA/backbone masks 和 CA 坐标由 `test_structure_transform_residue_axis_v2.py` 的
  `test_2emo_normalization_repairs_parent_span_topology_and_masks` 覆盖；本轮补入
  A:64–A:65 间无 TER 的检查及 chain ID。journey 继续验证 normalization output、
  mapping / component disposition、精确 Prompt 残基与 sequence，并检查 Prompt 与
  实际 resolved axis 的 layout / sequence 一致。
- 删除公共测试内重复的 `_DecomposeOperation` / `_AssembleOperation` 控制段。
  `test_prompt_assemble_materialize_v2.py` 的 `test_assemble_fails_on_layout_mismatch`、
  `test_decompose_carries_authoritative_layout`、`test_decompose_omits_absent_optional_tracks`
  保留直接 owner 契约；公共 Layout 负例仍运行真实 Workflow，公共 absent 正例额外读取
  assemble 与 edit 的真实 Typed Output 检查 secondary_structure 和 SASA 均 absent。
- 私有 `_display_axis` 与 `_evaluate_prompt_recipe` 调用由现有公共 Preview / Open
  interface 替代，保留原参数化科学输入。`:masked.` 解析与固定生成 ID 格式没有当前
  科学契约依据，以 operation trace 和显式 handle → residue ID 关联替代。
- 两组 annotation 场景合并仅消除 setup 重复；touching / nested 与三种来源共六组
  仍分别收集，保留 exact labels、annotation 数量及 nested explicit 的无来源路径。
- 删除 cloud-only 错误说明、print 和诊断性条件 Apply。两类来源错误改为确定的拒绝
  测试；无有效 Preview 时用 schema 合法的 Apply 请求，并验证错误仍是来源拒绝、Draft
  不变，不把无效请求或 digest mismatch 当作科学错误覆盖。

三份历史文件和唯一的跨测试 `_Call` / `_Port` / `_Value` 导入已删除。原测试文件名没有
被显式 verification selector 或其他测试导入；现有门禁仍通过目录收集接收 owner。
