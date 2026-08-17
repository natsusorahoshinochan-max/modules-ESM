#!/usr/bin/env python3
"""Own one acceptance campaign from qualification through certification."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterator, Mapping

from modules.acceptance_verification import (
    ACCEPTANCE_TIER_CONTRACTS,
    ACCEPTANCE_TIER_ORDER,
    INSTALLED_PROVIDER_TIER_ORDER,
    SOURCE_BOUND_TIER_ORDER,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN_SCHEMA_NAMESPACE = "protein-workbench-acceptance-campaign/v1"
PROFILE_SCHEMA_NAMESPACE = (
    "protein-workbench-acceptance-execution-profile/v1"
)
REPOSITORY_VERIFICATION_TIERS = (
    "routine",
    "examples-v2",
    "deterministic-acceptance",
    "scientific-repro",
    "local-esmfold2-v2-contract",
    "installed-package",
    "provider-isolation",
    "security-failure",
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

INPUT_DIGESTS = {
    "fresh-1pga": (
        "d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30"
    ),
    "fresh-2emo": (
        "6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700"
    ),
    "fresh-canonical-3gb1": (
        "ee623d3d9fd77a131895dc367c31ac8d7266b1d4f241b56325170e5f62ed7811"
    ),
    "fresh-5g53": (
        "a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537"
    ),
}


@dataclass(frozen=True, slots=True)
class SourceBoundContract:
    """One shipped source input and exact current Workflow contract."""

    input_path: str
    workflow_path: str


SOURCE_BOUND_CONTRACTS = {
    "fresh-1pga": SourceBoundContract(
        "pdbs/1PGA-75-gen1_0690.pdb",
        "examples/v2/source-bound-1pga.workflow.json",
    ),
    "fresh-2emo": SourceBoundContract(
        "pdbs/2EMO.pdb",
        "examples/v2/source-bound-2emo.workflow.json",
    ),
    "fresh-canonical-3gb1": SourceBoundContract(
        "pdbs/3GB1.pdb",
        "examples/v2/canonical-3gb1.workflow.json",
    ),
    "fresh-5g53": SourceBoundContract(
        "pdbs/5G53.pdb",
        "examples/v2/source-bound-5g53.workflow.json",
    ),
}

# These are Environment Configuration names, not Workflow parameters. The
# campaign manifest records path-free identities for their configured values;
# each tier's own Readiness contract remains the owner of exact asset admission.
PROVIDER_CONFIGURATION_CONTRACTS = {
    "installed-biohub-esmc": ("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",),
    "installed-biohub-esm3": ("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",),
    "installed-biohub-esmfold2": ("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",),
    "installed-local-esm3": ("HF_HUB_CACHE", "HF_HOME"),
    "installed-local-esmfold2": (
        "PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT",
        "PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT",
    ),
    "installed-mkdssp": ("PROTEIN_WORKBENCH_MKDSSP_BINARY",),
    "installed-proteinmpnn": ("PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",),
    "installed-simplefold-folding": (
        "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT",
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT",
    ),
    "installed-simplefold-confidence": (
        "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT",
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT",
    ),
    "installed-soluprot": ("PROTEIN_WORKBENCH_SOLUPROT_ROOT",),
    "installed-protein-sol": ("PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT",),
    "fresh-1pga": (
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",
        "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT",
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT",
    ),
    "fresh-2emo": (
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",
        "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
        "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT",
    ),
    "fresh-canonical-3gb1": (
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",
        "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
    ),
    "fresh-5g53": ("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",),
}


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    """Private local paths and transport policy for one campaign operator."""

    provider_configuration: Mapping[str, str]
    proxy_policy: str

    @classmethod
    def load(cls, path: Path) -> ExecutionProfile:
        """Load one closed-schema profile without copying it into evidence."""
        profile_path = path.expanduser().resolve(strict=True)
        if profile_path.is_relative_to(PROJECT_ROOT):
            raise RuntimeError(
                "acceptance execution profile must remain outside the repository"
            )
        document = json.loads(profile_path.read_bytes())
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
            or remote_transport["proxy_policy"] not in {"direct", "inherit"}
        ):
            raise RuntimeError("acceptance remote transport policy is invalid")
        configured = document["provider_configuration"]
        if not isinstance(configured, dict) or not all(
            isinstance(name, str) and isinstance(value, str) and bool(value)
            for name, value in configured.items()
        ):
            raise RuntimeError("acceptance Provider configuration is invalid")
        allowed = {
            variable
            for variables in PROVIDER_CONFIGURATION_CONTRACTS.values()
            for variable in variables
        }
        required = allowed - {"HF_HUB_CACHE", "HF_HOME"}
        unexpected = set(configured) - allowed
        missing = required - set(configured)
        if unexpected or missing:
            details = ", ".join(sorted((*unexpected, *missing)))
            raise RuntimeError(
                f"acceptance Provider configuration names are invalid: {details}"
            )
        hub_roots = set(configured) & {"HF_HUB_CACHE", "HF_HOME"}
        if len(hub_roots) != 1:
            raise RuntimeError(
                "acceptance profile requires exactly one Hugging Face root"
            )
        resolved = {
            name: str(Path(value).expanduser().resolve(strict=True))
            for name, value in configured.items()
        }
        return cls(
            provider_configuration=resolved,
            proxy_policy=remote_transport["proxy_policy"],
        )

    def environment(self) -> dict[str, str]:
        """Return a process environment with explicit campaign inputs."""
        environment = os.environ.copy()
        controlled_names = {
            name
            for name in environment
            if name.startswith("PROTEIN_WORKBENCH_")
        }
        controlled_names.update({
            "HF_HUB_CACHE",
            "HF_HOME",
            "PYTHONPATH",
            "PYTEST_ADDOPTS",
        })
        for variable in controlled_names:
            environment.pop(variable, None)
        environment.update(self.provider_configuration)
        if self.proxy_policy == "direct":
            for variable in PROXY_VARIABLES:
                environment.pop(variable, None)
        return environment

    def path_free_identity(
        self,
        configuration_identities: Mapping[str, Any],
    ) -> str:
        """Bind effective inputs without publishing local paths or secrets."""
        proxy_identities = {}
        if self.proxy_policy == "inherit":
            proxy_identities = {
                variable: _sha256(value.encode())
                for variable in PROXY_VARIABLES
                if (value := os.environ.get(variable)) is not None
            }
        return _sha256(_canonical_bytes({
            "schema_namespace": PROFILE_SCHEMA_NAMESPACE,
            "provider_configuration_identities": configuration_identities,
            "remote_transport": {
                "proxy_policy": self.proxy_policy,
                "ambient_proxy_identities": proxy_identities,
            },
        }))


@contextmanager
def _configured_environment(profile: ExecutionProfile) -> Iterator[None]:
    original = os.environ.copy()
    configured = profile.environment()
    os.environ.clear()
    os.environ.update(configured)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


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
    temporary = path.with_name(f".{path.name}.staging")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        payload = _canonical_bytes(manifest)
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def acceptance_definition() -> dict[str, Any]:
    """Return the source-owned campaign definition without runtime results."""
    from core import build_discovered_frozen_catalog
    from protein_workbench_public import bundle_digest

    return {
        "schema_namespace": CAMPAIGN_SCHEMA_NAMESPACE,
        "tier_order": list(ACCEPTANCE_TIER_ORDER),
        "protocol_digest": bundle_digest(),
        "catalog_contract_digest": (
            build_discovered_frozen_catalog().contract_digest
        ),
        "source_bound_inputs": dict(INPUT_DIGESTS),
        "source_bound_contracts": {
            name: {
                "input_path": contract.input_path,
                "workflow_path": contract.workflow_path,
                "workflow_content_digest": _sha256(
                    (PROJECT_ROOT / contract.workflow_path).read_bytes()
                ),
            }
            for name, contract in SOURCE_BOUND_CONTRACTS.items()
        },
        "provider_configuration_contracts": {
            name: list(variables)
            for name, variables in PROVIDER_CONFIGURATION_CONTRACTS.items()
        },
        "tier_contracts": {
            name: {
                "pytest_arguments": list(contract.pytest_arguments),
                "timeout_seconds": contract.timeout_seconds,
                "required_run_labels": list(
                    contract.required_run_labels
                ),
                "lifecycle_receipt_required": (
                    contract.lifecycle_receipt_required
                ),
                "zero_skip": True,
                "clean_source": True,
                "retain_evidence_bundle": True,
            }
            for name, contract in ACCEPTANCE_TIER_CONTRACTS.items()
        },
        "execution": {
            "child_processes": "one_at_a_time",
            "pytest_xdist": False,
            "concurrent_tiers": False,
            "nested_local_model_processes": False,
            "resident_model_instances_per_local_model": 1,
        },
    }


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


def _configuration_identities() -> dict[str, dict[str, str]]:
    from modules.provider_contract import local_esm3_snapshot_root

    identities: dict[str, dict[str, str]] = {}
    for tier_name, variables in PROVIDER_CONFIGURATION_CONTRACTS.items():
        configured: dict[str, str] = {}
        if tier_name == "installed-local-esm3":
            snapshot = local_esm3_snapshot_root().resolve(strict=True)
            if os.environ.get("HF_HUB_CACHE"):
                variable = "HF_HUB_CACHE"
            elif os.environ.get("HF_HOME"):
                variable = "HF_HOME"
            else:
                variable = "HF_HOME_DEFAULT"
            observed = snapshot.stat()
            configured[variable] = _sha256(_canonical_bytes({
                "effective_snapshot": str(snapshot),
                "filesystem_identity": {
                    "inode": observed.st_ino,
                    "mode": observed.st_mode,
                    "modified_ns": observed.st_mtime_ns,
                },
            }))
            identities[tier_name] = configured
            continue
        for variable in variables:
            value = os.environ.get(variable)
            if value is None:
                raise RuntimeError(
                    f"acceptance campaign requires explicit {variable}"
                )
            path = Path(value).expanduser().resolve(strict=True)
            observed = path.stat()
            configured[variable] = _sha256(_canonical_bytes({
                "configured_value": str(path),
                "filesystem_identity": {
                    "inode": observed.st_ino,
                    "mode": observed.st_mode,
                    "size": observed.st_size,
                    "modified_ns": observed.st_mtime_ns,
                },
            }))
        identities[tier_name] = configured
    return identities


def _provider_asset_identities() -> dict[str, Any]:
    """Resolve path-free identities for every installed local Provider asset."""
    from modules.esm3.local_adapter import (
        configured_runtime_fingerprint as local_esm3_fingerprint,
    )
    from modules.folding.adapter import (
        LOCAL_DEVICE,
        LOCAL_ESMC_REVISION,
        LOCAL_ESMFOLD2_REVISION,
        configured_local_runtime_fingerprint,
        resolve_local_runtime,
    )
    from modules.folding.simplefold_adapter import (
        SIMPLEFOLD_DEVICE,
        configured_runtime_fingerprint as simplefold_folding_fingerprint,
        validate_simplefold_folding_environment,
    )
    from modules.folding.simplefold_confidence_adapter import (
        configured_runtime_fingerprint as simplefold_confidence_fingerprint,
        validate_simplefold_confidence_environment,
    )
    from modules.folding.simplefold_contract import (
        SIMPLEFOLD_CONFIDENCE_DEVICE,
    )
    from modules.proteinmpnn.adapter import (
        PROTEINMPNN_DEVICE,
        configured_runtime_fingerprint as proteinmpnn_fingerprint,
        proteinmpnn_readiness,
    )
    from modules.provider_contract import validate_local_esm3_snapshot
    from modules.solubility.adapter import (
        configured_protein_sol_runtime_fingerprint,
        configured_runtime_fingerprint as soluprot_fingerprint,
        validate_protein_sol_environment,
        validate_soluprot_environment,
    )
    from modules.structure_annotation.adapter import (
        mkdssp_provider_identity,
        mkdssp_readiness,
    )

    def required_path(variable: str) -> Path:
        value = os.environ.get(variable)
        if value is None:
            raise RuntimeError(
                f"acceptance campaign requires explicit {variable}"
            )
        return Path(value).expanduser().resolve(strict=True)

    validate_local_esm3_snapshot.cache_clear()
    validate_local_esm3_snapshot()
    local_esmfold2_fingerprint = configured_local_runtime_fingerprint()
    resolve_local_runtime({
        "model_snapshot_path": required_path(
            "PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT"
        ),
        "model_snapshot_revision": LOCAL_ESMFOLD2_REVISION,
        "language_model_snapshot_path": required_path(
            "PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT"
        ),
        "language_model_snapshot_revision": LOCAL_ESMC_REVISION,
        "runtime_directory": PROJECT_ROOT,
        "device": LOCAL_DEVICE,
        "resolved_runtime_fingerprint": local_esmfold2_fingerprint,
    })
    proteinmpnn_identity = proteinmpnn_fingerprint()
    if not proteinmpnn_readiness({
        "device": PROTEINMPNN_DEVICE,
        "provider_root": required_path(
            "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"
        ),
        "resolved_runtime_fingerprint": proteinmpnn_identity,
    }).passing:
        raise RuntimeError("frozen ProteinMPNN assets are unavailable")
    simplefold_roots = {
        "model_root": required_path(
            "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"
        ),
        "esm2_source_root": required_path(
            "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"
        ),
        "esm2_model_root": required_path(
            "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"
        ),
    }
    simplefold_folding_identity = simplefold_folding_fingerprint()
    validate_simplefold_folding_environment({
        **simplefold_roots,
        "device": SIMPLEFOLD_DEVICE,
        "resolved_runtime_fingerprint": simplefold_folding_identity,
    })
    simplefold_confidence_identity = simplefold_confidence_fingerprint()
    validate_simplefold_confidence_environment({
        **simplefold_roots,
        "device": SIMPLEFOLD_CONFIDENCE_DEVICE,
        "resolved_runtime_fingerprint": simplefold_confidence_identity,
    })
    soluprot_root = required_path("PROTEIN_WORKBENCH_SOLUPROT_ROOT")
    soluprot_identities = {
        mode: soluprot_fingerprint(mode)
        for mode in ("full", "no_tm")
    }
    for mode, identity in soluprot_identities.items():
        soluprot_environment: dict[str, Any] = {
            "python_executable": (
                soluprot_root / "var/environments/soluprot/bin/python"
            ),
            "wheel_path": (
                soluprot_root
                / "vendor/packages/soluprot-1.1.0-py3-none-any.whl"
            ),
            "site_packages_root": (
                soluprot_root
                / "var/environments/soluprot/lib/python3.12/site-packages"
            ),
            "usearch_executable": (
                soluprot_root / "var/tools/soluprot/usearch"
            ),
            "resolved_runtime_fingerprint": identity,
        }
        if mode == "full":
            soluprot_environment.update({
                "tmhmm_root": soluprot_root / "var/tools/soluprot/tmhmm",
                "perl_executable": Path("/usr/bin/perl"),
            })
        validate_soluprot_environment(soluprot_environment, mode=mode)
    protein_sol_identity = configured_protein_sol_runtime_fingerprint()
    validate_protein_sol_environment({
        "source_root": required_path("PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT"),
        "bash_executable": Path("/bin/bash"),
        "perl_executable": Path("/usr/bin/perl"),
        "resolved_runtime_fingerprint": protein_sol_identity,
    })
    if not mkdssp_readiness({
        "dssp_binary": str(required_path("PROTEIN_WORKBENCH_MKDSSP_BINARY")),
    }).passing:
        raise RuntimeError("frozen mkdssp assets are unavailable")

    return {
        "local_esm3": local_esm3_fingerprint(device="cpu"),
        "local_esmfold2": local_esmfold2_fingerprint,
        "mkdssp": mkdssp_provider_identity(),
        "proteinmpnn": proteinmpnn_identity,
        "simplefold_folding": simplefold_folding_identity,
        "simplefold_confidence": simplefold_confidence_identity,
        "soluprot": soluprot_identities,
        "protein_sol": protein_sol_identity,
    }


def _artifact_records(root: Path) -> list[dict[str, Any]]:
    records = []
    for kind, pattern in (("wheel", "*.whl"), ("sdist", "*.tar.gz")):
        matches = tuple(root.glob(pattern))
        if len(matches) != 1:
            raise RuntimeError(f"frozen {kind} artifact is not exact")
        path = matches[0]
        payload = path.read_bytes()
        records.append({
            "kind": kind,
            "filename": path.name,
            "size": len(payload),
            "content_digest": _sha256(payload),
        })
    return records


def _directory_digest(root: Path) -> str:
    inventory = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            inventory.append({
                "path": path.relative_to(root).as_posix(),
                "content_digest": _sha256(path.read_bytes()),
            })
    return _sha256(_canonical_bytes(inventory))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def prepare_campaign(
    root: Path,
    profile: ExecutionProfile,
) -> dict[str, Any]:
    """Freeze one clean candidate for qualification and certification."""
    revision, dirty = _git_authority()
    if dirty:
        raise RuntimeError("acceptance campaign requires a clean source revision")
    if root.exists():
        raise RuntimeError("acceptance campaign root already exists")
    root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(
        prefix=f".{root.name}.staging-",
        dir=root.parent,
    ))
    staging_root.chmod(0o700)
    try:
        artifact_root = staging_root / "artifacts"
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "build_backend.py"),
                str(artifact_root),
            ],
            cwd=PROJECT_ROOT,
            check=True,
            env=profile.environment(),
        )
        with _configured_environment(profile):
            configuration_identities = _configuration_identities()
            provider_asset_identities = _provider_asset_identities()
            profile_identity = profile.path_free_identity(
                configuration_identities
            )
        definition = acceptance_definition()
        observed_revision, observed_dirty = _git_authority()
        if observed_dirty or observed_revision != revision:
            raise RuntimeError("source changed while preparing campaign")
        manifest = {
            **definition,
            "source_revision": revision,
            "source_dirty": False,
            "installed_artifacts": _artifact_records(artifact_root),
            "provider_configuration_identities": configuration_identities,
            "provider_asset_identities": provider_asset_identities,
            "execution_profile_identity": profile_identity,
            "qualification": {"attempts": []},
            "certification": {"state": "not_started", "results": []},
        }
        _write_manifest(staging_root / "campaign.json", manifest)
    except BaseException:
        shutil.rmtree(staging_root)
        raise
    os.replace(staging_root, root)
    parent_descriptor = os.open(root.parent, os.O_RDONLY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    return manifest


def _load_campaign(root: Path) -> dict[str, Any]:
    manifest_path = root / "campaign.json"
    manifest = json.loads(manifest_path.read_bytes())
    changed = False
    for attempt in manifest["qualification"]["attempts"]:
        if attempt["outcome"] == "started":
            attempt["outcome"] = "interrupted"
            attempt["ended_at"] = _now()
            attempt["interruption"] = "controller_recovery"
            changed = True
    certification = manifest["certification"]
    if not certification["results"] and certification["state"] == "running":
        certification["state"] = "paused"
        changed = True
    if certification["results"]:
        active = certification["results"][-1]
        if active["outcome"] == "started":
            active["outcome"] = "interrupted"
            active["ended_at"] = _now()
            active["interruption"] = "controller_recovery"
            certification["state"] = "interrupted"
            changed = True
        elif certification["state"] == "running":
            certification["state"] = (
                "passed"
                if len(certification["results"]) == len(ACCEPTANCE_TIER_ORDER)
                and all(
                    result["outcome"] == "passed"
                    for result in certification["results"]
                )
                else "paused"
            )
            changed = True
    if changed:
        _write_manifest(manifest_path, manifest)
    return manifest


def _assert_candidate(
    root: Path,
    manifest: dict[str, Any],
    profile: ExecutionProfile,
) -> None:
    revision, dirty = _git_authority()
    if dirty or revision != manifest["source_revision"]:
        raise RuntimeError("frozen source revision changed")
    definition = acceptance_definition()
    for key in (
        "schema_namespace",
        "tier_order",
        "protocol_digest",
        "catalog_contract_digest",
        "source_bound_inputs",
        "source_bound_contracts",
        "provider_configuration_contracts",
        "tier_contracts",
        "execution",
    ):
        if manifest[key] != definition[key]:
            raise RuntimeError("frozen acceptance definition changed")
    if manifest["installed_artifacts"] != _artifact_records(root / "artifacts"):
        raise RuntimeError("frozen installed artifacts changed")
    for phase, results in (
        ("qualification", manifest["qualification"]["attempts"]),
        ("certification", manifest["certification"]["results"]),
    ):
        expected_root = (root / f"{phase}-results").resolve()
        for result in results:
            result_reference = result.get("verification_result")
            recorded_digest = result.get("evidence_bundle_digest")
            if result_reference is None and recorded_digest is None:
                continue
            if result_reference is None or recorded_digest is None:
                raise RuntimeError("retained verification result is incomplete")
            result_dir = (root / result_reference).resolve()
            if not result_dir.is_relative_to(expected_root):
                raise RuntimeError("retained verification result changed")
            if not result_dir.is_dir():
                raise RuntimeError("retained verification result is missing")
            if _directory_digest(result_dir) != recorded_digest:
                raise RuntimeError("retained verification result changed")
    with _configured_environment(profile):
        configuration_identities = _configuration_identities()
        if manifest["provider_configuration_identities"] != (
            configuration_identities
        ):
            raise RuntimeError("frozen Provider configuration changed")
        if manifest["execution_profile_identity"] != profile.path_free_identity(
            configuration_identities
        ):
            raise RuntimeError("frozen execution profile changed")
        if manifest["provider_asset_identities"] != _provider_asset_identities():
            raise RuntimeError("frozen Provider assets changed")


@dataclass(frozen=True, slots=True)
class TierExecution:
    returncode: int
    output: str


class TierExecutionInterrupted(KeyboardInterrupt):
    """The controller stopped a tier after collecting its terminal output."""

    def __init__(self, output: str) -> None:
        super().__init__("acceptance tier execution interrupted")
        self.output = output


def _terminate_child(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        output, _ = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        output, _ = process.communicate()
    return output


def _run_tier(
    root: Path,
    phase: str,
    tier_name: str,
    environment: Mapping[str, str],
) -> TierExecution:
    results_root = root / f"{phase}-results"
    env = dict(environment)
    env["PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT"] = str(results_root)
    env["PROTEIN_WORKBENCH_FROZEN_ARTIFACT_DIR"] = str(root / "artifacts")
    env["PROTEIN_WORKBENCH_ACCEPTANCE_CAMPAIGN_ROOT"] = str(root)
    env["PROTEIN_WORKBENCH_ACCEPTANCE_PHASE"] = phase
    process = subprocess.Popen(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "verify_backend.py"),
            tier_name,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate()
    except BaseException as error:
        interrupted_output = _terminate_child(process)
        print(interrupted_output, end="", flush=True)
        raise TierExecutionInterrupted(interrupted_output) from error
    print(output, end="", flush=True)
    return TierExecution(returncode=process.returncode, output=output)


def _attach_evidence(
    root: Path,
    attempt: dict[str, Any],
    output: str,
) -> str | None:
    matches = re.findall(
        r"^RETAINED VERIFICATION RESULT: (.+)$",
        output,
        flags=re.MULTILINE,
    )
    if len(matches) != 1:
        return "verification result location is unavailable"
    result_dir = Path(matches[0]).resolve()
    expected_root = (root / (
        "certification-results"
        if attempt["authoritative"]
        else "qualification-results"
    )).resolve()
    if not result_dir.is_relative_to(expected_root):
        return "verification result escaped phase root"
    attempt["evidence_bundle_digest"] = _directory_digest(result_dir)
    attempt["verification_result"] = result_dir.relative_to(root).as_posix()
    return None


def _finish_attempt(
    root: Path,
    manifest: dict[str, Any],
    attempt: dict[str, Any],
    execution: TierExecution,
) -> str:
    outcome = "passed" if execution.returncode == 0 else "failed"
    attempt["outcome"] = outcome
    attempt["ended_at"] = _now()
    controller_error = _attach_evidence(root, attempt, execution.output)
    if controller_error is not None:
        attempt["outcome"] = "failed"
        attempt["controller_error"] = controller_error
        if attempt["authoritative"]:
            manifest["certification"]["state"] = "failed"
        _write_manifest(root / "campaign.json", manifest)
        raise RuntimeError(controller_error)
    if attempt["authoritative"]:
        certification = manifest["certification"]
        if outcome == "failed":
            certification["state"] = "failed"
        elif (
            len(certification["results"]) == len(ACCEPTANCE_TIER_ORDER)
            and all(
                result["outcome"] == "passed"
                for result in certification["results"]
            )
        ):
            certification["state"] = "passed"
    _write_manifest(root / "campaign.json", manifest)
    return outcome


def _execute_attempt(
    root: Path,
    manifest: dict[str, Any],
    attempt: dict[str, Any],
    profile: ExecutionProfile,
) -> str:
    _write_manifest(root / "campaign.json", manifest)
    try:
        execution = _run_tier(
            root,
            "certification" if attempt["authoritative"] else "qualification",
            attempt["tier"],
            profile.environment(),
        )
    except BaseException as error:
        attempt["outcome"] = "interrupted"
        attempt["ended_at"] = _now()
        attempt["interruption"] = "controller_interrupted"
        if isinstance(error, TierExecutionInterrupted):
            controller_error = _attach_evidence(root, attempt, error.output)
            if controller_error is not None:
                attempt["controller_error"] = controller_error
        if attempt["authoritative"]:
            manifest["certification"]["state"] = "interrupted"
        _write_manifest(root / "campaign.json", manifest)
        raise
    return _finish_attempt(root, manifest, attempt, execution)


def _latest_qualification(manifest: dict[str, Any]) -> dict[str, str]:
    latest = {}
    for attempt in manifest["qualification"]["attempts"]:
        latest[attempt["tier"]] = attempt["outcome"]
    return latest


def _qualification_complete(manifest: dict[str, Any]) -> bool:
    latest = _latest_qualification(manifest)
    return all(latest.get(tier) == "passed" for tier in ACCEPTANCE_TIER_ORDER)


def qualify_tier(
    root: Path,
    tier_name: str,
    profile: ExecutionProfile,
) -> dict[str, Any]:
    """Run one rerunnable, explicitly non-authoritative qualification tier."""
    manifest = _load_campaign(root)
    if manifest["certification"]["state"] != "not_started":
        raise RuntimeError("qualification is closed after certification starts")
    _assert_candidate(root, manifest, profile)
    attempts = manifest["qualification"]["attempts"]
    attempt = {
        "tier": tier_name,
        "attempt": sum(item["tier"] == tier_name for item in attempts),
        "outcome": "started",
        "authoritative": False,
        "started_at": _now(),
    }
    attempts.append(attempt)
    outcome = _execute_attempt(root, manifest, attempt, profile)
    _assert_candidate(root, manifest, profile)
    if outcome == "failed":
        raise RuntimeError(f"qualification tier failed: {tier_name}")
    return manifest


def qualify_all(
    root: Path,
    profile: ExecutionProfile,
    *,
    prioritize: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Fill every missing Qualification Result in explicit risk-first order."""
    if len(set(prioritize)) != len(prioritize) or any(
        tier not in ACCEPTANCE_TIER_ORDER for tier in prioritize
    ):
        raise RuntimeError("qualification priority order is invalid")
    manifest = _load_campaign(root)
    if manifest["certification"]["state"] != "not_started":
        raise RuntimeError("qualification is closed after certification starts")
    _assert_candidate(root, manifest, profile)
    order = (*prioritize, *(
        tier for tier in ACCEPTANCE_TIER_ORDER if tier not in prioritize
    ))
    for tier_name in order:
        if _latest_qualification(manifest).get(tier_name) == "passed":
            continue
        manifest = qualify_tier(root, tier_name, profile)
    return manifest


def certify_through(
    root: Path,
    through: str,
    profile: ExecutionProfile,
) -> dict[str, Any]:
    """Run a fresh authoritative canonical prefix after full qualification."""
    manifest = _load_campaign(root)
    certification = manifest["certification"]
    if certification["state"] in {"failed", "interrupted"}:
        raise RuntimeError("certification is terminated")
    if certification["state"] == "passed":
        raise RuntimeError("certification is already complete")
    if not _qualification_complete(manifest):
        raise RuntimeError("qualification is incomplete")
    _assert_candidate(root, manifest, profile)
    results = certification["results"]
    completed = [item["tier"] for item in results]
    if completed != list(ACCEPTANCE_TIER_ORDER[: len(completed)]) or any(
        item["outcome"] != "passed" for item in results
    ):
        raise RuntimeError("certification results are not a passed prefix")
    target_index = ACCEPTANCE_TIER_ORDER.index(through)
    if target_index < len(completed):
        raise RuntimeError("certification tier has already passed")
    certification["state"] = "running"
    _write_manifest(root / "campaign.json", manifest)
    for tier_name in ACCEPTANCE_TIER_ORDER[len(completed): target_index + 1]:
        _assert_candidate(root, manifest, profile)
        attempt = {
            "tier": tier_name,
            "ordinal": len(results),
            "outcome": "started",
            "authoritative": True,
            "started_at": _now(),
        }
        results.append(attempt)
        outcome = _execute_attempt(root, manifest, attempt, profile)
        _assert_candidate(root, manifest, profile)
        if outcome == "failed":
            certification["state"] = "failed"
            _write_manifest(root / "campaign.json", manifest)
            raise RuntimeError(f"certification tier failed: {tier_name}")
    if len(results) == len(ACCEPTANCE_TIER_ORDER):
        certification["state"] = "passed"
    else:
        certification["state"] = "paused"
    _write_manifest(root / "campaign.json", manifest)
    return manifest


def campaign_status(
    root: Path,
    profile: ExecutionProfile,
) -> dict[str, Any]:
    """Return a compact durable campaign projection, recovering orphan starts."""
    manifest = _load_campaign(root)
    _assert_candidate(root, manifest, profile)
    certification = manifest["certification"]
    if certification["state"] == "passed":
        state = "certification_passed"
    elif certification["state"] in {"failed", "interrupted"}:
        state = f"certification_{certification['state']}"
    elif certification["state"] == "paused":
        state = "certification_paused"
    elif certification["state"] == "running":
        state = "certifying"
    elif _qualification_complete(manifest):
        state = "qualified"
    elif manifest["qualification"]["attempts"]:
        state = "qualifying"
    else:
        state = "prepared"
    latest = _latest_qualification(manifest)
    return {
        "state": state,
        "source_revision": manifest["source_revision"],
        "qualified_tiers": sum(
            latest.get(tier) == "passed" for tier in ACCEPTANCE_TIER_ORDER
        ),
        "qualification_tiers": len(ACCEPTANCE_TIER_ORDER),
        "qualification_outcomes": {
            tier: latest.get(tier, "not_run")
            for tier in ACCEPTANCE_TIER_ORDER
        },
        "certification_state": certification["state"],
        "certified_tiers": sum(
            item["outcome"] == "passed"
            for item in certification["results"]
        ),
    }


def verify_repository(profile: ExecutionProfile) -> None:
    """Run the final repository matrix serially from one explicit profile."""
    for tier in REPOSITORY_VERIFICATION_TIERS:
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "verify_backend.py"),
                tier,
            ],
            cwd=PROJECT_ROOT,
            env=profile.environment(),
            check=True,
        )


def _interrupt_on_termination(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt


def main() -> int:
    signal.signal(signal.SIGTERM, _interrupt_on_termination)
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("root", type=Path)
    prepare.add_argument("--profile", required=True, type=Path)
    qualify = subparsers.add_parser("qualify")
    qualify.add_argument("root", type=Path)
    qualify.add_argument("tier", choices=ACCEPTANCE_TIER_ORDER)
    qualify.add_argument("--profile", required=True, type=Path)
    qualify_every = subparsers.add_parser("qualify-all")
    qualify_every.add_argument("root", type=Path)
    qualify_every.add_argument("--profile", required=True, type=Path)
    qualify_every.add_argument(
        "--prioritize",
        action="append",
        default=[],
        choices=ACCEPTANCE_TIER_ORDER,
    )
    certify = subparsers.add_parser("certify-through")
    certify.add_argument("root", type=Path)
    certify.add_argument("tier", choices=ACCEPTANCE_TIER_ORDER)
    certify.add_argument("--profile", required=True, type=Path)
    status = subparsers.add_parser("status")
    status.add_argument("root", type=Path)
    status.add_argument("--profile", required=True, type=Path)
    repository = subparsers.add_parser("verify-repository")
    repository.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args()
    profile = ExecutionProfile.load(args.profile.resolve())
    if args.command == "verify-repository":
        verify_repository(profile)
        return 0
    root = args.root.resolve()
    if args.command == "status":
        print(json.dumps(campaign_status(root, profile), sort_keys=True))
        return 0
    if args.command == "prepare":
        prepare_campaign(root, profile)
    elif args.command == "qualify":
        qualify_tier(root, args.tier, profile)
    elif args.command == "qualify-all":
        qualify_all(root, profile, prioritize=tuple(args.prioritize))
    else:
        certify_through(root, args.tier, profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
