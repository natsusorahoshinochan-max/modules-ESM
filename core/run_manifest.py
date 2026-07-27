"""Durable source-bound facts for one Workflow run."""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import platform
import re
import secrets
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.graph import Workflow
from core.storage import StoragePathError, validate_identifier
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
_URI_USERINFO = re.compile(
    r"([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@"
)
_OPAQUE_API_TOKEN = re.compile(
    r"\b(?:(?:sk|pk)-[A-Za-z0-9_-]{8,}|hf_[A-Za-z0-9_-]{8,})\b"
)


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
    redacted = _KEY_VALUE.sub(r"\1\2[REDACTED]", redacted)
    redacted = _URI_USERINFO.sub(r"\1[REDACTED]@", redacted)
    return _OPAQUE_API_TOKEN.sub("[REDACTED]", redacted)


def _sanitize(value: Any) -> Any:
    secrets_to_redact = tuple(
        sorted(_secret_values(value), key=len, reverse=True)
    )
    return _redact(value, secrets_to_redact)


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
    effective_seeds: dict[str, int]
    environment: dict[str, Any]
    models: list[dict[str, Any]]
    status: str = "created"
    schema_version: int = 1
    created_at: str = field(default_factory=_timestamp)
    updated_at: str = field(default_factory=_timestamp)
    node_states: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    cache: list[dict[str, Any]] = field(default_factory=list)
    providers: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"readiness": [], "calls": []}
    )
    candidate_lineage: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

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
            effective_seeds={
                node_id: seed
                for node_id in sorted(workflow.nodes)
                if (
                    modules.get(workflow.nodes[node_id].module_id)
                    is not None
                    and modules[
                        workflow.nodes[node_id].module_id
                    ].uses_seed
                )
            },
            environment=runtime,
            models=model_facts,
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
            "effective_seeds": self.effective_seeds,
            "environment": self.environment,
            "models": self.models,
            "providers": self.providers,
            "node_states": self.node_states,
            "failures": self.failures,
            "cache": self.cache,
            "candidate_lineage": self.candidate_lineage,
            "artifacts": self.artifacts,
        }
        return _sanitize(result)


def read_run_manifest(run_dir: str | Path) -> dict[str, Any]:
    """Read the complete durable JSON document for one contained run."""
    path = Path(run_dir) / "manifest.json"
    if path.is_symlink():
        raise StoragePathError("run_id", "Invalid run_id")
    value = json.loads(path.read_text())
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
        details: dict[str, Any] | None = None,
    ) -> None:
        fact = _sanitize({
            "provider": provider,
            "ready": bool(ready),
            "details": details or {},
        })
        self.manifest.providers["readiness"].append(fact)
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

    def record_candidate_lineage(
        self,
        *,
        node_id: str,
        output_port: str,
        candidate_id: str,
        parent_ids: list[str],
    ) -> None:
        self.manifest.candidate_lineage.append({
            "node_id": validate_identifier(node_id, "node_id"),
            "output_port": output_port,
            "candidate_id": candidate_id,
            "parent_ids": list(parent_ids),
        })
        self.persist()

    def record_artifact(
        self,
        *,
        node_id: str,
        path: str | Path,
        output_dir: str | Path,
    ) -> bool:
        """Hash one regular, non-symlinked artifact inside this run."""
        output_root = Path(output_dir).resolve()
        supplied = Path(path)
        candidate = (
            supplied if supplied.is_absolute() else output_root / supplied
        )
        if candidate.is_symlink():
            raise StoragePathError("artifact_path", "Invalid artifact_path")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(output_root):
            raise StoragePathError("artifact_path", "Invalid artifact_path")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(resolved, flags)
        except FileNotFoundError:
            return False
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise StoragePathError(
                    "artifact_path",
                    "Invalid artifact_path",
                )
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
            self.manifest.artifacts.append({
                "node_id": validate_identifier(node_id, "node_id"),
                "reference": resolved.relative_to(output_root).as_posix(),
                "size": after.st_size,
                "sha256": digest.hexdigest(),
            })
            self.persist()
            return True
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
