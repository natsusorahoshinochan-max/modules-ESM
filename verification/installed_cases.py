"""Exact inner selectors for installed Provider gates.

The Campaign selects outer gates; each outer gate delegates to this one table.
"""

REQUIRED_PROVIDER_CASES = {
    "biohub_esm3": (
        (
            "tests/providers/test_installed_provider_gates_v2.py::"
            "test_biohub_esm3_all_remote_bindings_execute_exact_methods"
        ),
    ),
    "biohub_esmfold2": (
        (
            "tests/providers/test_installed_provider_gates_v2.py::"
            "test_biohub_esmfold2_executes_exact_method"
        ),
    ),
    "local_esm3": (
        (
            "tests/providers/test_local_esm3.py::"
            "test_local_esm3_all_generation_modes"
        ),
    ),
    "local_esmfold2": (
        (
            "tests/providers/test_installed_provider_gates_v2.py::"
            "test_local_esmfold2_executes_exact_method"
        ),
    ),
    "proteinmpnn": (
        (
            "tests/providers/test_installed_provider_gates_v2.py::"
            "test_proteinmpnn_design_and_score_execute_exact_methods"
        ),
        (
            "tests/providers/test_proteinmpnn_scoring_v2.py::"
            "test_proteinmpnn_v2_scoring_publishes_exact_native_observation"
        ),
        (
            "tests/providers/test_proteinmpnn_scoring_v2.py::"
            "test_proteinmpnn_v2_sibling_design_remains_exact_and_complete"
        ),
        (
            "tests/modules/proteinmpnn/test_proteinmpnn_v2.py::"
            "test_design_projects_canonical_axis_into_provider_safe_structure"
        ),
        (
            "tests/modules/proteinmpnn/test_proteinmpnn_v2.py::"
            "test_scoring_stages_numbering_gaps_and_preserves_backbone_mask"
        ),
        (
            "tests/modules/proteinmpnn/test_proteinmpnn_v2.py::"
            "test_design_and_score_preserve_same_chain_segment_topology"
        ),
        (
            "tests/modules/proteinmpnn/test_proteinmpnn_v2.py::"
            "test_provider_staging_capacity_counts_segments_not_workbench_"
            "chains"
        ),
    ),
    "mkdssp": (
        (
            "tests/providers/test_installed_provider_gates_v2.py::"
            "test_mkdssp_executes_exact_method_through_public_run"
        ),
    ),
    "simplefold_folding": (
        (
            "tests/providers/test_simplefold_v2.py::"
            "test_simplefold_v2_folds_3gb1_through_exact_binding"
        ),
    ),
    "simplefold_confidence": (
        (
            "tests/providers/test_simplefold_confidence_v2.py::"
            "test_simplefold_confidence_v2_evaluates_3gb1_exact_assets_"
            "without_refold"
        ),
    ),
    "soluprot": (
        (
            "tests/providers/test_soluprot_v2.py::"
            "test_model_backed_soluprot_golden_methods"
        ),
    ),
    "protein_sol": (
        (
            "tests/providers/test_protein_sol_v2.py::"
            "test_local_protein_sol_golden_multiple_metrics"
        ),
    ),
}
