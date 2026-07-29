"""Acceptance contract for the built, installed backend artifact."""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from core import build_discovered_frozen_catalog
from protein_workbench_public import bundle_bytes, bundle_digest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PROTOCOL_BYTES = bundle_bytes()
SOURCE_PROTOCOL_DIGEST = bundle_digest()
SOURCE_PORT_CATALOG = build_discovered_frozen_catalog()
SOURCE_PORT_CATALOG_BYTES = SOURCE_PORT_CATALOG.catalog_descriptor_bytes
SOURCE_PORT_CATALOG_DIGEST = SOURCE_PORT_CATALOG.contract_digest
SOURCE_PORT_TYPE_BYTES = {
    definition.type_id: definition.descriptor_bytes.hex()
    for definition in SOURCE_PORT_CATALOG.port_types
}
SOURCE_PORT_TYPE_DIGESTS = {
    definition.type_id: definition.contract_digest
    for definition in SOURCE_PORT_CATALOG.port_types
}
EXPECTED_MODULE_IDS = {
    "compute.dssp",
    "convert.extract_backbone",
    "convert.extract_sequence",
    "convert.map_track",
    "convert.select_chains",
    "esm3.generate",
    "esm3.generate_sequence",
    "esm3.generate_structure",
    "esm3.update_prompt_sequence",
    "esmfold2.fold",
    "export.sequence",
    "export.structure",
    "import.sequence",
    "import.structure",
    "prompt.add_function_annotation",
    "prompt.apply_residue_edits",
    "prompt.assemble_protein_prompt",
    "prompt.build_residue_layout",
    "prompt.compute_sasa",
    "prompt.compute_secondary_structure",
    "prompt.override_residue_track",
    "prompt.random_fixed_positions",
    "prompt.random_insert_masked",
    "prompt.random_mask",
    "proteinmpnn.constraints",
    "proteinmpnn.design",
    "proteinmpnn.score",
    "scoring.aggregate_confidence",
    "scoring.merge",
    "scoring.ss_agreement",
    "selection.concat",
    "selection.diversity",
    "selection.filter",
    "selection.pareto",
    "selection.sort",
    "selection.top_k",
    "selection.weighted_rank",
    "simplefold.evaluate",
    "simplefold.fold",
    "structure.align",
    "structure.batch_tm_score",
    "structure.pairwise_align",
    "structure.rmsd",
    "structure.tm_score",
    "stub.echo",
}


def _installed_direct_server_probe(port: int) -> str:
    """Build an installed-only synthetic direct Binding server bootstrap."""
    return r'''
from datetime import datetime, timezone
import os
from pathlib import Path
import time
import uvicorn
from core import (
    BehaviorReference,
    CatalogContract,
    FrozenCatalog,
    LazyImplementationFactory,
    ReadinessDeclaration,
    builtin_frozen_catalog,
)
from core.server import create_app

def contract(kind, identity, descriptor):
    return CatalogContract(
        contract_kind=kind,
        contract_id=identity,
        contract_version="2.0.0",
        descriptor={
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": kind,
            "contract_id": identity,
            "contract_version": "2.0.0",
            **descriptor,
        },
    )

builtin = builtin_frozen_catalog()
text = builtin.require_port_type("text", "2.0.0")
method = contract("method", "installed.direct.method", {
    "algorithm_identity": {"name": "installed-deterministic-text"},
    "model_identity": {"kind": "none"},
    "checkpoint_identity": {"kind": "none"},
    "featurization_identity": {"kind": "none"},
    "source_identity": {"kind": "installed-acceptance"},
    "scale_contract": {"kind": "identity"},
})
node = contract("node_type", "installed.direct", {
    "title": "Installed deterministic direct Node",
    "summary": "Validates installed readiness-gated direct execution.",
    "category": "acceptance",
    "inputs": [],
    "outputs": [{
        "name": "text",
        "port_type": text.reference(),
        "required": True,
        "multiplicity": "one",
        "scientific_meaning": "Installed canonical text",
    }],
    "parameter_groups": [],
    "node_parameters": {},
})
factory_behavior = BehaviorReference(
    "installed.direct/factory",
    "2.0.0",
    {},
)
readiness_behavior = BehaviorReference(
    "installed.direct/readiness",
    "2.0.0",
    {},
)
binding = contract("binding", "installed.direct.local", {
    "node_type": node.reference(),
    "method": method.reference(),
    "binding_parameters": {},
    "execution_route": "direct",
    "route_behavior": factory_behavior.descriptor(),
    "availability_declaration": {
        "behavior": {
            "behavior_id": "installed.direct/availability",
            "behavior_version": "2.0.0",
            "parameters": {},
        },
        "prerequisites": {},
    },
    "readiness_declaration": {
        "behavior": readiness_behavior.descriptor(),
        "prerequisites": {"installed_runtime": "required"},
    },
    "deterministic": True,
    "cacheable": False,
    "implementation_identity": {
        "name": "installed.direct.local",
        "factory": factory_behavior.descriptor(),
    },
    "produced_observations": [],
})

class Implementation:
    def __init__(self, resources):
        self._resources = resources

    def execute(self, *, inputs, node_parameters, binding_parameters):
        assert inputs == {}
        assert node_parameters == {}
        assert binding_parameters == {}
        with self._resources.engine_invocation(
            engine_identity="installed.direct.method/2.0.0",
        ):
            marker = Path(
                os.environ["PROTEIN_WORKBENCH_INSTALLED_BLOCK_MARKER"]
            )
            if marker.exists():
                marker.with_suffix(".started").write_text("started")
                while marker.exists():
                    time.sleep(0.05)
            return {"text": "INSTALLED_READY"}

def build(**kwargs):
    assert kwargs["environment_configuration"]["installed_runtime"] is True
    return Implementation(kwargs["run_resources"])

def ready(environment):
    return environment["installed_runtime"] is True

observed = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)
catalog = FrozenCatalog(
    builtin.port_types,
    contracts=(method, node, binding),
    availability=({
        "binding": binding.reference(),
        "observed_at": observed.isoformat(),
        "available": True,
    },),
    availability_observed_at=observed,
    factories={
        ("installed.direct.local", "2.0.0"): LazyImplementationFactory(
            behavior=factory_behavior,
            build=build,
        ),
    },
    readiness_declarations={
        ("installed.direct.local", "2.0.0"): ReadinessDeclaration(
            behavior=readiness_behavior,
            prerequisites={"installed_runtime": "required"},
            check=ready,
        ),
    },
)
app = create_app(
    frozen_catalog_override=catalog,
    v2_environment_configuration={
        ("installed.direct.local", "2.0.0"): {
            "values": {"installed_runtime": True},
            "safe_fingerprint": "installed-runtime-v1",
            "invalidation_token": "installed-assets-v1",
        },
    },
)
uvicorn.run(app, host="127.0.0.1", port=__PORT__, log_level="warning")
'''.replace("__PORT__", str(port))


def _build_artifacts(output_dir: Path) -> tuple[Path, Path]:
    subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "build_backend.py"),
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    wheels = list(output_dir.glob("protein_workbench-*.whl"))
    sdists = list(output_dir.glob("protein_workbench-*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
    return wheels[0], sdists[0]


@pytest.mark.installed_package
def test_built_artifacts_contain_backend_definitions_and_canonical_assets(
    tmp_path: Path,
) -> None:
    wheel, sdist = _build_artifacts(tmp_path / "dist")

    with zipfile.ZipFile(wheel) as archive:
        wheel_entries = archive.infolist()
        wheel_names = {entry.filename for entry in wheel_entries}
    with tarfile.open(sdist) as archive:
        sdist_entries = archive.getmembers()
        sdist_names = {
            name.split("/", 1)[1]
            for name in (entry.name for entry in sdist_entries)
            if "/" in name
        }

    required_names = {
        "examples/3gb1_pipeline.json",
        "examples/3gb1_pipeline_ui.json",
        "pdbs/3GB1.pdb",
        "protein_workbench_public/resources/v2/bundle.json",
    }
    required_names.update(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in PROJECT_ROOT.glob("modules/**/definition*.yaml")
    )

    assert required_names <= wheel_names
    assert required_names <= sdist_names
    assert {
        "docs/backend-verification.md",
        "docs/provider-install-contract.md",
        "scripts/build_backend.py",
        "scripts/verify_backend.py",
        "uv.lock",
    } <= sdist_names
    assert not any(name.startswith(("keys/", "repositories/")) for name in wheel_names)
    assert not any(name.startswith(("keys/", "repositories/")) for name in sdist_names)
    assert not any(
        name.startswith("modules/")
        and {"test", "tests", "fixture", "fixtures"}.intersection(
            Path(name).parts
        )
        for name in wheel_names
    )
    assert all(
        not name.startswith("/") and ".." not in Path(name).parts
        for name in wheel_names | sdist_names
    )
    assert all(
        not stat.S_ISLNK(entry.external_attr >> 16)
        and not ((entry.external_attr >> 16) & 0o002)
        for entry in wheel_entries
    )
    assert all(
        not entry.issym() and not entry.islnk() and not (entry.mode & 0o002)
        for entry in sdist_entries
    )


@pytest.mark.installed_package
def test_release_artifacts_are_reproducible(tmp_path: Path) -> None:
    first_wheel, first_sdist = _build_artifacts(tmp_path / "first")
    second_wheel, second_sdist = _build_artifacts(tmp_path / "second")

    assert sha256(first_wheel.read_bytes()).digest() == sha256(
        second_wheel.read_bytes()
    ).digest()
    assert sha256(first_sdist.read_bytes()).digest() == sha256(
        second_sdist.read_bytes()
    ).digest()


@pytest.mark.installed_package
def test_wheel_runs_discovery_canonical_validation_and_api_outside_source_tree(
    tmp_path: Path,
) -> None:
    wheel, _ = _build_artifacts(tmp_path / "dist")
    venv_dir = tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    python = venv_dir / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", str(wheel)],
        cwd=tmp_path,
        check=True,
    )

    run_dir = tmp_path / "outside-source"
    run_dir.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PROTEIN_WORKBENCH_SOURCE_ROOT"] = str(PROJECT_ROOT)
    for name in ("PROJECT", "CACHE", "OUTPUT", "RUN"):
        root = tmp_path / name.lower()
        root.mkdir()
        env[f"PROTEIN_WORKBENCH_{name}_ROOT"] = str(root)
    block_marker = tmp_path / "installed-run.block"
    env["PROTEIN_WORKBENCH_INSTALLED_BLOCK_MARKER"] = str(block_marker)

    expected = repr(sorted(EXPECTED_MODULE_IDS))
    probe = f"""
from pathlib import Path
import core
import modules
from core import (
    ModuleRegistry,
    TypeRegistry,
    build_discovered_frozen_catalog,
    discover_modules,
)
from protein_workbench_public import bundle_bytes, bundle_digest
import protein_workbench_public

source_root = Path(__import__("os").environ["PROTEIN_WORKBENCH_SOURCE_ROOT"]).resolve()
assert source_root not in Path(core.__file__).resolve().parents
assert source_root not in Path(modules.__file__).resolve().parents
assert source_root not in Path(protein_workbench_public.__file__).resolve().parents
assert bundle_bytes().hex() == {SOURCE_PROTOCOL_BYTES.hex()!r}
assert bundle_digest() == {SOURCE_PROTOCOL_DIGEST!r}
catalog = build_discovered_frozen_catalog()
assert catalog.catalog_descriptor_bytes.hex() == {SOURCE_PORT_CATALOG_BYTES.hex()!r}
assert catalog.contract_digest == {SOURCE_PORT_CATALOG_DIGEST!r}
assert {{
    definition.type_id: definition.descriptor_bytes.hex()
    for definition in catalog.port_types
}} == {SOURCE_PORT_TYPE_BYTES!r}
assert {{
    definition.type_id: definition.contract_digest
    for definition in catalog.port_types
}} == {SOURCE_PORT_TYPE_DIGESTS!r}

registry = ModuleRegistry(TypeRegistry())
discover_modules(registry)
assert sorted(item.module_id for item in registry.list_all()) == {expected}
"""
    subprocess.run(
        [str(python), "-I", "-c", probe],
        cwd=run_dir,
        env=env,
        check=True,
    )

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server_command = [
        str(python),
        "-I",
        "-c",
        _installed_direct_server_probe(port),
    ]

    def launch_server() -> subprocess.Popen[str]:
        return subprocess.Popen(
            server_command,
            cwd=run_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    server = launch_server()
    try:
        deadline = time.monotonic() + 20
        modules_payload = None
        while time.monotonic() < deadline:
            if server.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/modules",
                    timeout=1,
                ) as response:
                    modules_payload = json.load(response)
                break
            except OSError:
                time.sleep(0.1)
        if modules_payload is None:
            output = server.communicate(timeout=5)[0]
            pytest.fail(f"Installed API did not start:\n{output}")
        assert sorted(item["module_id"] for item in modules_payload) == sorted(
            EXPECTED_MODULE_IDS
        )
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/projects",
            timeout=2,
        ) as response:
            projects = json.load(response)
        canonical = [
            project
            for project in projects
            if project["id"] == "canonical-3gb1"
        ]
        assert len(canonical) == 1
        assert canonical[0]["seed"] is True
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v2/protocol",
            timeout=2,
        ) as response:
            installed_protocol_bytes = response.read()
            installed_protocol_digest = response.headers["Digest"]
        assert installed_protocol_bytes == SOURCE_PROTOCOL_BYTES
        assert installed_protocol_digest == SOURCE_PROTOCOL_DIGEST
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v2/catalog",
            timeout=2,
        ) as response:
            installed_catalog = json.load(response)
        assert any(
            contract["reference"]["contract_kind"] == "binding"
            and contract["reference"]["contract_id"]
            == "installed.direct.local"
            for contract in installed_catalog["contracts"]
        )

        def request_json(
            method: str,
            route: str,
            payload: dict | None = None,
        ) -> dict:
            encoded = (
                json.dumps(payload).encode("utf-8")
                if payload is not None
                else None
            )
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}{route}",
                data=encoded,
                headers=(
                    {"Content-Type": "application/json"}
                    if encoded is not None
                    else {}
                ),
                method=method,
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                return json.load(response)

        project = request_json(
            "POST",
            "/api/projects",
            {"name": "installed v2 authoring"},
        )
        project_id = project["id"]
        workflow = {
            "schema_version": "2.0.0",
            "workflow_id": project_id,
            "nodes": [
                {
                    "node_id": "installed-direct",
                    "node_type_id": "installed.direct",
                    "node_type_version": "2.0.0",
                    "binding_id": "installed.direct.local",
                    "binding_version": "2.0.0",
                    "node_parameters": {},
                    "binding_parameters": {},
                }
            ],
            "edges": [],
            "contract_lock": [],
        }
        saved = request_json(
            "PUT",
            f"/api/v2/projects/{project_id}/workflow",
            {
                "expected_workflow_revision": 0,
                "workflow": workflow,
            },
        )
        loaded = request_json(
            "GET",
            f"/api/v2/projects/{project_id}/workflow",
        )
        relocked = request_json(
            "POST",
            f"/api/v2/projects/{project_id}/workflow:relock",
            {"workflow_revision": 1},
        )
        compiled = request_json(
            "POST",
            f"/api/v2/projects/{project_id}/workflow:compile",
            {
                "workflow_revision": 2,
                "workflow": relocked["workflow"],
            },
        )
        assert saved["workflow_revision"] == 1
        assert loaded == saved
        assert relocked["workflow_revision"] == 2
        assert compiled["accepted"] is True
        assert compiled["workflow_revision"] == 2
        assert "execution_plan" not in compiled
        started = request_json(
            "POST",
            f"/api/v2/projects/{project_id}/runs",
            {
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "installed-direct-request",
            },
        )
        projection = request_json(
            "GET",
            f"/api/v2/projects/{project_id}/runs/{started['run_id']}",
        )
        assert projection["status"] == "succeeded"
        assert projection["compile_id"] == compiled["compile_id"]
        assert projection["workflow_revision"] == 2
        assert projection["node_dispositions"] == [
            {
                "node_id": "installed-direct",
                "outcome": "succeeded",
                "resolution": "executed",
                "terminal_sequence": projection[
                    "node_dispositions"
                ][0]["terminal_sequence"],
                "blocked_by": [],
            }
        ]
        assert projection["outputs"][0]["values"] == ["INSTALLED_READY"]
        assert projection["artifact_index"] == []

        block_marker.write_text("block")
        interrupted = request_json(
            "POST",
            f"/api/v2/projects/{project_id}/runs",
            {
                "workflow_revision": 2,
                "compile_id": compiled["compile_id"],
                "client_request_id": "installed-restart-request",
            },
        )
        interrupted_run_id = interrupted["run_id"]
        entered_marker = block_marker.with_suffix(".started")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not entered_marker.exists():
            time.sleep(0.05)
        assert entered_marker.is_file()

        websocket_url = (
            f"ws://127.0.0.1:{port}/api/v2/projects/{project_id}/runs/"
            f"{interrupted_run_id}/events"
        )
        with connect(
            websocket_url,
            open_timeout=5,
            close_timeout=2,
        ) as websocket:
            first_delivery = []
            while True:
                message = json.loads(websocket.recv(timeout=5))
                first_delivery.append(message)
                if message["event"]["type"] == "replay_complete":
                    break
        first_durable = [
            message
            for message in first_delivery
            if message["event"]["type"] not in {
                "replay_started",
                "replay_complete",
            }
        ]
        invocation_started = next(
            message
            for message in first_durable
            if message["event"]["type"] == "engine_invocation_started"
        )
        resume_cursor = first_delivery[-1]["cursor"]

        server.kill()
        server.communicate(timeout=5)
        server = launch_server()
        deadline = time.monotonic() + 20
        interrupted_projection = None
        while time.monotonic() < deadline:
            if server.poll() is not None:
                break
            try:
                interrupted_projection = request_json(
                    "GET",
                    f"/api/v2/projects/{project_id}/runs/"
                    f"{interrupted_run_id}",
                )
                break
            except OSError:
                time.sleep(0.1)
        if interrupted_projection is None:
            output = server.communicate(timeout=5)[0]
            pytest.fail(f"Restarted installed API did not recover:\n{output}")
        assert interrupted_projection["status"] == "interrupted"
        assert interrupted_projection["outputs"] == []
        assert interrupted_projection["artifact_index"] == []
        assert interrupted_projection["node_dispositions"][0]["outcome"] == (
            "interrupted"
        )

        with connect(
            f"{websocket_url}?after_sequence={resume_cursor}",
            open_timeout=5,
            close_timeout=2,
        ) as websocket:
            resumed = []
            try:
                while True:
                    resumed.append(
                        json.loads(websocket.recv(timeout=5))
                    )
            except ConnectionClosed as closed:
                assert closed.rcvd is not None
                assert closed.rcvd.code == 1000
        resumed_durable = [
            message
            for message in resumed
            if message["event"]["type"] not in {
                "replay_started",
                "replay_complete",
            }
        ]
        invocation_terminal = next(
            message
            for message in resumed_durable
            if message["event"]["type"] == "engine_invocation_terminal"
            and message["event"]["invocation_id"]
            == invocation_started["event"]["invocation_id"]
        )
        assert invocation_terminal["event"]["status"] == "outcome_unknown"
        delivered_sequences = [
            message["sequence"]
            for message in (*first_durable, *resumed_durable)
        ]
        assert len(delivered_sequences) == len(set(delivered_sequences))
        terminal_cursor = interrupted_projection["ledger_cursor"]

        block_marker.unlink()
        server.kill()
        server.communicate(timeout=5)
        server = launch_server()
        deadline = time.monotonic() + 20
        repeated_projection = None
        while time.monotonic() < deadline:
            if server.poll() is not None:
                break
            try:
                repeated_projection = request_json(
                    "GET",
                    f"/api/v2/projects/{project_id}/runs/"
                    f"{interrupted_run_id}",
                )
                break
            except OSError:
                time.sleep(0.1)
        if repeated_projection is None:
            output = server.communicate(timeout=5)[0]
            pytest.fail(f"Second installed restart did not recover:\n{output}")
        assert repeated_projection == interrupted_projection
        with connect(
            f"{websocket_url}?after_sequence={terminal_cursor}",
            open_timeout=5,
            close_timeout=2,
        ) as websocket:
            repeated_delivery = []
            try:
                while True:
                    repeated_delivery.append(
                        json.loads(websocket.recv(timeout=5))
                    )
            except ConnectionClosed as closed:
                assert closed.rcvd is not None
                assert closed.rcvd.code == 1000
        assert {
            message["event"]["type"]
            for message in repeated_delivery
        } == {"replay_started", "replay_complete"}
        assert not any((tmp_path / "cache").rglob("*"))
    finally:
        if server.poll() is None:
            server.terminate()
        try:
            server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate()
