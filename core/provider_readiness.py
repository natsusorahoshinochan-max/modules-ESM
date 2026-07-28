"""Workflow-scoped readiness resolved by trusted backend code."""

from __future__ import annotations

import os
import selectors
import signal
import stat
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from core.graph import Workflow
from core.provider_contract import (
    ESM_SDK_REVISION,
    SIMPLEFOLD_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ARTIFACT_SHA256,
    SIMPLEFOLD_AUXILIARY_ARTIFACTS,
    SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES,
    SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
    SIMPLEFOLD_REVISION,
    esm_provider_identity,
    proteinmpnn_provider_identity,
    simplefold_provider_identity,
    validate_biohub_token_file,
    validate_installed_provider_checkout,
    validate_local_esm3_snapshot,
)
from core.run_manifest import (
    ReadinessStatus,
    ResolvedProviderReadiness,
    sanitize_public_value,
)
from core.process_control import (
    signal_process_group,
    verification_uses_shared_process_group,
)


@dataclass(frozen=True)
class ProviderRequirement:
    """One provider boundary required by the submitted Workflow."""

    provider: str
    node_ids: tuple[str, ...]
    module_ids: tuple[str, ...]
    options: tuple[str, ...] = ()

    def source(self) -> dict[str, Any]:
        return {
            "kind": "workflow_required_boundary",
            "node_ids": list(self.node_ids),
            "module_ids": list(self.module_ids),
        }


@dataclass(frozen=True)
class ProviderReadinessFact:
    """One trusted resolver observation before execution acceptance."""

    provider: str
    status: ReadinessStatus
    provider_identity: dict[str, Any]
    details: dict[str, Any]


ReadinessResolver = Callable[
    [tuple[ProviderRequirement, ...]],
    Iterable[ProviderReadinessFact],
]


@dataclass(frozen=True)
class WorkflowReadiness:
    """Normalized, fail-closed readiness for one submitted Workflow."""

    facts: tuple[ResolvedProviderReadiness, ...]

    @property
    def ready(self) -> bool:
        return all(fact.ready for fact in self.facts)

    def executor_payload(self) -> dict[str, ResolvedProviderReadiness]:
        return {
            fact.provider: fact
            for fact in self.facts
        }

    def public_facts(self) -> list[dict[str, Any]]:
        return [fact.to_dict() for fact in self.facts]


_STATIC_PROVIDER_MODULES: dict[str, tuple[str, ...]] = {
    "biohub": ("esmfold2.fold",),
    "local-proteinmpnn": (
        "proteinmpnn.design",
        "proteinmpnn.score",
    ),
    "simplefold": (
        "simplefold.fold",
        "simplefold.evaluate",
    ),
    "mkdssp": (
        "compute.dssp",
        "prompt.compute_sasa",
        "prompt.compute_secondary_structure",
    ),
    "biopython-svd": (
        "structure.align",
        "structure.pairwise_align",
    ),
    "tmtools": (
        "structure.align",
        "structure.pairwise_align",
        "structure.tm_score",
        "structure.batch_tm_score",
    ),
}
_ESM3_MODULES = frozenset({
    "esm3.generate",
    "esm3.generate_sequence",
    "esm3.generate_structure",
})


def workflow_provider_requirements(
    workflow: Workflow,
    *,
    provider_aliases: Mapping[str, str] | None = None,
) -> tuple[ProviderRequirement, ...]:
    """Derive required scientific boundaries only from the trusted Workflow."""
    aliases = dict(provider_aliases or {})
    required_nodes: dict[str, set[str]] = defaultdict(set)
    required_modules: dict[str, set[str]] = defaultdict(set)
    provider_options: dict[str, set[str]] = defaultdict(set)

    def require(
        provider: str,
        *,
        node_id: str,
        module_id: str,
        option: str | None = None,
    ) -> None:
        selected = aliases.get(provider, provider)
        required_nodes[selected].add(node_id)
        required_modules[selected].add(module_id)
        if option is not None:
            provider_options[selected].add(option)

    for node in workflow.nodes.values():
        if node.module_id in _ESM3_MODULES:
            model_name = str(
                node.parameters.get("model_name", "esm3-medium-2024-08")
            )
            require(
                "local_open" if model_name == "esm3_sm_open_v1" else "biohub",
                node_id=node.node_id,
                module_id=node.module_id,
            )
        for provider, module_ids in _STATIC_PROVIDER_MODULES.items():
            if node.module_id not in module_ids:
                continue
            option = None
            if provider == "mkdssp":
                option = str(
                    node.parameters.get(
                        "dssp_binary",
                        "/opt/homebrew/bin/mkdssp",
                    )
                )
            require(
                provider,
                node_id=node.node_id,
                module_id=node.module_id,
                option=option,
            )

    return tuple(
        ProviderRequirement(
            provider=provider,
            node_ids=tuple(sorted(required_nodes[provider])),
            module_ids=tuple(sorted(required_modules[provider])),
            options=tuple(sorted(provider_options[provider])),
        )
        for provider in sorted(required_nodes)
    )


def _normalized_fact(
    requirement: ProviderRequirement,
    fact: ProviderReadinessFact,
) -> ResolvedProviderReadiness:
    status: ReadinessStatus = fact.status
    identity = sanitize_public_value(fact.provider_identity)
    details = sanitize_public_value(fact.details)
    if status not in {"ready", "unavailable", "failed"}:
        status = "failed"
        details = {"reason": "invalid_readiness_status"}
    if status == "ready" and (
        not isinstance(identity, dict) or not identity
    ):
        status = "failed"
        identity = {"provider": requirement.provider}
        details = {"reason": "missing_provider_identity"}
    return ResolvedProviderReadiness(
        provider=requirement.provider,
        status=status,
        provider_identity=identity,
        source=requirement.source(),
        details=details,
    )


def assess_workflow_readiness(
    workflow: Workflow,
    resolver: ReadinessResolver,
    *,
    provider_aliases: Mapping[str, str] | None = None,
) -> WorkflowReadiness:
    """Resolve and normalize readiness, failing closed on every ambiguity."""
    requirements = workflow_provider_requirements(
        workflow,
        provider_aliases=provider_aliases,
    )
    if not requirements:
        return WorkflowReadiness(())
    try:
        observed = tuple(resolver(requirements))
    except Exception as error:
        observed = tuple(
            ProviderReadinessFact(
                provider=requirement.provider,
                status="failed",
                provider_identity={"provider": requirement.provider},
                details={
                    "reason": "readiness_resolver_failed",
                    "error_type": type(error).__name__,
                },
            )
            for requirement in requirements
        )

    by_provider: dict[str, list[ProviderReadinessFact]] = defaultdict(list)
    for fact in observed:
        if isinstance(fact, ProviderReadinessFact):
            by_provider[fact.provider].append(fact)

    normalized: list[ResolvedProviderReadiness] = []
    for requirement in requirements:
        matches = by_provider.get(requirement.provider, [])
        if not matches:
            fact = ProviderReadinessFact(
                provider=requirement.provider,
                status="unavailable",
                provider_identity={"provider": requirement.provider},
                details={"reason": "readiness_missing"},
            )
        elif len(matches) > 1:
            fact = ProviderReadinessFact(
                provider=requirement.provider,
                status="failed",
                provider_identity={"provider": requirement.provider},
                details={"reason": "ambiguous_readiness"},
            )
        else:
            fact = matches[0]
        normalized.append(_normalized_fact(requirement, fact))
    return WorkflowReadiness(tuple(normalized))


def _fact(
    requirement: ProviderRequirement,
    *,
    status: ReadinessStatus,
    identity: dict[str, Any],
    details: dict[str, Any],
) -> ProviderReadinessFact:
    return ProviderReadinessFact(
        provider=requirement.provider,
        status=status,
        provider_identity=identity,
        details=details,
    )


def _probe_biohub(requirement: ProviderRequirement) -> ProviderReadinessFact:
    identity = esm_provider_identity()
    configured = os.environ.get("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE")
    try:
        if not configured:
            raise FileNotFoundError
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
        validate_biohub_token_file(configured)
    except (FileNotFoundError, ImportError, OSError, RuntimeError):
        return _fact(
            requirement,
            status="unavailable",
            identity=identity,
            details={"access_configured": bool(configured)},
        )
    return _fact(
        requirement,
        status="ready",
        identity=identity,
        details={"access_configured": True},
    )


def _probe_local_esm3(requirement: ProviderRequirement) -> ProviderReadinessFact:
    identity = esm_provider_identity(local=True)
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
        validate_local_esm3_snapshot()
    except (FileNotFoundError, ImportError, OSError, RuntimeError):
        return _fact(
            requirement,
            status="unavailable",
            identity=identity,
            details={"snapshot_validated": False},
        )
    return _fact(
        requirement,
        status="ready",
        identity=identity,
        details={"snapshot_validated": True},
    )


def _probe_proteinmpnn(
    requirement: ProviderRequirement,
) -> ProviderReadinessFact:
    from modules.proteinmpnn import check_proteinmpnn_readiness

    readiness = check_proteinmpnn_readiness()
    return _fact(
        requirement,
        status="ready" if readiness.ready else "unavailable",
        identity=proteinmpnn_provider_identity(),
        details={
            "checkout_and_checkpoint_validated": readiness.ready,
        },
    )


def _probe_mkdssp(requirement: ProviderRequirement) -> ProviderReadinessFact:
    binaries = requirement.options or ("/opt/homebrew/bin/mkdssp",)
    approved_binary = os.environ.get(
        "PROTEIN_WORKBENCH_MKDSSP_BINARY",
        "/opt/homebrew/bin/mkdssp",
    )
    if any(binary != approved_binary for binary in binaries):
        return _fact(
            requirement,
            status="failed",
            identity={"binary": "mkdssp", "required_version": "4.6.1"},
            details={"reason": "unapproved_binary_selection"},
        )
    configured_path = Path(approved_binary)
    try:
        approved_path = configured_path.resolve(strict=True)
        approved_stat = approved_path.stat()
    except OSError:
        approved_path = configured_path
        approved_stat = None
    if (
        not configured_path.is_absolute()
        or approved_stat is None
        or not stat.S_ISREG(approved_stat.st_mode)
        or approved_stat.st_uid not in {0, os.geteuid()}
        or approved_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        return _fact(
            requirement,
            status="unavailable",
            identity={"binary": "mkdssp", "required_version": "4.6.1"},
            details={"version_match": False},
        )
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            [str(approved_path), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=not verification_uses_shared_process_group(),
        )
        return_code, output = _bounded_process_output(
            process,
            limit=4096,
            timeout=10,
        )
        version_output = output.decode(
            "utf-8",
            errors="replace",
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        if process is not None and process.poll() is None:
            signal_process_group(
                process.pid,
                signal.SIGKILL,
                fallback=process.kill,
            )
            process.wait()
        return _fact(
            requirement,
            status="unavailable",
            identity={"binary": "mkdssp", "required_version": "4.6.1"},
            details={"version_match": False},
        )
    version_match = (
        return_code == 0
        and "mkdssp version 4.6.1" in version_output
    )
    return _fact(
        requirement,
        status="ready" if version_match else "unavailable",
        identity={"binary": "mkdssp", "required_version": "4.6.1"},
        details={"version_match": version_match},
    )


def _bounded_process_output(
    process: subprocess.Popen[bytes],
    *,
    limit: int,
    timeout: float,
) -> tuple[int, bytes]:
    """Read one child pipe with a hard in-memory and write-time bound."""
    if process.stdout is None:
        raise RuntimeError("Provider readiness process has no output pipe")
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    selector = selectors.DefaultSelector()
    selector.register(descriptor, selectors.EVENT_READ)
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout)
            events = selector.select(timeout=min(remaining, 0.1))
            for _, _ in events:
                chunk = os.read(
                    descriptor,
                    min(4096, limit + 1 - len(output)),
                )
                if chunk:
                    output.extend(chunk)
                    if len(output) > limit:
                        raise RuntimeError(
                            "Provider readiness output exceeded limit"
                        )
            return_code = process.poll()
            if return_code is None:
                continue
            while len(output) <= limit:
                try:
                    chunk = os.read(
                        descriptor,
                        min(4096, limit + 1 - len(output)),
                    )
                except BlockingIOError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
            if len(output) > limit:
                raise RuntimeError(
                    "Provider readiness output exceeded limit"
                )
            return return_code, bytes(output)
    finally:
        selector.close()
        process.stdout.close()


def _probe_biopython(requirement: ProviderRequirement) -> ProviderReadinessFact:
    try:
        import Bio
        import numpy
    except ImportError:
        return _fact(
            requirement,
            status="unavailable",
            identity={"provider": "biopython-svd"},
            details={"installed": False},
        )
    return _fact(
        requirement,
        status="ready",
        identity={
            "biopython_version": Bio.__version__,
            "numpy_version": numpy.__version__,
        },
        details={"installed": True},
    )


def _probe_tmtools(requirement: ProviderRequirement) -> ProviderReadinessFact:
    try:
        import tmtools
    except ImportError:
        return _fact(
            requirement,
            status="unavailable",
            identity={"provider": "tmtools"},
            details={"installed": False},
        )
    return _fact(
        requirement,
        status="ready",
        identity={"tmtools_version": version("tmtools")},
        details={"installed": bool(tmtools.__name__)},
    )


def _regular_files_match(
    root: Path,
    expected: Mapping[str, str],
    identities: Mapping[str, Mapping[str, Any]],
) -> bool:
    from modules.simplefold_adapter import _sha256_regular_file

    for name, digest in expected.items():
        artifact = root / name
        if artifact.is_symlink() or not artifact.is_file():
            return False
        expected_bytes = identities.get(name, {}).get("bytes")
        if _sha256_regular_file(
            artifact,
            expected_bytes=expected_bytes,
        ) != digest:
            return False
    return True


def _probe_simplefold(
    requirement: ProviderRequirement,
) -> ProviderReadinessFact:
    identity = simplefold_provider_identity(SIMPLEFOLD_ARTIFACT_SHA256)
    configured_model = os.environ.get(
        "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"
    )
    configured_esm2_models = os.environ.get(
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"
    )
    try:
        if not configured_model or not configured_esm2_models:
            raise FileNotFoundError
        model_root = Path(configured_model).expanduser()
        esm2_model_root = Path(configured_esm2_models).expanduser()
        required_model_hashes = {
            name: SIMPLEFOLD_ARTIFACT_SHA256[name]
            for name in (
                *SIMPLEFOLD_ARTIFACT_IDENTITIES,
                *SIMPLEFOLD_AUXILIARY_ARTIFACTS,
            )
        }
        if (
            model_root.is_symlink()
            or not model_root.is_dir()
            or esm2_model_root.is_symlink()
            or not esm2_model_root.is_dir()
            or not _regular_files_match(
                model_root,
                required_model_hashes,
                SIMPLEFOLD_ARTIFACT_IDENTITIES,
            )
            or not _regular_files_match(
                esm2_model_root,
                SIMPLEFOLD_ESM2_ARTIFACT_SHA256,
                SIMPLEFOLD_ESM2_ARTIFACT_IDENTITIES,
            )
        ):
            raise FileNotFoundError
        validate_installed_provider_checkout("simplefold", SIMPLEFOLD_REVISION)
        from modules.simplefold_adapter import validated_simplefold_esm2_root

        validated_simplefold_esm2_root()
    except (FileNotFoundError, ImportError, OSError, RuntimeError):
        return _fact(
            requirement,
            status="unavailable",
            identity=identity,
            details={"artifact_contract_complete": False},
        )
    return _fact(
        requirement,
        status="ready",
        identity=identity,
        details={"artifact_contract_complete": True},
    )


def resolve_live_provider_readiness(
    requirements: tuple[ProviderRequirement, ...],
) -> tuple[ProviderReadinessFact, ...]:
    """Probe required production boundaries without trusting request payloads."""
    probes = {
        "biohub": _probe_biohub,
        "local_open": _probe_local_esm3,
        "local-proteinmpnn": _probe_proteinmpnn,
        "simplefold": _probe_simplefold,
        "mkdssp": _probe_mkdssp,
        "biopython-svd": _probe_biopython,
        "tmtools": _probe_tmtools,
    }
    facts: list[ProviderReadinessFact] = []
    for requirement in requirements:
        probe = probes.get(requirement.provider)
        if probe is None:
            facts.append(_fact(
                requirement,
                status="unavailable",
                identity={"provider": requirement.provider},
                details={"reason": "unsupported_provider_boundary"},
            ))
            continue
        try:
            facts.append(probe(requirement))
        except Exception as error:
            facts.append(_fact(
                requirement,
                status="failed",
                identity={"provider": requirement.provider},
                details={
                    "reason": "readiness_probe_failed",
                    "error_type": type(error).__name__,
                },
            ))
    return tuple(facts)


class LiveProviderReadinessResolver:
    """Serialize expensive live probes without retaining stale green facts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __call__(
        self,
        requirements: tuple[ProviderRequirement, ...],
    ) -> tuple[ProviderReadinessFact, ...]:
        facts: list[ProviderReadinessFact] = []
        with self._lock:
            for requirement in requirements:
                facts.append(
                    resolve_live_provider_readiness((requirement,))[0]
                )
        return tuple(facts)
