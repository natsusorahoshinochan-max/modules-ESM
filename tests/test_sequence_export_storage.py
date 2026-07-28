"""Containment contracts for run-scoped sequence exports."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.executor import Executor
from core.graph import Workflow, WorkflowEdge, WorkflowNode
from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.run_manifest import RunManifest, RunManifestStore
from core.storage import (
    StoragePathError,
    validate_relative_path,
    write_private_new_file,
)
from core.workflow_module import WorkflowModule
from datatypes import Candidate, CandidateCollection, ProteinSequence
from modules.export_sequence.module import ExportSequenceModule
from modules.import_sequence.module import ImportSequenceModule


@pytest.mark.parametrize(
    "escape_kind",
    ("traversal", "absolute"),
)
def test_sequence_export_rejects_artifact_escape_without_external_write(
    tmp_path: Path,
    escape_kind: str,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )
    if escape_kind == "traversal":
        outside = Path(context.output_dir or "").parent / "outside.fa"
        artifact_name = "../outside.fa"
    else:
        outside = tmp_path / "absolute-outside.fa"
        artifact_name = str(outside)
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("ORIGINAL\n")

    with pytest.raises(StoragePathError):
        ExportSequenceModule().run(
            {"sequence": ProteinSequence(sequence="AGS")},
            {"filename": artifact_name},
            context,
        )

    assert outside.read_text() == "ORIGINAL\n"


def test_sequence_export_refuses_symlinked_parent_directory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )
    output_dir = Path(context.output_dir or "")
    output_dir.parent.mkdir(parents=True)
    output_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises((OSError, StoragePathError)):
        ExportSequenceModule().run(
            {"sequence": ProteinSequence(sequence="AGS")},
            {"filename": "out.fa"},
            context,
        )

    assert list(outside.iterdir()) == []


def test_sequence_export_refuses_existing_hardlink_before_writing(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.fa"
    outside.write_text("ORIGINAL\n")
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )
    destination = (
        tmp_path / "project" / "outputs" / "run-a" / "result.fa"
    )
    destination.parent.mkdir(parents=True)
    os.link(outside, destination)

    with pytest.raises((FileExistsError, StoragePathError)):
        ExportSequenceModule().run(
            {"sequence": ProteinSequence(sequence="AGS")},
            {"filename": "result.fa"},
            context,
        )

    assert outside.read_text() == "ORIGINAL\n"


def test_sequence_export_rejects_oversized_public_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from modules.export_sequence import module as export_sequence_module

    monkeypatch.setattr(
        export_sequence_module,
        "MAX_PUBLIC_ARTIFACT_BYTES",
        32,
    )
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )

    with pytest.raises(ValueError, match="retrieval limit"):
        ExportSequenceModule().run(
            {"sequence": ProteinSequence(sequence="A" * 33)},
            {"filename": "oversized.fa"},
            context,
        )

    assert not Path(context.output_dir or "").exists()


def test_sequence_export_rejects_non_ascii_before_writing(
    tmp_path: Path,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )

    with pytest.raises(ValueError, match="ASCII"):
        ExportSequenceModule().run(
            {"sequence": ProteinSequence(sequence="A\u00c9G")},
            {"filename": "non-ascii.fa"},
            context,
        )

    assert not Path(context.output_dir or "").exists()


def test_sequence_export_requires_a_leaf_filename(
    tmp_path: Path,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )

    with pytest.raises(StoragePathError):
        ExportSequenceModule().run(
            {"sequence": ProteinSequence(sequence="AGS")},
            {"filename": "nested/out.fa"},
            context,
        )

    assert not Path(context.output_dir or "").exists()


def test_manifest_store_rejects_undeclared_standalone_artifact(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    artifact = output_dir / "unbound.fa"
    artifact.write_text(">unbound\nAGS\n")
    manifest = RunManifest.for_execution(
        project_id="project-a",
        run_id="run-a",
        workflow=Workflow(),
        modules={},
        seed=42,
        source_dir=tmp_path,
    )

    with RunManifestStore(tmp_path / "run", manifest) as store:
        with pytest.raises(ValueError, match="standalone opt-in"):
            store.record_artifact(
                node_id="export",
                path=artifact,
                output_dir=output_dir,
                output_port="file_path",
            )
        with pytest.raises(ValueError, match="output Port"):
            store.record_artifact(
                node_id="export",
                path=artifact,
                output_dir=output_dir,
                artifact_kind="standalone",
            )


def test_module_batch_cannot_bypass_standalone_port_opt_in(
    tmp_path: Path,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )
    context._manifest_store = SimpleNamespace(
        record_artifacts=lambda **kwargs: True,
    )

    with pytest.raises(ValueError, match="Candidate bindings"):
        context.record_artifacts([{
            "path": "bypass.fa",
            "output_port": "file_path",
            "artifact_kind": "standalone",
        }])


def _sequence_export_workflow() -> Workflow:
    workflow = Workflow()
    workflow.add_node(WorkflowNode(
        "import", "import.sequence", "1.0.0",
        {"file_path": "source.fasta"},
    ))
    workflow.add_node(WorkflowNode(
        "export", "export.sequence", "2.0.0",
        {"filename": "unpublished.fa"},
    ))
    workflow.add_edge(WorkflowEdge(
        "import", "sequence", "export", "sequence",
    ))
    return workflow


class _CandidateAndStandaloneModule(WorkflowModule):
    @property
    def definition(self) -> ModuleDefinition:
        return ModuleDefinition.from_yaml_string(
            """
module_id: test.candidate_and_standalone
version: 1.0.0
display_name: Candidate and standalone
category: output
output_ports:
  - name: candidates
    type_id: candidate.collection
  - name: file_path
    type_id: file.path
    artifact_kind: standalone
"""
        )

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del inputs, parameters
        path = write_private_new_file(
            context.output_dir or "",
            validate_relative_path("summary.fa", "artifact_name"),
            b">summary\nAGS\n",
            field="artifact_name",
        )
        return {
            "candidates": CandidateCollection(
                collection_id="mixed",
                item_type="protein.sequence",
                items=[Candidate(
                    candidate_id="candidate-a",
                    data=ProteinSequence(sequence="AGS"),
                )],
            ),
            "file_path": str(path),
        }


def test_explicit_standalone_port_overrides_candidate_inference(
    tmp_path: Path,
) -> None:
    workflow = Workflow()
    workflow.add_node(WorkflowNode(
        "mixed", "test.candidate_and_standalone", "1.0.0",
    ))
    module = _CandidateAndStandaloneModule()
    asyncio.run(Executor().execute(
        workflow,
        {module.definition.module_id: module},
        str(tmp_path),
        "run-a",
    ))
    manifest = json.loads(
        (tmp_path / "runs" / "run-a" / "manifest.json").read_text()
    )

    assert manifest["artifacts"] == [{
        "node_id": "mixed",
        "reference": "summary.fa",
        "size": 13,
        "sha256": (
            "364f729e86d79c55d8fb102411ed4176807e6af"
            "9b1cf0c8357987afc6b03f293"
        ),
        "output_port": "file_path",
        "artifact_kind": "standalone",
    }]


def test_worker_export_rolls_back_when_parent_manifest_rejects_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "source.fasta").write_text(">source\nAGS\n")
    monkeypatch.setattr(
        RunManifestStore,
        "record_artifact",
        lambda self, **kwargs: False,
    )

    async def execute() -> None:
        await Executor().execute(
            _sequence_export_workflow(),
            {
                "import.sequence": ImportSequenceModule(),
                "export.sequence": ExportSequenceModule(),
            },
            str(tmp_path),
            "run-a",
            cancellation_requested=asyncio.Event(),
        )

    asyncio.run(execute())

    assert not (
        tmp_path / "outputs" / "run-a" / "unpublished.fa"
    ).exists()
    manifest = json.loads(
        (tmp_path / "runs" / "run-a" / "manifest.json").read_text()
    )
    assert manifest["status"] == "failed"
