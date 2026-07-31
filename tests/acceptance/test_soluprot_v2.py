"""Model-backed SoluProt acceptance through the public V2 Run seam."""

from __future__ import annotations

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
    parse_workflow_document,
)
from core.port_types import canonical_json_bytes
from core.workflow_v2 import WorkflowEdge
from modules.solubility.adapter import (
    configured_runtime_fingerprint,
    soluprot_readiness,
)


pytestmark = [pytest.mark.acceptance, pytest.mark.local_provider]

EXTERNAL_ROOT = Path("/Users/sorachan/Documents/ESM-workflow-NEXT")
FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2] / "modules/solubility/fixtures"
)
SEQUENCE = "".join(
    line.strip()
    for line in (FIXTURE_ROOT / "soluprot_input.fasta").read_text().splitlines()
    if not line.startswith(">")
)
EXPECTED = {
    mode: float(
        (FIXTURE_ROOT / f"soluprot_{mode}_expected.csv")
        .read_text()
        .splitlines()[1]
        .rsplit(",", 1)[1]
    )
    for mode in ("full", "no_tm")
}


def _environment(mode: str) -> dict[str, Any]:
    environment: dict[str, Any] = {
        "python_executable": (
            EXTERNAL_ROOT / "var/environments/soluprot/bin/python"
        ),
        "wheel_path": (
            EXTERNAL_ROOT
            / "vendor/packages/soluprot-1.1.0-py3-none-any.whl"
        ),
        "site_packages_root": (
            EXTERNAL_ROOT
            / "var/environments/soluprot/lib/python3.12/site-packages"
        ),
        "usearch_executable": (
            EXTERNAL_ROOT / "var/tools/soluprot/usearch"
        ),
        "resolved_runtime_fingerprint": configured_runtime_fingerprint(mode),
    }
    if mode == "full":
        environment["tmhmm_root"] = (
            EXTERNAL_ROOT / "var/tools/soluprot/tmhmm"
        )
        environment["perl_executable"] = Path("/usr/bin/perl")
    return environment


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


def _run(
    tmp_path: Path,
    *,
    mode: str,
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
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
    saved = authoring.save(
        project.id,
        expected_workflow_revision=0,
        workflow=WorkflowDocument(
            schema_version="2.1.0",
            workflow_id=project.id,
            nodes=(
                WorkflowNodeInstance(
                    node_id="source",
                    node_type_id="contract_test.folding_sequence_source",
                    node_type_version="2.1.0",
                    binding_id=(
                        "contract_test.folding_sequence_source.direct"
                    ),
                    binding_version="2.1.0",
                    node_parameters={"sequence": SEQUENCE},
                    binding_parameters={},
                ),
                WorkflowNodeInstance(
                    node_id="score",
                    node_type_id="solubility.score_sequence",
                    node_type_version="2.1.0",
                    binding_id=binding_id,
                    binding_version="2.1.0",
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
    relocked = authoring.relock(
        project.id,
        workflow_revision=saved["workflow_revision"],
    )
    compiled = authoring.compile(
        project.id,
        workflow_revision=relocked["workflow_revision"],
        workflow=parse_workflow_document(relocked["workflow"]),
    )
    environment_values = _environment(mode)
    service = V2RunService(
        projects,
        catalog,
        authoring,
        EnvironmentConfiguration(
            {
                (binding_id, "2.1.0"): {
                    "values": environment_values,
                    "safe_fingerprint": configured_runtime_fingerprint(mode),
                    "invalidation_token": configured_runtime_fingerprint(mode),
                }
            }
        ),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_revision=relocked["workflow_revision"],
            compile_id=compiled.public_receipt()["compile_id"],
            client_request_id=f"model-backed-soluprot-{mode}",
        )
        service.shutdown()
        return (
            catalog,
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
    mode: str,
    expected: float,
) -> None:
    required = [
        EXTERNAL_ROOT / "var/environments/soluprot/bin/python",
        EXTERNAL_ROOT / "vendor/packages/soluprot-1.1.0-py3-none-any.whl",
        EXTERNAL_ROOT / "var/tools/soluprot/usearch",
    ]
    if mode == "full":
        required.extend(
            (
                EXTERNAL_ROOT / "var/tools/soluprot/tmhmm",
                Path("/usr/bin/perl"),
            )
        )
    assert all(path.exists() for path in required), (
        "required locked SoluProt assets are unavailable"
    )

    catalog, projection, events = _run(tmp_path, mode=mode)

    assert projection["status"] == "succeeded", projection
    binding_id = f"solubility.soluprot_{mode}.local"
    output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "score"
    )
    scores = _decode_output(catalog, output)
    assert len(scores.entries) == 1
    observation = scores.entries[0]
    assert observation.value == expected
    assert observation.method.contract_id == (
        f"solubility.soluprot_{mode}.v1_1_0"
    )
    assert observation.metric.contract_id == (
        "solubility.soluprot_probability"
    )
    started = {
        (
            event["event"]["invocation_id"],
            event["event"]["engine_identity"],
        )
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith(
            f"soluprot.{mode}.v1_1_0/"
        )
    }
    terminals = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        in {invocation_id for invocation_id, _ in started}
    ]
    assert len(started) == 1
    assert next(iter(started))[1].endswith(
        configured_runtime_fingerprint(mode)
    )
    assert [event["status"] for event in terminals] == ["succeeded"]
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"] == binding_id
        and event["event"]["binding"]["contract_version"] == "2.1.0"
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


def test_stale_no_tm_asset_replacement_invalidates_readiness(
    tmp_path: Path,
) -> None:
    replacement = tmp_path / "usearch"
    replacement.write_bytes(b"stale replacement")
    replacement.chmod(0o700)
    environment = _environment("no_tm")
    environment["usearch_executable"] = replacement

    conclusion = soluprot_readiness(environment, mode="no_tm")

    assert conclusion.passing is False
    assert conclusion.reason_code == "soluprot_no_tm_runtime_unavailable"
