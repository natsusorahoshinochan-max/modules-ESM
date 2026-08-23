"""Provider-free public acceptance for the source-bound 2EMO Workflow."""

from __future__ import annotations

from protein_workbench_public.bootstrap import module_registrations

from dataclasses import replace
import hashlib
import json
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
    BindingEnvironment,
    ReadinessResult,
)
from core.workflow.compiler import (
    CompilationRequest,
    compile,
    lock_workflow,
)
from protein_workbench_public.workflow_codec import decode_workflow_document
from tests.support.application import create_application
from datatypes.candidate import CandidateCollection
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
    PairwiseObservationContext,
    ScoreCollection,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from modules.folding.esmfold2_contract import REMOTE_ESMFOLD2_MODEL
from modules.structure_comparison.contracts import (
    RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
    SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
)
from modules.structure_comparison.domain import StructureAlignmentEvidence
from modules.structure_comparison.metrics import (
    rmsd_from_evidence,
    tm_score_from_evidence,
)
from modules.structure_transform.domain import (
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.csh_normalization import normalize_csh_parent_span
from protein_workbench_public import encode_project_input_content
from tests.fixtures.canonical_3gb1_v2 import ControlledFoldResponse
from tests.fixtures.public_v2 import (
    retrieve_typed_output_canonical_bytes,
    wait_for_testclient_run_terminal,
)


ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = ROOT / "pdbs" / "2EMO.pdb"
WORKFLOW_PATH = ROOT / "examples" / "v2" / "source-bound-2emo.workflow.json"
INPUT_SHA256 = "6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700"
FIXED_IDS = (
    "A:42", "A:44", "A:46", "A:60", "A:61", "A:62", "A:63",
    "A:64", "A:65", "A:66", "A:67", "A:68", "A:69", "A:70",
    "A:71", "A:72", "A:92", "A:94", "A:96", "A:110", "A:112",
    "A:121", "A:123", "A:145", "A:148", "A:150", "A:165",
    "A:167", "A:183", "A:203", "A:205", "A:220", "A:222",
)
_AA3 = dict(zip(
    "ACDEFGHIKLMNPQRSTVWY",
    ("ALA", "CYS", "ASP", "GLU", "PHE", "GLY", "HIS", "ILE", "LYS", "LEU", "MET", "ASN", "PRO", "GLN", "ARG", "SER", "THR", "VAL", "TRP", "TYR"),
    strict=True,
))
_AA1 = {value: key for key, value in _AA3.items()}


def _payload() -> dict[str, Any]:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _provider_free_catalog() -> Any:
    def available() -> AvailabilityResult:
        return AvailabilityResult.available()

    def ready(check_input: BindingEnvironment) -> ReadinessResult:
        return ReadinessResult(bool(check_input.values))

    opened = {
        "proteinmpnn.design.local",
        "folding.fold.esmfold2_remote",
        "solubility.protein_sol.local",
    }
    registrations: list[ModulePackageRegistration] = []
    for registration in module_registrations():
        registrations.append(replace(
            registration,
            bindings=tuple(
                replace(
                    binding,
                    availability=replace(binding.availability, check=available),
                    readiness=replace(binding.readiness, check=ready),
                ) if binding.binding_id in opened else binding
                for binding in registration.bindings
            ),
        ))
    return build_frozen_catalog(tuple(registrations))


class _ControlledProteinMPNN:
    provider_identity = "provider-free-2emo-proteinmpnn"

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
        sequence = "".join(
            _AA1[line[17:20].strip()]
            for line in pdb_string.splitlines()
            if line.startswith("ATOM  ") and line[12:16].strip() == "CA"
        )
        return [{"name": "target", "seq": sequence, "seq_chain_A": sequence}]

    def design(self, request: Any) -> list[ProteinSequence]:
        self.requests.append(request)
        _, reference = next(iter(request.reference_sequences.items()))
        fixed_by_chain = next(iter(request.fixed_position_dict.values()))
        fixed_positions = set(next(iter(fixed_by_chain.values())))
        alphabet = "ACDEFGHIKLMNPQRSTVWY"
        designable_positions = tuple(
            position
            for position in range(1, len(reference) + 1)
            if position not in fixed_positions
        )
        results = []
        for sample in range(request.num_sequences):
            sequence = list(reference)
            position = designable_positions[sample]
            sequence[position - 1] = next(
                residue for residue in alphabet
                if residue != sequence[position - 1]
            )
            results.append(ProteinSequence("".join(sequence)))
        return results

    def score(self, request: Any, sequence: ProteinSequence) -> float:
        raise AssertionError((request, sequence))


def _pdb_for_designed_sequence(normalized_pdb: str, sequence: str) -> str:
    residue_ids = tuple(range(6, 230))
    residue_names = dict(zip(residue_ids, map(_AA3.__getitem__, sequence), strict=True))
    lines = []
    for line in normalized_pdb.splitlines():
        if line.startswith("ATOM  "):
            residue_number = int(line[22:26])
            if line[12:16].strip() not in {"N", "CA", "C", "O"}:
                continue
            line = (
                line[:17]
                + residue_names[residue_number].rjust(3)
                + line[20:]
            )
            lines.append(line)
        elif line.startswith(("TER", "END")):
            lines.append(line)
    return "\n".join(lines) + "\n"


class _ControlledESMFold2:
    def __init__(self, normalized_pdb: str) -> None:
        self.normalized_pdb = normalized_pdb
        self.calls: list[tuple[str, str, Any]] = []

    def fold(self, *, sequence: str, model_name: str, config: Any):
        slot = len(self.calls)
        self.calls.append((sequence, model_name, config))
        plddt = 65.0 if slot in {2, 5} else 90.0
        return ControlledFoldResponse(
            sequence=sequence,
            pdb_string=_pdb_for_designed_sequence(self.normalized_pdb, sequence),
            ptm=torch.tensor(0.95),
            plddt=torch.tensor([plddt / 100.0] * len(sequence)),
            pae=torch.zeros((len(sequence), len(sequence))),
        )


def test_controlled_fold_fixture_has_exact_sequence_and_lawful_backbone() -> None:
    normalized, _ = normalize_csh_parent_span(
        ProteinStructure(INPUT_PATH.read_text(encoding="ascii"))
    )
    sequence = "".join(
        _AA1[line[17:20].strip()]
        for line in normalized.pdb_string.splitlines()
        if line.startswith("ATOM  ") and line[12:16].strip() == "CA"
    )
    designed = _pdb_for_designed_sequence(normalized.pdb_string, sequence)
    atom_lines = tuple(
        line for line in designed.splitlines() if line.startswith("ATOM  ")
    )
    assert all(
        line.startswith(("ATOM  ", "TER", "END"))
        for line in designed.splitlines()
    )
    assert not any(
        line.startswith("HETATM") for line in designed.splitlines()
    )
    assert {line[12:16].strip() for line in atom_lines} == {
        "N", "CA", "C", "O",
    }
    assert "".join(
        _AA1[line[17:20].strip()]
        for line in atom_lines
        if line[12:16].strip() == "CA"
    ) == sequence
    assert tuple(
        int(line[22:26])
        for line in atom_lines
        if line[12:16].strip() == "CA"
    ) == tuple(range(6, 230))


def _decode_values(
    client: TestClient,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> tuple[Any, ...]:
    output = next(
        item for item in projection["outputs"]
        if item["node_id"] == node_id and item["output_port"] == output_port
    )
    codec = catalog.require_port_type(
        output["port_type"]["contract_id"],
        output["port_type"]["contract_version"],
    )
    return tuple(
        codec.decode(retrieve_typed_output_canonical_bytes(
            client,
            projection["project_id"],
            projection["run_id"],
            output,
            index,
        ))
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


def _exact_reference(raw: dict[str, str]) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=raw["contract_kind"],
        contract_id=raw["contract_id"],
        contract_version=raw["contract_version"],
        contract_digest=raw["contract_digest"],
    )


def _assert_closed_scientific_acceptance(
    *,
    catalog: Any,
    payload: dict[str, Any],
    normalized_candidates: CandidateCollection,
    normalizations: CandidateModifiedResidueNormalizationAssociations,
    reference_axes: CandidateResolvedResidueAxisAssociations,
    designs: CandidateCollection,
    folds: CandidateCollection,
    alignments: tuple[StructureAlignmentEvidence, ...],
    confidence: ScoreCollection,
    protein_sol_scores: ScoreCollection,
    tm_scores: ScoreCollection,
    rmsd_scores: ScoreCollection,
    passing: CandidateCollection,
    solubilities: list[float],
    expected_passing: int,
) -> None:
    """Prove the exact evidence graph required for 2EMO acceptance."""
    assert len(normalized_candidates.items) == 1
    assert len(normalizations.entries) == 1
    assert len(reference_axes.entries) == 1
    normalized_reference = normalized_candidates.items[0]
    normalization_association = normalizations.entries[0]
    assert normalization_association.subject.candidate_id == (
        normalized_reference.candidate_id
    )
    assert len(normalization_association.normalizations.entries) == 1
    normalization = normalization_association.normalizations.entries[0]
    assert (
        normalization.observed_residue_id,
        normalization.parent_residue_ids,
        normalization.parent_sequence,
    ) == ("A:66", ("A:65", "A:66", "A:67"), "SHG")
    axis_association = reference_axes.entries[0]
    assert axis_association.subject == normalization_association.subject
    assert axis_association.residue_axis.layout.length == 224
    assert axis_association.residue_axis.layout.residue_ids[58:63] == (
        "A:64", "A:65", "A:66", "A:67", "A:68",
    )
    assert axis_association.residue_axis.sequence[59:62] == "SHG"

    assert len(designs.items) == len(folds.items) == 8
    assert all(
        design.parent_ids == (normalized_reference.candidate_id,)
        for design in designs.items
    )
    designs_by_id = {design.candidate_id: design for design in designs.items}
    assert len(designs_by_id) == 8
    assert all(
        len(fold.parent_ids) == 1 and fold.parent_ids[0] in designs_by_id
        for fold in folds.items
    )

    fold_ids = tuple(fold.candidate_id for fold in folds.items)
    expected_residue_ids = tuple(f"A:{index}" for index in range(6, 230))
    assert len(alignments) == 8
    alignments_by_subject = {
        alignment.subject.candidate_id: alignment
        for alignment in alignments
    }
    assert set(alignments_by_subject) == set(fold_ids)
    alignment_codec = catalog.require_port_type(
        "structure_comparison.alignment_evidence",
        "5.0.0",
    )
    for fold in folds.items:
        alignment = alignments_by_subject[fold.candidate_id]
        assert type(alignment) is StructureAlignmentEvidence
        assert alignment.subject.candidate_id == fold.candidate_id
        assert alignment.reference == normalization_association.subject
        assert alignment.method == SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE
        assert alignment.normalization.subject_axis_residue_count == 224
        assert alignment.normalization.reference_axis_residue_count == 224
        assert alignment.normalization.subject_ca_count == 224
        assert alignment.normalization.reference_ca_count == 224
        assert alignment.normalization.aligned_atom_count == 224
        assert tuple(
            item.subject_residue_id for item in alignment.correspondence
        ) == expected_residue_ids
        assert tuple(
            item.reference_residue_id for item in alignment.correspondence
        ) == expected_residue_ids
        assert all(
            item.subject_atom_name == item.reference_atom_name == "CA"
            for item in alignment.correspondence
        )

    selectors = {
        selector["selector_id"]: selector
        for selector in payload["observation_selectors"]
    }
    tm_selector = selectors["tm-reference-normalized"]
    rmsd_selector = selectors["ca-rmsd"]
    assert len(tm_scores.entries) == len(rmsd_scores.entries) == 8
    tm_by_subject = {
        observation.subject.candidate_id: observation
        for observation in tm_scores.entries
    }
    rmsd_by_subject = {
        observation.subject.candidate_id: observation
        for observation in rmsd_scores.entries
    }
    assert set(tm_by_subject) == set(rmsd_by_subject) == set(fold_ids)
    for fold in folds.items:
        alignment = alignments_by_subject[fold.candidate_id]
        evidence_digest = alignment_codec.content_digest(alignment)
        tm_observation = tm_by_subject[fold.candidate_id]
        rmsd_observation = rmsd_by_subject[fold.candidate_id]
        for observation, selector, method, normalization in (
            (
                tm_observation,
                tm_selector,
                TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
                "reference-axis-residue-count",
            ),
            (
                rmsd_observation,
                rmsd_selector,
                RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
                "aligned-CA-mean-square-distance",
            ),
        ):
            assert observation.subject == alignment.subject
            assert observation.source_partition == selector["source_partition"]
            assert observation.metric == _exact_reference(selector["metric"])
            assert observation.method == method == _exact_reference(
                selector["method"]
            )
            assert type(observation.context) is PairwiseObservationContext
            context = observation.context
            assert context.subject.role == "subject"
            assert context.subject.candidate == alignment.subject
            assert context.reference.role == "reference"
            assert context.reference.candidate == alignment.reference
            assert context.pairing_mode == "fixed_reference"
            assert context.normalization == normalization
            assert context.evidence_content_digest == evidence_digest
            assert context.evidence_method == alignment.method
            assert context.subject_axis_content_digest == (
                alignment.subject_axis_content_digest
            )
            assert context.reference_axis_content_digest == (
                alignment.reference_axis_content_digest
            )
            assert context.normalization_length == 224
            assert context.aligned_atom_count == 224
            assert observation.residue_axis is None
        assert tm_observation.value == pytest.approx(
            tm_score_from_evidence(alignment), abs=1e-15
        )
        assert rmsd_observation.value == pytest.approx(
            rmsd_from_evidence(alignment), abs=1e-15
        )
        assert tm_observation.value >= 0.8
        assert rmsd_observation.value <= 2.5

    plddt_selector = selectors["mean-plddt"]
    assert len(confidence.entries) == 32
    assert {
        observation.metric.contract_id for observation in confidence.entries
    } == {
        "structure.plddt.per_residue",
        "structure.plddt.mean_residue",
        "structure.ptm",
        "structure.pae",
    }
    assert all(
        observation.method == _exact_reference(plddt_selector["method"])
        and type(observation.context) is IntrinsicObservationContext
        and observation.source_partition == "prediction_confidence"
        for observation in confidence.entries
    )
    mean_plddt = tuple(
        observation
        for observation in confidence.entries
        if observation.metric == _exact_reference(plddt_selector["metric"])
    )
    mean_plddt_by_subject = {
        observation.subject.candidate_id: observation
        for observation in mean_plddt
    }
    assert set(mean_plddt_by_subject) == set(fold_ids)
    for fold in folds.items:
        observation = mean_plddt_by_subject[fold.candidate_id]
        sample_slot = int(str(fold.metadata["sample_slot"]).split(":")[1])
        expected_plddt = 65.0 if sample_slot in {2, 5} else 90.0
        assert float(observation.value) == pytest.approx(
            expected_plddt,
            abs=1e-5,
        )
        assert observation.source_partition == plddt_selector["source_partition"]
        assert observation.residue_axis is not None
        assert observation.residue_axis.source.candidate_id == fold.parent_ids[0]
        assert observation.residue_axis.layout.length == 224
        assert observation.residue_axis.layout.residue_ids == expected_residue_ids

    protein_sol_selector = selectors["protein-sol-scaled"]
    assert len(protein_sol_scores.entries) == 24
    assert {
        observation.metric.contract_id
        for observation in protein_sol_scores.entries
    } == {
        "solubility.protein_sol_percent",
        "solubility.protein_sol_scaled",
        "solubility.protein_sol_pi",
    }
    scaled_solubility = tuple(
        observation
        for observation in protein_sol_scores.entries
        if observation.metric == _exact_reference(protein_sol_selector["metric"])
    )
    scaled_by_subject = {
        observation.subject.candidate_id: observation
        for observation in scaled_solubility
    }
    assert set(scaled_by_subject) == set(designs_by_id)
    calibration_context = CalibrationObservationContext(
        calibration_metric="population_scaled_solubility",
        calibration_value=0.446,
        calibration_unit="dimensionless",
        population_id="niwa_non_membrane_2396",
    )
    assert all(
        observation.source_partition
        == protein_sol_selector["source_partition"]
        and observation.method
        == _exact_reference(protein_sol_selector["method"])
        and observation.context == calibration_context
        and observation.residue_axis is None
        for observation in scaled_solubility
    )
    for design in designs.items:
        observation = scaled_by_subject[design.candidate_id]
        sample_index = int(design.metadata["sample_index"])
        assert float(observation.value) == pytest.approx(
            solubilities[sample_index], abs=1e-15
        )
    expected_passing_ids = {
        fold.candidate_id
        for fold in folds.items
        if float(mean_plddt_by_subject[fold.candidate_id].value) >= 70
        and float(scaled_by_subject[fold.parent_ids[0]].value) >= 0.446
        and float(tm_by_subject[fold.candidate_id].value) >= 0.8
        and float(rmsd_by_subject[fold.candidate_id].value) <= 2.5
    }
    assert {candidate.candidate_id for candidate in passing.items} == (
        expected_passing_ids
    )
    assert len(passing.items) == expected_passing


def test_source_bound_2emo_is_exact_locked_and_compilable() -> None:
    assert hashlib.sha256(INPUT_PATH.read_bytes()).hexdigest() == INPUT_SHA256
    catalog = build_frozen_catalog(module_registrations())
    workflow = decode_workflow_document(_payload())
    assert workflow.workflow_id == "source-bound-2emo"
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

    nodes = {node.node_id: node for node in workflow.nodes}
    assert nodes["design-sequences"].node_parameters == {
        "effective_seed": 2066001,
        "num_sequences": 8,
        "temperature": 0.1,
        "backbone_noise": 0,
    }
    assert nodes["design-sequences"].binding_id == "proteinmpnn.design.local"
    assert tuple(nodes["author-constraints"].node_parameters["fixed_residue_ids"]) == FIXED_IDS
    assert nodes["fold-esmfold2"].node_parameters == {
        "effective_seed": 2066002,
        "num_samples": 1,
    }
    assert nodes["fold-esmfold2"].binding_id == "folding.fold.esmfold2_remote"
    filters = {
        node.node_id: (node.node_parameters["operator"], node.node_parameters["threshold"])
        for node in workflow.nodes if node.node_id.startswith("filter-")
    }
    assert filters == {
        "filter-tm": (">=", 0.8),
        "filter-rmsd": ("<=", 2.5),
        "filter-plddt": (">=", 70),
        "filter-protein-sol": (">=", 0.446),
    }
    broken = replace(
        workflow,
        edges=tuple(edge for edge in workflow.edges if not (
            edge.source_node_id == "materialize-confidence"
            and edge.target_node_id == "filter-plddt"
        )),
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


@pytest.mark.parametrize(
    ("solubilities", "expected_passing"),
    (([0.50, 0.40, 0.60, 0.30, 0.70, 0.20, 0.80, 0.10], 3), ([0.10] * 8, 0)),
)
def test_source_bound_2emo_public_journey_closes_exact_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    solubilities: list[float],
    expected_passing: int,
) -> None:
    import modules.solubility.protein_sol as solubility_adapter

    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        path = tmp_path / name.lower()
        path.mkdir()
        monkeypatch.setenv(f"PROTEIN_WORKBENCH_{name}_ROOT", str(path))

    proteinmpnn = _ControlledProteinMPNN()

    monkeypatch.setattr(
        "modules.proteinmpnn.adapter._provider_for_environment",
        lambda _environment, _directory, _models: proteinmpnn,
    )
    prepared_sequences: list[str] = []

    def prepare_protein_sol(**kwargs: Any):
        prepared_sequences[:] = kwargs["sequences"]
        return (("provider-free-protein-sol",), kwargs["staging_directory"] / "seq_prediction.txt")

    def run_protein_sol(**kwargs: Any) -> int:
        rows = [
            "HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,population-sol,pI"
        ]
        rows.extend(
            f"SEQUENCE PREDICTIONS,>candidate_{index},50.000,{value:.3f},0.446,7.000"
            for index, value in enumerate(solubilities)
        )
        (kwargs["staging_directory"] / "seq_prediction.txt").write_text(
            "\n".join(rows) + "\n",
            encoding="ascii",
        )
        return 0

    monkeypatch.setattr(solubility_adapter, "_prepare_protein_sol_invocation", prepare_protein_sol)
    monkeypatch.setattr(solubility_adapter, "_run_local_process", run_protein_sol)

    normalized, _ = normalize_csh_parent_span(
        ProteinStructure(INPUT_PATH.read_text(encoding="ascii"))
    )
    folding = _ControlledESMFold2(normalized.pdb_string)
    monkeypatch.setattr(
        "modules.folding.esmfold2_remote.build_remote_engine",
        lambda _environment: folding,
    )

    environment = {
        ("proteinmpnn.design.local", "11.0.0"): {
            "values": {
                "device": "cpu",
                "provider_root": ROOT / "repositories" / "ProteinMPNN",
            },
        },
        ("folding.fold.esmfold2_remote", "9.0.0"): {
            "values": {
                "endpoint_id": "provider-free",
                "credential_handle": "provider-free-folding-credential",
            },
        },
        ("solubility.protein_sol.local", "5.0.0"): {
            "values": {
                "source_root": Path("/provider-free/protein-sol"),
                "bash_executable": Path("/provider-free/bash"),
                "perl_executable": Path("/provider-free/perl"),
            },
        },
    }
    catalog = _provider_free_catalog()
    with TestClient(create_application(
        frozen_catalog_override=catalog,
        v2_environment_configuration=environment,
    )) as client:
        project_id = client.post(
            "/api/v2/projects", json={"name": "source-bound 2EMO"}
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
        next(node for node in payload["nodes"] if node["node_id"] == "import-input")["node_parameters"] = {
            "project_input_ref": uploaded.json()["project_input_ref"]
        }
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={"workflow": payload},
        )
        assert committed.status_code == 200, committed.json()
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed.json()["workflow_commit_id"],
                "client_request_id": f"provider-free-2emo-{expected_passing}",
            },
        )
        assert started.status_code == 202, started.json()
        projection = wait_for_testclient_run_terminal(
            client, project_id, started.json()["run_id"], timeout_seconds=90
        )
        assert projection["status"] == "succeeded", json.dumps(
            projection, indent=2
        )
        assert len(projection["node_dispositions"]) == len(payload["nodes"])
        assert all(item["outcome"] == "succeeded" for item in projection["node_dispositions"])
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
        assert events[-1]["event"] == {"type": "run_terminal", "status": "succeeded"}
        assert "values" not in json.dumps(events)

        normalized_candidates = _decode(client, catalog, projection, "normalize-reference", "structure_candidates")
        normalizations = _decode(client, catalog, projection, "materialize-reference-normalizations", "modified_residue_normalizations")
        reference_axes = _decode(client, catalog, projection, "resolve-reference", "residue_axes")
        designs = _decode(client, catalog, projection, "design-sequences", "sequence_candidates")
        folds = _decode(client, catalog, projection, "fold-esmfold2", "structure_candidates")
        alignments = _decode_values(
            client, catalog, projection, "align-folds", "alignments"
        )
        tm_scores = _decode(client, catalog, projection, "score-tm", "scores")
        rmsd_scores = _decode(
            client, catalog, projection, "score-rmsd", "scores"
        )
        confidence = _decode(client, catalog, projection, "materialize-confidence", "observations")
        protein_sol_scores = _decode(client, catalog, projection, "score-protein-sol", "scores")
        tm_passing = _decode(client, catalog, projection, "filter-tm", "candidates")
        rmsd_passing = _decode(client, catalog, projection, "filter-rmsd", "candidates")
        plddt_passing = _decode(client, catalog, projection, "filter-plddt", "candidates")
        solubility_passing = _decode(client, catalog, projection, "filter-protein-sol", "candidates")
        soluble_folds = _decode(client, catalog, projection, "select-soluble-folds", "candidates")
        passing = _decode(client, catalog, projection, "passing-candidates", "candidates")

        assert type(normalized_candidates) is CandidateCollection
        assert type(normalizations) is CandidateModifiedResidueNormalizationAssociations
        assert type(reference_axes) is CandidateResolvedResidueAxisAssociations
        assert type(designs) is type(folds) is type(passing) is CandidateCollection
        assert type(confidence) is type(protein_sol_scores) is ScoreCollection
        normalization = normalizations.entries[0].normalizations.entries[0]
        assert normalization.observed_residue_id == "A:66"
        assert normalization.parent_residue_ids == ("A:65", "A:66", "A:67")
        assert normalization.parent_sequence == "SHG"
        axis = reference_axes.entries[0].residue_axis
        assert axis.layout.length == 224
        assert axis.layout.residue_ids[58:63] == ("A:64", "A:65", "A:66", "A:67", "A:68")
        assert axis.sequence[59:62] == "SHG"
        assert len(designs.items) == len(folds.items) == 8
        assert all(child.parent_ids == (normalized_candidates.items[0].candidate_id,) for child in designs.items)
        design_ids = {child.candidate_id for child in designs.items}
        assert all(
            len(child.parent_ids) == 1 and child.parent_ids[0] in design_ids
            for child in folds.items
        )
        assert all("constraint_digest" in child.metadata for child in designs.items)
        assert {
            (
                child.metadata["effective_seed"],
                child.metadata["num_sequences"],
                child.metadata["temperature"],
                child.metadata["backbone_noise"],
            )
            for child in designs.items
        } == {(2066001, 8, 0.1, 0.0)}
        fixed_indices = tuple(int(residue_id.split(":")[1]) - 6 for residue_id in FIXED_IDS)
        assert all(
            all(child.data.sequence[index] == axis.sequence[index] for index in fixed_indices)
            for child in designs.items
        )
        assert {entry.subject.candidate_id for entry in confidence.entries} == {
            child.candidate_id for child in folds.items
        }
        assert {entry.subject.candidate_id for entry in protein_sol_scores.entries} == {
            child.candidate_id for child in designs.items
        }
        assert len(tm_passing.items) == 8
        assert len(rmsd_passing.items) == 8
        assert len(plddt_passing.items) == 6
        assert len(solubility_passing.items) == sum(
            value >= 0.446 for value in solubilities
        )
        assert len(soluble_folds.items) == len(solubility_passing.items)
        assert len(passing.items) == expected_passing
        _assert_closed_scientific_acceptance(
            catalog=catalog,
            payload=payload,
            normalized_candidates=normalized_candidates,
            normalizations=normalizations,
            reference_axes=reference_axes,
            designs=designs,
            folds=folds,
            alignments=alignments,
            confidence=confidence,
            protein_sol_scores=protein_sol_scores,
            tm_scores=tm_scores,
            rmsd_scores=rmsd_scores,
            passing=passing,
            solubilities=solubilities,
            expected_passing=expected_passing,
        )

        if expected_passing:
            tm_entries = list(tm_scores.entries)
            first_tm = tm_entries[0]
            assert type(first_tm.context) is PairwiseObservationContext
            tm_entries[0] = replace(
                first_tm,
                context=replace(
                    first_tm.context,
                    evidence_content_digest=f"sha256:{'0' * 64}",
                ),
            )
            confidence_entries = tuple(
                observation
                for observation in confidence.entries
                if not (
                    observation.subject.candidate_id
                    == folds.items[0].candidate_id
                    and observation.metric.contract_id
                    == "structure.plddt.mean_residue"
                )
            )
            contradictory_folds = replace(
                folds,
                items=(
                    replace(
                        folds.items[0],
                        parent_ids=("contradictory-design-parent",),
                    ),
                    *folds.items[1:],
                ),
            )
            evidence_gaps = (
                {
                    "normalizations": CandidateModifiedResidueNormalizationAssociations()
                },
                {"alignments": alignments[:-1]},
                {
                    "tm_scores": ScoreCollection(
                        tm_scores.collection_id,
                        tuple(tm_entries),
                    )
                },
                {
                    "confidence": ScoreCollection(
                        confidence.collection_id,
                        confidence_entries,
                    )
                },
                {"folds": contradictory_folds},
            )
            acceptance_inputs = {
                "catalog": catalog,
                "payload": payload,
                "normalized_candidates": normalized_candidates,
                "normalizations": normalizations,
                "reference_axes": reference_axes,
                "designs": designs,
                "folds": folds,
                "alignments": alignments,
                "confidence": confidence,
                "protein_sol_scores": protein_sol_scores,
                "tm_scores": tm_scores,
                "rmsd_scores": rmsd_scores,
                "passing": passing,
                "solubilities": solubilities,
                "expected_passing": expected_passing,
            }
            for gap in evidence_gaps:
                with pytest.raises(AssertionError):
                    _assert_closed_scientific_acceptance(
                        **(acceptance_inputs | gap)
                    )

    assert len(proteinmpnn.requests) == 1
    request = proteinmpnn.requests[0]
    assert request.target_length == 224
    assert request.model_name == "v_48_020"
    assert request.num_sequences == 8
    assert request.temperature == 0.1
    assert request.backbone_noise == 0.0
    assert request.residue_identity_mapping[58:63] == (
        ("A:64", 0, "A", 59),
        ("A:65", 0, "A", 60),
        ("A:66", 0, "A", 61),
        ("A:67", 0, "A", 62),
        ("A:68", 0, "A", 63),
    )
    assert request.fixed_position_dict == {
        "target": {"A": [int(item.split(":")[1]) - 5 for item in FIXED_IDS]}
    }
    assert len(folding.calls) == 8
    assert {model_name for _, model_name, _ in folding.calls} == {
        REMOTE_ESMFOLD2_MODEL
    }
    assert len(prepared_sequences) == 8
