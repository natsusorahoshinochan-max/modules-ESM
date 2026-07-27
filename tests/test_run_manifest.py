"""Public run-manifest and Cache provenance behavior."""

from __future__ import annotations

import asyncio
import json
import pickle
import subprocess
from pathlib import Path
from typing import Any

from core import Executor, Workflow, WorkflowNode
from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import Candidate, CandidateCollection, ProteinStructure


class ManifestObservingModule(WorkflowModule):
    """A test Module that observes the durable public run namespace."""

    def __init__(self, expected_manifest: Path) -> None:
        self.expected_manifest = expected_manifest
        self.observed_status: str | None = None
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
        del inputs, parameters, context
        self.observed_status = json.loads(
            self.expected_manifest.read_text()
        )["status"]
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
            details={"authorization": "Bearer runtime-placeholder"},
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

    manifest = json.loads(manifest_path.read_text())
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

    origin_manifest = json.loads(
        (
            project_dir
            / "runs"
            / "cache-origin"
            / "manifest.json"
        ).read_text()
    )
    consumer_manifest = json.loads(
        (
            project_dir
            / "runs"
            / "cache-consumer"
            / "manifest.json"
        ).read_text()
    )
    assert CountingModule.calls == 1
    assert first_result == second_result == {"count": {"text": "call-1"}}
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

        manifest = json.loads(
            (
                project_dir / "runs" / run_id / "manifest.json"
            ).read_text()
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

    manifest = json.loads(
        (
            project_dir / "runs" / "artifact-run" / "manifest.json"
        ).read_text()
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
            "message": "provider rejected api_key=[REDACTED]",
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
    origin = json.loads(
        (
            project_dir / "runs" / "safe-origin" / "manifest.json"
        ).read_text()
    )
    cache_key = origin["cache"][0]["cache_key"]
    cache_path = project_dir / "cache" / "count" / f"{cache_key}.pkl"
    marker = tmp_path / "unsafe-pickle-executed"
    cache_path.write_bytes(pickle.dumps(UntrustedCachePayload(marker)))

    run("untrusted-cache")

    manifest = json.loads(
        (
            project_dir / "runs" / "untrusted-cache" / "manifest.json"
        ).read_text()
    )
    assert not marker.exists()
    assert CountingModule.calls == 2
    assert manifest["cache"][0]["outcome"] == "miss"
