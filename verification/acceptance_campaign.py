"""One structured authority for the real-Provider Acceptance Campaign."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType
from typing import Any, Literal


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN_SCHEMA_NAMESPACE = "protein-workbench-acceptance-campaign/v3"
CAMPAIGN_DEFINITION_SCHEMA_NAMESPACE = (
    "protein-workbench-acceptance-campaign-definition/v1"
)
PROFILE_SCHEMA_NAMESPACE = (
    "protein-workbench-acceptance-execution-profile/v1"
)
TIER_EXECUTION_OUTCOME_SCHEMA_NAMESPACE = (
    "protein-workbench-acceptance-tier-execution-outcome/v1"
)
PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@dataclass(frozen=True, slots=True)
class SourceBoundAssets:
    """Exact shipped input and Workflow fixed by one source-bound tier."""

    input_path: str
    input_sha256: str
    workflow_path: str


@dataclass(frozen=True, slots=True)
class AcceptanceTier:
    """One immutable entry in the canonical Acceptance Campaign sequence."""

    name: str
    pytest_arguments: tuple[str, ...]
    timeout_seconds: int
    zero_skip: bool
    junit_required: bool
    required_run_labels: tuple[str, ...]
    lifecycle_receipt_required: bool
    environment_configuration: tuple[tuple[str, ...], ...]
    source_bound: SourceBoundAssets | None = None


def _tier(
    name: str,
    selector: str,
    *,
    required_run_labels: tuple[str, ...],
    environment_configuration: tuple[tuple[str, ...], ...],
    timeout_seconds: int = 30 * 60,
    lifecycle_receipt_required: bool = False,
    source_bound: SourceBoundAssets | None = None,
) -> AcceptanceTier:
    return AcceptanceTier(
        name=name,
        pytest_arguments=(selector,),
        timeout_seconds=timeout_seconds,
        zero_skip=True,
        junit_required=True,
        required_run_labels=required_run_labels,
        lifecycle_receipt_required=lifecycle_receipt_required,
        environment_configuration=environment_configuration,
        source_bound=source_bound,
    )


_BIOHUB = (("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",),)
_LOCAL_ESM3 = (("HF_HUB_CACHE", "HF_HOME"),)
_LOCAL_ESMFOLD2 = (
    ("PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT",),
    ("PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT",),
)
_PROTEINMPNN = (("PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",),)
_MKDSSP = (("PROTEIN_WORKBENCH_MKDSSP_BINARY",),)
_SIMPLEFOLD = (
    ("PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",),
    ("PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT",),
    ("PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT",),
)
_SOLUPROT = (("PROTEIN_WORKBENCH_SOLUPROT_ROOT",),)
_PROTEIN_SOL = (("PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT",),)


CANONICAL_ACCEPTANCE_TIERS = (
    _tier(
        "installed-biohub-esmc",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_biohub_esmc_gate"
        ),
        required_run_labels=("biohub-esmc",),
        environment_configuration=_BIOHUB,
    ),
    _tier(
        "installed-biohub-esm3",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_biohub_esm3_gate"
        ),
        timeout_seconds=40 * 60,
        required_run_labels=(
            "biohub-medium-generate-sequence",
            "biohub-medium-generate-structure",
            "biohub-medium-generate-paired",
            "biohub-open-generate-sequence",
            "biohub-open-generate-structure",
            "biohub-open-generate-paired",
        ),
        environment_configuration=_BIOHUB,
    ),
    _tier(
        "installed-biohub-esmfold2",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_biohub_esmfold2_gate"
        ),
        timeout_seconds=35 * 60,
        required_run_labels=("biohub-esmfold2",),
        environment_configuration=_BIOHUB,
    ),
    _tier(
        "installed-local-esm3",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_local_esm3_gate"
        ),
        required_run_labels=(
            "local-esm3-generate-paired",
            "local-esm3-generate-sequence",
            "local-esm3-generate-structure",
        ),
        environment_configuration=_LOCAL_ESM3,
    ),
    _tier(
        "installed-local-esmfold2",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_local_esmfold2_gate"
        ),
        timeout_seconds=105 * 60,
        required_run_labels=("local-esmfold2",),
        environment_configuration=_LOCAL_ESMFOLD2,
    ),
    _tier(
        "installed-mkdssp",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_mkdssp_gate"
        ),
        required_run_labels=("mkdssp",),
        environment_configuration=_MKDSSP,
    ),
    _tier(
        "installed-proteinmpnn",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_proteinmpnn_gate"
        ),
        timeout_seconds=75 * 60,
        required_run_labels=(
            "proteinmpnn-design",
            "proteinmpnn-score",
            "proteinmpnn-native-score",
            "proteinmpnn-sibling-design",
        ),
        lifecycle_receipt_required=True,
        environment_configuration=_PROTEINMPNN,
    ),
    _tier(
        "installed-simplefold-folding",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_simplefold_folding_gate"
        ),
        required_run_labels=("simplefold-folding",),
        environment_configuration=_SIMPLEFOLD,
    ),
    _tier(
        "installed-simplefold-confidence",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_simplefold_confidence_gate"
        ),
        required_run_labels=("simplefold-confidence",),
        environment_configuration=_SIMPLEFOLD,
    ),
    _tier(
        "installed-soluprot",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_soluprot_gate"
        ),
        required_run_labels=("soluprot-full", "soluprot-no-tm"),
        environment_configuration=_SOLUPROT,
    ),
    _tier(
        "installed-protein-sol",
        (
            "tests/test_installed_backend_v2.py::"
            "test_installed_protein_sol_gate"
        ),
        required_run_labels=("protein-sol",),
        environment_configuration=_PROTEIN_SOL,
    ),
    _tier(
        "fresh-1pga",
        (
            "tests/test_fresh_source_bound_acceptance_v2.py::"
            "test_fresh_1pga_installed_public_run_retains_auditable_bundle"
        ),
        timeout_seconds=120 * 60,
        required_run_labels=("fresh-1pga",),
        environment_configuration=(*_BIOHUB, *_SIMPLEFOLD),
        source_bound=SourceBoundAssets(
            input_path="pdbs/1PGA-75-gen1_0690.pdb",
            input_sha256=(
                "d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30"
            ),
            workflow_path="examples/v2/source-bound-1pga.workflow.json",
        ),
    ),
    _tier(
        "fresh-2emo",
        (
            "tests/test_fresh_source_bound_acceptance_v2.py::"
            "test_fresh_2emo_installed_public_run_retains_auditable_bundle"
        ),
        timeout_seconds=180 * 60,
        required_run_labels=("fresh-2emo",),
        lifecycle_receipt_required=True,
        environment_configuration=(*_BIOHUB, *_PROTEINMPNN, *_PROTEIN_SOL),
        source_bound=SourceBoundAssets(
            input_path="pdbs/2EMO.pdb",
            input_sha256=(
                "6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700"
            ),
            workflow_path="examples/v2/source-bound-2emo.workflow.json",
        ),
    ),
    _tier(
        "fresh-canonical-3gb1",
        (
            "tests/test_fresh_remote_3gb1_v2.py::"
            "test_fresh_remote_3gb1_installed_public_run_"
            "retains_auditable_bundle"
        ),
        timeout_seconds=90 * 60,
        required_run_labels=("fresh-canonical-3gb1",),
        environment_configuration=(*_BIOHUB, *_PROTEINMPNN),
        source_bound=SourceBoundAssets(
            input_path="pdbs/3GB1.pdb",
            input_sha256=(
                "ee623d3d9fd77a131895dc367c31ac8d7266b1d4f241b56325170e5f62ed7811"
            ),
            workflow_path="examples/v2/canonical-3gb1.workflow.json",
        ),
    ),
    _tier(
        "fresh-5g53",
        (
            "tests/test_fresh_source_bound_acceptance_v2.py::"
            "test_fresh_5g53_installed_public_run_retains_auditable_bundle"
        ),
        timeout_seconds=180 * 60,
        required_run_labels=("fresh-5g53",),
        environment_configuration=_BIOHUB,
        source_bound=SourceBoundAssets(
            input_path="pdbs/5G53.pdb",
            input_sha256=(
                "a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537"
            ),
            workflow_path="examples/v2/source-bound-5g53.workflow.json",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    """Private Environment Configuration for one Acceptance Campaign."""

    provider_configuration: Mapping[str, str]
    proxy_policy: str

    def __post_init__(self) -> None:
        if self.proxy_policy not in {"direct", "inherit"}:
            raise RuntimeError("acceptance remote transport policy is invalid")
        if not all(
            isinstance(name, str) and isinstance(value, str) and value
            for name, value in self.provider_configuration.items()
        ):
            raise RuntimeError("acceptance Provider configuration is invalid")
        allowed = {
            name
            for tier in CANONICAL_ACCEPTANCE_TIERS
            for alternatives in tier.environment_configuration
            for name in alternatives
        }
        configured_names = set(self.provider_configuration)
        if configured_names - allowed:
            raise RuntimeError(
                "acceptance Provider configuration names are invalid"
            )
        if any(
            len(configured_names.intersection(alternatives)) != 1
            for tier in CANONICAL_ACCEPTANCE_TIERS
            for alternatives in tier.environment_configuration
        ):
            raise RuntimeError(
                "acceptance Provider configuration requirements are incomplete"
            )
        expanded_paths = {
            name: Path(value).expanduser()
            for name, value in self.provider_configuration.items()
        }
        if any(not path.is_absolute() for path in expanded_paths.values()):
            raise RuntimeError(
                "acceptance Provider configuration requires absolute paths"
            )
        object.__setattr__(
            self,
            "provider_configuration",
            MappingProxyType({
                name: str(
                    path
                    if name == "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"
                    else path.resolve()
                )
                for name, path in expanded_paths.items()
            }),
        )

    @classmethod
    def load(cls, path: Path) -> ExecutionProfile:
        document = json.loads(path.expanduser().read_text(encoding="utf-8"))
        if not isinstance(document, dict) or set(document) != {
            "schema_namespace",
            "provider_configuration",
            "remote_transport",
        }:
            raise RuntimeError("acceptance execution profile shape is invalid")
        if document["schema_namespace"] != PROFILE_SCHEMA_NAMESPACE:
            raise RuntimeError("acceptance execution profile schema is invalid")
        remote_transport = document["remote_transport"]
        if (
            not isinstance(remote_transport, dict)
            or set(remote_transport) != {"proxy_policy"}
        ):
            raise RuntimeError("acceptance remote transport shape is invalid")
        provider_configuration = document["provider_configuration"]
        if not isinstance(provider_configuration, dict):
            raise RuntimeError("acceptance Provider configuration shape is invalid")
        return cls(
            provider_configuration=provider_configuration,
            proxy_policy=remote_transport["proxy_policy"],
        )

    def _base_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        controlled = {
            name
            for name in environment
            if name.startswith("PROTEIN_WORKBENCH_")
        }
        controlled.update({
            "HF_HUB_CACHE",
            "HF_HOME",
            "PYTHONPATH",
            "PYTEST_ADDOPTS",
        })
        for name in controlled:
            environment.pop(name, None)
        if self.proxy_policy == "direct":
            for name in PROXY_VARIABLES:
                environment.pop(name, None)
        return environment

    def environment_for(self, tier: AcceptanceTier) -> dict[str, str]:
        """Project only the Environment Configuration declared by one tier."""
        environment = self._base_environment()
        for alternatives in tier.environment_configuration:
            for name in alternatives:
                if name in self.provider_configuration:
                    environment[name] = self.provider_configuration[name]
        return environment

    def complete_environment(self) -> dict[str, str]:
        """Project the full profile for preparation or repository checks."""
        environment = self._base_environment()
        environment.update(self.provider_configuration)
        return environment

    def public_definition(self) -> dict[str, Any]:
        """Describe the bound profile without persisting private paths."""
        private_document = {
            "schema_namespace": PROFILE_SCHEMA_NAMESPACE,
            "provider_configuration": dict(self.provider_configuration),
            "remote_transport": {"proxy_policy": self.proxy_policy},
        }
        return {
            "content_digest": "sha256:"
            + hashlib.sha256(_canonical_bytes(private_document)).hexdigest(),
            "provider_configuration_names": sorted(
                self.provider_configuration
            ),
            "remote_transport": {"proxy_policy": self.proxy_policy},
        }


@dataclass(frozen=True, slots=True)
class TierExecutionOutcome:
    """Structured child handoff admitted once by the Campaign."""

    tier: str
    source_revision: str
    retained_location: str
    conclusion: Literal["passed", "failed", "interrupted"]
    tests: int
    failures: int
    skipped: int
    retained_run_labels: tuple[str, ...]
    lifecycle_receipt_retained: bool
    junit_retained: bool
    diagnostic_files: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "retained_run_labels",
            tuple(self.retained_run_labels),
        )
        object.__setattr__(
            self,
            "diagnostic_files",
            tuple(self.diagnostic_files),
        )
        if self.conclusion not in {"passed", "failed", "interrupted"}:
            raise ValueError("tier execution conclusion is invalid")
        if not all(
            type(value) is str and value
            for value in (
                self.tier,
                self.source_revision,
                self.retained_location,
            )
        ):
            raise ValueError("tier execution outcome identity is invalid")
        if any(
            type(value) is not int or value < 0
            for value in (self.tests, self.failures, self.skipped)
        ):
            raise ValueError("tier execution counts are invalid")
        if (
            len(set(self.retained_run_labels))
            != len(self.retained_run_labels)
            or not all(self.retained_run_labels)
        ):
            raise ValueError("retained Run labels are invalid")
        if (
            type(self.lifecycle_receipt_retained) is not bool
            or type(self.junit_retained) is not bool
            or not all(
                type(value) is str and value
                for value in self.diagnostic_files
            )
        ):
            raise ValueError("tier execution outcome retained facts are invalid")

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_namespace": TIER_EXECUTION_OUTCOME_SCHEMA_NAMESPACE,
            "tier": self.tier,
            "source_revision": self.source_revision,
            "retained_location": self.retained_location,
            "conclusion": self.conclusion,
            "tests": self.tests,
            "failures": self.failures,
            "skipped": self.skipped,
            "retained_run_labels": list(self.retained_run_labels),
            "lifecycle_receipt_retained": (
                self.lifecycle_receipt_retained
            ),
            "junit_retained": self.junit_retained,
            "diagnostic_files": list(self.diagnostic_files),
        }

    @classmethod
    def from_document(cls, document: object) -> TierExecutionOutcome:
        if not isinstance(document, dict) or set(document) != {
            "schema_namespace",
            "tier",
            "source_revision",
            "retained_location",
            "conclusion",
            "tests",
            "failures",
            "skipped",
            "retained_run_labels",
            "lifecycle_receipt_retained",
            "junit_retained",
            "diagnostic_files",
        }:
            raise RuntimeError("tier execution outcome shape is invalid")
        if document["schema_namespace"] != (
            TIER_EXECUTION_OUTCOME_SCHEMA_NAMESPACE
        ):
            raise RuntimeError("tier execution outcome schema is invalid")
        run_labels = document["retained_run_labels"]
        diagnostic_files = document["diagnostic_files"]
        if (
            not isinstance(run_labels, list)
            or not isinstance(diagnostic_files, list)
        ):
            raise RuntimeError("tier execution outcome container shape is invalid")
        return cls(
            tier=document["tier"],
            source_revision=document["source_revision"],
            retained_location=document["retained_location"],
            conclusion=document["conclusion"],
            tests=document["tests"],
            failures=document["failures"],
            skipped=document["skipped"],
            retained_run_labels=tuple(run_labels),
            lifecycle_receipt_retained=document[
                "lifecycle_receipt_retained"
            ],
            junit_retained=document["junit_retained"],
            diagnostic_files=tuple(diagnostic_files),
        )


def acceptance_tier(name: str) -> AcceptanceTier:
    """Return one canonical tier by exact identity."""
    for tier in CANONICAL_ACCEPTANCE_TIERS:
        if tier.name == name:
            return tier
    raise KeyError(name)


def acceptance_definition() -> dict[str, Any]:
    """Project the immutable canonical tier sequence for preparation."""
    return {
        "schema_namespace": CAMPAIGN_DEFINITION_SCHEMA_NAMESPACE,
        "tiers": [
            {
                "name": tier.name,
                "pytest_arguments": list(tier.pytest_arguments),
                "timeout_seconds": tier.timeout_seconds,
                "zero_skip": tier.zero_skip,
                "junit_required": tier.junit_required,
                "required_run_labels": list(tier.required_run_labels),
                "lifecycle_receipt_required": (
                    tier.lifecycle_receipt_required
                ),
                "environment_configuration": [
                    list(names)
                    for names in tier.environment_configuration
                ],
                "source_bound": (
                    None
                    if tier.source_bound is None
                    else {
                        "input_path": tier.source_bound.input_path,
                        "input_sha256": tier.source_bound.input_sha256,
                        "workflow_path": tier.source_bound.workflow_path,
                    }
                ),
            }
            for tier in CANONICAL_ACCEPTANCE_TIERS
        ],
    }


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        + b"\n"
    )


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_bytes(_canonical_bytes(manifest))


def _git_authority() -> tuple[str, bool]:
    revision = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["/usr/bin/git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    )
    return revision, dirty


def _validate_source_bound_assets() -> None:
    for tier in CANONICAL_ACCEPTANCE_TIERS:
        source_bound = tier.source_bound
        if source_bound is None:
            continue
        input_path = PROJECT_ROOT / source_bound.input_path
        if hashlib.sha256(input_path.read_bytes()).hexdigest() != (
            source_bound.input_sha256
        ):
            raise RuntimeError(
                f"Acceptance Campaign input digest changed: {tier.name}"
            )
        if not (PROJECT_ROOT / source_bound.workflow_path).is_file():
            raise RuntimeError(
                f"Acceptance Campaign Workflow is missing: {tier.name}"
            )


def _candidate_definition(
    artifact_root: Path,
) -> dict[str, dict[str, str]]:
    wheels = tuple(artifact_root.glob("*.whl"))
    sdists = tuple(artifact_root.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError(
            "acceptance campaign requires exactly one wheel and one sdist"
        )
    return {
        kind: {
            "path": (Path("artifacts") / artifact.name).as_posix(),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
        for kind, artifact in (("wheel", wheels[0]), ("sdist", sdists[0]))
    }


def prepare_campaign(
    root: Path,
    profile: ExecutionProfile,
) -> dict[str, Any]:
    """Build and bind the candidate for one clean Acceptance Campaign."""
    revision, dirty = _git_authority()
    if dirty:
        raise RuntimeError("acceptance campaign requires a clean source revision")
    if root.exists():
        raise RuntimeError("acceptance campaign root already exists")
    _validate_source_bound_assets()
    artifact_root = root / "artifacts"
    artifact_root.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "verification.build",
            str(artifact_root),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        env=profile.complete_environment(),
    )
    manifest = {
        "schema_namespace": CAMPAIGN_SCHEMA_NAMESPACE,
        "source_revision": revision,
        "candidate": _candidate_definition(artifact_root),
        "definition": acceptance_definition(),
        "execution_profile": profile.public_definition(),
        "state": "prepared",
        "executions": [],
    }
    _write_manifest(root / "campaign.json", manifest)
    return manifest


class _TierOutcomeAdmissionError(RuntimeError):
    pass


def write_tier_execution_outcome(
    path: Path,
    outcome: TierExecutionOutcome,
) -> None:
    """Publish one structured child handoff at the Campaign-owned seam."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(outcome.to_document()))


def _load_tier_execution_outcome(path: Path) -> TierExecutionOutcome:
    try:
        return TierExecutionOutcome.from_document(
            json.loads(path.read_bytes())
        )
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as error:
        raise _TierOutcomeAdmissionError(
            "acceptance tier returned an invalid structured outcome"
        ) from error


def _load_campaign(root: Path) -> dict[str, Any]:
    document = json.loads((root / "campaign.json").read_bytes())
    if not isinstance(document, dict) or set(document) != {
        "schema_namespace",
        "source_revision",
        "candidate",
        "definition",
        "execution_profile",
        "state",
        "executions",
    }:
        raise RuntimeError("acceptance campaign shape is invalid")
    if document["schema_namespace"] != CAMPAIGN_SCHEMA_NAMESPACE:
        raise RuntimeError("acceptance campaign schema is invalid")
    candidate = document["candidate"]
    if (
        not isinstance(candidate, dict)
        or set(candidate) != {"wheel", "sdist"}
        or not all(
            isinstance(entry, dict)
            and set(entry) == {"path", "sha256"}
            and isinstance(entry["path"], str)
            and isinstance(entry["sha256"], str)
            for entry in candidate.values()
        )
    ):
        raise RuntimeError("acceptance campaign candidate is invalid")
    if not isinstance(document["executions"], list):
        raise RuntimeError("acceptance campaign executions are invalid")
    return document


def _run_tier(
    root: Path,
    tier: AcceptanceTier,
    environment: Mapping[str, str],
) -> TierExecutionOutcome:
    env = dict(environment)
    env["PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT"] = str(
        root / "results"
    )
    env["PROTEIN_WORKBENCH_FROZEN_ARTIFACT_DIR"] = str(root / "artifacts")
    env["PROTEIN_WORKBENCH_ACCEPTANCE_CAMPAIGN_ROOT"] = str(root)
    outcome_path = root / "child-outcomes" / f"{tier.name}.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "verification.backend",
            "--acceptance-outcome",
            str(outcome_path),
            tier.name,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(completed.stdout, end="", flush=True)
    if not outcome_path.is_file():
        raise _TierOutcomeAdmissionError(
            f"acceptance tier did not return a structured outcome: {tier.name}"
        )
    return _load_tier_execution_outcome(outcome_path)


def _admit_tier_outcome(
    root: Path,
    tier: AcceptanceTier,
    source_revision: str,
    outcome: TierExecutionOutcome,
    *,
    started_at: str,
    ended_at: str,
) -> dict[str, Any]:
    if outcome.tier != tier.name or outcome.source_revision != source_revision:
        raise _TierOutcomeAdmissionError(
            "tier execution outcome identity does not match the Campaign"
        )
    relative_location = Path(outcome.retained_location)
    if (
        relative_location.is_absolute()
        or len(relative_location.parts) != 2
        or relative_location.parts[0] != tier.name
        or ".." in relative_location.parts
        or relative_location.as_posix() != outcome.retained_location
    ):
        raise _TierOutcomeAdmissionError(
            "tier execution retained location is invalid"
        )
    retained_root = root / "results" / relative_location
    if not retained_root.is_dir():
        raise _TierOutcomeAdmissionError(
            "tier execution retained location is missing"
        )
    evidence_root = retained_root / "evidence"
    for run_label in outcome.retained_run_labels:
        run_label_path = Path(run_label)
        if (
            run_label_path.is_absolute()
            or run_label_path.parts != (run_label,)
            or run_label == ".."
        ):
            raise _TierOutcomeAdmissionError(
                "tier execution Run label is invalid"
            )
        if not (evidence_root / "runs" / run_label).is_dir():
            raise _TierOutcomeAdmissionError(
                "tier execution Run label is not retained"
            )
    if outcome.lifecycle_receipt_retained and not (
        evidence_root / "model-lifecycle.json"
    ).is_file():
        raise _TierOutcomeAdmissionError(
            "tier execution lifecycle receipt is not retained"
        )
    if outcome.junit_retained and not (retained_root / "pytest.xml").is_file():
        raise _TierOutcomeAdmissionError(
            "tier execution JUnit result is not retained"
        )
    diagnostic_paths = tuple(
        Path(diagnostic) for diagnostic in outcome.diagnostic_files
    )
    if any(
        diagnostic.is_absolute()
        or diagnostic.parts != (source,)
        or source == ".."
        for source, diagnostic in zip(
            outcome.diagnostic_files,
            diagnostic_paths,
            strict=True,
        )
    ):
        raise _TierOutcomeAdmissionError(
            "tier execution diagnostic location is invalid"
        )
    if any(
        not (retained_root / diagnostic).is_file()
        for diagnostic in diagnostic_paths
    ):
        raise _TierOutcomeAdmissionError(
            "tier execution diagnostic is not retained"
        )

    complete = (
        outcome.conclusion == "passed"
        and outcome.tests > 0
        and outcome.failures == 0
        and (not tier.zero_skip or outcome.skipped == 0)
        and set(tier.required_run_labels).issubset(
            outcome.retained_run_labels
        )
        and (
            not tier.lifecycle_receipt_required
            or outcome.lifecycle_receipt_retained
        )
        and (not tier.junit_required or outcome.junit_retained)
    )
    if outcome.conclusion == "passed" and not complete:
        raise _TierOutcomeAdmissionError(
            "passed tier execution is structurally incomplete"
        )

    retained_location = (Path("results") / relative_location).as_posix()
    verification_summary = {
        "tests": outcome.tests,
        "failures": outcome.failures,
        "skipped": outcome.skipped,
    }
    acceptance_result = (
        {
            "tier": tier.name,
            "source_revision": source_revision,
            "retained_location": retained_location,
            "required_run_labels": list(tier.required_run_labels),
            "lifecycle_receipt": (
                (
                    Path(retained_location)
                    / "evidence"
                    / "model-lifecycle.json"
                ).as_posix()
                if tier.lifecycle_receipt_required
                else None
            ),
            "junit": (
                (Path(retained_location) / "pytest.xml").as_posix()
                if tier.junit_required
                else None
            ),
            "verification_summary": verification_summary,
        }
        if complete
        else None
    )
    return {
        "tier": tier.name,
        "conclusion": outcome.conclusion,
        "started_at": started_at,
        "ended_at": ended_at,
        "retained_location": retained_location,
        "retained_run_labels": list(outcome.retained_run_labels),
        "lifecycle_receipt_retained": (
            outcome.lifecycle_receipt_retained
        ),
        "junit_retained": outcome.junit_retained,
        "verification_summary": verification_summary,
        "diagnostics": [
            (Path(retained_location) / path).as_posix()
            for path in outcome.diagnostic_files
        ],
        "acceptance_result": acceptance_result,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def run_campaign(
    root: Path,
    profile: ExecutionProfile,
) -> dict[str, Any]:
    """Execute the bound candidate once in exact canonical serial order."""
    manifest = _load_campaign(root)
    if manifest["state"] != "prepared":
        raise RuntimeError("acceptance campaign already started")
    if manifest["definition"] != acceptance_definition():
        raise RuntimeError("acceptance campaign definition changed after prepare")
    if manifest["execution_profile"] != profile.public_definition():
        raise RuntimeError("acceptance execution profile changed after prepare")
    candidate_paths = {
        kind: root / entry["path"]
        for kind, entry in manifest["candidate"].items()
    }
    if any(
        Path(entry["path"]).parts[:1] != ("artifacts",)
        or len(Path(entry["path"]).parts) != 2
        or not candidate_paths[kind].is_file()
        for kind, entry in manifest["candidate"].items()
    ):
        raise RuntimeError("acceptance campaign candidate is missing")
    if any(
        hashlib.sha256(candidate_paths[kind].read_bytes()).hexdigest()
        != entry["sha256"]
        for kind, entry in manifest["candidate"].items()
    ):
        raise RuntimeError("acceptance campaign candidate changed after prepare")
    revision, dirty = _git_authority()
    if dirty or revision != manifest["source_revision"]:
        raise RuntimeError(
            "acceptance campaign candidate revision changed after prepare"
        )

    manifest["state"] = "running"
    _write_manifest(root / "campaign.json", manifest)
    try:
        for tier in CANONICAL_ACCEPTANCE_TIERS:
            started_at = _now()
            try:
                outcome = _run_tier(
                    root,
                    tier,
                    profile.environment_for(tier),
                )
                execution = _admit_tier_outcome(
                    root,
                    tier,
                    manifest["source_revision"],
                    outcome,
                    started_at=started_at,
                    ended_at=_now(),
                )
            except _TierOutcomeAdmissionError:
                manifest["state"] = "failed"
                _write_manifest(root / "campaign.json", manifest)
                raise
            manifest["executions"].append(execution)
            if outcome.conclusion == "failed":
                manifest["state"] = "failed"
                _write_manifest(root / "campaign.json", manifest)
                raise RuntimeError(f"acceptance tier failed: {tier.name}")
            if outcome.conclusion == "interrupted":
                manifest["state"] = "interrupted"
                _write_manifest(root / "campaign.json", manifest)
                raise RuntimeError(f"acceptance tier interrupted: {tier.name}")
            _write_manifest(root / "campaign.json", manifest)
    except BaseException:
        if manifest["state"] == "running":
            manifest["state"] = "interrupted"
            _write_manifest(root / "campaign.json", manifest)
        raise

    if len(manifest["executions"]) != len(CANONICAL_ACCEPTANCE_TIERS) or any(
        execution["acceptance_result"] is None
        for execution in manifest["executions"]
    ):
        manifest["state"] = "failed"
        _write_manifest(root / "campaign.json", manifest)
        raise RuntimeError("acceptance campaign is structurally incomplete")
    manifest["state"] = "passed"
    _write_manifest(root / "campaign.json", manifest)
    return manifest


def campaign_status(root: Path) -> dict[str, Any]:
    """Project Campaign completion from its admitted structured executions."""
    manifest = _load_campaign(root)
    outcomes = {
        execution["tier"]: execution["conclusion"]
        for execution in manifest["executions"]
    }
    return {
        "state": manifest["state"],
        "source_revision": manifest["source_revision"],
        "passed_tiers": sum(
            execution["acceptance_result"] is not None
            for execution in manifest["executions"]
        ),
        "total_tiers": len(CANONICAL_ACCEPTANCE_TIERS),
        "outcomes": {
            tier.name: outcomes.get(tier.name, "not_run")
            for tier in CANONICAL_ACCEPTANCE_TIERS
        },
    }
