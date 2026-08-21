"""Model-backed SoluProt acceptance through the public V2 Run seam."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from core import (
    EnvironmentConfiguration,
    ProjectManager,
    V2RunService,
    WorkflowAuthoringService,
    WorkflowDocument,
    WorkflowNodeInstance,
    build_frozen_catalog,
)
from core.workflow_v2 import WorkflowEdge
from tests.acceptance.retained_evidence import retain_service_run


pytestmark = [pytest.mark.acceptance, pytest.mark.local_provider]

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2] / "modules/solubility/fixtures"
)
SEQUENCE = "".join(
    line.strip()
    for line in (FIXTURE_ROOT / "soluprot_input.fasta").read_text().splitlines()
    if not line.startswith(">")
)
SEQUENCES = (SEQUENCE, SEQUENCE[::-1])
EXPECTED = {
    mode: float(
        (FIXTURE_ROOT / f"soluprot_{mode}_expected.csv")
        .read_text()
        .splitlines()[1]
        .rsplit(",", 1)[1]
    )
    for mode in ("full", "no_tm")
}


def _trusted_external_root() -> Path:
    configured = os.environ.get("PROTEIN_WORKBENCH_SOLUPROT_ROOT")
    assert configured is not None, (
        "PROTEIN_WORKBENCH_SOLUPROT_ROOT must select the trusted SoluProt "
        "runtime root"
    )
    root = Path(configured).expanduser()
    assert root.is_absolute()
    return root.resolve()


def _environment(mode: str) -> dict[str, Any]:
    external_root = _trusted_external_root()
    environment: dict[str, Any] = {
        "python_executable": (
            external_root / "var/environments/soluprot/bin/python"
        ),
        "wheel_path": (
            external_root
            / "vendor/packages/soluprot-1.1.0-py3-none-any.whl"
        ),
        "site_packages_root": (
            external_root
            / "var/environments/soluprot/lib/python3.12/site-packages"
        ),
        "usearch_executable": (
            external_root / "var/tools/soluprot/usearch"
        ),
    }
    if mode == "full":
        environment["tmhmm_root"] = (
            external_root / "var/tools/soluprot/tmhmm"
        )
        environment["perl_executable"] = Path("/usr/bin/perl")
    return environment


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


def _run(
    tmp_path: Path,
    *,
    mode: str,
) -> tuple[Any, V2RunService, dict[str, Any], tuple[dict[str, Any], ...]]:
    from modules.solubility.package import MODULE_PACKAGE
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    binding_id = f"solubility.soluprot_{mode}.local"
    catalog = build_frozen_catalog((MODULE_PACKAGE, SOURCE_PACKAGE))
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(f"model-backed SoluProt {mode}")
    authoring = WorkflowAuthoringService(projects, catalog)
    committed = authoring.commit(
        project.id,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=(
                WorkflowNodeInstance(
                    node_id="source",
                    node_type_id=(
                        "contract_test.folding_sequence_batch_source"
                    ),
                    node_type_version="4.0.0",
                    binding_id=(
                        "contract_test.folding_sequence_batch_source.direct"
                    ),
                    binding_version="4.0.0",
                    node_parameters={"sequences": list(SEQUENCES)},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="score",
                    node_type_id="solubility.score_sequence",
                    node_type_version="5.0.0",
                    binding_id=binding_id,
                    binding_version="5.0.0",
                    node_parameters={},
                    binding_parameters={},
                ),
            ),
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
    environment_values = _environment(mode)
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (binding_id, "5.0.0"): {
                    "values": environment_values,
                }
            }
        ),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id=f"model-backed-soluprot-{mode}",
        )
        service.shutdown()
        return (
            catalog,
            service,
            service.projection(project.id, receipt["run_id"]),
            service.public_events(project.id, receipt["run_id"]),
        )
    finally:
        service.shutdown()


@pytest.mark.parametrize(
    ("mode", "expected"),
    tuple(EXPECTED.items()),
)
def test_model_backed_soluprot_golden_methods(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected: float,
) -> None:
    import modules.solubility.adapter as adapter

    recorded: list[dict[str, Any]] = []
    original_invoke = adapter.invoke_soluprot

    def record_and_delegate(**kwargs: Any) -> None:
        staging_directory = kwargs["staging_directory"]
        record = {
            "command": tuple(kwargs["command"]),
            "staging_directory": staging_directory,
            "input_fasta": (
                staging_directory / "input.fasta"
            ).read_text(encoding="ascii"),
        }
        original_invoke(**kwargs)
        record["raw_output"] = (
            staging_directory / "output.csv"
        ).read_bytes()
        recorded.append(record)

    monkeypatch.setattr(adapter, "invoke_soluprot", record_and_delegate)

    catalog, service, projection, events = _run(tmp_path, mode=mode)

    assert projection["status"] == "succeeded", projection
    binding_id = f"solubility.soluprot_{mode}.local"
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "score"
    )
    scores = _decode_output(catalog, service, projection, output)
    source_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "source"
        and output["output_port"] == "sequence_candidates"
    )
    source_candidates = _decode_output(
        catalog,
        service,
        projection,
        source_output,
    )
    assert len(scores.entries) == len(source_candidates.items) == 2
    assert len(recorded) == 1
    record = recorded[0]
    staging_directory = record["staging_directory"]
    environment = _environment(mode)
    site_packages_root = environment["site_packages_root"]
    model_directory = (
        "grad_clf_v1_tc"
        if mode == "full"
        else "grad_clf_v1_tc_notmhmm"
    )
    expected_command = [
        str(environment["python_executable"]),
        "-I",
        "-X",
        f"pycache_prefix={staging_directory / 'bytecode-cache'}",
        "-m",
        "soluprot_core.cli",
        "--i_fa",
        str(staging_directory / "input.fasta"),
        "--o_csv",
        str(staging_directory / "output.csv"),
        "--tmp_dir",
        str(staging_directory / "provider-work"),
        "--model",
        str(
            site_packages_root
            / "data"
            / "models"
            / model_directory
            / "model.json"
        ),
        "--usearch",
        str(environment["usearch_executable"]),
        "--pdb",
        str(
            site_packages_root
            / "data"
            / "Ecoli_xray_nmr_pdb_no_nesg.fa"
        ),
        "--check_unknown",
        "--no_proc",
        "1",
    ]
    if mode == "full":
        expected_command.extend(
            [
                "--tmhmm",
                str(environment["tmhmm_root"] / "bin" / "tmhmm"),
            ]
        )
    else:
        expected_command.append("--no_tmhmm")
    assert record["command"] == tuple(expected_command)
    assert record["input_fasta"] == "".join(
        f">candidate_{index}\n{sequence}\n"
        for index, sequence in enumerate(SEQUENCES)
    )
    sequence_type = catalog.require_port_type(
        "protein.sequence",
        "3.0.0",
    )
    observations_by_subject = {
        (
            observation.subject.candidate_id,
            observation.subject.content_digest,
        ): observation
        for observation in scores.entries
    }
    ordered_observations = tuple(
        observations_by_subject[
            (
                candidate.candidate_id,
                sequence_type.content_digest(candidate.data),
            )
        ]
        for candidate in source_candidates.items
    )
    raw_predictions = adapter.parse_soluprot_output(
        record["raw_output"],
        staged_subjects={
            f"candidate_{index}": observation.subject
            for index, observation in enumerate(ordered_observations)
        },
    )
    assert tuple(
        prediction.subject for prediction in raw_predictions
    ) == tuple(
        observation.subject for observation in ordered_observations
    )
    assert tuple(
        observation.value for observation in ordered_observations
    ) == tuple(
        prediction.soluble_probability for prediction in raw_predictions
    )
    assert ordered_observations[0].value == expected
    assert {
        observation.method.contract_id for observation in scores.entries
    } == {f"solubility.soluprot_{mode}.v1_1_0"}
    assert {
        observation.metric.contract_id for observation in scores.entries
    } == {"solubility.soluprot_probability"}
    observation = scores.entries[0]
    started = {
        (
            event["event"]["invocation_id"],
            event["event"]["engine_identity"],
        )
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"]
        == observation.method.contract_digest
    }
    terminals = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        in {invocation_id for invocation_id, _ in started}
    ]
    assert len(started) == 1
    assert [event["status"] for event in terminals] == ["succeeded"]
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"] == binding_id
        and event["event"]["binding"]["contract_version"] == "5.0.0"
        and event["event"]["conclusion"] == "passing"
    )
    invocation_id = next(iter(started))[0]
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["invocation_id"] == invocation_id
    )
    assert readiness_index < invocation_index
    assert [
        event["event"]["status"]
        for event in events
        if event["event"]["type"] == "run_terminal"
    ] == ["succeeded"]
    retain_service_run(
        f"soluprot-{mode.replace('_', '-')}",
        catalog=catalog,
        service=service,
        projection=projection,
        events=events,
    )
