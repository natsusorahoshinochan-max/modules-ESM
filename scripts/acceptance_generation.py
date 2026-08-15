#!/usr/bin/env python3
"""Run one frozen current-generation acceptance sequence, strictly serially."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from modules.acceptance_verification import (
    ACCEPTANCE_TIER_CONTRACTS,
    ACCEPTANCE_TIER_ORDER,
    INSTALLED_PROVIDER_TIER_ORDER,
    SOURCE_BOUND_TIER_ORDER,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_NAMESPACE = "protein-workbench-acceptance-generation/v1"

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
# generation manifest records path-free identities for their configured values;
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


def generation_definition() -> dict[str, Any]:
    """Return the source-owned acceptance definition without runtime results."""
    from core import build_discovered_frozen_catalog
    from protein_workbench_public import bundle_digest

    return {
        "schema_namespace": SCHEMA_NAMESPACE,
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
                    f"acceptance generation requires explicit {variable}"
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
        SIMPLEFOLD_CONFIDENCE_DEVICE,
        configured_runtime_fingerprint as simplefold_confidence_fingerprint,
        validate_simplefold_confidence_environment,
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
                f"acceptance generation requires explicit {variable}"
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


def start_generation(root: Path) -> dict[str, Any]:
    """Create one non-self-referential authority at the current clean commit."""
    revision, dirty = _git_authority()
    if dirty:
        raise RuntimeError("acceptance generation requires a clean source revision")
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    manifest_path = root / "generation.json"
    if manifest_path.exists():
        raise RuntimeError("acceptance generation already exists")
    artifact_root = root / "artifacts"
    subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "build_backend.py"),
            str(artifact_root),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    manifest = {
        **generation_definition(),
        "source_revision": revision,
        "source_dirty": False,
        "installed_artifacts": _artifact_records(artifact_root),
        "provider_configuration_identities": _configuration_identities(),
        "provider_asset_identities": _provider_asset_identities(),
        "results": [],
    }
    _write_manifest(manifest_path, manifest)
    return manifest


def _load_manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / "generation.json").read_bytes())


def _assert_authority(root: Path, manifest: dict[str, Any]) -> None:
    revision, dirty = _git_authority()
    if dirty or revision != manifest["source_revision"]:
        raise RuntimeError("frozen source revision changed")
    definition = generation_definition()
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
    if manifest["provider_configuration_identities"] != (
        _configuration_identities()
    ):
        raise RuntimeError("frozen Provider configuration changed")
    if manifest["provider_asset_identities"] != _provider_asset_identities():
        raise RuntimeError("frozen Provider assets changed")


def run_through(root: Path, through: str) -> dict[str, Any]:
    """Run the exact missing prefix through one requested tier."""
    manifest = _load_manifest(root)
    _assert_authority(root, manifest)
    completed = [result["tier"] for result in manifest["results"]]
    expected_prefix = list(ACCEPTANCE_TIER_ORDER[: len(completed)])
    if completed != expected_prefix:
        raise RuntimeError("acceptance results are not one contiguous prefix")
    if manifest["results"] and manifest["results"][-1]["outcome"] != "passed":
        raise RuntimeError("acceptance generation is terminated")
    target_index = ACCEPTANCE_TIER_ORDER.index(through)
    if target_index < len(completed) - 1:
        raise RuntimeError("acceptance tier has already been passed")

    results_root = root / "tier-results"
    env = os.environ.copy()
    env["PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT"] = str(results_root)
    env["PROTEIN_WORKBENCH_FROZEN_ARTIFACT_DIR"] = str(root / "artifacts")
    env["PROTEIN_WORKBENCH_ACCEPTANCE_GENERATION_ROOT"] = str(root)
    for tier_name in ACCEPTANCE_TIER_ORDER[len(completed): target_index + 1]:
        _assert_authority(root, manifest)
        completed_process = subprocess.run(
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
            check=False,
        )
        print(completed_process.stdout, end="", flush=True)
        _assert_authority(root, manifest)
        matches = re.findall(
            r"^RETAINED VERIFICATION RESULT: (.+)$",
            completed_process.stdout,
            flags=re.MULTILINE,
        )
        if len(matches) != 1:
            raise RuntimeError("verification result location is unavailable")
        result_dir = Path(matches[0]).resolve()
        outcome = (
            "passed" if completed_process.returncode == 0 else "failed"
        )
        manifest["results"].append({
            "tier": tier_name,
            "ordinal": len(manifest["results"]),
            "evidence_bundle_digest": _directory_digest(result_dir),
            "verification_result": result_dir.relative_to(root).as_posix(),
            "outcome": outcome,
        })
        _write_manifest(root / "generation.json", manifest)
        if outcome == "failed":
            raise RuntimeError(f"acceptance tier failed: {tier_name}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("root", type=Path)
    run = subparsers.add_parser("run-through")
    run.add_argument("root", type=Path)
    run.add_argument("tier", choices=ACCEPTANCE_TIER_ORDER)
    args = parser.parse_args()
    if args.command == "start":
        start_generation(args.root.resolve())
    else:
        run_through(args.root.resolve(), args.tier)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
