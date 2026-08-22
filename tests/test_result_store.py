"""Closed-interface contracts for immutable Result persistence and replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.catalog.builtins import builtin_frozen_catalog
from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from core.execution.ledger import (
    PublishedArtifact,
    PublishedOutput,
)
from core.execution.output_admission import admit_node_output
from core.execution.output_admission.admission import (
    NodeOutputPlan,
    OutputPortPlan,
)
from core.execution.output_admission.artifacts import (
    ArtifactOutputDeclaration,
)
from core.execution.results import (
    IndexedOutput,
    ProjectReplayIndex,
    ReplayIndexEntry,
    ResultIntegrityError,
    ResultStore,
)
from core.operation import ArtifactPayload
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore, StoredObject
from core.scoring.observation_plan import ProducedObservationPlan
from datatypes.exact_reference import ExactContractReference


_METHOD = ExactContractReference(
    "method",
    "test.result-store.method",
    "1.0.0",
    "sha256:" + "1" * 64,
)
_RESULT_IDENTITY = "sha256:" + "2" * 64
_METADATA = {
    "result_identity_plan_facts": {
        "digest": "exact-fixture",
        "integral_weight": 1.0,
    }
}


def _artifact_port_type() -> PortTypeDefinition:
    def validate(value: object) -> None:
        if type(value) is not ArtifactPayload:
            raise ValueError("expected one exact artifact payload")

    return PortTypeDefinition(
        type_id="test.result-store.artifact",
        version="1.0.0",
        validator=BehaviorReference(
            "test.result-store.artifact/validate",
            "1.0.0",
            {},
        ),
        codec=BehaviorReference(
            "test.result-store.artifact/codec",
            "1.0.0",
            {},
        ),
        content_identity=BehaviorReference(
            "test.result-store.artifact/content",
            "1.0.0",
            {},
        ),
        runtime_validator=validate,
        runtime_to_wire=lambda value: {
            "body": value.body.hex(),
            "media_type": value.media_type,
            "filename": value.filename,
        },
        runtime_from_wire=lambda value: ArtifactPayload(
            body=bytes.fromhex(value["body"]),
            media_type=value["media_type"],
            filename=value["filename"],
        ),
    )


def _output_plan() -> NodeOutputPlan:
    text = builtin_frozen_catalog().require_port_type("text", "2.1.0")
    artifact = _artifact_port_type()
    return NodeOutputPlan(
        node_id="producer",
        producing_method=_METHOD,
        output_ports={
            "summary": OutputPortPlan(True, "one", text),
            "structure": OutputPortPlan(True, "one", artifact),
        },
        candidate_data_port_types={},
        produced_observations=ProducedObservationPlan(
            binding_method=_METHOD,
        ),
        artifact_outputs=(
            ArtifactOutputDeclaration(
                output_port="structure",
                artifact_kind="standalone",
                artifact_media_type="chemical/x-pdb",
                accepted_media_types=("chemical/x-pdb",),
            ),
        ),
    )


def _result_store(
    tmp_path: Path,
) -> tuple[ProjectManager, str, ProjectReplayIndex, ResultStore]:
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("Result Store fixture")
    replay_index = ProjectReplayIndex(projects)
    store = ResultStore(ProjectObjectStore(projects), replay_index)
    return projects, project.id, replay_index, store


def test_store_stages_without_publishing_a_replay_entry(
    tmp_path: Path,
) -> None:
    _projects, project_id, replay_index, store = _result_store(tmp_path)
    plan = _output_plan()
    admitted = admit_node_output(
        node_plan=plan,
        admitted_inputs={},
        raw_outputs={
            "summary": "ready",
            "structure": ArtifactPayload(
                body=b"MODEL        1\nEND\n",
                media_type="chemical/x-pdb",
                filename="result.pdb",
            ),
        },
        result_identity=_RESULT_IDENTITY,
    )

    store.store(
        project_id=project_id,
        materialization_run_id="run-source",
        admitted_output=admitted,
        result_contract_metadata=_METADATA,
    )

    assert replay_index.lookup(project_id, _RESULT_IDENTITY) is None


def test_cache_metadata_divergence_fails_fast_instead_of_becoming_a_miss(
    tmp_path: Path,
) -> None:
    _projects, project_id, replay_index, store = _result_store(tmp_path)
    plan = _output_plan()
    admitted = admit_node_output(
        node_plan=plan,
        admitted_inputs={},
        raw_outputs={
            "summary": "ready",
            "structure": ArtifactPayload(
                body=b"MODEL        1\nEND\n",
                media_type="chemical/x-pdb",
                filename="result.pdb",
            ),
        },
        result_identity=_RESULT_IDENTITY,
    )
    stored = store.store(
        project_id=project_id,
        materialization_run_id="run-source",
        admitted_output=admitted,
        result_contract_metadata=_METADATA,
    )
    replay_index.index(
        project_id,
        ReplayIndexEntry(
            result_identity=_RESULT_IDENTITY,
            result_contract_metadata={"different": True},
            producer_run_id="run-source",
            producer_node_id="producer",
            node_result_manifest=stored.node_result_manifest,
            outputs=tuple(
                IndexedOutput(output.output_port, output.value_manifest)
                for output in stored.outputs
            ),
        ),
    )

    with pytest.raises(ResultIntegrityError):
        store.lookup_replay(
            project_id=project_id,
            materialization_run_id="run-replay",
            node_plan=plan,
            result_identity=_RESULT_IDENTITY,
            result_contract_metadata=_METADATA,
        )


def test_restore_rejects_an_invalid_persisted_manifest_through_the_store(
    tmp_path: Path,
) -> None:
    projects, project_id, _replay_index, store = _result_store(tmp_path)
    invalid_manifest = ProjectObjectStore(projects).store(project_id, b"{}")

    with pytest.raises(ResultIntegrityError):
        store.restore(
            project_id=project_id,
            materialization_run_id="run-replay",
            producer_run_id="run-source",
            node_plan=_output_plan(),
            result_identity=_RESULT_IDENTITY,
            result_contract_metadata=_METADATA,
            node_result_manifest=invalid_manifest,
        )


def test_replay_index_accepts_canonical_semantic_output_port_names(
    tmp_path: Path,
) -> None:
    _projects, project_id, replay_index, _store = _result_store(tmp_path)
    reference = StoredObject("sha256:" + "3" * 64, 17)
    entry = ReplayIndexEntry(
        result_identity=_RESULT_IDENTITY,
        result_contract_metadata={},
        producer_run_id="run-source",
        producer_node_id="producer",
        node_result_manifest=reference,
        outputs=(IndexedOutput("score:primary", reference),),
    )

    replay_index.index(project_id, entry)

    assert replay_index.lookup(project_id, _RESULT_IDENTITY) == entry


def test_restore_and_reads_use_the_result_store_interface(
    tmp_path: Path,
) -> None:
    _projects, project_id, _replay_index, store = _result_store(tmp_path)
    plan = _output_plan()
    admitted = admit_node_output(
        node_plan=plan,
        admitted_inputs={},
        raw_outputs={
            "summary": "ready",
            "structure": ArtifactPayload(
                body=b"MODEL        1\nEND\n",
                media_type="chemical/x-pdb",
                filename="result.pdb",
            ),
        },
        result_identity=_RESULT_IDENTITY,
    )
    stored = store.store(
        project_id=project_id,
        materialization_run_id="run-source",
        admitted_output=admitted,
        result_contract_metadata=_METADATA,
    )

    restored = store.restore(
        project_id=project_id,
        materialization_run_id="run-replay",
        producer_run_id="run-source",
        node_plan=plan,
        result_identity=_RESULT_IDENTITY,
        result_contract_metadata=_METADATA,
        node_result_manifest=stored.node_result_manifest,
    )

    assert restored.resolution == "cache_replayed"
    assert restored.admitted_output.ports["summary"].value == "ready"
    assert restored.admitted_output.ports["structure"].value == (
        admitted.ports["structure"].value
    )
    summary = next(
        output for output in stored.outputs if output.output_port == "summary"
    )
    value = store.read_typed_value(
        project_id,
        PublishedOutput(
            node_id=summary.node_id,
            output_port=summary.output_port,
            port_type=summary.port_type,
            content_digest=summary.content_digest,
            result_identity=stored.result_identity,
            materialization={
                "run_id": summary.materialization_run_id,
                "resolution": summary.resolution,
            },
            producer_provenance={
                "producer_run_id": summary.producer_run_id,
                "producer_result_identity": stored.result_identity,
                "output_port": summary.output_port,
            },
            value_count=summary.value_count,
            value_manifest_reference=summary.value_manifest.content_digest,
        ),
        0,
    )
    assert value.canonical_bytes == admitted.ports["summary"].values[
        0
    ].canonical_bytes

    artifact = stored.artifacts[0]
    assert store.read_artifact(
        project_id,
        PublishedArtifact(
            artifact_reference=artifact.artifact_reference,
            artifact_kind=artifact.artifact_kind,
            node_id=artifact.node_id,
            output_port=artifact.output_port,
            media_type=artifact.media_type,
            filename=artifact.filename,
            size=artifact.body.size,
            content_digest=artifact.body.content_digest,
            candidate_id=artifact.candidate_id,
        ),
    ) == b"MODEL        1\nEND\n"
