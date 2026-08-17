#!/usr/bin/env python3
"""Build and run one serial real-Provider acceptance campaign."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

from modules.acceptance_verification import (
    ACCEPTANCE_TIER_CONTRACTS,
    ACCEPTANCE_TIER_ORDER,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN_SCHEMA_NAMESPACE = "protein-workbench-acceptance-campaign/v2"
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
    """One shipped scientific input and Workflow."""

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
    """Private paths used by the acceptance child processes."""

    provider_configuration: Mapping[str, str]
    proxy_policy: str

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
            or remote_transport["proxy_policy"] not in {"direct", "inherit"}
        ):
            raise RuntimeError("acceptance remote transport policy is invalid")
        provider_configuration = document["provider_configuration"]
        if not isinstance(provider_configuration, dict) or not all(
            isinstance(name, str) and isinstance(value, str) and value
            for name, value in provider_configuration.items()
        ):
            raise RuntimeError("acceptance Provider configuration is invalid")
        allowed = {
            variable
            for variables in PROVIDER_CONFIGURATION_CONTRACTS.values()
            for variable in variables
        }
        required = allowed - {"HF_HUB_CACHE", "HF_HOME"}
        if set(provider_configuration) - allowed or required - set(
            provider_configuration
        ):
            raise RuntimeError("acceptance Provider configuration names are invalid")
        if len(set(provider_configuration) & {"HF_HUB_CACHE", "HF_HOME"}) != 1:
            raise RuntimeError(
                "acceptance profile requires exactly one Hugging Face root"
            )
        configured = {
            name: str(Path(value).expanduser().resolve())
            for name, value in provider_configuration.items()
        }
        return cls(
            provider_configuration=configured,
            proxy_policy=remote_transport["proxy_policy"],
        )

    def environment(self) -> dict[str, str]:
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
        environment.update(self.provider_configuration)
        if self.proxy_policy == "direct":
            for name in PROXY_VARIABLES:
                environment.pop(name, None)
        return environment


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


def acceptance_definition() -> dict[str, Any]:
    """Return the single acceptance run definition."""
    return {
        "schema_namespace": CAMPAIGN_SCHEMA_NAMESPACE,
        "tier_order": list(ACCEPTANCE_TIER_ORDER),
        "tier_contracts": {
            name: {
                "pytest_arguments": list(contract.pytest_arguments),
                "timeout_seconds": contract.timeout_seconds,
                "required_run_labels": list(contract.required_run_labels),
                "lifecycle_receipt_required": (
                    contract.lifecycle_receipt_required
                ),
            }
            for name, contract in ACCEPTANCE_TIER_CONTRACTS.items()
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


def _now() -> str:
    return datetime.now(UTC).isoformat()


def prepare_campaign(
    root: Path,
    profile: ExecutionProfile,
) -> dict[str, Any]:
    """Build the artifact used by one clean acceptance run."""
    revision, dirty = _git_authority()
    if dirty:
        raise RuntimeError("acceptance campaign requires a clean source revision")
    if root.exists():
        raise RuntimeError("acceptance campaign root already exists")
    artifact_root = root / "artifacts"
    artifact_root.mkdir(parents=True)
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
    manifest = {
        "schema_namespace": CAMPAIGN_SCHEMA_NAMESPACE,
        "source_revision": revision,
        "tier_order": list(ACCEPTANCE_TIER_ORDER),
        "state": "prepared",
        "results": [],
    }
    _write_manifest(root / "campaign.json", manifest)
    return manifest


def _load_campaign(root: Path) -> dict[str, Any]:
    return json.loads((root / "campaign.json").read_bytes())


@dataclass(frozen=True, slots=True)
class TierExecution:
    returncode: int
    output: str


def _run_tier(
    root: Path,
    tier_name: str,
    environment: Mapping[str, str],
) -> TierExecution:
    env = dict(environment)
    env["PROTEIN_WORKBENCH_VERIFICATION_RESULTS_ROOT"] = str(
        root / "results"
    )
    env["PROTEIN_WORKBENCH_FROZEN_ARTIFACT_DIR"] = str(root / "artifacts")
    env["PROTEIN_WORKBENCH_ACCEPTANCE_CAMPAIGN_ROOT"] = str(root)
    completed = subprocess.run(
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
    )
    print(completed.stdout, end="", flush=True)
    return TierExecution(
        returncode=completed.returncode,
        output=completed.stdout,
    )


def _verification_result(root: Path, output: str) -> str:
    match = re.search(
        r"^RETAINED VERIFICATION RESULT: (.+)$",
        output,
        flags=re.MULTILINE,
    )
    if match is None:
        raise RuntimeError("acceptance tier did not retain its result")
    return Path(match.group(1)).resolve().relative_to(root.resolve()).as_posix()


def run_campaign(
    root: Path,
    profile: ExecutionProfile,
) -> dict[str, Any]:
    """Run every real Provider tier once, serially, in canonical order."""
    manifest = _load_campaign(root)
    if manifest["state"] != "prepared":
        raise RuntimeError("acceptance campaign already started")
    manifest["state"] = "running"
    _write_manifest(root / "campaign.json", manifest)
    try:
        for tier_name in ACCEPTANCE_TIER_ORDER:
            started_at = _now()
            execution = _run_tier(root, tier_name, profile.environment())
            outcome = "passed" if execution.returncode == 0 else "failed"
            result = {
                "tier": tier_name,
                "outcome": outcome,
                "started_at": started_at,
                "ended_at": _now(),
                "verification_result": _verification_result(
                    root,
                    execution.output,
                ),
            }
            manifest["results"].append(result)
            if outcome == "failed":
                manifest["state"] = "failed"
                _write_manifest(root / "campaign.json", manifest)
                raise RuntimeError(f"acceptance tier failed: {tier_name}")
            _write_manifest(root / "campaign.json", manifest)
    except BaseException:
        if manifest["state"] == "running":
            manifest["state"] = "interrupted"
            _write_manifest(root / "campaign.json", manifest)
        raise
    manifest["state"] = "passed"
    _write_manifest(root / "campaign.json", manifest)
    return manifest


def campaign_status(root: Path) -> dict[str, Any]:
    """Return the observable outcome of one acceptance run."""
    manifest = _load_campaign(root)
    outcomes = {
        result["tier"]: result["outcome"]
        for result in manifest["results"]
    }
    return {
        "state": manifest["state"],
        "source_revision": manifest["source_revision"],
        "passed_tiers": sum(
            outcome == "passed" for outcome in outcomes.values()
        ),
        "total_tiers": len(ACCEPTANCE_TIER_ORDER),
        "outcomes": {
            tier: outcomes.get(tier, "not_run")
            for tier in ACCEPTANCE_TIER_ORDER
        },
    }


def verify_repository(profile: ExecutionProfile) -> None:
    """Run the repository checks serially with the same explicit environment."""
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


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("root", type=Path)
    prepare.add_argument("--profile", required=True, type=Path)
    run = subparsers.add_parser("run")
    run.add_argument("root", type=Path)
    run.add_argument("--profile", required=True, type=Path)
    status = subparsers.add_parser("status")
    status.add_argument("root", type=Path)
    repository = subparsers.add_parser("verify-repository")
    repository.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(campaign_status(args.root.resolve()), sort_keys=True))
        return 0
    profile = ExecutionProfile.load(args.profile.resolve())
    if args.command == "verify-repository":
        verify_repository(profile)
    elif args.command == "prepare":
        prepare_campaign(args.root.resolve(), profile)
    else:
        run_campaign(args.root.resolve(), profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
