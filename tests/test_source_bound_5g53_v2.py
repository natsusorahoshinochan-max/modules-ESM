"""Provider-free public acceptance for the source-bound 5G53 Workflow.

The pre-agreed seams are the shipped source-bound Workflow, the immutable
production Catalog/compiler, and the public REST/WebSocket Run surface.
"""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog

from protein_workbench_public.bootstrap import module_registrations

import hashlib
import json
from pathlib import Path
from typing import Any

from dataclasses import replace

from fastapi.testclient import TestClient
import pytest
import torch

from core.workflow.compiler import (
    CompilationRequest,
    compile,
    lock_workflow,
)
from protein_workbench_public.workflow_codec import decode_workflow_document
from tests.support.application import create_application
from datatypes.candidate import (
    Candidate,
    CandidateDataReference,
    CandidateCollection,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import PairwiseCandidateMapping
from datatypes.structure import ProteinStructure
from modules.structure_comparison.domain import InsertedLoopEvaluationCollection
from datatypes.prediction import prediction_key
from modules.structure_prediction.port_types import (
    PREDICTION_RESIDUE_AXIS_PORT_TYPE,
)
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociations,
)
from protein_workbench_public import encode_project_input_content
from tests.fixtures.canonical_3gb1_v2 import (
    ControlledESMResponse,
    ControlledFoldingClient,
    controlled_catalog,
    controlled_environment,
    pdb_for_sequence,
)
from tests.fixtures.public_v2 import (
    retrieve_typed_output_canonical_bytes,
    wait_for_testclient_run_terminal,
)


ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = ROOT / "pdbs" / "5G53.pdb"
WORKFLOW_PATH = ROOT / "examples" / "v2" / "source-bound-5g53.workflow.json"
INPUT_SHA256 = "a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537"
BRANCH_LOOP_IDS = {
    "shorter-8": tuple(f"A:gap211_224.short.{index:02d}" for index in range(1, 9)),
    "numbering-implied-12": tuple(f"A:{index}" for index in range(212, 224)),
    "longer-16": tuple(f"A:gap211_224.long.{index:02d}" for index in range(1, 17)),
}
BRANCHES = (
    ("shorter-8", 8, 5353008),
    ("numbering-implied-12", 12, 5353012),
    ("longer-16", 16, 5353016),
)
_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def _payload() -> dict[str, Any]:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _decode_values(
    client: TestClient,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> tuple[Any, ...]:
    output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == node_id and item["output_port"] == output_port
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


def _decode(
    client: TestClient,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> Any:
    values = _decode_values(client, catalog, projection, node_id, output_port)
    assert len(values) == 1
    return values[0]


class _Controlled5G53ESM3:
    def __init__(self) -> None:
        self.sequence_prompts: list[Any] = []
        self.structure_prompts: list[Any] = []

    @staticmethod
    def _complete(masked_sequence: str, sample_index: int) -> str:
        replacement = _ALPHABET[sample_index % len(_ALPHABET)]
        return "".join(
            replacement if residue == "_" else residue for residue in masked_sequence
        )

    @staticmethod
    def _response(sequence: str, *, offset: int) -> ControlledESMResponse:
        length = len(sequence)
        coordinates = torch.zeros((length, 37, 3))
        coordinates[:, 0, 0] = torch.arange(length) * 3.8 - 1.2
        coordinates[:, 1, 0] = torch.arange(length) * 3.8
        coordinates[:, 2, 0] = torch.arange(length) * 3.8 + 1.2
        pae = torch.tensor(
            [
                [
                    min(float(abs(left - right)) + offset * 0.01, 31.75)
                    for right in range(length)
                ]
                for left in range(length)
            ]
        )
        return ControlledESMResponse(
            sequence=sequence,
            coordinates=coordinates,
            ptm=torch.tensor(0.90 - offset * 0.001),
            plddt=torch.tensor([0.90 - offset * 0.001] * length),
            pae=pae,
            pdb_string=pdb_for_sequence(
                sequence,
                bend=offset * 0.01,
            ).removesuffix("TER\nEND\n"),
        )

    def generate(self, protein: Any, config: Any) -> ControlledESMResponse:
        if config.track == "sequence":
            sample_index = len(self.sequence_prompts)
            self.sequence_prompts.append(protein)
            sequence = self._complete(protein.sequence, sample_index)
            return self._response(sequence, offset=sample_index)
        assert config.track == "structure"
        sample_index = len(self.structure_prompts)
        self.structure_prompts.append(protein)
        return self._response(protein.sequence, offset=sample_index)


def test_source_bound_5g53_is_shipped_with_current_catalog_contracts() -> None:
    assert hashlib.sha256(INPUT_PATH.read_bytes()).hexdigest() == INPUT_SHA256
    catalog = build_frozen_catalog(module_registrations())
    catalog.require_contract(
        "node_type",
        "structure_comparison.evaluate_inserted_loop",
        "2.0.0",
    )
    confidence_method = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_remote",
        "9.0.0",
    ).descriptor["method"]
    evaluation_method = catalog.require_contract(
        "method",
        "structure_comparison.inserted_loop.exact_evidence_gate",
        "2.0.0",
    )
    assert (
        evaluation_method.descriptor["algorithm_identity"]["confidence_method"]
        == confidence_method
    )
    assert (
        evaluation_method.descriptor["featurization_identity"]["confidence"]["method"]
        == confidence_method
    )
    evidence_port = catalog.require_contract(
        "port_type",
        "structure_comparison.inserted_loop_evaluation",
        "2.0.0",
    )
    assert (
        evidence_port.descriptor()["validator"]["parameters"]["confidence_method"]
        == confidence_method
    )
    workflow = decode_workflow_document(_payload())
    assert workflow.workflow_id == "source-bound-5g53"
    assert workflow.contract_lock
    assert lock_workflow(
        replace(workflow, contract_lock=()),
        catalog,
    ) == workflow
    compile(
        CompilationRequest(
            workflow,
            1,
        ),
        catalog,
    )

    pdb_text = INPUT_PATH.read_text(encoding="ascii")
    assert sum(line.startswith("ATOM  ") for line in pdb_text.splitlines()) == 7247
    assert sum(line.startswith("HETATM") for line in pdb_text.splitlines()) == 112
    assert {
        line[21:22] for line in pdb_text.splitlines() if line.startswith("ATOM  ")
    } == {"A", "B", "C", "D"}
    assert pdb_text.endswith("END\n")

    nodes = {node.node_id: node for node in workflow.nodes}
    assert nodes["select-chain-a"].node_parameters == {"chain_ids": ("A",)}
    for branch, loop_length, seed in BRANCHES:
        generation = nodes[f"generate-{branch}"]
        assert generation.binding_id == "esm3.generate_paired.biohub_medium"
        assert generation.node_parameters == {
            "effective_seed": seed,
            "num_samples": 2,
            "num_steps": 20,
            "temperature": 0.7,
            "top_p": 1.0,
            "schedule": "cosine",
            "strategy": "random",
            "temperature_annealing": True,
        }
        insertions = nodes[f"insert-{branch}"].node_parameters["insertions"]
        assert len(insertions) == 1
        insertion = insertions[0]
        assert insertion["after_residue_id"] == "A:211"
        assert insertion["before_residue_id"] == "A:224"
        assert tuple(insertion["inserted_residue_ids"]) == BRANCH_LOOP_IDS[branch]
        assert len(BRANCH_LOOP_IDS[branch]) == loop_length
        assert nodes[f"fold-{branch}"].binding_id == "folding.fold.esmfold2_remote"
        assert nodes[f"fold-{branch}"].node_parameters == {
            "effective_seed": 5353999,
            "num_samples": 1,
        }
        evaluation = nodes[f"evaluate-{branch}"].node_parameters
        assert len(evaluation["resolved_core_residue_ids"]) == 283
        core_ids = tuple(evaluation["resolved_core_residue_ids"])
        assert core_ids[core_ids.index("A:146") + 1] == "A:159"
        assert core_ids[core_ids.index("A:211") + 1] == "A:224"
        assert evaluation["resolved_core_tm_score_minimum"] == 0.75
        assert evaluation["resolved_core_rmsd_angstrom_maximum"] == 3.0
        assert evaluation["counterpart_tm_score_minimum"] == 0.70
        assert evaluation["counterpart_rmsd_angstrom_maximum"] == 3.5
        assert evaluation["resolved_core_mean_plddt_minimum"] == 70.0
        assert evaluation["junction_cn_distance_angstrom_minimum"] == 1.15
        assert evaluation["junction_cn_distance_angstrom_maximum"] == 1.55
        assert evaluation["loop_core_nonbonded_distance_angstrom_minimum"] == 2.0

    broken = replace(
        workflow,
        edges=tuple(
            edge
            for edge in workflow.edges
            if not (
                edge.source_node_id == "materialize-confidence-shorter-8"
                and edge.target_node_id == "evaluate-shorter-8"
            )
        ),
        contract_lock=(),
    )
    with pytest.raises(ValueError):
        compile(
            CompilationRequest(
                lock_workflow(broken, catalog),
                2,
            ),
            catalog,
        )


def test_source_bound_5g53_public_journey_closes_large_scientific_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        path = tmp_path / name.lower()
        path.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(path))

    esm3 = _Controlled5G53ESM3()
    folding = ControlledFoldingClient()
    catalog = controlled_catalog()
    environment = controlled_environment(monkeypatch, esm3, folding)
    with TestClient(
        create_application(
            frozen_catalog_override=catalog,
            v2_environment_configuration=environment,
        )
    ) as client:
        project_id = client.post(
            "/api/v2/projects", json={"name": "source-bound 5G53"}
        ).json()["id"]
        uploaded = client.post(
            f"/api/v2/projects/{project_id}/inputs",
            json={
                "filename": INPUT_PATH.name,
                "content_base64": encode_project_input_content(INPUT_PATH.read_bytes()),
            },
        )
        assert uploaded.status_code == 201
        assert uploaded.json()["content_digest"] == f"sha256:{INPUT_SHA256}"
        payload = _payload()
        payload["workflow_id"] = project_id
        payload["contract_lock"] = []
        next(node for node in payload["nodes"] if node["node_id"] == "import-input")[
            "node_parameters"
        ] = {"project_input_ref": uploaded.json()["project_input_ref"]}
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={"workflow": payload},
        )
        assert committed.status_code == 200, committed.json()
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed.json()["workflow_commit_id"],
                "client_request_id": "provider-free-5g53-large-values",
            },
        )
        assert started.status_code == 202, started.json()
        projection = wait_for_testclient_run_terminal(
            client,
            project_id,
            started.json()["run_id"],
            timeout_seconds=180,
        )
        assert projection["status"] == "succeeded", json.dumps(projection, indent=2)
        assert len(projection["node_dispositions"]) == len(payload["nodes"])
        assert all(
            item["outcome"] == "succeeded" for item in projection["node_dispositions"]
        )
        assert all("values" not in output for output in projection["outputs"])

        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{projection['run_id']}/events"
        ) as websocket:
            events = []
            while True:
                message = websocket.receive_json()
                events.append(message)
                if message["event"]["type"] == "run_terminal":
                    break
        assert events[-1]["event"] == {
            "type": "run_terminal",
            "status": "succeeded",
        }
        assert "values" not in json.dumps(events)
        assert [
            event["event"]["invocation_provenance"]
            for event in events
            if event["event"]["type"] == "engine_invocation_started"
            and "project_input_filename"
            in event["event"].get("invocation_provenance", {})
        ] == [{"project_input_filename": "5G53.pdb"}]

        imported_output = next(
            output
            for output in projection["outputs"]
            if output["node_id"] == "import-input"
            and output["output_port"] == "structure_candidates"
        )
        assert imported_output["producer_provenance"] == {
            "producer_run_id": projection["run_id"],
            "producer_result_identity": imported_output["result_identity"],
            "output_port": "structure_candidates",
        }

        imported = _decode(
            client, catalog, projection, "import-input", "structure_candidates"
        )
        selected = _decode(
            client, catalog, projection, "select-chain-a", "structure_candidates"
        )
        reference_axes = _decode(
            client, catalog, projection, "resolve-reference", "residue_axes"
        )
        assert type(imported) is type(selected) is CandidateCollection
        assert imported.items[0].data == ProteinStructure(
            INPUT_PATH.read_text(encoding="ascii")
        )
        assert {
            line[21:22]
            for line in imported.items[0].data.pdb_string.splitlines()
            if line.startswith("ATOM  ")
        } == {"A", "B", "C", "D"}
        assert any(
            line.startswith("HETATM")
            for line in imported.items[0].data.pdb_string.splitlines()
        )
        selected_records = selected.items[0].data.pdb_string.splitlines()
        assert selected.items[0].metadata["transform"] == (
            "structure_transform.select_candidate_chains"
        )
        assert selected.items[0].metadata["parent_index"] == 0
        assert selected.items[0].metadata["chain_ids"] == ("A",)
        assert {
            line[21:22]
            for line in selected_records
            if line.startswith(("ATOM  ", "HETATM"))
        } == {"A"}
        assert sum(line.startswith("HETATM") for line in selected_records) == 62
        assert selected.items[0].parent_ids == (imported.items[0].candidate_id,)
        assert type(reference_axes) is CandidateResolvedResidueAxisAssociations
        reference_axis = reference_axes.entries[0].residue_axis
        assert reference_axis.layout.length == 283
        assert (
            reference_axis.layout.residue_ids[
                reference_axis.layout.residue_ids.index("A:146") + 1
            ]
            == "A:159"
        )
        assert (
            reference_axis.layout.residue_ids[
                reference_axis.layout.residue_ids.index("A:211") + 1
            ]
            == "A:224"
        )

        sequence_port = catalog.require_port_type("protein.sequence", "3.0.0")
        structure_port = catalog.require_port_type("protein.structure", "4.0.0")

        def exact_reference(
            candidate: Candidate,
            data_type_id: str,
            port_type: Any,
        ) -> CandidateDataReference:
            return CandidateDataReference(
                candidate.candidate_id,
                data_type_id,
                port_type.content_digest(candidate.data),
            )

        merged_sequences = _decode(
            client, catalog, projection, "merge-sequences", "candidates"
        )
        merged_counterparts = _decode(
            client, catalog, projection, "merge-counterparts", "candidates"
        )
        merged_reconstructions = _decode(
            client, catalog, projection, "merge-reconstructions", "candidates"
        )
        merged_folds = _decode(client, catalog, projection, "merge-folds", "candidates")
        merged_pairing = _decode(
            client, catalog, projection, "merge-counterpart-pairings", "pairing"
        )
        merged_fold_pairing = _decode(
            client,
            catalog,
            projection,
            "merge-fold-counterpart-pairings",
            "pairing",
        )
        passing = _decode(client, catalog, projection, "merge-passing", "candidates")
        assert all(
            type(value) is CandidateCollection
            for value in (
                merged_sequences,
                merged_counterparts,
                merged_reconstructions,
                merged_folds,
                passing,
            )
        )
        assert len(merged_sequences.items) == 6
        assert len(merged_counterparts.items) == 6
        assert len(merged_reconstructions.items) == 6
        assert len(merged_folds.items) == 6
        assert type(merged_pairing) is PairwiseCandidateMapping
        assert len(merged_pairing.entries) == 6
        assert tuple(
            (entry.subject, entry.reference) for entry in merged_pairing.entries
        ) == tuple(
            (
                exact_reference(sequence, "protein.sequence", sequence_port),
                exact_reference(counterpart, "protein.structure", structure_port),
            )
            for sequence, counterpart in zip(
                merged_sequences.items,
                merged_counterparts.items,
                strict=True,
            )
        )
        assert tuple(
            (entry.subject, entry.reference) for entry in merged_fold_pairing.entries
        ) == tuple(
            (
                exact_reference(fold, "protein.structure", structure_port),
                exact_reference(counterpart, "protein.structure", structure_port),
            )
            for fold, counterpart in zip(
                merged_folds.items,
                merged_counterparts.items,
                strict=True,
            )
        )
        assert tuple(
            len(candidate.data.sequence) for candidate in merged_sequences.items
        ) == (291, 291, 295, 295, 299, 299)
        assert tuple(
            sum(
                line.startswith("ATOM  ") and line[12:16].strip() == "CA"
                for line in candidate.data.pdb_string.splitlines()
            )
            for candidate in merged_reconstructions.items
        ) == (291, 291, 295, 295, 299, 299)

        esm3_method = ExactContractReference(
            **catalog.require_contract(
                "binding",
                "esm3.generate_paired.biohub_medium",
                "8.0.0",
            ).descriptor["method"]
        )
        expected_prompt_index = 0
        for branch, loop_length, _ in BRANCHES:
            insertion_node = next(
                node
                for node in payload["nodes"]
                if node["node_id"] == f"insert-{branch}"
            )
            insertions = insertion_node["node_parameters"]["insertions"]
            assert len(insertions) == 1
            assert (
                tuple(insertions[0]["inserted_residue_ids"])
                == (BRANCH_LOOP_IDS[branch])
            )
            loop_ids = BRANCH_LOOP_IDS[branch]
            insertion_index = reference_axis.layout.residue_ids.index("A:211") + 1
            expected_residue_ids = (
                reference_axis.layout.residue_ids[:insertion_index]
                + loop_ids
                + reference_axis.layout.residue_ids[insertion_index:]
            )
            expected_masked_sequence = (
                reference_axis.sequence[:insertion_index]
                + "_" * loop_length
                + reference_axis.sequence[insertion_index:]
            )
            sequences = _decode(
                client,
                catalog,
                projection,
                f"generate-{branch}",
                "sequence_candidates",
            )
            counterparts = _decode(
                client,
                catalog,
                projection,
                f"generate-{branch}",
                "structure_candidates",
            )
            reconstructions = _decode(
                client,
                catalog,
                projection,
                f"generate-{branch}",
                "sequence_reconstruction_candidates",
            )
            counterpart_pairing = _decode(
                client,
                catalog,
                projection,
                f"generate-{branch}",
                "counterpart_pairs",
            )
            confidence_facts = _decode(
                client,
                catalog,
                projection,
                f"generate-{branch}",
                "confidence_facts",
            )
            reconstruction_confidence = _decode(
                client,
                catalog,
                projection,
                f"generate-{branch}",
                "sequence_reconstruction_confidence_facts",
            )
            folds = _decode(
                client,
                catalog,
                projection,
                f"fold-{branch}",
                "structure_candidates",
            )
            assert len(sequences.items) == len(counterparts.items) == 2
            assert len(reconstructions.items) == 2
            assert len(counterpart_pairing.entries) == 2
            assert confidence_facts.observation_method == esm3_method
            assert reconstruction_confidence.observation_method == esm3_method
            assert tuple(
                (entry.subject, entry.reference)
                for entry in counterpart_pairing.entries
            ) == tuple(
                (
                    exact_reference(sequence, "protein.sequence", sequence_port),
                    exact_reference(
                        counterpart,
                        "protein.structure",
                        structure_port,
                    ),
                )
                for sequence, counterpart in zip(
                    sequences.items,
                    counterparts.items,
                    strict=True,
                )
            )
            assert tuple(
                counterpart.parent_ids for counterpart in counterparts.items
            ) == tuple((sequence.candidate_id,) for sequence in sequences.items)
            assert tuple(
                reconstruction.parent_ids for reconstruction in reconstructions.items
            ) == tuple((sequence.candidate_id,) for sequence in sequences.items)
            assert tuple(fold.parent_ids for fold in folds.items) == tuple(
                (sequence.candidate_id,) for sequence in sequences.items
            )
            assert tuple(
                candidate.data.residue_ids for candidate in sequences.items
            ) == (expected_residue_ids, expected_residue_ids)
            assert tuple(
                candidate.metadata["sample_index"] for candidate in sequences.items
            ) == (0, 1)
            assert all(
                len(candidate.data.sequence) == 283 + loop_length
                for candidate in sequences.items
            )
            facts_by_key = {
                fact.prediction_key: fact for fact in confidence_facts.entries
            }
            reconstruction_facts_by_key = {
                fact.prediction_key: fact for fact in reconstruction_confidence.entries
            }
            for offset, (sequence, counterpart, reconstruction) in enumerate(
                zip(
                    sequences.items,
                    counterparts.items,
                    reconstructions.items,
                    strict=True,
                )
            ):
                fact = facts_by_key[counterpart.metadata["prediction_key"]]
                reconstruction_fact = reconstruction_facts_by_key[
                    reconstruction.metadata["prediction_key"]
                ]
                prompt_index = expected_prompt_index + offset
                sequence_prompt = esm3.sequence_prompts[prompt_index]
                structure_prompt = esm3.structure_prompts[prompt_index]
                assert sequence_prompt.sequence == expected_masked_sequence
                assert structure_prompt.sequence == sequence.data.sequence
                assert tuple(sequence_prompt.coordinates.shape) == (
                    283 + loop_length,
                    37,
                    3,
                )
                visible_backbone = torch.isfinite(
                    sequence_prompt.coordinates[:, (0, 1, 2), :]
                ).all(dim=(1, 2))
                assert tuple(
                    index for index, visible in enumerate(visible_backbone) if visible
                ) == tuple(
                    index
                    for index in range(283 + loop_length)
                    if not insertion_index <= index < insertion_index + loop_length
                )
                for confidence, candidate, output_role in (
                    (fact, counterpart, "structure_candidates"),
                    (
                        reconstruction_fact,
                        reconstruction,
                        "sequence_reconstruction_candidates",
                    ),
                ):
                    structure_digest = structure_port.content_digest(candidate.data)
                    axis_digest = PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(
                        confidence.prediction_axis
                    )
                    assert confidence.structure_content_digest == structure_digest
                    assert confidence.prediction_axis.layout.residue_ids == (
                        expected_residue_ids
                    )
                    assert confidence.prediction_axis.sequence == sequence.data
                    assert confidence.prediction_key == prediction_key(
                        output_role=output_role,
                        output_slot=offset,
                        structure_content_digest=structure_digest,
                        prediction_axis_content_digest=axis_digest,
                    )
                    assert candidate.metadata["prediction_key"] == (
                        confidence.prediction_key
                    )
            expected_prompt_index += 2
            for collection in (confidence_facts, reconstruction_confidence):
                assert len(collection.entries) == 2
                assert all(
                    fact.pae is not None
                    and len(fact.pae) == 283 + loop_length
                    and len(fact.pae[0]) == 283 + loop_length
                    for fact in collection.entries
                )
            evaluation = _decode(
                client,
                catalog,
                projection,
                f"evaluate-{branch}",
                "quality_evidence",
            )
            assert type(evaluation) is InsertedLoopEvaluationCollection
            assert len(evaluation.entries) == 2
            for evidence in evaluation.entries:
                assert len(evidence.resolved_core_residue_ids) == 283
                assert len(evidence.loop_residue_ids) == loop_length
                assert len(evidence.prediction_to_structure_correspondence) == (
                    283 + loop_length
                )
                assert evidence.resolved_core_tm_score >= 0.0
                assert evidence.resolved_core_rmsd_angstrom >= 0.0
                assert evidence.counterpart_tm_score >= 0.0
                assert evidence.counterpart_rmsd_angstrom >= 0.0
                assert evidence.resolved_core_mean_plddt > 0.0
                assert evidence.loop_mean_plddt > 0.0
                assert 1.15 <= evidence.left_junction.distance_angstrom <= 1.55
                assert 1.15 <= evidence.right_junction.distance_angstrom <= 1.55
                assert (
                    evidence.minimum_loop_core_nonbonded_distance.distance_angstrom
                    < 2.0
                )
                assert evidence.junctions_passed
                assert not evidence.clash_passed
                assert not evidence.accepted
        assert passing.items == ()

        assert len(projection["artifact_index"]) == 6
        for artifact in projection["artifact_index"]:
            downloaded = client.get(
                f"/api/v2/projects/{project_id}/runs/{projection['run_id']}"
                f"/artifacts/{artifact['artifact_reference']}"
            )
            assert downloaded.status_code == 200
            assert downloaded.headers["Digest"] == artifact["content_digest"]
            assert hashlib.sha256(downloaded.content).hexdigest() == (
                artifact["content_digest"].removeprefix("sha256:")
            )

    assert len(esm3.sequence_prompts) == len(esm3.structure_prompts) == 6
    assert len(folding.calls) == 6
