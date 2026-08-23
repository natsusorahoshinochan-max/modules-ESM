"""Acceptance contracts for the clean installed v2 backend artifact."""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog

from protein_workbench_public.bootstrap import module_registrations

import hashlib
import json
import os
import socket
import subprocess
import tarfile
import time
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from verification.acceptance_campaign import acceptance_tier
from protein_workbench_public.protocol import (
    bundle_bytes,
    bundle_digest,
)
from tests.support.public_request import (
    prepare_run_event_stream_request,
    prepare_rest_request,
)
from tests.support.protocol import (
    validate_artifact_response,
    validate_event,
)
from tests.public_protocol_acceptance_client import PublicProtocolAcceptanceClient
from tests.acceptance.installed_harness import (
    InstalledArtifact,
    build_artifacts,
    installed_artifact,
    run_external_acceptance,
)
from tests.acceptance.retained_evidence import (
    require_retained_evidence,
    retain_rest_run,
)
from websockets.sync.client import connect


pytestmark = pytest.mark.installed_package

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_CATALOG = build_frozen_catalog(module_registrations())
SOURCE_CATALOG_BYTES = SOURCE_CATALOG.catalog_descriptor_bytes
SOURCE_CATALOG_DIGEST = SOURCE_CATALOG.contract_digest
SOURCE_PROTOCOL_BYTES = bundle_bytes()
SOURCE_PROTOCOL_DIGEST = bundle_digest()
LOOPBACK_URL_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({})
)
BIOHUB_ESMC_GATE_VERSION = "5.0.0"
BIOHUB_ESMC_METHOD_VERSION = "3.0.0"
REQUIRED_PROVIDER_CASES = {
    "biohub_esm3": (
        (
            "tests/acceptance/test_installed_provider_gates_v2.py::"
            "test_biohub_esm3_all_remote_bindings_execute_exact_methods"
        ),
    ),
    "biohub_esmfold2": (
        (
            "tests/acceptance/test_installed_provider_gates_v2.py::"
            "test_biohub_esmfold2_executes_exact_method"
        ),
    ),
    "local_esm3": (
        (
            "tests/acceptance/test_local_esm3.py::"
            "test_local_esm3_all_generation_modes"
        ),
    ),
    "local_esmfold2": (
        (
            "tests/acceptance/test_installed_provider_gates_v2.py::"
            "test_local_esmfold2_executes_exact_method"
        ),
    ),
    "proteinmpnn": (
        (
            "tests/acceptance/test_installed_provider_gates_v2.py::"
            "test_proteinmpnn_design_and_score_execute_exact_methods"
        ),
        (
            "tests/acceptance/test_proteinmpnn_scoring_v2.py::"
            "test_proteinmpnn_v2_scoring_publishes_exact_native_observation"
        ),
        (
            "tests/acceptance/test_proteinmpnn_scoring_v2.py::"
            "test_proteinmpnn_v2_sibling_design_remains_exact_and_complete"
        ),
    ),
    "mkdssp": (
        (
            "tests/acceptance/test_installed_provider_gates_v2.py::"
            "test_mkdssp_executes_exact_method_through_public_run"
        ),
    ),
    "simplefold_folding": (
        (
            "tests/acceptance/test_simplefold_v2.py::"
            "test_simplefold_v2_folds_3gb1_through_exact_binding"
        ),
    ),
    "simplefold_confidence": (
        (
            "tests/acceptance/test_simplefold_confidence_v2.py::"
            "test_simplefold_confidence_v2_evaluates_3gb1_exact_assets_"
            "without_refold"
        ),
    ),
    "soluprot": (
        (
            "tests/acceptance/test_soluprot_v2.py::"
            "test_model_backed_soluprot_golden_methods"
        ),
    ),
    "protein_sol": (
        (
            "tests/acceptance/test_protein_sol_v2.py::"
            "test_local_protein_sol_golden_multiple_metrics"
        ),
    ),
}


def _installed_probe(
    installed: InstalledArtifact,
    source_root: Path,
) -> dict[str, object]:
    probe = """
import hashlib
import json
from pathlib import Path
import core
import datatypes
import examples
import modules
import pdbs
import protein_workbench_public
from core.catalog.builder import build_frozen_catalog
from protein_workbench_public.protocol import bundle_bytes, bundle_digest
from protein_workbench_public.bootstrap import module_registrations
from protein_workbench_public.catalog_codec import encode_catalog_projection

source_root = Path(__import__("os").environ["PW_SOURCE_ROOT"]).resolve()
origins = {
    "core": str(Path(core.__file__).resolve()),
    "datatypes": str(Path(datatypes.__file__).resolve()),
    "examples": str(Path(examples.__file__).resolve()),
    "modules": str(Path(modules.__file__).resolve()),
    "pdbs": str(Path(pdbs.__file__).resolve()),
    "public": str(Path(protein_workbench_public.__file__).resolve()),
}
assert all(not Path(path).is_relative_to(source_root) for path in origins.values())
catalog = build_frozen_catalog(module_registrations())
print(json.dumps({
    "origins": origins,
    "protocol_hex": bundle_bytes().hex(),
    "protocol_digest": bundle_digest(),
    "catalog_hex": catalog.catalog_descriptor_bytes.hex(),
    "catalog_digest": catalog.contract_digest,
    "contracts": [contract.reference() for contract in catalog.contracts],
    "availability": encode_catalog_projection(
        catalog.projection(),
        protocol_digest=bundle_digest(),
    )["availability"],
}, sort_keys=True))
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PW_SOURCE_ROOT"] = str(source_root)
    completed = subprocess.run(
        [str(installed.python), "-I", "-c", probe],
        cwd=installed.run_root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_server(port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            with LOOPBACK_URL_OPENER.open(
                f"http://127.0.0.1:{port}/api/v2/protocol",
                timeout=1,
            ) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.05)
    output = _stop_server(process)
    pytest.fail(f"installed backend did not start:\n{output}")


def _stop_server(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.terminate()
    try:
        return process.communicate(timeout=10)[0]
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)[0]


def _wait_terminal(
    client: PublicProtocolAcceptanceClient,
    project_id: str,
    run_id: str,
    *,
    timeout: float = 30,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        projection = client.request(
            "run_projection",
            {"project_id": project_id, "run_id": run_id},
        )
        if projection["status"] in {
            "succeeded",
            "failed",
            "cancelled",
            "interrupted",
        }:
            return projection
        time.sleep(0.02)
    raise AssertionError("installed Run did not reach a terminal projection")


def _collect_run_events(
    port: int,
    project_id: str,
    run_id: str,
) -> list[dict[str, object]]:
    stream = prepare_run_event_stream_request(
        {"project_id": project_id, "run_id": run_id}
    )
    messages: list[dict[str, object]] = []
    with connect(
        f"ws://127.0.0.1:{port}{stream.route}",
        open_timeout=5,
        close_timeout=5,
        proxy=None,
    ) as websocket:
        while True:
            message = json.loads(websocket.recv(timeout=30))
            validate_event(message)
            messages.append(message)
            if message["event"]["type"] == "run_terminal":
                return messages


def test_built_artifact_is_reproducible_complete_and_fixture_free(
    tmp_path: Path,
) -> None:
    first_wheel, first_sdist = build_artifacts(tmp_path / "first")
    second_wheel, second_sdist = build_artifacts(tmp_path / "second")
    assert hashlib.sha256(first_wheel.read_bytes()).digest() == hashlib.sha256(
        second_wheel.read_bytes()
    ).digest()
    assert hashlib.sha256(first_sdist.read_bytes()).digest() == hashlib.sha256(
        second_sdist.read_bytes()
    ).digest()

    with zipfile.ZipFile(first_wheel) as archive:
        entries = archive.infolist()
        names = {entry.filename for entry in entries}
    with tarfile.open(first_sdist) as archive:
        sdist_entries = archive.getmembers()
        sdist_names = {
            Path(*Path(entry.name).parts[1:]).as_posix()
            for entry in sdist_entries
        }
        assert all(
            not entry.issym()
            and not entry.islnk()
            and not bool(entry.mode & 0o002)
            for entry in sdist_entries
        )

    required = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in PROJECT_ROOT.glob("modules/**/*.yaml")
        if not {"fixture", "fixtures", "test", "tests"}.intersection(path.parts)
    }
    required |= {
        "examples/v2/capability-inventory.json",
        "examples/v2/canonical-3gb1.workflow.json",
        "examples/v2/repository-capabilities.workflow.json",
        "examples/v2/source-bound-1pga.workflow.json",
        "examples/v2/source-bound-2emo.workflow.json",
        "examples/v2/source-bound-5g53.workflow.json",
        "pdbs/1PGA-75-gen1_0690.pdb",
        "pdbs/2EMO.pdb",
        "pdbs/3GB1.pdb",
        "pdbs/5G53.pdb",
        "protein_workbench_public/resources/v2/bundle.json",
    }
    assert required <= names
    assert required <= sdist_names
    assert not any(
        name.startswith("tests/")
        or "zero_core_packages" in name
        or "verification-results" in Path(name).parts
        or {"fixture", "fixtures", "test", "tests"}.intersection(
            Path(name).parts
        )
        for name in names
    )
    assert not any(
        name.startswith("tests/")
        or "zero_core_packages" in name
        or "verification-results" in Path(name).parts
        or {"fixture", "fixtures", "test", "tests"}.intersection(
            Path(name).parts
        )
        for name in sdist_names
    )


def test_installed_protocol_catalog_identity_and_separate_availability(
    installed_artifact: InstalledArtifact,
) -> None:
    installed = _installed_probe(installed_artifact, PROJECT_ROOT)
    assert bytes.fromhex(str(installed["protocol_hex"])) == SOURCE_PROTOCOL_BYTES
    assert installed["protocol_digest"] == SOURCE_PROTOCOL_DIGEST
    assert bytes.fromhex(str(installed["catalog_hex"])) == SOURCE_CATALOG_BYTES
    assert installed["catalog_digest"] == SOURCE_CATALOG_DIGEST
    assert installed["contracts"] == [
        contract.reference() for contract in SOURCE_CATALOG.contracts
    ]
    assert installed["availability"]
    assert all(
        set(snapshot) >= {"binding", "observed_at", "available"}
        for snapshot in installed["availability"]
    )
    assert "availability" not in json.loads(
        bytes.fromhex(str(installed["catalog_hex"]))
    )


def test_installed_backend_completes_full_public_v2_journey(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(variable, "http://127.0.0.1:1")
    for variable in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(variable, raising=False)
    port = _free_port()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(root)
    server = subprocess.Popen(
        [
            str(installed_artifact.python),
            "-I",
            "-m",
            "protein_workbench_public.cli",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=installed_artifact.run_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server(port, server)
        base_url = f"http://127.0.0.1:{port}"
        with LOOPBACK_URL_OPENER.open(
            f"{base_url}/api/v2/protocol",
            timeout=2,
        ) as response:
            assert response.read() == SOURCE_PROTOCOL_BYTES
            assert response.headers["Digest"] == SOURCE_PROTOCOL_DIGEST
        with PublicProtocolAcceptanceClient(base_url) as client:
            catalog = client.request("catalog_snapshot", {})
            assert catalog["catalog_contract_digest"] == SOURCE_CATALOG_DIGEST
            project_id = client.create_project(
                "installed public v2 acceptance"
            )["id"]
            uploaded = client.publish_project_input(
                project_id,
                filename="3GB1.pdb",
                content=(PROJECT_ROOT / "pdbs" / "3GB1.pdb").read_bytes(),
            )
            input_reference = uploaded["project_input_ref"]
            assert client.project_input_metadata(
                project_id,
                input_reference,
            ) == uploaded
            workflow = {
                "schema_version": "2.1.0",
                "workflow_id": project_id,
                "nodes": [
                    {
                        "node_id": "import",
                        "node_type_id": "protein_io.import_structure",
                        "node_type_version": "6.0.0",
                        "binding_id": "protein_io.import_structure.direct",
                        "binding_version": "6.0.0",
                        "node_parameters": {
                            "project_input_ref": input_reference
                        },
                        "binding_parameters": {},
                    },
                    {
                        "node_id": "export",
                        "node_type_id": "protein_io.export_structure",
                        "node_type_version": "6.0.0",
                        "binding_id": "protein_io.export_structure.direct",
                        "binding_version": "6.0.0",
                        "node_parameters": {},
                        "binding_parameters": {},
                    },
                    *[
                        {
                            "node_id": f"export-{index}",
                            "node_type_id": "protein_io.export_structure",
                            "node_type_version": "6.0.0",
                            "binding_id": (
                                "protein_io.export_structure.direct"
                            ),
                            "binding_version": "6.0.0",
                            "node_parameters": {},
                            "binding_parameters": {},
                        }
                        for index in range(32)
                    ],
                ],
                "edges": [
                    {
                        "source_node_id": "import",
                        "source_port": "structure",
                        "target_node_id": "export",
                        "target_port": "structure",
                    },
                    *[
                        {
                            "source_node_id": "import",
                            "source_port": "structure",
                            "target_node_id": f"export-{index}",
                            "target_port": "structure",
                        }
                        for index in range(32)
                    ],
                ],
                "selection_objectives": [],
                "contract_lock": [],
            }
            saved = client.request(
                "save_project_workflow_draft",
                {
                    "project_id": project_id,
                    "workflow": workflow,
                },
            )
            draft = client.request(
                "project_workflow_draft",
                {"project_id": project_id},
            )
            assert draft == saved
            committed = client.request(
                "commit_project_workflow",
                {
                    "project_id": project_id,
                    "workflow": workflow,
                },
            )
            active = client.request(
                "project_active_workflow_commit",
                {"project_id": project_id},
            )
            assert active == committed
            first = client.request(
                "start_run",
                {
                    "project_id": project_id,
                    "workflow_commit_id": committed[
                        "workflow_commit_id"
                    ],
                    "client_request_id": "installed-first",
                },
            )
            stream = prepare_run_event_stream_request(
                {"project_id": project_id, "run_id": first["run_id"]}
            )
            streamed = []
            replay_complete_index = None
            with connect(
                f"ws://127.0.0.1:{port}{stream.route}",
                open_timeout=5,
                close_timeout=5,
                proxy=None,
            ) as websocket:
                while True:
                    message = json.loads(websocket.recv(timeout=5))
                    validate_event(message)
                    streamed.append(message)
                    if message["event"]["type"] == "replay_complete":
                        replay_complete_index = len(streamed) - 1
                    if (
                        replay_complete_index is not None
                        and message["event"]["type"] == "run_terminal"
                    ):
                        break
            assert replay_complete_index is not None
            replayed = streamed[: replay_complete_index + 1]
            live = streamed[replay_complete_index + 1 :]
            event_types = {message["event"]["type"] for message in replayed}
            assert {
                "replay_started",
                "replay_complete",
            } <= event_types
            assert any(
                message["event"]["type"] == "run_terminal"
                for message in live
            )

            first_projection = _wait_terminal(
                client,
                project_id,
                first["run_id"],
            )
            assert first_projection["status"] == "succeeded"
            assert all(
                disposition["resolution"] in {"executed", "cache_replayed"}
                for disposition in first_projection["node_dispositions"]
            )
            assert any(
                disposition["resolution"] == "executed"
                for disposition in first_projection["node_dispositions"]
            )
            artifact = first_projection["artifact_index"][0]
            assert artifact["filename"] == "structure.pdb"
            artifact_request = prepare_rest_request(
                "artifact_retrieval",
                {
                    "project_id": project_id,
                    "run_id": first["run_id"],
                    "artifact_reference": artifact["artifact_reference"],
                },
            )
            retrieved = httpx.request(
                artifact_request.method,
                f"{base_url}{artifact_request.route}",
                timeout=5,
                trust_env=False,
            )
            retrieved.raise_for_status()
            payload = retrieved.content
            assert retrieved.headers["content-disposition"] == (
                "attachment; filename*=UTF-8''structure.pdb"
            )
            validate_artifact_response(
                {
                    "artifact": artifact,
                    "content_disposition": retrieved.headers[
                        "content-disposition"
                    ],
                },
                retrieved.headers,
                payload,
            )

            second = client.request(
                "start_run",
                {
                    "project_id": project_id,
                    "workflow_commit_id": committed[
                        "workflow_commit_id"
                    ],
                    "client_request_id": "installed-cache-replay",
                },
            )
            second_projection = _wait_terminal(
                client,
                project_id,
                second["run_id"],
            )
            assert second_projection["status"] == "succeeded"
            assert any(
                disposition["resolution"] == "cache_replayed"
                for disposition in second_projection["node_dispositions"]
            )
            derived = client.request(
                "start_derived_run",
                {
                    "project_id": project_id,
                    "source_run_id": first["run_id"],
                    "policy": "force_selected",
                    "node_ids": [
                        "export",
                        *[f"export-{index}" for index in range(32)],
                    ],
                    "client_request_id": "installed-derived",
                },
            )
            cancelled = client.request(
                "cancel_run",
                {
                    "project_id": project_id,
                    "run_id": derived["run_id"],
                    "reason": "installed acceptance cancellation race",
                },
            )
            assert cancelled["outcome"] in {
                "already_requested",
                "cancellation_requested",
            }
            derived_projection = _wait_terminal(
                client,
                project_id,
                derived["run_id"],
            )
            assert derived_projection["derived_from_run_id"] == first["run_id"]
            assert derived_projection["status"] == "cancelled"
    finally:
        _stop_server(server)


def _run_installed_provider_case(
    installed: InstalledArtifact,
    tmp_path: Path,
    case: str,
) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PW_SOURCE_ROOT"] = str(PROJECT_ROOT)
    if case in {"biohub_esm3", "biohub_esmfold2"}:
        token_file = Path(
            env["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"]
        )
        env["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"] = str(token_file)
    if case == "simplefold_folding":
        env["PROTEIN_WORKBENCH_PROVIDER_IDENTITY_PROFILE"] = (
            "simplefold-v2-folding"
        )
    elif case == "simplefold_confidence":
        env["PROTEIN_WORKBENCH_PROVIDER_IDENTITY_PROFILE"] = (
            "simplefold-v2-confidence"
        )
    run_external_acceptance(
        installed,
        tmp_path,
        selectors=REQUIRED_PROVIDER_CASES[case],
        environment=env,
        timeout_seconds={
            "local_esmfold2": 90 * 60,
            "proteinmpnn": 60 * 60,
        }.get(case, 30 * 60),
    )
    _require_configured_installed_evidence()


def _require_configured_installed_evidence() -> None:
    configured = os.environ.get(
        "PROTEIN_WORKBENCH_ACCEPTANCE_EVIDENCE_STAGING"
    )
    if configured is None:
        return
    tier = os.environ["PROTEIN_WORKBENCH_VERIFICATION_TIER"]
    contract = acceptance_tier(tier)
    require_retained_evidence(
        Path(configured),
        required_runs=contract.required_run_labels,
        lifecycle_required=contract.lifecycle_receipt_required,
    )
@contextmanager
def _running_installed_biohub_esmc_server(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> Iterator[tuple[int, str]]:
    token_file = Path(os.environ["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"])
    launcher = tmp_path / "installed_biohub_esmc_server.py"
    launcher.write_text(
        """
import os
from pathlib import Path
import core
import datatypes
import examples
import modules
import pdbs
import protein_workbench_public
from protein_workbench_public.bootstrap import create_application
from core.provider_support import read_private_credential_file

source = Path(os.environ["PW_SOURCE_ROOT"]).resolve()
for package in (
    core,
    datatypes,
    examples,
    modules,
    pdbs,
    protein_workbench_public,
):
    assert not Path(package.__file__).resolve().is_relative_to(source)
binding = ("esm3.represent_sequence.biohub_esmc_600m_2024_12", "5.0.0")
token = read_private_credential_file(
    Path(os.environ["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"])
)
app = create_application(v2_environment_configuration={
    binding: {
        "values": {
            "endpoint_id": "biohub",
            "credential_handle": token,
        },
    },
})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ["PW_SERVER_PORT"]),
        log_level="warning",
    )
""".lstrip(),
        encoding="utf-8",
    )
    port = _free_port()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PW_SOURCE_ROOT"] = str(PROJECT_ROOT)
    env["PW_SERVER_PORT"] = str(port)
    env["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"] = str(token_file)
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(root)
    server = subprocess.Popen(
        [str(installed_artifact.python), "-I", str(launcher)],
        cwd=installed_artifact.run_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server(port, server)
        yield port, f"http://127.0.0.1:{port}"
    finally:
        _stop_server(server)


def _assert_installed_esmc_catalog(
    catalog: dict[str, object],
) -> tuple[str, str]:
    contracts = {
        (
            item["reference"]["contract_kind"],
            item["reference"]["contract_id"],
            item["reference"]["contract_version"],
        ): item
        for item in catalog["contracts"]
    }
    binding_id = "esm3.represent_sequence.biohub_esmc_600m_2024_12"
    binding_key = ("binding", binding_id, BIOHUB_ESMC_GATE_VERSION)
    method_key = (
        "method",
        "esm3.represent_sequence.esmc_600m_2024_12",
        BIOHUB_ESMC_METHOD_VERSION,
    )
    assert contracts[binding_key]["descriptor"]["method"]["contract_id"] == (
        method_key[1]
    )
    assert contracts[method_key]["descriptor"]["model_identity"]["model"] == (
        "esmc-600m-2024-12"
    )
    return binding_id, contracts[method_key]["reference"]["contract_digest"]


def _start_installed_esmc_run(
    client: PublicProtocolAcceptanceClient,
    binding_id: str,
) -> tuple[str, str]:
    project_id = client.create_project(
        "installed Biohub ESMC acceptance"
    )["id"]
    uploaded = client.publish_project_input(
        project_id,
        filename="3GB1.fasta",
        content=(
            b">3GB1\n"
            b"MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE\n"
        ),
    )
    workflow = {
        "schema_version": "2.1.0",
        "workflow_id": project_id,
        "nodes": [
            {
                "node_id": "import",
                "node_type_id": "protein_io.import_sequence",
                "node_type_version": "6.0.0",
                "binding_id": "protein_io.import_sequence.direct",
                "binding_version": "6.0.0",
                "node_parameters": {
                    "project_input_ref": uploaded["project_input_ref"]
                },
                "binding_parameters": {},
            },
            {
                "node_id": "represent",
                "node_type_id": "esm3.represent_sequence",
                "node_type_version": BIOHUB_ESMC_GATE_VERSION,
                "binding_id": binding_id,
                "binding_version": BIOHUB_ESMC_GATE_VERSION,
                "node_parameters": {},
                "binding_parameters": {},
            },
        ],
        "edges": [
            {
                "source_node_id": "import",
                "source_port": "sequence",
                "target_node_id": "represent",
                "target_port": "sequence",
            }
        ],
        "selection_objectives": [],
        "contract_lock": [],
    }
    saved = client.request(
        "save_project_workflow_draft",
        {
            "project_id": project_id,
            "workflow": workflow,
        },
    )
    committed = client.request(
        "commit_project_workflow",
        {
            "project_id": project_id,
            "workflow": workflow,
        },
    )
    started = client.request(
        "start_run",
        {
            "project_id": project_id,
            "workflow_commit_id": committed["workflow_commit_id"],
            "client_request_id": "installed-biohub-esmc",
        },
    )
    return project_id, started["run_id"]


@pytest.mark.live_provider
def test_installed_biohub_esmc_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    with _running_installed_biohub_esmc_server(
        installed_artifact,
        tmp_path,
    ) as (port, base_url):
        with PublicProtocolAcceptanceClient(base_url) as client:
            catalog_snapshot = client.request("catalog_snapshot", {})
            binding_id, method_digest = _assert_installed_esmc_catalog(
                catalog_snapshot
            )
            project_id, run_id = _start_installed_esmc_run(
                client,
                binding_id,
            )
            messages = _collect_run_events(port, project_id, run_id)
            projection = _wait_terminal(
                client,
                project_id,
                run_id,
                timeout=120,
            )

            assert projection["status"] == "succeeded", projection
            representation = next(
                output
                for output in projection["outputs"]
                if output["node_id"] == "represent"
                and output["output_port"] == "representation"
            )
            _, canonical_value = client.typed_value(
                {
                    "project_id": project_id,
                    "run_id": run_id,
                    "node_id": representation["node_id"],
                    "output_port": representation["output_port"],
                    "value_index": 0,
                },
                representation,
            )
            assert representation["port_type"]["contract_id"] == (
                "esm3.esmc_sequence_representation"
            )
            value = json.loads(canonical_value)["value"]
            assert value["sequence"].startswith("MTYKLILNGKTL")
            assert len(value["mean_embedding"]) == 1152
            assert all(
                isinstance(item, (int, float))
                and item == item
                and abs(item) != float("inf")
                for item in value["mean_embedding"]
            )
            assert value["sequence_logits_shape"] == [
                len(value["sequence"]) + 2,
                64,
            ]

            events = [message["event"] for message in messages]
            readiness = [
                event
                for event in events
                if event["type"] == "readiness_attested"
                and event["binding"]["contract_id"] == binding_id
            ]
            assert len(readiness) == 1
            assert readiness[0]["conclusion"] == "passing"
            invocations = [
                event
                for event in events
                if event["type"] == "engine_invocation_started"
                and event["engine_identity"] == method_digest
            ]
            assert [event["engine_role"] for event in invocations] == [
                "sequence_encode",
                "sequence_logits",
            ]
            terminal_by_id = {
                event["invocation_id"]: event
                for event in events
                if event["type"] == "engine_invocation_terminal"
            }
            assert all(
                terminal_by_id[event["invocation_id"]]["status"]
                == "succeeded"
                for event in invocations
            )
            retain_rest_run(
                "biohub-esmc",
                catalog_snapshot=catalog_snapshot,
                client=client,
                projection=projection,
                events=messages,
            )
    _require_configured_installed_evidence()


@pytest.mark.live_provider
def test_installed_biohub_esm3_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_installed_provider_case(
        installed_artifact,
        tmp_path,
        "biohub_esm3",
    )


@pytest.mark.live_provider
def test_installed_biohub_esmfold2_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_installed_provider_case(
        installed_artifact,
        tmp_path,
        "biohub_esmfold2",
    )


@pytest.mark.local_provider
@pytest.mark.slow
def test_installed_local_esm3_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_installed_provider_case(installed_artifact, tmp_path, "local_esm3")


@pytest.mark.local_provider
@pytest.mark.slow
def test_installed_local_esmfold2_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_installed_provider_case(
        installed_artifact,
        tmp_path,
        "local_esmfold2",
    )


@pytest.mark.local_provider
@pytest.mark.slow
def test_installed_proteinmpnn_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_installed_provider_case(
        installed_artifact,
        tmp_path,
        "proteinmpnn",
    )


@pytest.mark.local_provider
def test_installed_mkdssp_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_installed_provider_case(
        installed_artifact,
        tmp_path,
        "mkdssp",
    )


@pytest.mark.local_provider
@pytest.mark.slow
def test_installed_simplefold_folding_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_installed_provider_case(
        installed_artifact,
        tmp_path,
        "simplefold_folding",
    )


@pytest.mark.local_provider
@pytest.mark.slow
def test_installed_simplefold_confidence_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_installed_provider_case(
        installed_artifact,
        tmp_path,
        "simplefold_confidence",
    )


@pytest.mark.local_provider
def test_installed_soluprot_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_installed_provider_case(installed_artifact, tmp_path, "soluprot")


@pytest.mark.local_provider
def test_installed_protein_sol_gate(
    installed_artifact: InstalledArtifact,
    tmp_path: Path,
) -> None:
    _run_installed_provider_case(installed_artifact, tmp_path, "protein_sol")
