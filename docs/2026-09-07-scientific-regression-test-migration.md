# 科学回归测试覆盖位置

依据：[测试归属规格](2026-09-07-scientific-regression-test-ownership-spec.md)。以下列出当前 owner 与科学行为覆盖。

## 来源结构

| 当前 owner / 用例 | 覆盖 |
|---|---|
| `test_prompt_structure_source_v2.py` / `test_2emo_csh_normalization_preserves_parent_span_and_builds_prompt` | axis 细节由现有 residue-axis owner 集中覆盖，见下文 |
| `test_prompt_structure_source_v2.py` / `test_2emo_raw_modified_polymer_is_rejected_at_residue_axis_seam` | 保留科学输入与断言 |
| `test_prompt_structure_source_v2.py` / `test_5g53_identity_insertions_preserve_every_modeled_residue_and_track` | 保留科学输入与断言 |

## Prompt 合同

| 当前 owner / 用例 | 覆盖 |
|---|---|
| `test_prompt_authoring_document_v2.py` / `test_public_and_catalog_authoring_documents_share_nested_contracts` | 保留科学输入与断言 |
| `test_prompt_authoring_recipe_v2.py` / `test_primary_source_is_optional_but_never_ambiguous` | 保留科学输入与断言 |
| `test_prompt_authoring_recipe_v2.py` / `test_sequence_source_uses_document_chains_without_fasta_header_identity` | 保留科学输入与断言 |
| `test_protein_io_v2.py` / `test_fasta_parser_leaves_empty_sequence_rejection_to_port_admission` | 保留科学输入与断言 |
| `test_prompt_authoring_recipe_v2.py` / `test_sequence_source_preserves_existing_identity_and_checks_chain_layout` | 保留科学输入与断言 |
| `test_prompt_authoring_recipe_v2.py` / `test_target_layout_can_delete_or_insert_but_cannot_reorder_source` | 保留科学输入与断言 |
| `test_prompt_authoring_recipe_v2.py` / `test_optional_track_clear_preserves_present_all_null_state` | 保留科学输入与断言 |
| `test_prompt_authoring_recipe_v2.py` / `test_annotations_use_layout_order_and_explicit_empty_replaces` | 保留科学输入与断言 |
| `test_prompt_authoring_recipe_v2.py` / `test_merge_requires_complete_monotone_correspondence_and_keeps_target_gaps` | 保留科学输入与断言 |
| `test_prompt_authoring_recipe_v2.py` / `test_merge_rejects_absent_adopt_and_partial_annotation_mapping` | 保留科学输入与断言 |
| `test_residue_track_closure_v2.py` / `test_protein_prompt_codec_normalizes_only_sasa_json_integers` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_open_random_trace_matches_preview` | same-seed-successive-insertions：链长 2，两次 seed 5；核对实际 trace |
| `test_structure_annotation_v2.py` / `test_observed_annotation_subject_must_reference_structure` | 保留非法 protein.sequence subject；通过实际 owning Port 的 `validate` 验证科学准入 |

## Prompt 公共接口

| 当前 owner / 用例 | 覆盖 |
|---|---|
| `test_prompt_authoring_public_v2.py` / `test_matching_assembly_control` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_preview_accepts_repositioned_explicit_insertion` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_preview_rejects_annotation_layout_mismatch_like_runtime` | 固定来源 HTTP 400；实际 Run 拒绝，核对 Preview 不写 Draft |
| `test_prompt_authoring_public_v2.py` / `test_preview_preserves_connected_absent_optional_tracks` | 读取实际 assemble/edit Typed Outputs 的两个 absent tracks |
| `test_prompt_authoring_public_v2.py` / `test_preview_can_repair_stale_sequence_chain_declaration` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_fasta_source_must_be_admitted_before_overrides` | 固定来源 HTTP 400；保留 source Run 失败，核对 Preview 不写 Draft |
| `test_prompt_authoring_public_v2.py` / `test_other_assembly_layout_mismatches_are_diagnosed` | 保留 coordinates/secondary_structure/SASA 三组输入，固定 Layout 错误 HTTP 400 并检查 Preview 不写 Draft |
| `test_prompt_authoring_public_v2.py` / `test_present_all_null_assembly_control` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_random_insert_axis_change_variant` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_merge_order_and_revision_conflict` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_annotation_contract_has_no_overlap_policy` | touching × explicit/inherited/merged；保留原输入和来源连接，并执行 Apply → Run |
| `test_prompt_authoring_public_v2.py` / `test_upstream_author_document_uses_owning_schema` | 保留 composition_id schema 拒绝与 Commit 422，错误指向 source Document 字段 |
| `test_prompt_authoring_public_v2.py` / `test_projection_axis_obeys_candidate_order` | 真实 Preview 覆盖四组 before/after/expected 与 tombstone 断言 |
| `test_prompt_authoring_public_v2.py` / `test_order_change_and_apply_preserve_identity` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_ordinary_deletion_does_not_report_order_change` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_annotation_contract_has_no_overlap_policy` | nested × explicit/inherited/merged；与 touching 组共享 setup，保留 blank explicit 场景 |
| `test_prompt_authoring_public_v2.py` / `test_duplicate_annotation_is_rejected_without_deduplication` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_deleted_overlap_policy_is_not_admitted` | 保留科学输入与断言 |
| `test_prompt_authoring_public_v2.py` / `test_open_random_trace_matches_preview` | 保留 single-insertion（链长 3、seed 42），并接收双操作场景 |

## 集中覆盖边界

- 2EMO journey 中的 224-residue layout、单 A segment、精确 A:64–A:68 顺序、SHG、
  CA/backbone masks 和 CA 坐标由 `test_structure_transform_residue_axis_v2.py` 的
  `test_2emo_normalization_repairs_parent_span_topology_and_masks` 覆盖，包括
  A:64–A:65 间无 TER 的检查及 chain ID。journey 继续验证 normalization output、
  mapping / component disposition、精确 Prompt 残基与 sequence，并检查 Prompt 与
  实际 resolved axis 的 layout / sequence 一致。
- `test_prompt_assemble_materialize_v2.py` 的 `test_assemble_fails_on_layout_mismatch`、
  `test_decompose_carries_authoritative_layout`、`test_decompose_omits_absent_optional_tracks`
  保留直接 owner 契约；公共 Layout 负例仍运行真实 Workflow，公共 absent 正例额外读取
  assemble 与 edit 的真实 Typed Output 检查 secondary_structure 和 SASA 均 absent。
- 公共 Preview / Open 覆盖参数化科学输入、operation trace 和显式 handle → residue ID 关联。
- annotation 覆盖 touching / nested 与三种来源共六组输入，分别核对 exact labels、annotation 数量及 nested explicit 的无来源路径。
- 来源错误由 Preview 的 structured error、Draft 不变和实际 Run 来源节点失败覆盖。
  Apply 直接保存已确认结果；`test_merge_order_and_revision_conflict` 覆盖一次 Draft revision 冲突。
