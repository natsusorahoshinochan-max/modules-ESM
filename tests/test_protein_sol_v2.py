"""Public seams for Protein-Sol's calibrated multi-Metric output."""

from tests.support.ledger import public_run_events, public_run_projection

from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from protein_workbench_public.scientific_codec import (
    encode_observation_context,
)

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.operation import (
    ReadinessResult,
)
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import V2RunService
from tests.support.result_store import result_store
from tests.support.contract_test_kit import (
    ModulePackageContractCase,
    verify_module_package_contract,
)
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.workflow.document import WorkflowEdge
from tests.fixtures.public_v2 import wait_for_service_run_terminal_events


def _prepare_soluprot_fixture(**kwargs: Any) -> tuple[tuple[str, ...], Path]:
    staging_directory = kwargs["staging_directory"]
    (staging_directory / "input.fasta").write_text(
        "".join(
            f">candidate_{index}\n{sequence}\n"
            for index, sequence in enumerate(kwargs["sequences"])
        )
    )
    mode_flag = "--tmhmm" if kwargs["mode"] == "full" else "--no_tmhmm"
    return (
        ("fixture-soluprot", mode_flag),
        staging_directory / "output.csv",
    )


def _prepare_protein_sol_fixture(
    **kwargs: Any,
) -> tuple[tuple[str, ...], Path]:
    staging_directory = kwargs["staging_directory"]
    (staging_directory / "input.fasta").write_text(
        "".join(
            f">candidate_{index}\n{sequence}\n"
            for index, sequence in enumerate(kwargs["sequences"])
        )
    )
    return (
        ("fixture-protein-sol",),
        staging_directory / "seq_prediction.txt",
    )


def _soluprot_admitted_environment(
    *,
    private_runtime_path: str,
    include_tm: bool,
) -> dict[str, Any]:
    private_root = Path(private_runtime_path)
    environment = {
        "python_executable": private_root / "python",
        "wheel_path": private_root / "soluprot.whl",
        "site_packages_root": private_root / "site-packages",
        "usearch_executable": private_root / "usearch",
    }
    if include_tm:
        environment.update({
            "tmhmm_root": private_root / "tmhmm",
            "perl_executable": private_root / "perl",
        })
    return environment


def _protein_sol_admitted_environment(
    *,
    private_runtime_path: str,
) -> dict[str, Any]:
    private_root = Path(private_runtime_path)
    return {
        "source_root": private_root / "source",
        "bash_executable": private_root / "bash",
        "perl_executable": private_root / "perl",
    }


def test_local_protein_sol_adapter_uses_readiness_admitted_environment_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility.adapter as adapter
    from datatypes.candidate import CandidateDataReference
    from datatypes.sequence import ProteinSequence
    from modules.solubility.adapter import SequenceSolubilitySubject

    events: list[str] = []
    source_root = tmp_path / "source"
    source_root.mkdir()
    for relative in adapter.PROTEIN_SOL_SOURCE_SHA256:
        (source_root / relative).write_bytes(relative.encode("ascii"))
    staging_directory = tmp_path / "staging"
    staging_directory.mkdir()
    bash_executable = tmp_path / "bash"

    class Resources:
        @contextmanager
        def temporary_directory(self, *, prefix: str):
            assert prefix == "protein-sol-"
            yield staging_directory

        @contextmanager
        def engine_invocation(
            self,
            *,
            engine_role: str,
        ):
            assert engine_role == "protein_sol_sequence_prediction"
            events.append("engine-started")
            yield "invocation-1"
            events.append("engine-succeeded")

    monkeypatch.setattr(
        adapter,
        "validate_protein_sol_environment",
        lambda environment: (_ for _ in ()).throw(
            AssertionError("readiness validator repeated during operation")
        ),
    )

    def invoke(**kwargs: Any) -> None:
        assert kwargs["command"] == (
            str(bash_executable),
            "multiple_prediction_wrapper_export.sh",
            "input.fasta",
        )
        assert (
            staging_directory / "multiple_prediction_wrapper_export.sh"
        ).read_bytes() == b"multiple_prediction_wrapper_export.sh"
        events.append("provider-invoked")
        output_path = kwargs["staging_directory"] / "seq_prediction.txt"
        output_path.write_bytes(
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419,0.252,"
            b"0.446,7.130\n"
        )

    monkeypatch.setattr(adapter, "invoke_protein_sol", invoke)
    local = adapter.LocalProteinSolAdapter(
        environment={
            "source_root": source_root,
            "bash_executable": bash_executable,
            "perl_executable": tmp_path / "perl",
        },
        resources=Resources(),
    )

    subject = CandidateDataReference(
        "candidate-a",
        "protein.sequence",
        f"sha256:{'a' * 64}",
    )
    predictions = local.predict(
        (
            SequenceSolubilitySubject(
                subject,
                ProteinSequence("ACDEFGHIKLMNPQRSTVWYA"),
            ),
        )
    )

    assert predictions == (
        adapter.ProteinSolPrediction(
            subject=subject,
            percent_soluble_fraction=32.419,
            scaled_soluble_fraction=0.252,
            isoelectric_point=7.13,
        ),
    )
    assert events == [
        "engine-started",
        "provider-invoked",
        "engine-succeeded",
    ]
    with pytest.raises(FrozenInstanceError):
        predictions[0].scaled_soluble_fraction = 0.5


def test_protein_sol_registers_one_exact_method_and_three_metrics() -> None:
    from modules.solubility.package import MODULE_PACKAGE

    catalog = build_frozen_catalog((MODULE_PACKAGE,))

    method = catalog.require_contract(
        "method",
        "solubility.protein_sol.sequence_prediction_2017",
        "3.0.0",
    )
    binding = catalog.require_contract(
        "binding",
        "solubility.protein_sol.local",
        "5.0.0",
    )
    metrics = {
        metric_id: catalog.require_contract(
            "metric",
            metric_id,
            "2.1.0",
        )
        for metric_id in (
            "solubility.protein_sol_percent",
            "solubility.protein_sol_scaled",
            "solubility.protein_sol_pi",
        )
    }

    assert method.descriptor["source_identity"] == {
        "kind": "official_release_archive",
        "provider": "Protein-Sol",
        "release": "2017-10",
        "official_download_url": (
            "https://protein-sol.manchester.ac.uk/cgi-bin/utilities/"
            "download_sequence_code.php"
        ),
        "download_url_role": "locator_only",
        "archive_sha256": (
            "4df32c61fca53adcb2394a528babd1ad85cb5c551bf7bd1c56d134097fb2b1b8"
        ),
        "source_files_sha256": {
            "fasta_seq_reformat_export.pl": (
                "ee671b4121e343e0dd660377a8204c2e5058fcf9185e8ea629b2c3c64562a8e9"
            ),
            "multiple_prediction_wrapper_export.sh": (
                "a7e7d0137508f34734584a6b37157e980bed769f400032f8ecb36949d17dc232"
            ),
            "profiles_gather_export.pl": (
                "ad1aadee73db9b828ed4e87b27bb75191cf48b4934cf8ab3855c80740b674eac"
            ),
            "seq_compositions_perc_pipeline_export.pl": (
                "8e8888220984b77c472333fa57750585d33e7aff93d44cb6b090fccd728d87cb"
            ),
            "seq_props_ALL_export.pl": (
                "f20eac44b526f9b694c6371b06a3a4a9c080d14da1241cb785d77230783efa15"
            ),
            "seq_reference_data.txt": (
                "6943cd600741d5d22b7518b8be40f2850bfa5586e96d637de3db688c7337d1f0"
            ),
            "server_prediction_seq_export.pl": (
                "80f8554e43d605c10a6feea983c222099869119b0a9d73411c5a1b2dd68c4b4d"
            ),
            "ss_propensities.txt": (
                "3c634b252ed83ffd363e6b0936e95813584facddb399f0fcc6769710755fa33f"
            ),
        },
    }
    assert method.descriptor["algorithm_identity"][
        "scientific_feature_count"
    ] == 35
    assert method.descriptor["algorithm_identity"][
        "raw_composition_column_count"
    ] == 36
    assert method.descriptor["algorithm_identity"][
        "raw_bookkeeping_column"
    ] == "totperc"
    assert method.descriptor["featurization_identity"]["sequence_alphabet"] == (
        "ACDEFGHIKLMNPQRSTVWY"
    )
    assert method.descriptor["featurization_identity"][
        "minimum_sequence_length"
    ] == 21
    assert binding.descriptor["method"]["contract_id"] == method.contract_id
    assert binding.descriptor["binding_parameters"] == {}
    assert binding.descriptor["route_behavior"]["parameters"][
        "response_subject_join"
    ] == "staged-fasta-identity"
    assert len(binding.descriptor["produced_observations"]) == 3
    assert {
        item["metric"]["contract_id"]
        for item in binding.descriptor["produced_observations"]
    } == set(metrics)
    assert {
        tuple(sorted(item["context_profile"].items()))
        for item in binding.descriptor["produced_observations"]
    } == {
        (
            ("calibration_metric", "population_scaled_solubility"),
            ("calibration_unit", "dimensionless"),
            ("calibration_value", 0.446),
            ("kind", "calibration"),
            ("population_id", "niwa_non_membrane_2396"),
        ),
        (("kind", "intrinsic"),),
    }

    assert metrics["solubility.protein_sol_percent"].descriptor[
        "canonical_range"
    ] == {"minimum": 5.208, "maximum": 113.241}
    assert metrics["solubility.protein_sol_percent"].descriptor["unit"] == (
        "percent_soluble_fraction"
    )
    assert metrics["solubility.protein_sol_scaled"].descriptor[
        "canonical_range"
    ] == {"minimum": 0, "maximum": 1}
    assert metrics["solubility.protein_sol_scaled"].descriptor["unit"] == (
        "dimensionless"
    )
    assert metrics["solubility.protein_sol_pi"].descriptor[
        "canonical_range"
    ] == {"minimum": 1, "maximum": 14}
    assert metrics["solubility.protein_sol_pi"].descriptor["unit"] == "ph"
    assert metrics["solubility.protein_sol_pi"].descriptor["direction"] == (
        "target"
    )


def test_protein_sol_requires_no_core_provider_special_case() -> None:
    project_root = Path(__file__).resolve().parent.parent
    core_source = "\n".join(
        path.read_text()
        for path in sorted((project_root / "core").glob("*.py"))
    ).lower()

    assert "protein_sol" not in core_source
    assert "protein-sol" not in core_source


def test_protein_sol_adapter_translation_preserves_exact_subject_identity(
) -> None:
    from datatypes.candidate import CandidateDataReference
    from modules.solubility.adapter import (
        ProteinSolPrediction,
        parse_protein_sol_output,
    )

    references = (
        CandidateDataReference(
            "candidate-a",
            "protein.sequence",
            f"sha256:{'a' * 64}",
        ),
        CandidateDataReference(
            "candidate-b",
            "protein.sequence",
            f"sha256:{'b' * 64}",
        ),
    )
    parsed = parse_protein_sol_output(
        (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419, 0.252, 0.446, 7.130\n"
            b"SEQUENCE PREDICTIONS,>candidate_1,80.162, 0.694, 0.446,11.910\n"
        ),
        staged_subjects={
            "candidate_0": references[0],
            "candidate_1": references[1],
        },
    )

    assert parsed == (
        ProteinSolPrediction(
            subject=references[0],
            percent_soluble_fraction=32.419,
            scaled_soluble_fraction=0.252,
            isoelectric_point=7.13,
        ),
        ProteinSolPrediction(
            subject=references[1],
            percent_soluble_fraction=80.162,
            scaled_soluble_fraction=0.694,
            isoelectric_point=11.91,
        ),
    )


def test_calibration_context_is_typed_and_round_trips_with_observation() -> None:
    from datatypes.candidate import CandidateDataReference
    from datatypes.exact_reference import ExactContractReference
    from datatypes.observation import (
        CalibrationObservationContext,
        ScoreCollection,
        ScoreObservation,
    )

    from modules.solubility.package import MODULE_PACKAGE

    catalog = build_frozen_catalog((MODULE_PACKAGE,))
    score_type = catalog.require_port_type("score.collection", "5.0.0")
    metric = catalog.require_contract(
        "metric",
        "solubility.protein_sol_scaled",
        "2.1.0",
    )
    method = catalog.require_contract(
        "method",
        "solubility.protein_sol.sequence_prediction_2017",
        "3.0.0",
    )
    context = CalibrationObservationContext(
        calibration_metric="population_scaled_solubility",
        calibration_value=0.446,
        calibration_unit="dimensionless",
        population_id="niwa_non_membrane_2396",
    )
    observation = ScoreObservation(
        subject=CandidateDataReference(
            candidate_id="candidate-1",
            data_type_id="protein.sequence",
            content_digest=f"sha256:{'1' * 64}",
        ),
        metric=ExactContractReference(**metric.reference()),
        method=ExactContractReference(**method.reference()),
        context=context,
        value=0.252,
        source_partition="protein_sol_scaled",
    )

    decoded = score_type.decode(
        score_type.encode(ScoreCollection("protein-sol", [observation]))
    )

    assert decoded.entries == (observation,)
    assert encode_observation_context(decoded.entries[0].context) == {
        "kind": "calibration",
        "calibration_metric": "population_scaled_solubility",
        "calibration_value": 0.446,
        "calibration_unit": "dimensionless",
        "population_id": "niwa_non_membrane_2396",
    }


def test_calibration_context_is_an_exact_selection_selector() -> None:
    from core.scoring.selection import (
        SelectionInput,
        SelectionObjective,
        resolve_objective_observations,
        ResolvedSelectionObjective,
        ResolvedUtilityTransform,
    )
    from core.parameters import AdmittedParameterValues
    from tests.support.output_admission import admit_fixture_port
    from datatypes.candidate import (
        Candidate,
        CandidateCollection,
        CandidateDataReference,
    )
    from datatypes.exact_reference import ExactContractReference
    from datatypes.observation import (
        CalibrationObservationContext,
        ScoreCollection,
        ScoreObservation,
    )
    from datatypes.sequence import ProteinSequence

    reference = lambda kind, contract_id: ExactContractReference(
        contract_kind=kind,
        contract_id=contract_id,
        contract_version="2.1.0",
        contract_digest=f"sha256:{'a' * 64}",
    )
    objective = SelectionObjective(
        objective_id="protein-sol-scaled",
        candidate_input=SelectionInput("source", "sequence_candidates"),
        score_collection_input=SelectionInput("score", "scores"),
        source_partition="protein_sol_scaled",
        metric=reference("metric", "solubility.protein_sol_scaled"),
        method=reference(
            "method",
            "solubility.protein_sol.sequence_prediction_2017",
        ),
        context_selector=CalibrationObservationContext(
            calibration_metric="population_scaled_solubility",
            calibration_value=0.446,
            calibration_unit="dimensionless",
            population_id="niwa_non_membrane_2396",
        ),
        utility_transform=reference(
            "utility_transform",
            "core.linear_increasing",
        ),
        utility_parameters={},
        weight=1.0,
        match_cardinality="exactly_one",
        missing_policy="error",
    )

    from protein_workbench_public.selection_codec import (
        selection_objective_from_public,
        selection_objective_to_public,
    )

    assert selection_objective_from_public(
        selection_objective_to_public(objective)
    ) == objective

    from protein_workbench_public import validate_schema

    validate_schema(
        "#/$defs/ObservationContextSelector",
        encode_observation_context(objective.context_selector),
    )

    candidates = CandidateCollection(
        collection_id="protein-sol-candidates",
        item_type="protein.sequence",
        items=[
            Candidate(
                candidate_id="candidate-1",
                data=ProteinSequence(
                    sequence="ACDEFGHIKLMNPQRSTVWYA",
                ),
            )
        ],
    )
    from modules.solubility.package import MODULE_PACKAGE

    catalog = build_frozen_catalog((MODULE_PACKAGE,))
    port_types = {
        definition.type_id: definition for definition in catalog.port_types
    }
    admitted_candidates = admit_fixture_port(
        port_type=catalog.require_port_type("candidate.collection", "4.0.0"),
        multiplicity="one",
        values=(candidates,),
        candidate_data_port_types=port_types,
    )
    observation = ScoreObservation(
        subject=admitted_candidates.candidate_data[0],
        metric=objective.metric,
        method=objective.method,
        context=objective.context_selector,
        value=0.252,
        source_partition=objective.source_partition,
    )
    admitted_scores = admit_fixture_port(
        port_type=catalog.require_port_type("score.collection", "5.0.0"),
        multiplicity="one",
        values=(ScoreCollection("protein-sol", [observation]),),
        candidate_data_port_types=port_types,
    )
    resolved_objective = ResolvedSelectionObjective(
        objective_id=objective.objective_id,
        candidate_input=objective.candidate_input,
        score_collection_input=objective.score_collection_input,
        source_partition=objective.source_partition,
        metric=objective.metric,
        method=objective.method,
        context_selector=objective.context_selector,
        utility=ResolvedUtilityTransform(
            reference=objective.utility_transform,
            parameters=AdmittedParameterValues({}),
            apply=lambda value, _parameters: value,
        ),
        weight=objective.weight,
        match_cardinality=objective.match_cardinality,
        missing_policy=objective.missing_policy,
    )
    resolved = resolve_objective_observations(
        candidates=admitted_candidates.value,
        collection=admitted_scores.value,
        objective=resolved_objective,
        out_of_scope_policy="ignore",
        duplicate_policy="deduplicate_identical",
    )

    assert resolved == {"candidate-1": observation}


def _decode_output(
    catalog: Any,
    service: V2RunService,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> Any:
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def _run_protein_sol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    sequence: str = "ACDEFGHIKLMNPQRSTVWYA",
    replay: bool = False,
) -> tuple[
    Any,
    V2RunService,
    tuple[dict[str, Any], ...],
    tuple[tuple[dict[str, Any], ...], ...],
    list[list[str]],
]:
    import modules.solubility.adapter as adapter
    import modules.solubility.package as package
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    monkeypatch.setattr(
        package,
        "protein_sol_readiness",
        lambda environment: ReadinessResult(
            True,
            proof_source="direct-observation",
            reason_code="protein_sol_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        adapter,
        "_prepare_protein_sol_invocation",
        _prepare_protein_sol_fixture,
    )
    calls: list[list[str]] = []

    def invoke(**kwargs: Any) -> None:
        calls.append(
            [
                line
                for line in (
                    kwargs["staging_directory"] / "input.fasta"
                ).read_text().splitlines()
                if not line.startswith(">")
            ]
        )
        payload = (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419, 0.252,"
            b" 0.446, 7.130\n"
        )
        output_path = kwargs["staging_directory"] / "seq_prediction.txt"
        output_path.write_bytes(payload)

    monkeypatch.setattr(adapter, "invoke_protein_sol", invoke)
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="4.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="4.0.0",
        node_parameters={"sequence": sequence},
        binding_parameters={},
    )
    score = WorkflowNodeInstance(
        node_id="score",
        node_type_id="solubility.score_sequence",
        node_type_version="5.0.0",
        binding_id="solubility.protein_sol.local",
        binding_version="5.0.0",
        node_parameters={},
        binding_parameters={},
    )
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create("Protein-Sol")
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=(source, score),
            edges=(
                WorkflowEdge(
                    "source",
                    "sequence_candidates",
                    "score",
                    "sequence_candidates",
                ),
            ),
            contract_lock=(),
        ),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            admit_environment_configuration(
                catalog,
                {
                    ("solubility.protein_sol.local", "5.0.0"): {
                        "values": _protein_sol_admitted_environment(
                            private_runtime_path="/must/not/publish"
                        ),
                    }
                },
            ),
            result_store(projects),
        ),
        result_store(projects),
    )
    projections: list[dict[str, Any]] = []
    event_groups: list[tuple[dict[str, Any], ...]] = []
    try:
        for index in range(2 if replay else 1):
            receipt = service.start(
                project.id,
                workflow_commit_id=committed.workflow_commit_id,
                client_request_id=f"protein-sol-{index}",
            )
            wait_for_service_run_terminal_events(
                service,
                project.id,
                receipt["run_id"],
            )
            projections.append(
                public_run_projection(service, project.id, receipt["run_id"])
            )
            event_groups.append(
                public_run_events(service, project.id, receipt["run_id"])
            )
    finally:
        service.shutdown()
    return catalog, service, tuple(projections), tuple(event_groups), calls


def test_protein_sol_one_method_publishes_three_calibrated_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, service, (projection,), (events,), calls = _run_protein_sol(
        tmp_path,
        monkeypatch,
    )

    assert projection["status"] == "succeeded"
    assert calls == [["ACDEFGHIKLMNPQRSTVWYA"]]
    output = next(
        item for item in projection["outputs"] if item["node_id"] == "score"
    )
    scores = _decode_output(catalog, service, projection, output)
    source_output = next(
        item
        for item in projection["outputs"]
        if item["node_id"] == "source"
        and item["output_port"] == "sequence_candidates"
    )
    candidates = _decode_output(catalog, service, projection, source_output)
    candidate = candidates.items[0]
    expected_digest = catalog.require_port_type(
        "protein.sequence",
        "3.0.0",
    ).content_digest(candidate.data)
    assert len(scores.entries) == 3
    assert {
        (
            entry.subject.candidate_id,
            entry.subject.data_type_id,
            entry.subject.content_digest,
        )
        for entry in scores.entries
    } == {
        (candidate.candidate_id, "protein.sequence", expected_digest)
    }
    assert {
        entry.metric.contract_id: entry.value
        for entry in scores.entries
    } == {
        "solubility.protein_sol_percent": 32.419,
        "solubility.protein_sol_scaled": 0.252,
        "solubility.protein_sol_pi": 7.13,
    }
    assert {
        entry.source_partition for entry in scores.entries
    } == {
        "protein_sol_percent",
        "protein_sol_scaled",
        "protein_sol_pi",
    }
    assert {
        entry.method.contract_id for entry in scores.entries
    } == {"solubility.protein_sol.sequence_prediction_2017"}
    contexts = {
        entry.metric.contract_id: encode_observation_context(entry.context)
        for entry in scores.entries
    }
    assert contexts["solubility.protein_sol_percent"] == {
        "kind": "calibration",
        "calibration_metric": "population_scaled_solubility",
        "calibration_value": 0.446,
        "calibration_unit": "dimensionless",
        "population_id": "niwa_non_membrane_2396",
    }
    assert contexts["solubility.protein_sol_scaled"] == {
        "kind": "calibration",
        "calibration_metric": "population_scaled_solubility",
        "calibration_value": 0.446,
        "calibration_unit": "dimensionless",
        "population_id": "niwa_non_membrane_2396",
    }
    assert contexts["solubility.protein_sol_pi"] == {
        "kind": "intrinsic",
    }
    invocations = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"]
        == scores.entries[0].method.contract_digest
    ]
    assert len(invocations) == 1
    assert "/must/not/publish" not in str((projection, events))


def test_protein_sol_binding_factory_injects_one_exact_local_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility.adapter as adapter
    import modules.solubility.package as package

    constructed: list[tuple[Any, Any]] = []
    exact_adapter = adapter.LocalProteinSolAdapter

    def build_adapter(**kwargs: Any) -> Any:
        constructed.append((kwargs["environment"], kwargs["resources"]))
        return exact_adapter(**kwargs)

    monkeypatch.setattr(package, "LocalProteinSolAdapter", build_adapter)

    _, _, (projection,), _, _ = _run_protein_sol(tmp_path, monkeypatch)

    assert projection["status"] == "succeeded"
    assert len(constructed) == 1


def test_protein_sol_rejects_twenty_residues_before_provider_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, (projection,), _, calls = _run_protein_sol(
        tmp_path,
        monkeypatch,
        sequence="ACDEFGHIKLMNPQRSTVWY",
    )

    assert projection["status"] == "failed"
    assert calls == []


@pytest.mark.parametrize(
    "sequence",
    (
        None,
        "ACDEFGHIKLMNPQRSTVWX",
        "ACDEFGHIKLMNPQRSTVWY",
    ),
)
def test_protein_sol_operation_owns_its_sequence_population(
    sequence: str | None,
) -> None:
    from datatypes.candidate import (
        Candidate,
        CandidateCollection,
    )
    from datatypes.sequence import ProteinSequence
    from modules.solubility.implementation import ProteinSolImplementation
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.scientific_operation import (
        operation_call,
        operation_context,
    )

    class TrustingAdapter:
        @staticmethod
        def predict(sequences: Any) -> tuple[Any, ...]:
            raise AssertionError("invalid Method input reached the Adapter")

    catalog = build_frozen_catalog((MODULE_PACKAGE,))
    context = operation_context(
        catalog,
        "solubility.protein_sol.local",
        object(),
        binding_version="5.0.0",
    )
    operation = ProteinSolImplementation(
        adapter=TrustingAdapter(),
        method=context.method,
        produced_observations=context.produced_observations,
    )
    call = operation_call(
        catalog=catalog,
        binding_id="solubility.protein_sol.local",
        binding_version="5.0.0",
        inputs={
            "sequence_candidates": CandidateCollection(
                "protein-sol-method-inputs",
                "protein.sequence",
                (
                    ()
                    if sequence is None
                    else (Candidate("candidate-1", ProteinSequence(sequence)),)
                ),
            )
        },
    )

    with pytest.raises(
        ValueError,
        match="canonical protein sequences of at least 21 residues",
    ):
        operation.execute(call)


def test_protein_sol_cache_replay_preserves_metrics_and_calibration_without_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, service, projections, event_groups, calls = _run_protein_sol(
        tmp_path,
        monkeypatch,
        replay=True,
    )

    first, replayed = projections
    assert first["status"] == replayed["status"] == "succeeded"
    first_scores = _decode_output(
        catalog,
        service,
        first,
        next(item for item in first["outputs"] if item["node_id"] == "score"),
    )
    replayed_scores = _decode_output(
        catalog,
        service,
        replayed,
        next(
            item for item in replayed["outputs"] if item["node_id"] == "score"
        ),
    )
    assert replayed_scores == first_scores
    assert calls == [["ACDEFGHIKLMNPQRSTVWYA"]]
    assert not any(
        event["event"]["type"] == "engine_invocation_started"
        for event in event_groups[1]
    )
    assert {
        item["resolution"] for item in replayed["node_dispositions"]
    } == {"cache_replayed"}


def test_protein_sol_readiness_requires_the_exact_scientific_sources(
    tmp_path: Path,
) -> None:
    from modules.solubility.adapter import (
        PROTEIN_SOL_SOURCE_SHA256,
        protein_sol_readiness,
        validate_protein_sol_environment,
    )

    source_root = tmp_path / "protein-sol"
    source_root.mkdir()
    for relative in PROTEIN_SOL_SOURCE_SHA256:
        (source_root / relative).write_bytes(b"stale source")
    conclusion = protein_sol_readiness(
        {
            "source_root": source_root,
            "bash_executable": Path("/bin/bash"),
            "perl_executable": Path("/usr/bin/perl"),
        }
    )

    assert conclusion == ReadinessResult(
        False,
        proof_source="direct-observation",
        reason_code="protein_sol_runtime_unavailable",
    )
    with pytest.raises(
        RuntimeError,
        match="configured Protein-Sol asset identity changed",
    ):
        validate_protein_sol_environment(
            {
                "source_root": source_root,
                "bash_executable": Path("/bin/bash"),
                "perl_executable": Path("/usr/bin/perl"),
            }
        )


def test_protein_sol_passes_shared_contract_test_kit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility.adapter as adapter
    import modules.solubility.package as package
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    monkeypatch.setattr(
        package,
        "protein_sol_readiness",
        lambda environment: ReadinessResult(
            True,
            proof_source="direct-observation",
            reason_code="protein_sol_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        package,
        "soluprot_readiness",
        lambda environment, *, mode: ReadinessResult(
            True,
            proof_source="direct-observation",
            reason_code=f"soluprot_{mode}_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        adapter,
        "_prepare_protein_sol_invocation",
        _prepare_protein_sol_fixture,
    )

    def invoke_protein_sol_fixture(**kwargs: Any) -> None:
        output_path = kwargs["staging_directory"] / "seq_prediction.txt"
        output_path.write_bytes(
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419,0.252,"
            b"0.446,7.130\n"
        )

    monkeypatch.setattr(
        adapter,
        "invoke_protein_sol",
        invoke_protein_sol_fixture,
    )
    monkeypatch.setattr(
        adapter,
        "_prepare_soluprot_invocation",
        _prepare_soluprot_fixture,
    )

    def invoke_soluprot_fixture(**kwargs: Any) -> None:
        output_path = kwargs["staging_directory"] / "output.csv"
        mode = (
            "no_tm"
            if "--no_tmhmm" in kwargs["command"]
            else "full"
        )
        output_path.write_bytes(
            b"runtime_id,fa_id,soluble\n"
            + (
                b"0,candidate_0,0.331\n"
                if mode == "full"
                else b"0,candidate_0,0.3465\n"
            )
        )

    monkeypatch.setattr(
        adapter,
        "invoke_soluprot",
        invoke_soluprot_fixture,
    )
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="4.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="4.0.0",
        node_parameters={"sequence": "ACDEFGHIKLMNPQRSTVWYA"},
        binding_parameters={},
    )
    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=tuple(
            ModulePackageContractCase(
                case_id=case_id,
                node_type_id="solubility.score_sequence",
                node_type_version="5.0.0",
                binding_id=binding_id,
                binding_version="5.0.0",
                node_parameters={},
                binding_parameters={},
                environment_values=(
                    _protein_sol_admitted_environment(
                        private_runtime_path="/secret/protein-sol"
                    )
                    if binding_id == "solubility.protein_sol.local"
                    else _soluprot_admitted_environment(
                        private_runtime_path="/secret/protein-sol",
                        include_tm=binding_id.endswith("full.local"),
                    )
                ),
                workflow_nodes=(source,),
                workflow_edges=(
                    WorkflowEdge(
                        "source",
                        "sequence_candidates",
                        "contract-test-node",
                        "sequence_candidates",
                    ),
                ),
                expected_observation_counts={"scores": expected_count},
                forbidden_public_fragments=("/secret/protein-sol",),
            )
            for case_id, binding_id, expected_count in (
                (
                    "soluprot-full",
                    "solubility.soluprot_full.local",
                    1,
                ),
                (
                    "soluprot-no-tm",
                    "solubility.soluprot_no_tm.local",
                    1,
                ),
                (
                    "protein-sol-calibrated-metrics",
                    "solubility.protein_sol.local",
                    3,
                ),
            )
        ),
        supporting_registrations=(SOURCE_PACKAGE,),
        work_root=tmp_path,
    )

    assert [case.status for case in report.case_reports] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]
