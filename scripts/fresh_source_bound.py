#!/usr/bin/env python3
"""Execute one installed source-bound Workflow and retain public evidence."""

from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import sys
import time
from typing import Any


CONTRACTS = {
    "fresh-1pga": {
        "project_name": "fresh source-bound 1PGA",
        "input": "1PGA-75-gen1_0690.pdb",
        "input_digest": (
            "d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30"
        ),
        "workflow": "source-bound-1pga.workflow.json",
    },
    "fresh-2emo": {
        "project_name": "fresh source-bound 2EMO",
        "input": "2EMO.pdb",
        "input_digest": (
            "6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700"
        ),
        "workflow": "source-bound-2emo.workflow.json",
    },
    "fresh-5g53": {
        "project_name": "fresh source-bound 5G53",
        "input": "5G53.pdb",
        "input_digest": (
            "a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537"
        ),
        "workflow": "source-bound-5g53.workflow.json",
    },
}


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _remote_environment() -> tuple[dict[tuple[str, str], Any], bytes]:
    from esm.sdk.forge import (
        ESM3ForgeInferenceClient,
        SequenceStructureForgeInferenceClient,
    )
    from modules.folding.adapter import REMOTE_ESMFOLD2_MODEL
    from modules.provider_contract import read_biohub_token

    token = read_biohub_token()

    def esm3_factory(
        *,
        model_name: str,
        endpoint_id: str,
        credential_handle: str,
    ) -> Any:
        if endpoint_id != "biohub" or credential_handle != token:
            raise RuntimeError("remote ESM-3 Environment Configuration changed")
        return ESM3ForgeInferenceClient(
            model=model_name,
            token=credential_handle,
            request_timeout=180,
            max_retry_attempts=1,
        )

    def folding_factory(
        *,
        model_name: str,
        endpoint_id: str,
        credential_handle: str,
    ) -> Any:
        if (
            endpoint_id != "biohub"
            or credential_handle != token
            or model_name != REMOTE_ESMFOLD2_MODEL
        ):
            raise RuntimeError(
                "remote ESMFold2 Environment Configuration changed"
            )
        return SequenceStructureForgeInferenceClient(
            model=model_name,
            token=credential_handle,
            request_timeout=240,
            max_retry_attempts=1,
        )

    return {
        ("esm3.generate_paired.biohub_medium", "7.0.0"): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": token,
                "client_factory": esm3_factory,
            },
            "safe_fingerprint": "biohub-esm3-medium-2024-08",
            "invalidation_token": "biohub-esm3-medium-2024-08",
        },
        ("folding.fold.esmfold2_remote", "7.0.0"): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": token,
                "client_factory": folding_factory,
            },
            "safe_fingerprint": "biohub-esmfold2-fast-2026-05",
            "invalidation_token": "biohub-esmfold2-fast-2026-05",
        },
    }, token.encode()


def _environment(tier_name: str) -> tuple[dict[tuple[str, str], Any], bytes]:
    environment, credential = _remote_environment()
    if tier_name == "fresh-1pga":
        from modules.folding.simplefold_adapter import (
            SIMPLEFOLD_DEVICE,
            configured_runtime_fingerprint,
        )

        fingerprint = configured_runtime_fingerprint()
        environment[("folding.fold.simplefold_local", "6.0.0")] = {
            "values": {
                "model_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT"]
                ).resolve(),
                "esm2_source_root": Path(
                    os.environ["PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT"]
                ).resolve(),
                "esm2_model_root": Path(
                    os.environ[
                        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT"
                    ]
                ).resolve(),
                "device": SIMPLEFOLD_DEVICE,
                "resolved_runtime_fingerprint": fingerprint,
            },
            "safe_fingerprint": fingerprint,
            "invalidation_token": fingerprint,
        }
    elif tier_name == "fresh-2emo":
        from modules.proteinmpnn.adapter import (
            PROTEINMPNN_DEVICE,
            configured_runtime_fingerprint as proteinmpnn_fingerprint,
        )
        from modules.solubility.adapter import (
            configured_protein_sol_runtime_fingerprint,
        )

        mpnn_fingerprint = proteinmpnn_fingerprint()
        protein_sol_fingerprint = (
            configured_protein_sol_runtime_fingerprint()
        )
        environment[("proteinmpnn.design.local", "9.0.0")] = {
            "values": {
                "device": PROTEINMPNN_DEVICE,
                "provider_root": Path(
                    os.environ["PROTEIN_WORKBENCH_PROTEINMPNN_ROOT"]
                ).resolve(),
                "resolved_runtime_fingerprint": mpnn_fingerprint,
            },
            "safe_fingerprint": mpnn_fingerprint,
            "invalidation_token": mpnn_fingerprint,
        }
        environment[("solubility.protein_sol.local", "4.0.0")] = {
            "values": {
                "source_root": Path(
                    os.environ["PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT"]
                ).resolve(),
                "bash_executable": Path("/bin/bash"),
                "perl_executable": Path("/usr/bin/perl"),
                "resolved_runtime_fingerprint": protein_sol_fingerprint,
            },
            "safe_fingerprint": protein_sol_fingerprint,
            "invalidation_token": protein_sol_fingerprint,
        }
    return environment, credential


def _wait_terminal(client: Any, project_id: str, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 170 * 60
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
        )
        response.raise_for_status()
        projection = response.json()
        if projection["status"] in {
            "succeeded",
            "failed",
            "cancelled",
            "interrupted",
        }:
            return projection
        time.sleep(0.1)
    raise RuntimeError("source-bound Run did not terminate")


def _collect_events(client: Any, project_id: str, run_id: str) -> list[Any]:
    events = []
    with client.websocket_connect(
        f"/api/v2/projects/{project_id}/runs/{run_id}/events"
    ) as websocket:
        while True:
            event = websocket.receive_json()
            events.append(event)
            if event["event"]["type"] == "run_terminal":
                return events


def _retain_values(
    client: Any,
    root: Path,
    projection: dict[str, Any],
) -> list[dict[str, Any]]:
    from protein_workbench_public import (
        prepare_rest_request,
        validate_typed_value_response,
    )

    retained = []
    for output_index, output in enumerate(projection["outputs"]):
        for value_index in range(output["value_count"]):
            prepared = prepare_rest_request(
                "typed_value_retrieval",
                {
                    "project_id": projection["project_id"],
                    "run_id": projection["run_id"],
                    "node_id": output["node_id"],
                    "output_port": output["output_port"],
                    "value_index": value_index,
                },
            )
            response = client.request(prepared.method, prepared.route)
            response.raise_for_status()
            metadata = {
                "typed_value": {
                    "node_id": output["node_id"],
                    "output_port": output["output_port"],
                    "port_type": output["port_type"],
                    "port_content_digest": output["content_digest"],
                    "value_manifest_reference": output[
                        "value_manifest_reference"
                    ],
                    "value_index": value_index,
                    "value_count": output["value_count"],
                    "value_content_digest": response.headers["digest"],
                    "size": len(response.content),
                }
            }
            validate_typed_value_response(
                metadata,
                response.headers,
                response.content,
            )
            relative = Path("values") / f"{output_index:04d}-{value_index:04d}.bin"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(response.content)
            path.chmod(0o600)
            retained.append({
                **metadata["typed_value"],
                "bundle_path": relative.as_posix(),
            })
    return retained


def _retain_artifacts(
    client: Any,
    root: Path,
    projection: dict[str, Any],
) -> list[dict[str, Any]]:
    from protein_workbench_public import validate_artifact_response

    retained = []
    for index, artifact in enumerate(projection["artifact_index"]):
        response = client.get(
            f"/api/v2/projects/{projection['project_id']}/runs/"
            f"{projection['run_id']}/artifacts/"
            f"{artifact['artifact_reference']}"
        )
        response.raise_for_status()
        validate_artifact_response(
            {
                "artifact": artifact,
                "content_disposition": response.headers[
                    "content-disposition"
                ],
            },
            response.headers,
            response.content,
        )
        relative = Path("artifacts") / f"{index:04d}.bin"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(response.content)
        path.chmod(0o600)
        retained.append({
            **artifact,
            "bundle_path": relative.as_posix(),
            "retrieved_content_digest": _sha256(response.content),
        })
    return retained


def installed_main() -> int:
    from core import build_discovered_frozen_catalog
    from core.server import create_app
    from fastapi.testclient import TestClient
    from protein_workbench_public import (
        bundle_bytes,
        bundle_digest,
        encode_project_input_content,
    )

    tier_name = os.environ["PROTEIN_WORKBENCH_SOURCE_BOUND_TIER"]
    contract = CONTRACTS[tier_name]
    root = Path(os.environ["PROTEIN_WORKBENCH_FRESH_EVIDENCE_STAGING"])
    source_root = Path(os.environ["PW_SOURCE_ROOT"]).resolve()
    for package_name in (
        "core",
        "datatypes",
        "examples",
        "modules",
        "pdbs",
        "protein_workbench_public",
    ):
        package = sys.modules.get(package_name) or __import__(package_name)
        if Path(package.__file__).resolve().is_relative_to(source_root):
            raise RuntimeError("installed backend imported from source checkout")

    input_bytes = files("pdbs").joinpath(contract["input"]).read_bytes()
    if hashlib.sha256(input_bytes).hexdigest() != contract["input_digest"]:
        raise RuntimeError("source-bound input digest changed")
    workflow = json.loads(
        files("examples").joinpath("v2", contract["workflow"]).read_text(
            encoding="utf-8"
        )
    )
    environment, credential = _environment(tier_name)
    catalog = build_discovered_frozen_catalog()
    app = create_app(
        v2_environment_configuration=environment,
        _install_canonical_seed=False,
    )
    with TestClient(app) as client:
        protocol_response = client.get("/api/v2/protocol")
        protocol_response.raise_for_status()
        if (
            protocol_response.content != bundle_bytes()
            or protocol_response.headers["digest"] != bundle_digest()
        ):
            raise RuntimeError("installed public protocol changed")
        (root / "public-protocol.json").write_bytes(protocol_response.content)
        (root / "public-protocol.json").chmod(0o600)
        catalog_response = client.get("/api/v2/catalog")
        catalog_response.raise_for_status()
        if catalog_response.json()["catalog_contract_digest"] != (
            catalog.contract_digest
        ):
            raise RuntimeError("installed Catalog changed")
        _write_json(root / "catalog-snapshot.json", catalog_response.json())

        created = client.post(
            "/api/v2/projects",
            json={"name": contract["project_name"]},
        )
        created.raise_for_status()
        project_id = created.json()["id"]
        uploaded = client.post(
            f"/api/v2/projects/{project_id}/inputs",
            json={
                "filename": contract["input"],
                "content_base64": encode_project_input_content(input_bytes),
            },
        )
        uploaded.raise_for_status()
        if uploaded.json()["content_digest"] != (
            "sha256:" + contract["input_digest"]
        ):
            raise RuntimeError("Project Input identity changed")
        workflow["workflow_id"] = project_id
        workflow["contract_lock"] = []
        next(
            node
            for node in workflow["nodes"]
            if node["node_id"] == "import-input"
        )["node_parameters"] = {
            "project_input_ref": uploaded.json()["project_input_ref"]
        }
        committed = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={"expected_draft_revision": 0, "workflow": workflow},
        )
        committed.raise_for_status()
        started = client.post(
            f"/api/v2/projects/{project_id}/runs",
            json={
                "workflow_commit_id": committed.json()["workflow_commit_id"],
                "client_request_id": tier_name,
            },
        )
        started.raise_for_status()
        projection = _wait_terminal(
            client,
            project_id,
            started.json()["run_id"],
        )
        events = _collect_events(client, project_id, projection["run_id"])
        _write_json(root / "workflow.json", workflow)
        _write_json(root / "workflow-commit.json", committed.json())
        _write_json(root / "run-admission.json", started.json())
        _write_json(root / "run-projection.json", projection)
        _write_json(root / "events.json", events)
        _write_json(root / "typed-values.json", _retain_values(client, root, projection))
        _write_json(root / "artifacts.json", _retain_artifacts(client, root, projection))
        _write_json(root / "source-bound-receipt.json", {
            "schema_namespace": "protein-workbench-source-bound-evidence/v1",
            "tier": tier_name,
            "source_revision": os.environ[
                "PROTEIN_WORKBENCH_FRESH_SOURCE_REVISION"
            ],
            "input_content_digest": "sha256:" + contract["input_digest"],
            "workflow_content_digest": _sha256(
                files("examples").joinpath("v2", contract["workflow"]).read_bytes()
            ),
            "protocol_digest": bundle_digest(),
            "catalog_contract_digest": catalog.contract_digest,
            "run_id": projection["run_id"],
            "status": projection["status"],
        })
    for path in root.rglob("*"):
        if path.is_file() and credential in path.read_bytes():
            raise RuntimeError("credential reached retained evidence")
    return 0 if projection["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(installed_main())
