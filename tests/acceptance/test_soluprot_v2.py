"""Model-backed SoluProt acceptance through the public V2 Run seam."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection

import os
from pathlib import Path
import shlex
import shutil
from typing import Any

import pytest

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import V2RunService
from tests.support.result_store import result_store
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.workflow.document import WorkflowEdge
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
    return root


def _environment(mode: str) -> dict[str, Any]:
    external_root = _trusted_external_root()
    environment: dict[str, Any] = {
        "python_executable": (
            external_root / "var/environments/soluprot/bin/python"
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
        environment["perl_executable"] = Path(
            str(shutil.which("perl"))
        )
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
    usearch_executable: Path | None = None,
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
                    binding_id=(
                        "contract_test.folding_sequence_batch_source.direct"
                    ),
                    node_parameters={"sequences": list(SEQUENCES)},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="score",
                    node_type_id="solubility.score_sequence",
                    binding_id=binding_id,
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
            )),
    )
    environment_values = _environment(mode)
    if usearch_executable is not None:
        environment_values["usearch_executable"] = usearch_executable
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            admit_environment_configuration(
                catalog,
                {
                    binding_id: environment_values,
                },
            ),
            result_store(projects),
        ),
        result_store(projects),
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
            public_run_projection(service, project.id, receipt["run_id"]),
            public_run_events(service, project.id, receipt["run_id"]),
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
    import modules.solubility.soluprot as adapter

    recorded: list[dict[str, Any]] = []
    usearch_log = tmp_path / f"usearch-{mode}.argv"
    actual_usearch = _environment(mode)["usearch_executable"]
    usearch_probe = tmp_path / f"usearch-{mode}-probe"
    usearch_probe.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$#\" >> {shlex.quote(str(usearch_log))}\n"
        f"printf '%s\\n' \"$@\" >> {shlex.quote(str(usearch_log))}\n"
        f"exec {shlex.quote(str(actual_usearch))} \"$@\"\n",
        encoding="ascii",
    )
    usearch_probe.chmod(0o755)
    original_run_process = adapter._run_local_process

    def record_and_delegate(**kwargs: Any) -> int:
        staging_directory = kwargs["staging_directory"]
        perl_command = staging_directory / "perl"
        record = {
            "command": tuple(kwargs["command"]),
            "staging_directory": staging_directory,
            "path_entries": tuple(kwargs["path_entries"]),
            "timeout_seconds": kwargs["timeout_seconds"],
            "perl_command_is_symlink": perl_command.is_symlink(),
            "perl_command_target": (
                perl_command.resolve(strict=True)
                if perl_command.is_symlink()
                else None
            ),
            "input_fasta": (
                staging_directory / "input.fasta"
            ).read_text(encoding="ascii"),
        }
        return_code = original_run_process(**kwargs)
        record["raw_output"] = (
            staging_directory / "output.csv"
        ).read_bytes()
        recorded.append(record)
        return return_code

    monkeypatch.setattr(adapter, "_run_local_process", record_and_delegate)

    catalog, service, projection, events = _run(
        tmp_path,
        mode=mode,
        usearch_executable=usearch_probe,
    )

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
    assert usearch_log.is_file()
    record = recorded[0]
    assert record["timeout_seconds"] == 300.0
    staging_directory = record["staging_directory"]
    environment = _environment(mode)
    environment["usearch_executable"] = usearch_probe
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
        "-c",
        adapter._SOLUPROT_MODULE_DRIVER,
        str(site_packages_root),
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
                str(
                    site_packages_root
                    / "soluprot_assets/tmhmm-2.0d/bin/tmhmm"
                ),
            ]
        )
    else:
        expected_command.append("--no_tmhmm")
    assert record["command"] == tuple(expected_command)
    if mode == "full":
        assert record["perl_command_is_symlink"] is True
        assert record["perl_command_target"] == environment[
            "perl_executable"
        ].resolve(strict=True)
        assert record["path_entries"] == (staging_directory,)
    else:
        assert record["perl_command_is_symlink"] is False
        assert record["perl_command_target"] is None
        assert record["path_entries"] == ()
    assert record["input_fasta"] == "".join(
        f">candidate_{index}\n{sequence}\n"
        for index, sequence in enumerate(SEQUENCES)
    )
    expected_usearch_argv = (
        "-usearch_global",
        str(staging_directory / "provider-work/query.fa"),
        "-db",
        str(site_packages_root / "data/Ecoli_xray_nmr_pdb_no_nesg.fa"),
        "-id",
        "0.0",
        "-blast6out",
        str(staging_directory / "provider-work/identity.b6"),
        "-threads",
        "1",
        "-top_hits_only",
    )
    assert usearch_log.read_text(encoding="ascii").splitlines() == [
        str(len(expected_usearch_argv)),
        *expected_usearch_argv,
    ]
    sequence_type = catalog.require_port_type(
        "protein.sequence")
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
        == observation.method.contract_id
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
        service=service,
        projection=projection,
        events=events,
    )
