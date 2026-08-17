"""Small operation-scope lifecycle contracts for ProteinMPNN."""

from __future__ import annotations

import weakref
from pathlib import Path
from typing import Any

import pytest

from core import InputContentDigests, OperationCall
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    ProteinSequence,
)
from modules.proteinmpnn.adapter import LocalProteinMPNNAdapter
from modules.proteinmpnn.implementation import (
    ProteinMPNNDesignImplementation,
    ProteinMPNNScoreImplementation,
)
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.implementation import resolve_residue_axis
from scripts.fresh_source_bound import proteinmpnn_lifecycle_receipt
from tests.fixtures.proteinmpnn_sources.package import _fixture_structure


_DIGEST = "sha256:" + "1" * 64


def _reference(
    candidate_id: str,
    data_type_id: str,
    digit: str,
) -> CandidateDataReference:
    return CandidateDataReference(
        candidate_id=candidate_id,
        data_type_id=data_type_id,
        content_digest="sha256:" + digit * 64,
    )


def _operation_call(operation: str) -> OperationCall:
    structure = _fixture_structure(0)
    structure_candidate = Candidate("structure", structure)
    structure_reference = _reference("structure", "protein.structure", "2")
    inputs: dict[str, Any] = {
        "structure_candidates": CandidateCollection(
            "structures",
            "protein.structure",
            (structure_candidate,),
        ),
        "structure_residue_axes": CandidateResolvedResidueAxisAssociations((
            CandidateResolvedResidueAxisAssociation(
                structure_reference,
                resolve_residue_axis(structure),
            ),
        )),
    }
    input_digests = {
        "structure_candidates": InputContentDigests(
            port_type_id="candidate.collection",
            value_content_digests=(_DIGEST,),
            candidate_data=(structure_reference,),
        ),
        "structure_residue_axes": InputContentDigests(
            port_type_id=(
                "structure_transform."
                "candidate_resolved_residue_axis_associations"
            ),
            value_content_digests=(_DIGEST,),
        ),
    }
    if operation == "design":
        return OperationCall(
            inputs=inputs,
            node_parameters={
                "effective_seed": 1603,
                "num_sequences": 1,
                "temperature": 0.1,
                "backbone_noise": 0,
            },
            binding_parameters={},
            input_content_digests=input_digests,
        )

    sequence = Candidate(
        "sequence",
        ProteinSequence(
            "AGSTW",
            ("A:1", "A:2", "B:1", "B:2", "B:3"),
        ),
        (structure_candidate.candidate_id,),
    )
    sequence_reference = _reference("sequence", "protein.sequence", "3")
    inputs["sequence_candidates"] = CandidateCollection(
        "sequences",
        "protein.sequence",
        (sequence,),
    )
    input_digests["sequence_candidates"] = InputContentDigests(
        port_type_id="candidate.collection",
        value_content_digests=(_DIGEST,),
        candidate_data=(sequence_reference,),
    )
    return OperationCall(
        inputs=inputs,
        node_parameters={},
        binding_parameters={},
        input_content_digests=input_digests,
    )


class _Adapter:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.close_count = 0

    def design(self, **_kwargs: Any) -> list[ProteinSequence]:
        if self.fail:
            raise RuntimeError("design failed")
        return [ProteinSequence("AGSTW")]

    def score(self, **_kwargs: Any) -> float:
        if self.fail:
            raise RuntimeError("score failed")
        return 2.75

    def close(self) -> None:
        self.close_count += 1


def _contract_reference(kind: str) -> ExactContractReference:
    return ExactContractReference(kind, f"fixture.{kind}", "1.0.0", _DIGEST)


@pytest.mark.parametrize("operation", ("design", "score"))
@pytest.mark.parametrize("fail", (False, True))
def test_operation_closes_adapter_before_success_or_error_returns(
    operation: str,
    fail: bool,
) -> None:
    adapter = _Adapter(fail=fail)
    if operation == "design":
        implementation = ProteinMPNNDesignImplementation(
            resources=object(),  # type: ignore[arg-type]
            adapter=adapter,  # type: ignore[arg-type]
        )
    else:
        implementation = ProteinMPNNScoreImplementation(
            adapter=adapter,  # type: ignore[arg-type]
            method=_contract_reference("method"),
            metric=_contract_reference("metric"),
        )

    if fail:
        with pytest.raises(RuntimeError, match=f"{operation} failed"):
            implementation.execute(_operation_call(operation))
    else:
        implementation.execute(_operation_call(operation))

    assert adapter.close_count == 1


def test_adapter_close_releases_operation_scoped_model(tmp_path: Path) -> None:
    class Model:
        pass

    adapter = LocalProteinMPNNAdapter(
        environment={},
        resources=object(),  # type: ignore[arg-type]
    )
    model = Model()
    reference = weakref.ref(model)
    resident = (model, object())
    adapter._resident_models[("v_48_020", 0.0, tmp_path)] = resident
    del resident
    del model

    adapter.close()

    assert reference() is None


def test_2emo_rejects_protein_sol_entry_before_proteinmpnn_release() -> None:
    with pytest.raises(RuntimeError, match="before Protein-Sol"):
        proteinmpnn_lifecycle_receipt(
            load_count=1,
            released_before_protein_sol=False,
        )


def test_2emo_receipt_contains_only_the_required_direct_facts() -> None:
    assert proteinmpnn_lifecycle_receipt(
        load_count=1,
        released_before_protein_sol=True,
    ) == {
        "model": "proteinmpnn",
        "load_count": 1,
        "release": "before-protein-sol",
    }
