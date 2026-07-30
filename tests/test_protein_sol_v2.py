"""Public seams for Protein-Sol's calibrated multi-Metric output."""

from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ModulePackageContractCase,
    ProjectManager,
    ReadinessResult,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    parse_workflow_document,
    verify_module_package_contract,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from tests.fixtures.public_v2 import wait_for_service_run_terminal_events


def test_protein_sol_registers_one_exact_method_and_three_metrics() -> None:
    catalog = build_discovered_frozen_catalog()

    method = catalog.require_contract(
        "method",
        "solubility.protein_sol.sequence_prediction_2017",
        "2.0.0",
    )
    binding = catalog.require_contract(
        "binding",
        "solubility.protein_sol.local",
        "2.0.0",
    )
    metrics = {
        metric_id: catalog.require_contract(
            "metric",
            metric_id,
            "2.0.0",
        )
        for metric_id in (
            "solubility.protein_sol_percent",
            "solubility.protein_sol_scaled",
            "solubility.protein_sol_pi",
        )
    }

    assert method.descriptor["source_identity"]["dependency"] == "protein-sol"
    assert method.descriptor["source_identity"]["release"] == "2017-10"
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
    assert binding.descriptor["method"]["contract_id"] == method.contract_id
    assert binding.descriptor["binding_parameters"] == {}
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


def test_protein_sol_parser_preserves_all_upstream_quantities() -> None:
    from modules.solubility.adapter import parse_protein_sol_output

    parsed = parse_protein_sol_output(
        (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419, 0.252, 0.446, 7.130\n"
            b"SEQUENCE PREDICTIONS,>candidate_1,80.162, 0.694, 0.446,11.910\n"
        ),
        expected_count=2,
    )

    assert parsed == [
        {
            "percent_sol": 32.419,
            "scaled_sol": 0.252,
            "population_sol": 0.446,
            "pi": 7.13,
        },
        {
            "percent_sol": 80.162,
            "scaled_sol": 0.694,
            "population_sol": 0.446,
            "pi": 11.91,
        },
    ]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,nan,0.2,0.446,7.0\n",
            "finite three-decimal",
        ),
        (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419,1.001,0.446,7.130\n",
            "outside its declared range",
        ),
        (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419,0.900,0.446,7.130\n",
            "percent and scaled",
        ),
        (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419,0.252,0.445,7.130\n",
            "population calibration",
        ),
        (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>wrong,32.419,0.252,0.446,7.130\n",
            "identity or ordering",
        ),
        (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419,0.252,7.130\n",
            "header",
        ),
        (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n",
            "row count",
        ),
    ],
)
def test_protein_sol_parser_fails_closed(
    payload: bytes,
    message: str,
) -> None:
    from modules.solubility.adapter import parse_protein_sol_output

    with pytest.raises(ValueError, match=message):
        parse_protein_sol_output(payload, expected_count=1)


def test_calibration_context_is_typed_and_round_trips_with_observation() -> None:
    from datatypes import (
        CalibrationObservationContext,
        ExactContractReference,
        ScoreCollection,
        ScoreObservation,
    )

    catalog = build_discovered_frozen_catalog()
    score_type = catalog.require_port_type("score.collection", "2.0.0")
    metric = catalog.require_contract(
        "metric",
        "solubility.protein_sol_scaled",
        "2.0.0",
    )
    method = catalog.require_contract(
        "method",
        "solubility.protein_sol.sequence_prediction_2017",
        "2.0.0",
    )
    context = CalibrationObservationContext(
        calibration_metric="population_scaled_solubility",
        calibration_value=0.446,
        calibration_unit="dimensionless",
        population_id="niwa_non_membrane_2396",
    )
    observation = ScoreObservation(
        candidate_id="candidate-1",
        metric=ExactContractReference(**metric.reference()),
        method=ExactContractReference(**method.reference()),
        context=context,
        value=0.252,
        source_partition="protein_sol_scaled",
    )

    decoded = score_type.decode(
        score_type.encode(ScoreCollection("protein-sol", [observation]))
    )

    assert decoded.entries == [observation]
    assert decoded.entries[0].context.to_public() == {
        "kind": "calibration",
        "calibration_metric": "population_scaled_solubility",
        "calibration_value": 0.446,
        "calibration_unit": "dimensionless",
        "population_id": "niwa_non_membrane_2396",
    }


def test_calibration_context_is_an_exact_selection_selector() -> None:
    from core import (
        SelectionInput,
        SelectionObjective,
        resolve_objective_observations,
    )
    from datatypes import (
        CalibrationObservationContext,
        Candidate,
        CandidateCollection,
        ExactContractReference,
        ProteinSequence,
        ScoreCollection,
        ScoreObservation,
    )

    reference = lambda kind, contract_id: ExactContractReference(
        contract_kind=kind,
        contract_id=contract_id,
        contract_version="2.0.0",
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

    assert SelectionObjective.from_public(objective.to_public()) == objective

    from protein_workbench_public import validate_schema

    validate_schema(
        "#/$defs/ObservationContextSelector",
        objective.context_selector.to_public(),
    )

    observation = ScoreObservation(
        candidate_id="candidate-1",
        metric=objective.metric,
        method=objective.method,
        context=objective.context_selector,
        value=0.252,
        source_partition=objective.source_partition,
    )
    candidates = CandidateCollection(
        collection_id="protein-sol-candidates",
        item_type="protein.sequence",
        items=[
            Candidate(
                candidate_id="candidate-1",
                data=ProteinSequence(
                    sequence="ACDE",
                    residue_ids=["A:1", "A:2", "A:3", "A:4"],
                ),
            )
        ],
    )
    resolved = resolve_objective_observations(
        candidates=candidates,
        collection=ScoreCollection("protein-sol", [observation]),
        objective=objective,
    )

    assert resolved == {"candidate-1": observation}


def _decode_output(catalog: Any, output: dict[str, Any]) -> Any:
    reference = output["port_type"]
    port_type = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return port_type.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": port_type.type_id,
                "port_type_version": port_type.version,
                "value": output["values"][0],
            }
        )
    )


def _run_protein_sol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    sequence: str = "ACDEFGHIKLMNPQRSTVWY",
    provider_payload: bytes | None = None,
    replay: bool = False,
) -> tuple[
    Any,
    tuple[dict[str, Any], ...],
    tuple[tuple[dict[str, Any], ...], ...],
    list[list[str]],
]:
    import modules.solubility.implementation as implementation
    import modules.solubility.package as package
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    monkeypatch.setattr(
        package,
        "protein_sol_readiness",
        lambda environment: ReadinessResult(
            environment.get("fixture_ready") is True,
            proof_source="direct-observation",
            reason_code="protein_sol_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        implementation,
        "validate_protein_sol_environment",
        lambda environment: {
            "resolved_runtime_fingerprint": f"sha256:{'c' * 64}",
        },
    )
    calls: list[list[str]] = []

    def invoke(**kwargs: Any) -> bytes:
        calls.append(list(kwargs["sequences"]))
        return provider_payload or (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419, 0.252,"
            b" 0.446, 7.130\n"
        )

    monkeypatch.setattr(implementation, "invoke_protein_sol", invoke)
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="2.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="2.0.0",
        node_parameters={"sequence": sequence},
        binding_parameters={},
    )
    score = WorkflowNodeInstance(
        node_id="score",
        node_type_id="solubility.score_sequence",
        node_type_version="2.0.0",
        binding_id="solubility.protein_sol.local",
        binding_version="2.0.0",
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
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=WorkflowDocument(
            schema_version="2.0.0",
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
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                ("solubility.protein_sol.local", "2.0.0"): {
                    "values": {
                        "fixture_ready": True,
                        "private_runtime_path": "/must/not/publish",
                    },
                    "safe_fingerprint": "protein-sol-fixture-v1",
                    "invalidation_token": "protein-sol-fixture-v1",
                }
            }
        ),
    )
    projections: list[dict[str, Any]] = []
    event_groups: list[tuple[dict[str, Any], ...]] = []
    try:
        for index in range(2 if replay else 1):
            receipt = service.start(
                project.id,
                workflow_revision=relocked["workflow_revision"],
                compile_id=compiled.public_receipt()["compile_id"],
                client_request_id=f"protein-sol-{index}",
            )
            wait_for_service_run_terminal_events(
                service,
                project.id,
                receipt["run_id"],
            )
            projections.append(
                service.projection(project.id, receipt["run_id"])
            )
            event_groups.append(
                service.public_events(project.id, receipt["run_id"])
            )
    finally:
        service.shutdown()
    return catalog, tuple(projections), tuple(event_groups), calls


def test_protein_sol_one_method_publishes_three_calibrated_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, (projection,), (events,), calls = _run_protein_sol(
        tmp_path,
        monkeypatch,
    )

    assert projection["status"] == "succeeded"
    assert calls == [["ACDEFGHIKLMNPQRSTVWY"]]
    output = next(
        item for item in projection["outputs"] if item["node_id"] == "score"
    )
    scores = _decode_output(catalog, output)
    assert len(scores.entries) == 3
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
        entry.metric.contract_id: entry.context.to_public()
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
        and event["event"]["engine_identity"].startswith(
            "protein-sol.sequence-prediction-2017/"
        )
    ]
    assert len(invocations) == 1
    assert "/must/not/publish" not in str((projection, events))


def test_protein_sol_cache_replay_preserves_metrics_and_calibration_without_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, projections, event_groups, calls = _run_protein_sol(
        tmp_path,
        monkeypatch,
        replay=True,
    )

    first, replayed = projections
    assert first["status"] == replayed["status"] == "succeeded"
    first_scores = _decode_output(
        catalog,
        next(item for item in first["outputs"] if item["node_id"] == "score"),
    )
    replayed_scores = _decode_output(
        catalog,
        next(
            item for item in replayed["outputs"] if item["node_id"] == "score"
        ),
    )
    assert replayed_scores == first_scores
    assert calls == [["ACDEFGHIKLMNPQRSTVWY"]]
    assert not any(
        event["event"]["type"] == "engine_invocation_started"
        for event in event_groups[1]
    )
    assert {
        item["resolution"] for item in replayed["node_dispositions"]
    } == {"cache_replayed"}


def test_protein_sol_invalid_output_publishes_nothing_and_does_not_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, projections, event_groups, calls = _run_protein_sol(
        tmp_path,
        monkeypatch,
        provider_payload=(
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419,0.252,"
            b"0.445,7.130\n"
        ),
        replay=True,
    )

    assert [projection["status"] for projection in projections] == [
        "failed",
        "failed",
    ]
    assert calls == [
        ["ACDEFGHIKLMNPQRSTVWY"],
        ["ACDEFGHIKLMNPQRSTVWY"],
    ]
    assert all(
        not any(
            output["node_id"] == "score"
            for output in projection["outputs"]
        )
        for projection in projections
    )
    events = event_groups[0]
    invocation_id = next(
        event["event"]["invocation_id"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            "protein-sol.sequence-prediction-2017/"
        )
    )
    terminals = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"] == invocation_id
    ]
    assert [terminal["status"] for terminal in terminals] == ["succeeded"]


def test_protein_sol_invalid_sequence_fails_before_engine_invocation() -> None:
    from modules.solubility.adapter import validate_protein_sol_sequences

    with pytest.raises(
        ValueError,
        match="non-empty canonical protein sequences",
    ):
        validate_protein_sol_sequences(["ACDEFGHIKLMNPQRSTVWX"])


def test_protein_sol_exact_source_tree_controls_readiness(
    tmp_path: Path,
) -> None:
    from modules.solubility.adapter import (
        PROTEIN_SOL_SOURCE_SHA256,
        configured_protein_sol_runtime_fingerprint,
        protein_sol_readiness,
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
            "resolved_runtime_fingerprint": (
                configured_protein_sol_runtime_fingerprint()
            ),
        }
    )

    assert conclusion == ReadinessResult(
        False,
        proof_source="direct-observation",
        reason_code="protein_sol_runtime_unavailable",
    )


def test_protein_sol_passes_shared_contract_test_kit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.solubility.implementation as implementation
    import modules.solubility.package as package
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    monkeypatch.setattr(
        package,
        "protein_sol_readiness",
        lambda environment: ReadinessResult(
            environment.get("fixture_ready") is True,
            proof_source="direct-observation",
            reason_code="protein_sol_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        package,
        "soluprot_readiness",
        lambda environment, *, mode: ReadinessResult(
            environment.get("fixture_ready") is True,
            proof_source="direct-observation",
            reason_code=f"soluprot_{mode}_runtime_unavailable",
        ),
    )
    monkeypatch.setattr(
        implementation,
        "validate_protein_sol_environment",
        lambda environment: {
            "resolved_runtime_fingerprint": f"sha256:{'d' * 64}",
        },
    )
    monkeypatch.setattr(
        implementation,
        "invoke_protein_sol",
        lambda **kwargs: (
            b"HEADERS PREDICTIONS LINE,ID,percent-sol,scaled-sol,"
            b"population-sol,pI\n"
            b"SEQUENCE PREDICTIONS,>candidate_0,32.419,0.252,"
            b"0.446,7.130\n"
        ),
    )
    monkeypatch.setattr(
        implementation,
        "validate_soluprot_environment",
        lambda environment, *, mode: {
            "resolved_runtime_fingerprint": f"sha256:{'e' * 64}",
            "mode": mode,
        },
    )
    monkeypatch.setattr(
        implementation,
        "invoke_soluprot",
        lambda **kwargs: (
            b"runtime_id,fa_id,soluble\n"
            + (
                b"0,candidate_0,0.331\n"
                if kwargs["mode"] == "full"
                else b"0,candidate_0,0.3465\n"
            )
        ),
    )
    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="2.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="2.0.0",
        node_parameters={"sequence": "ACDEFGHIKLMNPQRSTVWY"},
        binding_parameters={},
    )
    report = verify_module_package_contract(
        MODULE_PACKAGE,
        execution_cases=tuple(
            ModulePackageContractCase(
                case_id=case_id,
                node_type_id="solubility.score_sequence",
                node_type_version="2.0.0",
                binding_id=binding_id,
                binding_version="2.0.0",
                node_parameters={},
                binding_parameters={},
                environment_values={
                    "fixture_ready": True,
                    "private_runtime_path": "/secret/protein-sol",
                },
                safe_environment_fingerprint=f"{case_id}-fixture-v1",
                invalidation_token=f"{case_id}-fixture-v1",
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
