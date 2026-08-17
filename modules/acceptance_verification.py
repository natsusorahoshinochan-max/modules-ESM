"""Module-owned contracts for one complete frozen acceptance generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AcceptanceTierContract:
    """One exact zero-skip, clean-source, retained-evidence tier."""

    pytest_arguments: tuple[str, ...]
    timeout_seconds: int
    required_run_labels: tuple[str, ...]
    lifecycle_receipt_required: bool


INSTALLED_PROVIDER_TIER_ORDER = (
    "installed-biohub-esmc",
    "installed-biohub-esm3",
    "installed-biohub-esmfold2",
    "installed-local-esm3",
    "installed-local-esmfold2",
    "installed-mkdssp",
    "installed-proteinmpnn",
    "installed-simplefold-folding",
    "installed-simplefold-confidence",
    "installed-soluprot",
    "installed-protein-sol",
)
SOURCE_BOUND_TIER_ORDER = (
    "fresh-1pga",
    "fresh-2emo",
    "fresh-canonical-3gb1",
    "fresh-5g53",
)
ACCEPTANCE_TIER_ORDER = (
    *INSTALLED_PROVIDER_TIER_ORDER,
    *SOURCE_BOUND_TIER_ORDER,
)


def _contract(
    selector: str,
    timeout_seconds: int = 30 * 60,
    *,
    required_run_labels: tuple[str, ...] = (),
    lifecycle_receipt_required: bool = False,
) -> AcceptanceTierContract:
    return AcceptanceTierContract(
        (selector,),
        timeout_seconds,
        required_run_labels,
        lifecycle_receipt_required,
    )


ACCEPTANCE_TIER_CONTRACTS = {
    "installed-biohub-esmc": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_biohub_esmc_gate"
        ),
        required_run_labels=("biohub-esmc",),
    ),
    "installed-biohub-esm3": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_biohub_esm3_gate"
        ),
        40 * 60,
        required_run_labels=(
            "biohub-medium-generate-sequence",
            "biohub-medium-generate-structure",
            "biohub-medium-generate-paired",
            "biohub-open-generate-sequence",
            "biohub-open-generate-structure",
            "biohub-open-generate-paired",
        ),
    ),
    "installed-biohub-esmfold2": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_biohub_esmfold2_gate"
        ),
        35 * 60,
        required_run_labels=("biohub-esmfold2",),
    ),
    "installed-local-esm3": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_local_esm3_gate"
        ),
        required_run_labels=(
            "local-esm3-generate-paired",
            "local-esm3-generate-sequence",
            "local-esm3-generate-structure",
        ),
    ),
    "installed-local-esmfold2": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_local_esmfold2_gate"
        ),
        105 * 60,
        required_run_labels=("local-esmfold2",),
    ),
    "installed-mkdssp": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_mkdssp_gate"
        ),
        required_run_labels=("mkdssp",),
    ),
    "installed-proteinmpnn": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_proteinmpnn_gate"
        ),
        75 * 60,
        required_run_labels=(
            "proteinmpnn-design",
            "proteinmpnn-score",
            "proteinmpnn-native-score",
            "proteinmpnn-sibling-design",
        ),
        lifecycle_receipt_required=True,
    ),
    "installed-simplefold-folding": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_simplefold_folding_gate"
        ),
        required_run_labels=("simplefold-folding",),
    ),
    "installed-simplefold-confidence": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_simplefold_confidence_gate"
        ),
        required_run_labels=("simplefold-confidence",),
    ),
    "installed-soluprot": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_soluprot_gate"
        ),
        required_run_labels=("soluprot-full", "soluprot-no-tm"),
    ),
    "installed-protein-sol": _contract(
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_protein_sol_gate"
        ),
        required_run_labels=("protein-sol",),
    ),
    "fresh-1pga": _contract(
        (
            "tests/test_fresh_source_bound_acceptance_v2.py::"
            "test_fresh_1pga_installed_public_run_retains_auditable_bundle"
        ),
        120 * 60,
    ),
    "fresh-2emo": _contract(
        (
            "tests/test_fresh_source_bound_acceptance_v2.py::"
            "test_fresh_2emo_installed_public_run_retains_auditable_bundle"
        ),
        180 * 60,
        lifecycle_receipt_required=True,
    ),
    "fresh-canonical-3gb1": _contract(
        (
            "tests/test_fresh_remote_3gb1_v2.py::"
            "test_fresh_remote_3gb1_installed_public_run_"
            "retains_auditable_bundle"
        ),
        90 * 60,
    ),
    "fresh-5g53": _contract(
        (
            "tests/test_fresh_source_bound_acceptance_v2.py::"
            "test_fresh_5g53_installed_public_run_retains_auditable_bundle"
        ),
        180 * 60,
    ),
}

if tuple(ACCEPTANCE_TIER_CONTRACTS) != ACCEPTANCE_TIER_ORDER:
    raise RuntimeError("acceptance tier contracts are not in exact order")
