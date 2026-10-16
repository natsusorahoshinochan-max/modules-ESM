"""Execute installed Provider selectors and require their declared retained Runs."""

from __future__ import annotations

import os
from pathlib import Path

from verification.acceptance_campaign import acceptance_tier
from verification.installed_cases import REQUIRED_PROVIDER_CASES
from tests.providers.installed_harness import (
    InstalledArtifact,
    run_external_acceptance,
)
from tests.providers.retained_evidence import require_retained_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_installed_provider_case(
    installed: InstalledArtifact,
    tmp_path: Path,
    case: str,
) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PW_SOURCE_ROOT"] = str(PROJECT_ROOT)
    if case == "soluprot":
        configured_root = Path(env["PROTEIN_WORKBENCH_SOLUPROT_ROOT"])
        spaced_root = tmp_path / "SoluProt Provider Root With Spaces"
        spaced_root.symlink_to(configured_root, target_is_directory=True)
        env["PROTEIN_WORKBENCH_SOLUPROT_ROOT"] = str(spaced_root)
    if case in {"biohub_esm3", "biohub_esmfold2"}:
        token_file = Path(
            env["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"]
        )
        env["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"] = str(token_file)
    if case == "simplefold_folding":
        env["PROTEIN_WORKBENCH_PROVIDER_IDENTITY_PROFILE"] = (
            "simplefold-v2-folding"
        )
    elif case == "simplefold_confidence":
        env["PROTEIN_WORKBENCH_PROVIDER_IDENTITY_PROFILE"] = (
            "simplefold-v2-confidence"
        )
    run_external_acceptance(
        installed,
        tmp_path,
        selectors=REQUIRED_PROVIDER_CASES[case],
        environment=env,
        timeout_seconds={
            "local_esmfold2": 90 * 60,
            "proteinmpnn": 60 * 60,
        }.get(case, 30 * 60),
    )
    require_configured_installed_evidence()


def require_configured_installed_evidence() -> None:
    configured = os.environ.get(
        "PROTEIN_WORKBENCH_ACCEPTANCE_EVIDENCE_STAGING"
    )
    if configured is None:
        return
    tier = os.environ["PROTEIN_WORKBENCH_VERIFICATION_TIER"]
    contract = acceptance_tier(tier)
    require_retained_evidence(
        Path(configured),
        required_runs=contract.required_run_labels,
        lifecycle_required=contract.lifecycle_receipt_required,
    )
