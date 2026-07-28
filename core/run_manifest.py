"""Durable source-bound facts for one Workflow run."""

from __future__ import annotations

import hashlib
import fcntl
import json
import math
import os
import platform
import re
import secrets
import stat
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from core.graph import Workflow
from core.recovery_types import RecoveryProvenance
from core.storage import (
    StoragePathError,
    open_private_regular_file,
    validate_identifier,
    validate_relative_path,
)
from core.workflow_module import WorkflowModule


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_value(value: Any) -> Any:
    """Return a deterministic JSON-compatible representation."""
    if isinstance(value, dict):
        return {
            str(key): _json_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


_SENSITIVE_KEY = re.compile(
    r"(?:secret|token|password|credential|api[_-]?key|authorization|cookie|"
    r"private[_-]?key|access[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_KEY_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret|authorization)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_HEADER_VALUE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)"
    r"(\s*[:=]\s*)[^\r\n]+"
)
_BASIC_VALUE = re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=]{8,}")
_URI_USERINFO = re.compile(
    r"([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@"
)
_OPAQUE_API_TOKEN = re.compile(
    r"\b(?:"
    r"(?:sk|pk)-[A-Za-z0-9_-]{8,}|"
    r"hf_[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}"
    r")\b"
)
_OPAQUE_SCORE_SECRET = re.compile(r"[A-Za-z0-9+/=]{32,}\Z")
_MAX_MANIFEST_SCORES = 4096
_MAX_SCORE_SUBJECTS = 32
_MAX_SCORE_DETAILS_BYTES = 512 * 1024
_MAX_SCORE_DETAILS_TOTAL_BYTES = 8 * 1024 * 1024
ReadinessStatus = Literal["ready", "unavailable", "failed"]
_ALLOWED_SCORE_DETAIL_KEYS = {
    "aligned_residues",
    "coarse",
    "compared",
    "count",
    "coverage",
    "d0",
    "matched",
    "matrix",
    "metrics",
    "model",
    "normalization",
    "normalization_length",
    "per_residue",
    "per_residue_count",
    "per_residue_match",
    "residue_axes",
    "rmsd",
    "sample_index",
    "score",
    "shape",
    "summary",
    "unit",
    "units",
    "weight",
}


def _secret_values(value: Any, *, sensitive: bool = False) -> set[str]:
    values: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            values.update(
                _secret_values(
                    child,
                    sensitive=sensitive or bool(_SENSITIVE_KEY.search(str(key))),
                )
            )
    elif isinstance(value, (list, tuple)):
        for child in value:
            values.update(_secret_values(child, sensitive=sensitive))
    elif sensitive and isinstance(value, str) and len(value) >= 4:
        values.add(value)
    return values


def _redact(value: Any, secret_values: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            name = str(key)
            result[name] = (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(name)
                else _redact(child, secret_values)
            )
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(child, secret_values) for child in value]
    if not isinstance(value, str):
        return value
    redacted = value
    for secret in secret_values:
        redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _HEADER_VALUE.sub(r"\1\2[REDACTED]", redacted)
    redacted = _BEARER_VALUE.sub(r"\1[REDACTED]", redacted)
    redacted = _BASIC_VALUE.sub("Basic [REDACTED]", redacted)
    redacted = _KEY_VALUE.sub(r"\1\2[REDACTED]", redacted)
    redacted = _URI_USERINFO.sub(r"\1[REDACTED]@", redacted)
    return _OPAQUE_API_TOKEN.sub("[REDACTED]", redacted)


def _sanitize(value: Any) -> Any:
    secrets_to_redact = tuple(
        sorted(_secret_values(value), key=len, reverse=True)
    )
    return _redact(value, secrets_to_redact)


def sanitize_public_value(value: Any) -> Any:
    """Return a recursively redacted value safe for public API responses."""
    return _sanitize(value)


def _validate_score_details(value: Any, *, depth: int = 0) -> None:
    """Accept only bounded scientific JSON values, never opaque objects."""
    if depth > 12:
        raise ValueError("Manifest score detail nesting is too deep")
    if isinstance(value, dict):
        for key, child in value.items():
            if (
                not isinstance(key, str)
                or key not in _ALLOWED_SCORE_DETAIL_KEYS
            ):
                raise ValueError(
                    "Manifest score detail key is not approved"
                )
            _validate_score_details(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _validate_score_details(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise ValueError("Manifest score detail number must be finite")
    if isinstance(value, str):
        if (
            len(value) > 128
            or _sanitize(value) != value
            or _OPAQUE_SCORE_SECRET.fullmatch(value) is not None
        ):
            raise ValueError(
                "Manifest score detail string is unsafe"
            )
        return
    raise ValueError("Manifest score details must be scientific JSON values")


def canonical_json(value: Any) -> bytes:
    """Encode a value with recursive dictionary normalization."""
    return json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def workflow_sha256(workflow: Workflow) -> str:
    """Hash the scientific Workflow contract, excluding mutable Node state."""
    payload = {
        "nodes": sorted(
            (
                {
                    "node_id": node.node_id,
                    "module_id": node.module_id,
                    "module_version": node.module_version,
                    "parameters": node.parameters,
                }
                for node in workflow.nodes.values()
            ),
            key=lambda item: item["node_id"],
        ),
        "edges": sorted(
            (
                {
                    "source_node_id": edge.source_node_id,
                    "source_port": edge.source_port,
                    "target_node_id": edge.target_node_id,
                    "target_port": edge.target_port,
                }
                for edge in workflow.edges
            ),
            key=lambda item: (
                item["source_node_id"],
                item["source_port"],
                item["target_node_id"],
                item["target_port"],
            ),
        ),
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def discover_source(source_dir: str | Path) -> dict[str, Any]:
    """Read Git revision and dirty state without modifying the checkout."""
    directory = Path(source_dir)

    def git(*arguments: str) -> subprocess.CompletedProcess[str]:
        safe_environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        return subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "submodule.recurse=false",
                *arguments,
            ],
            cwd=directory,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=safe_environment,
        )

    try:
        revision = git("rev-parse", "--verify", "HEAD")
    except (OSError, subprocess.TimeoutExpired):
        return {"revision": None, "dirty": None}
    if revision.returncode != 0:
        return {"revision": None, "dirty": None}
    try:
        status = git(
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--ignore-submodules=all",
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"revision": revision.stdout.strip(), "dirty": None}
    return {
        "revision": revision.stdout.strip(),
        "dirty": status.returncode != 0 or bool(status.stdout),
    }


@dataclass
class RunManifest:
    """The JSON-serializable facts attached to one contained run."""

    project_id: str
    run_id: str
    source: dict[str, Any]
    workflow: dict[str, Any]
    modules: list[dict[str, Any]]
    run_seed: int
    effective_seeds: dict[str, int]
    environment: dict[str, Any]
    models: list[dict[str, Any]]
    status: str = "created"
    schema_version: int = 1
    created_at: str = field(default_factory=_timestamp)
    updated_at: str = field(default_factory=_timestamp)
    node_states: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    blocking_reasons: list[dict[str, Any]] = field(default_factory=list)
    cache: list[dict[str, Any]] = field(default_factory=list)
    providers: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"readiness": [], "calls": []}
    )
    candidate_lineage: list[dict[str, Any]] = field(default_factory=list)
    scores: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    recovery: dict[str, Any] | None = None

    @classmethod
    def for_execution(
        cls,
        *,
        project_id: str,
        run_id: str,
        workflow: Workflow,
        modules: dict[str, WorkflowModule],
        seed: int,
        source_dir: str | Path,
        environment: dict[str, Any] | None = None,
        recovery: RecoveryProvenance | None = None,
    ) -> "RunManifest":
        runtime = {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": sys.platform,
        }
        if environment:
            runtime.update(_sanitize(environment))
        module_facts = []
        model_facts = []
        for node in sorted(workflow.nodes.values(), key=lambda item: item.node_id):
            module = modules.get(node.module_id)
            version = (
                module.definition.version
                if module is not None
                else node.module_version
            )
            module_facts.append({
                "node_id": node.node_id,
                "module_id": node.module_id,
                "version": version,
            })
            if module is not None:
                parameter_defaults = {
                    parameter.name: parameter.default
                    for parameter in module.definition.parameters
                }
                identity_items = [
                    node.parameters.get(key, parameter_defaults.get(key))
                    for key in ("model_name", "model", "model_id")
                    if (
                        key in node.parameters
                        or parameter_defaults.get(key) is not None
                    )
                ]
                if identity_items:
                    model_facts.append(_sanitize({
                        "node_id": node.node_id,
                        "module_id": node.module_id,
                        "version": version,
                        "identity": identity_items[0],
                    }))
        return cls(
            project_id=project_id,
            run_id=run_id,
            source=discover_source(source_dir),
            workflow={"sha256": workflow_sha256(workflow)},
            modules=module_facts,
            run_seed=seed,
            effective_seeds={
                node_id: (
                    seed
                    if workflow.nodes[node_id].parameters.get("seed") is None
                    else workflow.nodes[node_id].parameters["seed"]
                )
                for node_id in sorted(workflow.nodes)
                if (
                    modules.get(workflow.nodes[node_id].module_id)
                    is not None
                    and modules[
                        workflow.nodes[node_id].module_id
                    ].uses_seed_for(
                        workflow.nodes[node_id].parameters
                    )
                )
            },
            environment=runtime,
            models=model_facts,
            recovery=(
                _sanitize(recovery.to_dict())
                if recovery is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the stable public JSON shape."""
        result = {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "workflow": self.workflow,
            "modules": self.modules,
            "run_seed": self.run_seed,
            "effective_seeds": self.effective_seeds,
            "environment": self.environment,
            "models": self.models,
            "providers": self.providers,
            "node_states": self.node_states,
            "failures": self.failures,
            "blocking_reasons": self.blocking_reasons,
            "cache": self.cache,
            "candidate_lineage": self.candidate_lineage,
            "scores": self.scores,
            "artifacts": self.artifacts,
        }
        if self.recovery is not None:
            result["recovery"] = self.recovery
        return _sanitize(result)


@dataclass(frozen=True)
class ResolvedProviderReadiness:
    """One normalized readiness fact ready for public persistence."""

    provider: str
    status: ReadinessStatus
    provider_identity: dict[str, Any]
    source: dict[str, Any]
    details: dict[str, Any]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, Any]:
        return _sanitize({
            "provider": self.provider,
            "status": self.status,
            "ready": self.ready,
            "provider_identity": self.provider_identity,
            "source": self.source,
            "details": self.details,
        })


def read_run_manifest(run_dir: str | Path) -> dict[str, Any]:
    """Read the complete durable JSON document for one contained run."""
    descriptor = open_private_regular_file(
        run_dir,
        ("manifest.json",),
        field="run_manifest",
    )
    try:
        before = os.fstat(descriptor)
        if before.st_size > 64 * 1024 * 1024:
            raise ValueError("Run manifest must be a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as manifest_file:
            payload = manifest_file.read()
        after = os.fstat(descriptor)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(
            getattr(before, field_name) != getattr(after, field_name)
            for field_name in stable_fields
        ):
            raise ValueError("Run manifest changed while reading")
    finally:
        os.close(descriptor)
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Run manifest must be a JSON object")
    return value


class RunManifestStore:
    """Atomically persist one manifest through a held run-directory handle."""

    def __init__(self, run_dir: str | Path, manifest: RunManifest) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self.run_dir.is_symlink():
            raise StoragePathError("run_id", "Invalid run_id")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        self._directory_fd = os.open(self.run_dir, flags)
        self._lock_fd = os.open(
            ".manifest.lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=self._directory_fd,
        )
        try:
            fcntl.flock(
                self._lock_fd,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            os.close(self._lock_fd)
            os.close(self._directory_fd)
            raise RuntimeError("Run manifest is already being updated") from None
        try:
            os.stat(
                "manifest.json",
                dir_fd=self._directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            self.close()
            raise FileExistsError("Run manifest already exists")
        self.manifest = manifest
        self._score_details_bytes = sum(
            len(canonical_json(score.get("details", {})))
            for score in manifest.scores
        )
        self.persist()

    @property
    def path(self) -> Path:
        return self.run_dir / "manifest.json"

    def persist(self) -> None:
        """Replace the complete manifest and fsync file plus directory."""
        self.manifest.updated_at = _timestamp()
        payload = json.dumps(
            _json_value(self.manifest.to_dict()),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ).encode()
        temporary_name = f".manifest.{secrets.token_hex(12)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=self._directory_fd,
            )
            with os.fdopen(descriptor, "wb", closefd=True) as destination:
                descriptor = None
                destination.write(payload)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(
                temporary_name,
                "manifest.json",
                src_dir_fd=self._directory_fd,
                dst_dir_fd=self._directory_fd,
            )
            os.fsync(self._directory_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=self._directory_fd)
            except FileNotFoundError:
                pass

    def set_status(self, status: str) -> None:
        self.manifest.status = status
        self.persist()

    def record_node_state(
        self,
        node_id: str,
        old_state: str,
        state: str,
    ) -> None:
        self.manifest.node_states.append({
            "sequence": len(self.manifest.node_states) + 1,
            "timestamp": _timestamp(),
            "node_id": validate_identifier(node_id, "node_id"),
            "old_state": old_state,
            "state": state,
        })
        self.persist()

    def record_cache(
        self,
        *,
        node_id: str,
        cache_key: str,
        outcome: str,
        published: bool = False,
    ) -> None:
        safe_node_id = validate_identifier(node_id, "node_id")
        self.manifest.cache.append({
            "node_id": safe_node_id,
            "cache_key": validate_identifier(cache_key, "cache_key"),
            "outcome": outcome,
            "published": published,
            "consumer": {
                "project_id": self.manifest.project_id,
                "run_id": self.manifest.run_id,
                "node_id": safe_node_id,
            },
        })
        self.persist()

    def record_provider_readiness(
        self,
        *,
        provider: str,
        ready: bool,
        status: str | None = None,
        provider_identity: dict[str, Any] | None = None,
        source: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        fact = _sanitize({
            "provider": provider,
            "ready": bool(ready),
            "details": details or {},
        })
        if status is not None:
            fact["status"] = status
        if provider_identity is not None:
            fact["provider_identity"] = provider_identity
        if source is not None:
            fact["source"] = source
        self.manifest.providers["readiness"].append(fact)
        self.persist()

    def record_resolved_provider_readiness(
        self,
        readiness: ResolvedProviderReadiness,
    ) -> None:
        self.manifest.providers["readiness"].append(readiness.to_dict())
        self.persist()

    def record_provider_call(
        self,
        *,
        provider: str,
        operation: str,
        model: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        fact: dict[str, Any] = {
            "provider": provider,
            "operation": operation,
        }
        if model is not None:
            fact["model"] = model
        if details:
            fact["details"] = details
        self.manifest.providers["calls"].append(_sanitize(fact))
        self.persist()

    def record_failure(
        self,
        *,
        node_id: str,
        kind: str,
        message: str,
    ) -> None:
        self.manifest.failures.append(_sanitize({
            "node_id": validate_identifier(node_id, "node_id"),
            "kind": kind,
            "message": message,
        }))
        self.persist()

    def record_blocked(
        self,
        *,
        node_id: str,
        upstream_node_ids: list[str],
    ) -> dict[str, Any]:
        reason = {
            "kind": "upstream_terminal",
            "message": "Required upstream Node did not complete",
            "upstream_node_ids": [
                validate_identifier(upstream_id, "node_id")
                for upstream_id in upstream_node_ids
            ],
        }
        self.manifest.blocking_reasons.append({
            "node_id": validate_identifier(node_id, "node_id"),
            "reason": reason,
        })
        self.persist()
        return reason

    def record_candidate_lineage(
        self,
        *,
        node_id: str,
        output_port: str,
        candidate_id: str,
        parent_ids: list[str],
    ) -> None:
        safe_node_id = validate_identifier(node_id, "node_id")
        safe_output_port = validate_identifier(
            output_port,
            "output_port",
        )
        safe_candidate_id = validate_identifier(
            candidate_id,
            "candidate_id",
        )
        safe_parent_ids = [
            validate_identifier(parent_id, "parent_id")
            for parent_id in parent_ids
        ]
        self.manifest.candidate_lineage.append({
            "node_id": safe_node_id,
            "output_port": safe_output_port,
            "candidate_id": safe_candidate_id,
            "parent_ids": safe_parent_ids,
        })
        self.persist()

    def record_score(
        self,
        *,
        node_id: str,
        output_port: str,
        score_id: str,
        value: float,
        subjects: list[str],
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record one bounded Candidate-bound scientific score."""
        self.record_scores(
            node_id=node_id,
            output_port=output_port,
            facts=[{
                "score_id": score_id,
                "value": value,
                "subjects": subjects,
                "details": details,
            }],
        )

    def record_scores(
        self,
        *,
        node_id: str,
        output_port: str,
        facts: Iterable[dict[str, Any]],
    ) -> None:
        """Validate one ScoreCollection and persist it once."""
        safe_node_id = validate_identifier(node_id, "node_id")
        safe_output_port = validate_identifier(
            output_port,
            "output_port",
        )
        staged: list[dict[str, Any]] = []
        staged_detail_bytes = 0
        for fact in facts:
            if (
                len(self.manifest.scores) + len(staged)
                >= _MAX_MANIFEST_SCORES
            ):
                raise RuntimeError("Run manifest score limit exceeded")
            if not isinstance(fact, dict):
                raise ValueError("Manifest score fact must be an object")
            record, detail_bytes = self._validated_score(
                node_id=safe_node_id,
                output_port=safe_output_port,
                score_id=fact.get("score_id"),
                value=fact.get("value"),
                subjects=fact.get("subjects"),
                details=fact.get("details"),
            )
            if (
                self._score_details_bytes
                + staged_detail_bytes
                + detail_bytes
                > _MAX_SCORE_DETAILS_TOTAL_BYTES
            ):
                raise ValueError(
                    "Manifest score detail total exceeds size limit"
                )
            staged.append(record)
            staged_detail_bytes += detail_bytes
        if not staged:
            return
        self.manifest.scores.extend(staged)
        self._score_details_bytes += staged_detail_bytes
        self.persist()

    @staticmethod
    def _validated_score(
        *,
        node_id: str,
        output_port: str,
        score_id: Any,
        value: Any,
        subjects: Any,
        details: Any,
    ) -> tuple[dict[str, Any], int]:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError("Manifest score value must be finite")
        if (
            not isinstance(subjects, list)
            or len(subjects) > _MAX_SCORE_SUBJECTS
        ):
            raise ValueError("Manifest score subject limit exceeded")
        safe_subjects = [
            validate_identifier(subject, "score_subject")
            for subject in subjects
        ]
        raw_details = {} if details is None else details
        if not isinstance(raw_details, dict):
            raise ValueError("Manifest score details must be an object")
        _validate_score_details(raw_details)
        safe_details = _sanitize(raw_details)
        detail_bytes = len(canonical_json(safe_details))
        if detail_bytes > _MAX_SCORE_DETAILS_BYTES:
            raise ValueError("Manifest score details exceed size limit")
        return ({
            "node_id": node_id,
            "output_port": output_port,
            "score_id": validate_identifier(score_id, "score_id"),
            "value": float(value),
            "subjects": safe_subjects,
            "details": safe_details,
        }, detail_bytes)

    def record_artifact(
        self,
        *,
        node_id: str,
        path: str | Path,
        output_dir: str | Path,
        candidate_id: str | None = None,
        output_port: str | None = None,
        artifact_kind: str | None = None,
    ) -> bool:
        """Hash one regular, non-symlinked artifact inside this run."""
        return self.record_artifacts(
            node_id=node_id,
            output_dir=output_dir,
            artifacts=[{
                "path": path,
                "candidate_id": candidate_id,
                "output_port": output_port,
                "artifact_kind": artifact_kind,
            }],
        )

    def record_artifacts(
        self,
        *,
        node_id: str,
        output_dir: str | Path,
        artifacts: Iterable[dict[str, Any]],
    ) -> bool:
        """Hash and bind an artifact collection with one manifest update."""
        records: list[dict[str, Any]] = []
        for artifact in artifacts:
            record = self._artifact_record(
                node_id=node_id,
                path=artifact.get("path"),
                output_dir=output_dir,
                candidate_id=artifact.get("candidate_id"),
                output_port=artifact.get("output_port"),
                artifact_kind=artifact.get("artifact_kind"),
            )
            if record is None:
                return False
            records.append(record)
        if not records:
            return True

        updated = [
            dict(existing)
            for existing in self.manifest.artifacts
        ]
        for record in records:
            self._merge_artifact_record(updated, record)
        previous = self.manifest.artifacts
        self.manifest.artifacts = updated
        try:
            self.persist()
        except Exception:
            self.manifest.artifacts = previous
            raise
        return True

    @staticmethod
    def _merge_artifact_record(
        artifacts: list[dict[str, Any]],
        record: dict[str, Any],
    ) -> None:
        existing = next(
            (
                artifact
                for artifact in artifacts
                if artifact.get("reference") == record["reference"]
            ),
            None,
        )
        if existing is None:
            artifacts.append(record)
            return
        existing_kind = (
            "standalone"
            if existing.get("artifact_kind") == "standalone"
            else (
                "candidate"
                if existing.get("candidate_id") is not None
                else None
            )
        )
        record_kind = (
            "standalone"
            if record.get("artifact_kind") == "standalone"
            else (
                "candidate"
                if record.get("candidate_id") is not None
                else None
            )
        )
        if (
            existing_kind is not None
            and record_kind is not None
            and existing_kind != record_kind
        ):
            raise RuntimeError(
                "Artifact reference has conflicting provenance"
            )
        for field_name in ("node_id", "size", "sha256"):
            if existing.get(field_name) != record[field_name]:
                raise RuntimeError(
                    "Artifact reference has conflicting provenance"
                )
        for field_name in ("output_port", "candidate_id"):
            value = record.get(field_name)
            if value is None:
                continue
            current = existing.get(field_name)
            if current is not None and current != value:
                raise RuntimeError(
                    "Artifact reference has conflicting provenance"
                )
            if current is None:
                existing[field_name] = value

    @staticmethod
    def _artifact_record(
        *,
        node_id: str,
        path: str | Path,
        output_dir: str | Path,
        candidate_id: str | None,
        output_port: str | None,
        artifact_kind: str | None,
    ) -> dict[str, Any] | None:
        if output_port is None:
            raise ValueError(
                "Artifact requires an output Port binding"
            )
        if candidate_id is None:
            if artifact_kind != "standalone":
                raise ValueError(
                    "Candidate-less artifact requires standalone opt-in"
                )
        elif artifact_kind is not None:
            raise ValueError(
                "Candidate artifact cannot be standalone"
            )
        output_root = Path(output_dir).absolute()
        supplied = Path(path)
        candidate = Path(os.path.abspath(
            supplied if supplied.is_absolute() else output_root / supplied
        ))
        try:
            reference = candidate.relative_to(output_root).as_posix()
        except ValueError:
            raise StoragePathError(
                "artifact_path",
                "Invalid artifact_path",
            ) from None
        reference_parts = validate_relative_path(
            reference,
            "artifact_path",
        )
        try:
            descriptor = open_private_regular_file(
                output_root,
                reference_parts,
                field="artifact_path",
            )
        except FileNotFoundError:
            return None
        except OSError as error:
            raise StoragePathError(
                "artifact_path",
                "Invalid artifact_path",
            ) from error
        try:
            before = os.fstat(descriptor)
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "rb", closefd=False) as artifact:
                while chunk := artifact.read(1024 * 1024):
                    digest.update(chunk)
            after = os.fstat(descriptor)
            stable_fields = (
                "st_dev",
                "st_ino",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
            if any(
                getattr(before, field_name) != getattr(after, field_name)
                for field_name in stable_fields
            ):
                raise RuntimeError("Artifact changed while hashing")
            record: dict[str, Any] = {
                "node_id": validate_identifier(node_id, "node_id"),
                "reference": reference,
                "size": after.st_size,
                "sha256": digest.hexdigest(),
            }
            record["output_port"] = validate_identifier(
                output_port,
                "output_port",
            )
            if candidate_id is not None:
                record["candidate_id"] = validate_identifier(
                    candidate_id,
                    "candidate_id",
                )
            else:
                record["artifact_kind"] = artifact_kind
            return record
        finally:
            os.close(descriptor)

    def mark_cache_published(self, node_id: str, cache_key: str) -> None:
        for event in reversed(self.manifest.cache):
            if (
                event["node_id"] == node_id
                and event["cache_key"] == cache_key
            ):
                event["published"] = True
                self.persist()
                return

    def close(self) -> None:
        if getattr(self, "_lock_fd", -1) >= 0:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = -1
        if self._directory_fd >= 0:
            os.close(self._directory_fd)
            self._directory_fd = -1

    def __enter__(self) -> "RunManifestStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def create_run_manifest_store(
    *,
    run_dir: str | Path,
    project_id: str,
    run_id: str,
    workflow: Workflow,
    modules: dict[str, WorkflowModule],
    seed: int,
    source_dir: str | Path,
    environment: dict[str, Any] | None = None,
    recovery: RecoveryProvenance | None = None,
    store_factory: Callable[
        [str | Path, RunManifest],
        RunManifestStore,
    ] = RunManifestStore,
) -> RunManifestStore:
    """Create the canonical manifest owner for one run."""
    return store_factory(
        run_dir,
        RunManifest.for_execution(
            project_id=project_id,
            run_id=run_id,
            workflow=workflow,
            modules=modules,
            seed=seed,
            source_dir=source_dir,
            environment=environment,
            recovery=recovery,
        ),
    )
