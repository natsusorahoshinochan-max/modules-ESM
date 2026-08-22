"""Provider-free public acceptance for the source-bound 1PGA Workflow.

The pre-agreed seams are the shipped source-bound Workflow, the immutable
production Catalog/compiler, and the public REST/WebSocket Run surface.
"""

from __future__ import annotations

from protein_workbench_public.bootstrap import module_registrations

import hashlib
import json
from dataclasses import replace
import math
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest
import torch

from core.catalog.builder import (
    build_frozen_catalog,
)
from core.catalog.declarations import (
    AvailabilityResult,
    ModulePackageRegistration,
)
from core.operation import (
    ReadinessCheckInput,
    ReadinessResult,
)
from core.workflow.compiler import (
    CompilationRequest,
    compile,
    lock_workflow,
)
from protein_workbench_public.workflow_codec import decode_workflow_document
from protein_workbench_public.bootstrap import create_application
from datatypes.candidate import CandidateCollection
from datatypes.observation import (
    PairwiseCandidateMapping,
    ScoreCollection,
)
from datatypes.structure import ProteinStructure
from modules.structure_comparison.domain import (
    StructureAlignmentEvidence,
    ThreeWayConsistencyEvidence,
)
from modules.structure_comparison.contracts import (
    REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
    RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
    SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    SIMPLEFOLD_FOLD_METHOD_REFERENCE,
    THREE_WAY_CONSISTENCY_METHOD_REFERENCE,
    TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
)
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociations,
)
from protein_workbench_public import encode_project_input_content
from tests.fixtures.canonical_3gb1_v2 import ControlledFoldResponse
from tests.fixtures.public_v2 import (
    retrieve_typed_output_canonical_bytes,
    wait_for_testclient_run_terminal,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = PROJECT_ROOT / "pdbs" / "1PGA-75-gen1_0690.pdb"
WORKFLOW_PATH = (
    PROJECT_ROOT / "examples" / "v2" / "source-bound-1pga.workflow.json"
)
INPUT_SHA256 = (
    "d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30"
)
INPUT_SEQUENCE = (
    "MKESYKVILTNKKTEKNLVLTTTQEVSNEENAHDKEKVFVEEYANKTLGNPAFTNWTYQFDATHDEWFCVVEANL"
)
INPUT_RESIDUE_IDS = tuple(f"A:{index}" for index in range(1, 76))


def _upstream_simplefold_serialized_pdb(pdb_string: str) -> str:
    return "\n".join(
        line.ljust(80) for line in (*pdb_string.splitlines(), "")
    )


def _workflow_payload() -> dict[str, object]:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _provider_free_catalog() -> Any:
    def available() -> AvailabilityResult:
        return AvailabilityResult.available()

    def ready(check_input: ReadinessCheckInput) -> ReadinessResult:
        return ReadinessResult(bool(check_input.values))

    opened = {
        "folding.fold.esmfold2_remote",
        "folding.fold.simplefold_local",
    }
    registrations: list[ModulePackageRegistration] = []
    for registration in module_registrations():
        registrations.append(
            replace(
                registration,
                bindings=tuple(
                    replace(
                        binding,
                        availability=replace(
                            binding.availability,
                            check=available,
                        ),
                        readiness=replace(
                            binding.readiness,
                            check=ready,
                        ),
                    )
                    if binding.binding_id in opened
                    else binding
                    for binding in registration.bindings
                ),
            )
        )
    return build_frozen_catalog(tuple(registrations))


def _provider_free_simplefold_environment(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: Any,
) -> dict[str, Any]:
    import modules.folding.simplefold_contract as simplefold_contract
    import modules.folding.simplefold_runtime as simplefold_runtime

    monkeypatch.setattr(
        simplefold_runtime,
        "fold_sequence",
        lambda **kwargs: client.fold(
            sequence=kwargs["sequence"],
            num_steps=kwargs["num_steps"],
            num_samples=kwargs["num_samples"],
            effective_seed=kwargs["effective_seed"],
            staging_directory=Path(kwargs["project_dir"]),
        ),
    )

    closure = replace(
        simplefold_contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
        sources=(),
    )
    monkeypatch.setattr(
        simplefold_contract,
        "SIMPLEFOLD_FOLDING_ASSET_CLOSURE",
        closure,
    )
    configured_roots = {
        environment_key: root / environment_key
        for environment_key in {
            entry.environment_key for entry in closure.files
        }
    }
    for configured_root in configured_roots.values():
        configured_root.mkdir(parents=True)
    for entry in closure.files:
        (configured_roots[entry.environment_key] / entry.runtime_filename).write_bytes(
            f"provider-free-{entry.runtime_filename}".encode()
        )
    return {
        **configured_roots,
        "device": simplefold_contract.SIMPLEFOLD_DEVICE,
    }


class _ControlledESMFold2:
    def __init__(self, structure: str, *, plddt: float = 90.0) -> None:
        self.structure = structure
        self.plddt = plddt
        self.calls: list[str] = []

    def fold(self, *, sequence: str, model_name: str, config: Any):
        del model_name, config
        self.calls.append(sequence)
        count = len(sequence)
        return ControlledFoldResponse(
            sequence=sequence,
            pdb_string=self.structure,
            ptm=torch.tensor(0.95),
            plddt=torch.tensor([self.plddt / 100.0] * count),
            pae=torch.zeros((count, count)),
        )


class _ControlledSimpleFold:
    def __init__(self, structure: str, *, plddt: float = 90.0) -> None:
        self.structure = structure
        self.plddt = plddt
        self.calls: list[dict[str, Any]] = []

    def fold(self, **kwargs: Any):
        self.calls.append(kwargs)
        assert kwargs["num_steps"] == 50
        assert kwargs["num_samples"] == 1
        return (
            [
                ProteinStructure(
                    _upstream_simplefold_serialized_pdb(self.structure)
                )
            ],
            [{"sample_index": 0, "per_residue": [self.plddt] * 75}],
        )


def _deformed_source(structure: str, amplitude: float) -> str:
    lines: list[str] = []
    for line in structure.splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            residue_number = int(line[22:26])
            x = float(line[30:38])
            y = float(line[38:46]) + amplitude * math.sin(
                residue_number * 0.37
            )
            z = float(line[46:54]) + amplitude * math.cos(
                residue_number * 0.23
            )
            line = line[:30] + f"{x:8.3f}{y:8.3f}{z:8.3f}" + line[54:]
        lines.append(line)
    return "\n".join(lines) + "\n"


def _decoded_outputs(
    client: TestClient,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> tuple[Any, ...]:
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == node_id
        and item["output_port"] == output_port
    )
    codec = catalog.require_port_type(
        output["port_type"]["contract_id"],
        output["port_type"]["contract_version"],
    )
    return tuple(
        codec.decode(
            retrieve_typed_output_canonical_bytes(
                client,
                projection["project_id"],
                projection["run_id"],
                output,
                index,
            )
        )
        for index in range(output["value_count"])
    )


def _decoded_output(
    client: TestClient,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> Any:
    values = _decoded_outputs(
        client,
        catalog,
        projection,
        node_id,
        output_port,
    )
    assert len(values) == 1
    return values[0]


def test_source_bound_1pga_is_exact_locked_and_compilable() -> None:
    assert hashlib.sha256(INPUT_PATH.read_bytes()).hexdigest() == INPUT_SHA256
    catalog = build_frozen_catalog(module_registrations())
    workflow = decode_workflow_document(_workflow_payload())

    assert workflow.workflow_id == "source-bound-1pga"
    assert workflow.schema_version == "2.1.0"
    assert workflow.contract_lock
    assert lock_workflow(workflow, catalog) == workflow
    compiled = compile(
                   CompilationRequest(
                       workflow,
                       1,
                   ),
                   catalog,
               )
    assert compiled.resolved_contracts == workflow.contract_lock

    nodes = {node.node_id: node for node in workflow.nodes}
    assert nodes["import-input"].node_parameters == {
        "project_input_ref": "1PGA-75-gen1_0690.pdb"
    }
    assert nodes["fold-esmfold2"].node_parameters == {
        "effective_seed": 1075001,
        "num_samples": 1,
    }
    assert nodes["fold-esmfold2"].binding_id == (
        "folding.fold.esmfold2_remote"
    )
    assert nodes["fold-simplefold"].node_parameters == {
        "effective_seed": 1075002,
        "num_samples": 1,
    }
    assert nodes["fold-simplefold"].binding_id == (
        "folding.fold.simplefold_local"
    )
    assert nodes["fold-simplefold"].binding_parameters == {"num_steps": 50}
    assert nodes["classify-consistency"].node_type_id == (
        "structure_comparison.classify_three_way_consistency"
    )


def test_source_bound_1pga_public_journey_closes_complete_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))

    source_bytes = INPUT_PATH.read_bytes()
    source_text = source_bytes.decode("ascii")
    esmfold2 = _ControlledESMFold2(source_text)
    simplefold = _ControlledSimpleFold(source_text)
    monkeypatch.setattr(
        "modules.folding.adapter.build_remote_engine",
        lambda _environment: esmfold2,
    )
    environment = {
        ("folding.fold.esmfold2_remote", "9.0.0"): {
            "values": {
                "endpoint_id": "provider-free",
                "credential_handle": "provider-free-folding-credential",
            },
        },
        ("folding.fold.simplefold_local", "10.0.0"): {
            "values": _provider_free_simplefold_environment(
                tmp_path / "simplefold-assets",
                monkeypatch,
                simplefold,
            ),
        },
    }
    catalog = _provider_free_catalog()
    app = create_application(
        frozen_catalog_override=catalog,
        v2_environment_configuration=environment,
        _install_canonical_seed=False,
    )

    with TestClient(app) as client:
        snapshot = client.get("/api/v2/catalog")
        assert snapshot.status_code == 200
        assert snapshot.json()["catalog_contract_digest"] == catalog.contract_digest
        project = client.post(
            "/api/v2/projects",
            json={"name": "source-bound 1PGA provider-free acceptance"},
        )
        assert project.status_code == 201
        project_id = project.json()["id"]
        uploaded = client.post(
            f"/api/v2/projects/{project_id}/inputs",
            json={
                "filename": INPUT_PATH.name,
                "content_base64": encode_project_input_content(source_bytes),
            },
        )
        assert uploaded.status_code == 201
        assert uploaded.json()["content_digest"] == f"sha256:{INPUT_SHA256}"

        workflow = _workflow_payload()
        workflow["workflow_id"] = project_id
        workflow["contract_lock"] = []
        import_node = next(
            node
            for node in workflow["nodes"]
            if node["node_id"] == "import-input"
        )
        import_node["node_parameters"] = {
            "project_input_ref": uploaded.json()["project_input_ref"]
        }
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": workflow,
            },
        )
        assert committed.status_code == 200, committed.json()
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed.json()["workflow_commit_id"],
                "client_request_id": "provider-free-source-bound-1pga",
            },
        )
        assert started.status_code == 202, started.json()
        run_id = started.json()["run_id"]
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            run_id,
            timeout_seconds=60,
        )
        assert projection["status"] == "succeeded", projection[
            "node_dispositions"
        ]
        assert len(projection["node_dispositions"]) == len(workflow["nodes"])
        assert all(
            item["outcome"] == "succeeded"
            for item in projection["node_dispositions"]
        )
        assert all("values" not in output for output in projection["outputs"])

        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{run_id}/events"
        ) as websocket:
            events: list[dict[str, Any]] = []
            while True:
                message = websocket.receive_json()
                events.append(message)
                if message["event"]["type"] == "run_terminal":
                    break
        assert events[-1]["event"] == {
            "type": "run_terminal",
            "status": "succeeded",
        }
        assert [message["sequence"] for message in events] == sorted(
            message["sequence"] for message in events
        )
        assert "values" not in json.dumps(events)

        input_candidates = _decoded_output(
            client, catalog, projection, "import-input", "structure_candidates"
        )
        sequence_parents = _decoded_output(
            client, catalog, projection, "extract-sequence", "sequence_candidates"
        )
        esmfold2_structures = _decoded_output(
            client, catalog, projection, "fold-esmfold2", "structure_candidates"
        )
        simplefold_structures = _decoded_output(
            client, catalog, projection, "fold-simplefold", "structure_candidates"
        )
        assert all(
            type(value) is CandidateCollection
            for value in (
                input_candidates,
                sequence_parents,
                esmfold2_structures,
                simplefold_structures,
            )
        )
        assert input_candidates.items[0].data.pdb_string == source_text
        assert sequence_parents.items[0].data.sequence == INPUT_SEQUENCE
        assert sequence_parents.items[0].data.residue_ids == INPUT_RESIDUE_IDS
        assert sequence_parents.items[0].parent_ids == (
            input_candidates.items[0].candidate_id,
        )
        assert esmfold2_structures.items[0].parent_ids == (
            sequence_parents.items[0].candidate_id,
        )
        assert simplefold_structures.items[0].parent_ids == (
            sequence_parents.items[0].candidate_id,
        )

        pairing = _decoded_output(
            client, catalog, projection, "pair-methods", "pairing"
        )
        assert type(pairing) is PairwiseCandidateMapping
        assert len(pairing.entries) == 1
        assert pairing.entries[0].subject.candidate_id == (
            esmfold2_structures.items[0].candidate_id
        )
        assert pairing.entries[0].reference.candidate_id == (
            simplefold_structures.items[0].candidate_id
        )

        for node_id, candidates in (
            ("resolve-input", input_candidates),
            ("resolve-esmfold2", esmfold2_structures),
            ("resolve-simplefold", simplefold_structures),
        ):
            axes = _decoded_output(
                client, catalog, projection, node_id, "residue_axes"
            )
            assert type(axes) is CandidateResolvedResidueAxisAssociations
            assert len(axes.entries) == 1
            assert axes.entries[0].subject.candidate_id == (
                candidates.items[0].candidate_id
            )
            assert axes.entries[0].residue_axis.layout.length == 75
            assert axes.entries[0].residue_axis.sequence == (
                sequence_parents.items[0].data.sequence
            )

        alignments = tuple(
            _decoded_output(client, catalog, projection, node_id, "alignments")
            for node_id in (
                "align-esmfold2-input",
                "align-simplefold-input",
                "align-methods",
            )
        )
        assert all(type(item) is StructureAlignmentEvidence for item in alignments)
        assert all(
            item.method == SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE
            and tuple(
                correspondence.subject_residue_id
                for correspondence in item.correspondence
            )
            == INPUT_RESIDUE_IDS
            and tuple(
                correspondence.reference_residue_id
                for correspondence in item.correspondence
            )
            == INPUT_RESIDUE_IDS
            and all(
                correspondence.subject_atom_name == "CA"
                and correspondence.reference_atom_name == "CA"
                for correspondence in item.correspondence
            )
            for item in alignments
        )
        assert [
            (
                item.subject.candidate_id,
                item.reference.candidate_id,
                item.normalization.reference_axis_residue_count,
                item.normalization.aligned_atom_count,
            )
            for item in alignments
        ] == [
            (
                esmfold2_structures.items[0].candidate_id,
                input_candidates.items[0].candidate_id,
                75,
                75,
            ),
            (
                simplefold_structures.items[0].candidate_id,
                input_candidates.items[0].candidate_id,
                75,
                75,
            ),
            (
                esmfold2_structures.items[0].candidate_id,
                simplefold_structures.items[0].candidate_id,
                75,
                75,
            ),
        ]

        confidence = tuple(
            _decoded_output(client, catalog, projection, node_id, "observations")
            for node_id in (
                "materialize-esmfold2-confidence",
                "materialize-simplefold-confidence",
            )
        )
        assert all(type(item) is ScoreCollection for item in confidence)
        assert {
            observation.subject.candidate_id
            for collection in confidence
            for observation in collection.entries
        } == {
            esmfold2_structures.items[0].candidate_id,
            simplefold_structures.items[0].candidate_id,
        }
        assert input_candidates.items[0].candidate_id not in {
            observation.subject.candidate_id
            for collection in confidence
            for observation in collection.entries
        }

        consistency = _decoded_output(
            client, catalog, projection, "classify-consistency", "consistency"
        )
        assert type(consistency) is ThreeWayConsistencyEvidence
        assert consistency.classification == "three_way_consistent"
        assert consistency.subreason is None
        assert consistency.input_b_factor_semantics == (
            "uninterpreted_coordinate_temperature_factor"
        )
        assert [
            item.mean_residue_plddt for item in consistency.confidences
        ] == pytest.approx([90.0, 90.0])
        assert all(item.eligible for item in consistency.confidences)
        assert consistency.residue_count == 75
        assert tuple(item.method for item in consistency.confidences) == (
            REMOTE_ESMFOLD2_FOLD_METHOD_REFERENCE,
            SIMPLEFOLD_FOLD_METHOD_REFERENCE,
        )
        assert [edge.edge_id for edge in consistency.edges] == [
            "input_esmfold2",
            "input_simplefold",
            "esmfold2_simplefold",
        ]
        assert all(
            edge.close
            and edge.tm_score >= 0.8
            and edge.rmsd_angstrom <= 2.5
            and edge.normalization_length == 75
            and edge.aligned_atom_count == 75
            and edge.alignment_method
            == SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE
            and edge.tm_score_method == TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE
            and edge.rmsd_method == RMSD_FROM_EVIDENCE_METHOD_REFERENCE
            for edge in consistency.edges
        )
        alignment_codec = catalog.require_port_type(
            "structure_comparison.alignment_evidence",
            "5.0.0",
        )
        assert [
            edge.alignment_evidence_content_digest
            for edge in consistency.edges
        ] == [alignment_codec.content_digest(item) for item in alignments]
        score_codec = catalog.require_port_type("score.collection", "5.0.0")
        tm_scores = tuple(
            _decoded_output(client, catalog, projection, node_id, "scores")
            for node_id in (
                "tm-esmfold2-input",
                "tm-simplefold-input",
                "tm-methods",
            )
        )
        rmsd_scores = tuple(
            _decoded_output(client, catalog, projection, node_id, "scores")
            for node_id in (
                "rmsd-esmfold2-input",
                "rmsd-simplefold-input",
                "rmsd-methods",
            )
        )
        assert [edge.tm_score_content_digest for edge in consistency.edges] == [
            score_codec.content_digest(item) for item in tm_scores
        ]
        assert [edge.rmsd_content_digest for edge in consistency.edges] == [
            score_codec.content_digest(item) for item in rmsd_scores
        ]
        assert [
            item.score_content_digest for item in consistency.confidences
        ] == [score_codec.content_digest(item) for item in confidence]
        assert (
            consistency.classification_method
            == THREE_WAY_CONSISTENCY_METHOD_REFERENCE
        )

    assert len(esmfold2.calls) == 1
    assert len(simplefold.calls) == 1


@pytest.mark.parametrize(
    (
        "esmfold2_deformation",
        "simplefold_deformation",
        "simplefold_plddt",
        "expected_classification",
        "expected_subreason",
    ),
    (
        (0.0, 3.0, 90.0, "method_disagreement", None),
        (3.0, 3.0, 90.0, "input_disagreement", None),
        (3.0, 6.0, 90.0, "all_disagree", None),
        (
            1.5,
            3.0,
            90.0,
            "insufficient_evidence",
            "threshold_boundary_nontransitive",
        ),
        (
            0.0,
            0.0,
            69.0,
            "insufficient_evidence",
            "method_confidence_below_threshold",
        ),
    ),
)
def test_source_bound_1pga_public_classification_contract(
    tmp_path: Path,
    monkeypatch,
    esmfold2_deformation: float,
    simplefold_deformation: float,
    simplefold_plddt: float,
    expected_classification: str,
    expected_subreason: str | None,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(root))
    source = INPUT_PATH.read_text(encoding="ascii")
    esmfold2 = _ControlledESMFold2(
        _deformed_source(source, esmfold2_deformation)
    )
    simplefold = _ControlledSimpleFold(
        _deformed_source(source, simplefold_deformation),
        plddt=simplefold_plddt,
    )
    monkeypatch.setattr(
        "modules.folding.adapter.build_remote_engine",
        lambda _environment: esmfold2,
    )
    environment = {
        ("folding.fold.esmfold2_remote", "9.0.0"): {
            "values": {
                "endpoint_id": "provider-free",
                "credential_handle": "provider-free-folding-credential",
            },
        },
        ("folding.fold.simplefold_local", "10.0.0"): {
            "values": _provider_free_simplefold_environment(
                tmp_path / "simplefold-assets",
                monkeypatch,
                simplefold,
            ),
        },
    }
    catalog = _provider_free_catalog()
    with TestClient(
        create_application(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
            _install_canonical_seed=False,
        )
    ) as client:
        project_id = client.post(
            "/api/v2/projects",
            json={"name": "source-bound 1PGA classification"},
        ).json()["id"]
        uploaded = client.post(
            f"/api/v2/projects/{project_id}/inputs",
            json={
                "filename": INPUT_PATH.name,
                "content_base64": encode_project_input_content(
                    INPUT_PATH.read_bytes()
                ),
            },
        ).json()
        workflow = _workflow_payload()
        workflow["workflow_id"] = project_id
        workflow["contract_lock"] = []
        next(
            node
            for node in workflow["nodes"]
            if node["node_id"] == "import-input"
        )["node_parameters"] = {
            "project_input_ref": uploaded["project_input_ref"]
        }
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={"workflow": workflow},
        )
        assert committed.status_code == 200, committed.json()
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed.json()["workflow_commit_id"],
                "client_request_id": "provider-free-1pga-classification",
            },
        )
        assert started.status_code == 202, started.json()
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
            timeout_seconds=60,
        )
        assert projection["status"] == "succeeded", projection[
            "node_dispositions"
        ]
        consistency = _decoded_output(
            client,
            catalog,
            projection,
            "classify-consistency",
            "consistency",
        )
        assert consistency.classification == expected_classification
        assert consistency.subreason == expected_subreason
        if expected_subreason == "threshold_boundary_nontransitive":
            assert sum(edge.close for edge in consistency.edges) == 2
