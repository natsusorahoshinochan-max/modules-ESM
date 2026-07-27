"""Public run-manifest and Cache provenance behavior."""

from __future__ import annotations

import asyncio
import json
import os
import pickle
import subprocess
from pathlib import Path
from typing import Any

import pytest

from core import (
    CachePublishStatus,
    CacheStore,
    Executor,
    RunManifest,
    RunManifestStore,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    read_run_manifest,
)
from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.storage import StoragePathError
from core.workflow_module import WorkflowModule
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinStructure,
    ResidueLayout,
    ResidueTrack,
)
from modules.prompt_random_insert_masked import RandomInsertMaskedModule


class ManifestObservingModule(WorkflowModule):
    """A test Module that observes the durable public run namespace."""

    uses_seed = True

    def __init__(self, expected_manifest: Path) -> None:
        self.expected_manifest = expected_manifest
        self.observed_status: str | None = None
        self.observed_seed: int | None = None
        self._definition = ModuleDefinition.from_yaml_string(
            """
module_id: test.manifest_observer
version: 2.4.1
display_name: Manifest observer
category: model
output_ports:
  - name: text
    type_id: text
parameters:
  - name: model_name
    type: str
"""
        )

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del inputs, parameters
        self.observed_status = read_run_manifest(
            self.expected_manifest.parent
        )["status"]
        self.observed_seed = context.seed
        return {"text": "complete"}


class CountingModule(WorkflowModule):
    """A complete Module whose executions are visible at the public seam."""

    calls = 0

    def __init__(self) -> None:
        self._definition = ModuleDefinition.from_yaml_string(
            """
module_id: test.counting
version: 1.0.0
display_name: Counting
category: conversion
output_ports:
  - name: text
    type_id: text
parameters:
  - name: options
    type: str
"""
        )

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del inputs, parameters, context
        type(self).calls += 1
        return {"text": f"call-{self.calls}"}


class TrackSourceModule(WorkflowModule):
    """A complete typed source for the canonical insertion Module."""

    def __init__(self) -> None:
        self._definition = ModuleDefinition.from_yaml_string(
            """
module_id: test.track_source
version: 1.0.0
display_name: Track source
category: input
output_ports:
  - name: track
    type_id: residue.track
  - name: layout
    type_id: residue.layout
"""
        )

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del inputs, parameters, context
        return {
            "track": ResidueTrack(values=["A", "C"], sentinel=None),
            "layout": ResidueLayout(chain_id="A", length=2),
        }


class MissingSelectedTrackOutputModule(RandomInsertMaskedModule):
    """A contract-violating Module that omits its selected typed output."""

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del parameters, context
        return {"layout": inputs["layout"]}


def _typed_output_workflow() -> Workflow:
    workflow = Workflow()
    workflow.add_node(
        WorkflowNode("source", "test.track_source", "1.0.0")
    )
    workflow.add_node(
        WorkflowNode(
            "insert",
            "prompt.random_insert_masked",
            "1.1.0",
            {"count": 1},
        )
    )
    workflow.add_edge(
        WorkflowEdge("source", "track", "insert", "track")
    )
    workflow.add_edge(
        WorkflowEdge("source", "layout", "insert", "layout")
    )
    return workflow


class PartialModule(WorkflowModule):
    """A contract-violating Module that returns an incomplete output set."""

    calls = 0

    def __init__(self) -> None:
        self._definition = ModuleDefinition.from_yaml_string(
            """
module_id: test.partial
version: 1.0.0
display_name: Partial
category: conversion
output_ports:
  - name: required_output
    type_id: text
"""
        )

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del inputs, parameters, context
        type(self).calls += 1
        return {}


class NonePartialModule(PartialModule):
    """A partial Module that names its Port but has no value for it."""

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del inputs, parameters, context
        type(self).calls += 1
        return {"required_output": None}


class ProviderModule(WorkflowModule):
    """A Module that records one real provider-boundary call."""

    calls = 0

    def __init__(self) -> None:
        self._definition = ModuleDefinition.from_yaml_string(
            """
module_id: test.provider
version: 3.0.0
display_name: Provider
category: model
output_ports:
  - name: text
    type_id: text
"""
        )

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del inputs, parameters
        type(self).calls += 1
        context.record_provider_call(
            "fixture-provider",
            "generate",
            model="fixture-model-v3",
            details={
                "authorization": "Basic dXNlcjpwYXNz",
                "cookie": "session=runtime-placeholder",
            },
        )
        return {"text": "provider-output"}


class ArtifactCandidateModule(WorkflowModule):
    """A Module producing both Candidate lineage and a run artifact."""

    def __init__(self) -> None:
        self._definition = ModuleDefinition.from_yaml_string(
            """
module_id: test.artifact_candidate
version: 1.0.0
display_name: Artifact candidate
category: model
output_ports:
  - name: candidates
    type_id: protein.structure.collection
  - name: file_path
    type_id: file.path
"""
        )

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del inputs, parameters
        artifact = context.output_path("models/model-1.pdb")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"MODEL\n")
        candidates = CandidateCollection(
            collection_id="generated",
            item_type="protein.structure",
            items=[
                Candidate(
                    candidate_id="candidate-1",
                    data=ProteinStructure(pdb_string="MODEL\n"),
                    parent_ids=["prompt-7"],
                )
            ],
        )
        return {"candidates": candidates, "file_path": str(artifact)}


class FailingProviderModule(WorkflowModule):
    """A Module whose diagnostic repeats a credential-like parameter."""

    def __init__(self) -> None:
        self._definition = ModuleDefinition.from_yaml_string(
            """
module_id: test.failing_provider
version: 1.0.0
display_name: Failing provider
category: model
output_ports:
  - name: text
    type_id: text
parameters:
  - name: api_key
    type: str
"""
        )

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del inputs, context
        raise RuntimeError(
            f"provider rejected api_key={parameters['api_key']}"
        )


class UntrustedCachePayload:
    """A pickle payload that would create a marker if globals were allowed."""

    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self) -> tuple[Any, tuple[str]]:
        import os

        return os.system, (f"touch {self.marker}",)


def _git(command: list[str], repository: Path) -> str:
    return subprocess.run(
        ["git", *command],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_executor_persists_source_bound_manifest_before_node_execution(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(["init", "-b", "main"], source)
    _git(["config", "user.name", "Manifest Test"], source)
    _git(["config", "user.email", "manifest@example.invalid"], source)
    (source / "tracked.txt").write_text("known source\n")
    _git(["add", "tracked.txt"], source)
    _git(["commit", "-m", "known source"], source)
    expected_revision = _git(["rev-parse", "HEAD"], source)

    project_dir = tmp_path / "project"
    manifest_path = project_dir / "runs" / "source-bound" / "manifest.json"
    module = ManifestObservingModule(manifest_path)
    workflow = Workflow()
    workflow.add_node(
        WorkflowNode(
            "observer",
            "test.manifest_observer",
            "2.4.1",
            {"model_name": "known-model", "nested": {"b": 2, "a": 1}},
        )
    )

    asyncio.run(
        Executor().execute(
            workflow,
            {"test.manifest_observer": module},
            str(project_dir),
            "source-bound",
            seed=73,
            project_id="project-11",
            source_dir=source,
            environment={"runtime": "fixture-runtime"},
        )
    )

    manifest = read_run_manifest(manifest_path.parent)
    assert module.observed_status == "running"
    assert manifest["status"] == "completed"
    assert manifest["project_id"] == "project-11"
    assert manifest["run_id"] == "source-bound"
    assert manifest["source"] == {
        "revision": expected_revision,
        "dirty": False,
    }
    assert manifest["workflow"]["sha256"] == (
        "dd797a2a527c418e3039395ff17ebfb4ee9164942105161046083912685a33a5"
    )
    assert manifest["modules"] == [
        {
            "node_id": "observer",
            "module_id": "test.manifest_observer",
            "version": "2.4.1",
        }
    ]
    assert manifest["effective_seeds"] == {"observer": 73}
    assert manifest["environment"]["runtime"] == "fixture-runtime"
    assert manifest["models"] == [
        {
            "node_id": "observer",
            "module_id": "test.manifest_observer",
            "version": "2.4.1",
            "identity": "known-model",
        }
    ]
    assert [
        (event["node_id"], event["state"])
        for event in manifest["node_states"]
    ] == [
        ("observer", "queued"),
        ("observer", "running"),
        ("observer", "completed"),
    ]


def test_node_seed_override_is_the_effective_manifest_seed(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    manifest_path = project_dir / "runs" / "node-seed" / "manifest.json"
    module = ManifestObservingModule(manifest_path)
    workflow = Workflow()
    workflow.add_node(
        WorkflowNode(
            "observer",
            "test.manifest_observer",
            "2.4.1",
            {"seed": 101},
        )
    )

    asyncio.run(
        Executor().execute(
            workflow,
            {"test.manifest_observer": module},
            str(project_dir),
            "node-seed",
            seed=73,
        )
    )

    manifest = read_run_manifest(manifest_path.parent)
    assert module.observed_seed == 101
    assert manifest["effective_seeds"] == {"observer": 101}


def test_source_discovery_does_not_execute_repository_fsmonitor(
    tmp_path: Path,
) -> None:
    source = tmp_path / "untrusted-source"
    source.mkdir()
    _git(["init", "-b", "main"], source)
    _git(["config", "user.name", "Manifest Test"], source)
    _git(["config", "user.email", "manifest@example.invalid"], source)
    (source / "tracked.txt").write_text("source\n")
    _git(["add", "tracked.txt"], source)
    _git(["commit", "-m", "source"], source)
    fsmonitor = source / "fsmonitor"
    fsmonitor.write_text(
        "#!/bin/sh\n"
        "touch fsmonitor-executed\n"
        "printf '1\\n'\n"
    )
    fsmonitor.chmod(0o700)
    _git(["config", "core.fsmonitor", "./fsmonitor"], source)

    workflow = Workflow()
    asyncio.run(
        Executor().execute(
            workflow,
            {},
            str(tmp_path / "project"),
            "source-probe",
            source_dir=source,
        )
    )

    assert not (source / "fsmonitor-executed").exists()


def test_recursive_parameter_identity_attributes_cache_hit_to_consuming_run(
    tmp_path: Path,
) -> None:
    CountingModule.calls = 0
    project_dir = tmp_path / "project"
    module = CountingModule()

    first = Workflow()
    first.add_node(
        WorkflowNode(
            "count",
            "test.counting",
            "1.0.0",
            {
                "options": {
                    "outer": {
                        "alpha": 1,
                        "beta": {"x": 2, "y": 3},
                    }
                }
            },
        )
    )
    second = Workflow()
    second.add_node(
        WorkflowNode(
            "count",
            "test.counting",
            "1.0.0",
            {
                "options": {
                    "outer": {
                        "beta": {"y": 3, "x": 2},
                        "alpha": 1,
                    }
                }
            },
        )
    )

    first_result = asyncio.run(
        Executor().execute(
            first,
            {"test.counting": module},
            str(project_dir),
            "cache-origin",
            project_id="project-11",
        )
    )
    second_result = asyncio.run(
        Executor().execute(
            second,
            {"test.counting": module},
            str(project_dir),
            "cache-consumer",
            project_id="project-11",
        )
    )

    origin_manifest = read_run_manifest(
        project_dir / "runs" / "cache-origin"
    )
    consumer_manifest = read_run_manifest(
        project_dir / "runs" / "cache-consumer"
    )
    assert CountingModule.calls == 1
    assert first_result == second_result == {"count": {"text": "call-1"}}
    assert origin_manifest["effective_seeds"] == {}
    assert origin_manifest["cache"] == [
        {
            "node_id": "count",
            "cache_key": consumer_manifest["cache"][0]["cache_key"],
            "outcome": "miss",
            "published": True,
            "consumer": {
                "project_id": "project-11",
                "run_id": "cache-origin",
                "node_id": "count",
            },
        }
    ]
    assert consumer_manifest["cache"] == [
        {
            "node_id": "count",
            "cache_key": origin_manifest["cache"][0]["cache_key"],
            "outcome": "hit",
            "published": False,
            "consumer": {
                "project_id": "project-11",
                "run_id": "cache-consumer",
                "node_id": "count",
            },
        }
    ]


def test_requested_seed_always_partitions_cache_without_false_effective_seed(
    tmp_path: Path,
) -> None:
    CountingModule.calls = 0
    project_dir = tmp_path / "project"
    cache_keys = []
    for seed in (11, 12):
        workflow = Workflow()
        workflow.add_node(
            WorkflowNode("count", "test.counting", "1.0.0")
        )
        asyncio.run(
            Executor().execute(
                workflow,
                {"test.counting": CountingModule()},
                str(project_dir),
                f"seed-{seed}",
                seed=seed,
                project_id="project-11",
            )
        )
        manifest = read_run_manifest(
            project_dir / "runs" / f"seed-{seed}"
        )
        assert manifest["effective_seeds"] == {}
        cache_keys.append(manifest["cache"][0]["cache_key"])

    assert CountingModule.calls == 2
    assert cache_keys[0] != cache_keys[1]


def test_state_callback_failure_cannot_leave_manifest_non_terminal(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    workflow = Workflow()
    workflow.add_node(
        WorkflowNode("count", "test.counting", "1.0.0")
    )
    executor = Executor()

    def broken_callback(*_: object) -> None:
        raise RuntimeError("observer failed")

    executor.on_state_change(broken_callback)
    result = asyncio.run(
        executor.execute(
            workflow,
            {"test.counting": CountingModule()},
            str(project_dir),
            "callback-failure",
            project_id="project-11",
        )
    )

    manifest = read_run_manifest(
        project_dir / "runs" / "callback-failure"
    )
    assert result["count"]["text"].startswith("call-")
    assert manifest["status"] == "completed"


def test_executor_accepts_selected_typed_output_and_records_complete_manifest(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    workflow = _typed_output_workflow()

    result = asyncio.run(
        Executor().execute(
            workflow,
            {
                "test.track_source": TrackSourceModule(),
                "prompt.random_insert_masked": RandomInsertMaskedModule(),
            },
            str(project_dir),
            "typed-output",
            seed=42,
            project_id="project-11-15",
        )
    )

    inserted = result["insert"]
    assert set(inserted) == {"track", "layout"}
    assert inserted["track"].values.count(None) == 1
    assert inserted["layout"].length == 3
    manifest = read_run_manifest(
        project_dir / "runs" / "typed-output"
    )
    assert manifest["status"] == "completed"
    assert manifest["failures"] == []
    assert [
        (event["node_id"], event["outcome"], event["published"])
        for event in manifest["cache"]
    ] == [
        ("source", "miss", True),
        ("insert", "miss", True),
    ]


def test_missing_selected_typed_output_fails_and_is_not_cached(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    workflow = _typed_output_workflow()

    result = asyncio.run(
        Executor().execute(
            workflow,
            {
                "test.track_source": TrackSourceModule(),
                "prompt.random_insert_masked": (
                    MissingSelectedTrackOutputModule()
                ),
            },
            str(project_dir),
            "missing-typed-output",
            seed=42,
            project_id="project-11-15",
        )
    )

    assert set(result) == {"source"}
    manifest = read_run_manifest(
        project_dir / "runs" / "missing-typed-output"
    )
    assert manifest["status"] == "failed"
    assert manifest["failures"][0]["kind"] == "incomplete_node_output"
    assert manifest["cache"][-1]["node_id"] == "insert"
    assert manifest["cache"][-1]["published"] is False


def test_partial_node_output_fails_structurally_and_is_never_cached(
    tmp_path: Path,
) -> None:
    PartialModule.calls = 0
    project_dir = tmp_path / "project"
    module = PartialModule()

    for run_id in ("partial-a", "partial-b"):
        workflow = Workflow()
        workflow.add_node(
            WorkflowNode("partial", "test.partial", "1.0.0")
        )
        assert asyncio.run(
            Executor().execute(
                workflow,
                {"test.partial": module},
                str(project_dir),
                run_id,
                project_id="project-11",
            )
        ) == {}

        manifest = read_run_manifest(
            project_dir / "runs" / run_id
        )
        assert manifest["status"] == "failed"
        assert manifest["failures"] == [
            {
                "node_id": "partial",
                "kind": "incomplete_node_output",
                "message": (
                    "Module 'test.partial' did not produce required "
                    "output Ports: required_output"
                ),
            }
        ]
        assert manifest["cache"][0]["outcome"] == "miss"
        assert manifest["cache"][0]["published"] is False

    assert PartialModule.calls == 2
    assert list((project_dir / "cache").rglob("*.pkl")) == []


def test_none_valued_required_output_is_partial_and_never_cached(
    tmp_path: Path,
) -> None:
    NonePartialModule.calls = 0
    project_dir = tmp_path / "project"
    workflow = Workflow()
    workflow.add_node(
        WorkflowNode("partial", "test.partial", "1.0.0")
    )

    result = asyncio.run(
        Executor().execute(
            workflow,
            {"test.partial": NonePartialModule()},
            str(project_dir),
            "none-partial",
            project_id="project-11",
        )
    )

    manifest = read_run_manifest(
        project_dir / "runs" / "none-partial"
    )
    assert result == {}
    assert manifest["status"] == "failed"
    assert manifest["failures"][0]["kind"] == "incomplete_node_output"
    assert manifest["cache"][0]["published"] is False
    assert list((project_dir / "cache").rglob("*.pkl")) == []


def test_cache_publication_rejects_symlinked_node_namespace(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    outside = tmp_path / "outside"
    outside.mkdir()
    cache_root = project_dir / "cache"
    cache_root.mkdir(parents=True)
    (cache_root / "count").symlink_to(outside, target_is_directory=True)
    workflow = Workflow()
    workflow.add_node(
        WorkflowNode("count", "test.counting", "1.0.0")
    )

    asyncio.run(
        Executor().execute(
            workflow,
            {"test.counting": CountingModule()},
            str(project_dir),
            "symlink-cache",
            project_id="project-11",
        )
    )

    assert list(outside.iterdir()) == []


def test_provider_readiness_is_distinct_from_redacted_actual_calls(
    tmp_path: Path,
) -> None:
    ProviderModule.calls = 0
    project_dir = tmp_path / "project"
    module = ProviderModule()
    readiness = {
        "fixture-provider": {
            "ready": True,
            "api_key": "readiness-placeholder-value",
            "endpoint": "https://provider.example.invalid",
        }
    }

    for run_id in ("provider-origin", "provider-cache-hit"):
        workflow = Workflow()
        workflow.add_node(
            WorkflowNode("provider", "test.provider", "3.0.0")
        )
        asyncio.run(
            Executor().execute(
                workflow,
                {"test.provider": module},
                str(project_dir),
                run_id,
                project_id="project-11",
                provider_readiness=readiness,
            )
        )

    origin_text = (
        project_dir
        / "runs"
        / "provider-origin"
        / "manifest.json"
    ).read_text()
    cache_hit_text = (
        project_dir
        / "runs"
        / "provider-cache-hit"
        / "manifest.json"
    ).read_text()
    origin = json.loads(origin_text)
    cache_hit = json.loads(cache_hit_text)

    assert ProviderModule.calls == 1
    assert origin["providers"] == {
        "readiness": [
            {
                "provider": "fixture-provider",
                "ready": True,
                "details": {
                    "api_key": "[REDACTED]",
                    "endpoint": "https://provider.example.invalid",
                },
            }
        ],
        "calls": [
            {
                "provider": "fixture-provider",
                "operation": "generate",
                "model": "fixture-model-v3",
                "details": {
                    "node_id": "provider",
                    "authorization": "[REDACTED]",
                    "cookie": "[REDACTED]",
                },
            }
        ],
    }
    assert cache_hit["providers"]["readiness"] == (
        origin["providers"]["readiness"]
    )
    assert cache_hit["providers"]["calls"] == []
    assert cache_hit["cache"][0]["outcome"] == "hit"
    assert "readiness-placeholder-value" not in origin_text + cache_hit_text
    assert "runtime-placeholder" not in origin_text + cache_hit_text
    assert "dXNlcjpwYXNz" not in origin_text + cache_hit_text


def test_candidate_lineage_and_artifact_integrity_are_run_bound(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    workflow = Workflow()
    workflow.add_node(
        WorkflowNode(
            "generator",
            "test.artifact_candidate",
            "1.0.0",
        )
    )

    asyncio.run(
        Executor().execute(
            workflow,
            {"test.artifact_candidate": ArtifactCandidateModule()},
            str(project_dir),
            "artifact-run",
            project_id="project-11",
        )
    )

    manifest = read_run_manifest(
        project_dir / "runs" / "artifact-run"
    )
    assert manifest["candidate_lineage"] == [
        {
            "node_id": "generator",
            "output_port": "candidates",
            "candidate_id": "candidate-1",
            "parent_ids": ["prompt-7"],
        }
    ]
    assert manifest["artifacts"] == [
        {
            "node_id": "generator",
            "output_port": "candidates",
            "candidate_id": "candidate-1",
            "reference": "models/model-1.pdb",
            "size": 6,
            "sha256": (
                "9ebc83e1f0234ba216df410887534d108"
                "90a4aee0fdae5dbf5a6c770b1642596"
            ),
        }
    ]
    assert manifest["cache"][0]["outcome"] == "miss"
    assert manifest["cache"][0]["published"] is False
    assert str(project_dir) not in json.dumps(manifest["artifacts"])


def test_manifest_store_refuses_hardlinked_artifacts(
    tmp_path: Path,
) -> None:
    workflow = Workflow()
    manifest = RunManifest.for_execution(
        project_id="project-11",
        run_id="hardlink-run",
        workflow=workflow,
        modules={},
        seed=42,
        source_dir=tmp_path,
    )
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    outside = tmp_path / "outside-secret"
    outside.write_bytes(b"SECRET")
    linked = output_dir / "artifact.bin"
    os.link(outside, linked)

    with RunManifestStore(tmp_path / "run", manifest) as store:
        with pytest.raises(StoragePathError):
            store.record_artifact(
                node_id="export",
                path=linked,
                output_dir=output_dir,
                candidate_id="candidate-1",
                output_port="structures",
            )


def test_failure_diagnostics_and_environment_are_recursively_redacted(
    tmp_path: Path,
) -> None:
    credential_placeholder = "fixture-value-built-at-runtime"
    project_dir = tmp_path / "project"
    workflow = Workflow()
    workflow.add_node(
        WorkflowNode(
            "provider",
            "test.failing_provider",
            "1.0.0",
            {"api_key": credential_placeholder},
        )
    )

    asyncio.run(
        Executor().execute(
            workflow,
            {"test.failing_provider": FailingProviderModule()},
            str(project_dir),
            "redacted-failure",
            project_id="project-11",
            environment={
                "nested": {
                    "credentials": {
                        "access_token": credential_placeholder,
                    }
                }
            },
        )
    )

    manifest_text = (
        project_dir
        / "runs"
        / "redacted-failure"
        / "manifest.json"
    ).read_text()
    manifest = json.loads(manifest_text)
    assert credential_placeholder not in manifest_text
    assert manifest["status"] == "failed"
    assert manifest["environment"]["nested"] == {
        "credentials": "[REDACTED]"
    }
    assert manifest["failures"] == [
        {
            "node_id": "provider",
            "kind": "RuntimeError",
            "message": "Node execution failed (RuntimeError)",
        }
    ]


def test_untrusted_cache_payload_is_a_miss_and_is_not_executed(
    tmp_path: Path,
) -> None:
    CountingModule.calls = 0
    project_dir = tmp_path / "project"
    module = CountingModule()

    def run(run_id: str) -> None:
        workflow = Workflow()
        workflow.add_node(
            WorkflowNode("count", "test.counting", "1.0.0")
        )
        asyncio.run(
            Executor().execute(
                workflow,
                {"test.counting": module},
                str(project_dir),
                run_id,
                project_id="project-11",
            )
        )

    run("safe-origin")
    origin = read_run_manifest(
        project_dir / "runs" / "safe-origin"
    )
    cache_key = origin["cache"][0]["cache_key"]
    cache_path = Executor().cache_path(
        str(project_dir),
        "count",
        cache_key,
    )
    marker = tmp_path / "unsafe-pickle-executed"
    cache_path.write_bytes(pickle.dumps(UntrustedCachePayload(marker)))

    run("untrusted-cache")

    manifest = read_run_manifest(
        project_dir / "runs" / "untrusted-cache"
    )
    assert not marker.exists()
    assert CountingModule.calls == 2
    assert manifest["cache"][0]["outcome"] == "miss"

    cache_path.write_bytes(pickle.dumps({"text": "forged"}))
    run("forged-cache")
    forged_manifest = read_run_manifest(
        project_dir / "runs" / "forged-cache"
    )
    assert CountingModule.calls == 3
    assert forged_manifest["cache"][0]["outcome"] == "miss"


def test_manifest_object_never_retains_raw_credentials(
    tmp_path: Path,
) -> None:
    workflow = Workflow()
    workflow.add_node(
        WorkflowNode("count", "test.counting", "1.0.0")
    )
    placeholder = "runtime-only-credential-placeholder"
    manifest = RunManifest.for_execution(
        project_id="project-11",
        run_id="repr-redaction",
        workflow=workflow,
        modules={"test.counting": CountingModule()},
        seed=42,
        source_dir=tmp_path,
        environment={
            "api_key": placeholder,
            "endpoint": (
                f"https://{placeholder}@provider.example.invalid"
            ),
        },
    )

    assert placeholder not in repr(manifest)
    assert manifest.environment["api_key"] == "[REDACTED]"
    assert manifest.environment["endpoint"] == (
        "https://[REDACTED]@provider.example.invalid"
    )


def test_scoring_module_model_identity_is_not_category_dependent(
    tmp_path: Path,
) -> None:
    from modules.proteinmpnn.module_score import ProteinMPNNScoreModule

    workflow = Workflow()
    workflow.add_node(
        WorkflowNode(
            "score",
            "proteinmpnn.score",
            "1.0.0",
        )
    )
    manifest = RunManifest.for_execution(
        project_id="project-11",
        run_id="scoring-model",
        workflow=workflow,
        modules={"proteinmpnn.score": ProteinMPNNScoreModule()},
        seed=42,
        source_dir=tmp_path,
    )

    assert manifest.models == [
        {
            "node_id": "score",
            "module_id": "proteinmpnn.score",
            "version": "1.0.0",
            "identity": "v_48_020",
        }
    ]


def test_one_run_namespace_rejects_concurrent_manifest_writers(
    tmp_path: Path,
) -> None:
    workflow = Workflow()
    manifest = RunManifest.for_execution(
        project_id="project-11",
        run_id="exclusive-run",
        workflow=workflow,
        modules={},
        seed=42,
        source_dir=tmp_path,
    )
    run_dir = tmp_path / "runs" / "exclusive-run"

    with RunManifestStore(run_dir, manifest):
        competing = RunManifest.for_execution(
            project_id="project-11",
            run_id="exclusive-run",
            workflow=workflow,
            modules={},
            seed=42,
            source_dir=tmp_path,
        )
        with pytest.raises(
            RuntimeError,
            match="already being updated",
        ):
            RunManifestStore(run_dir, competing)


def test_cache_rejects_public_integrity_key_and_reports_publish_owner(
    tmp_path: Path,
) -> None:
    unsafe_root = tmp_path / "unsafe-cache"
    unsafe_node = unsafe_root / "node"
    unsafe_node.mkdir(parents=True, mode=0o777)
    unsafe_root.chmod(0o777)
    unsafe_node.chmod(0o777)
    integrity_key = unsafe_root / ".integrity-key"
    integrity_key.write_bytes(b"x" * 32)
    integrity_key.chmod(0o644)

    with CacheStore(unsafe_root, "node") as unsafe_cache:
        with pytest.raises(
            StoragePathError,
            match="integrity key permissions",
        ):
            unsafe_cache.load("unsafe")

    safe_root = tmp_path / "safe-cache"
    with CacheStore(safe_root, "node") as safe_cache:
        assert safe_cache.save("key", {"text": "first"}) == (
            CachePublishStatus.CREATED
        )
        assert safe_cache.save("key", {"text": "second"}) == (
            CachePublishStatus.EXISTING_VALID
        )
        garbage = safe_cache.path("garbage")
        garbage.write_bytes(b"not an authenticated envelope")
        garbage.chmod(0o600)
        assert safe_cache.save("garbage", {"text": "value"}) == (
            CachePublishStatus.FAILED
        )
