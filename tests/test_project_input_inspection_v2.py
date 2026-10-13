"""Public read-only Project Input inspection uses current scientific owners."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.catalog.builder import build_frozen_catalog
from core.project.manager import ProjectManager
from modules.protein_io.inspection import read_structure_input
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from modules.structure_transform.projections import select_chains
from modules.structure_transform.residue_axis import resolve_residue_axis
from tests.support.application import create_application
from tests.support.protocol import validate_response


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, ProjectManager, str]]:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(
        frozen_catalog_override=build_frozen_catalog((PROTEIN_IO_PACKAGE,)),
    )
    with TestClient(app) as http:
        response = http.post("/api/v2/projects", json={"name": "Inspect inputs"})
        assert response.status_code == 201, response.text
        yield http, app.state.project_manager, response.json()["id"]


def publish(
    http: TestClient, project_id: str, payload: bytes, filename: str,
) -> dict[str, Any]:
    response = http.post(f"/api/v2/projects/{project_id}/inputs", json={
        "filename": filename,
        "content_base64": base64.b64encode(payload).decode("ascii"),
    })
    assert response.status_code == 201, response.text
    validate_response("publish_project_input", 201, response.json())
    return response.json()


def test_fasta_inspection_preserves_record_order_names_and_source_without_writes(
    client: tuple[TestClient, ProjectManager, str],
) -> None:
    http, projects, project_id = client
    payload = b"\n>same name\nac d\n>same name\nacd\n>\nWY\n"
    published = publish(http, project_id, payload, "explicit-format.pdb")
    input_ref = published["project_input_ref"]
    prefix = f"/api/v2/projects/{project_id}"
    workspace = http.get(f"{prefix}/workspace").json()
    metadata = projects.require_meta(project_id)
    response = http.post(f"{prefix}/inputs/{input_ref}:inspect", json={"format": "fasta"})
    assert response.status_code == 200, response.text
    validate_response("inspect_project_input", 200, response.json())
    assert response.json() == {
        "project_id": project_id,
        "project_input_ref": input_ref,
        "content_digest": published["content_digest"],
        "format": "fasta",
        "records": [
            {"record_index": 1, "header": "same name", "display_name": "same name", "line_number": 2, "length": 3},
            {"record_index": 2, "header": "same name", "display_name": "same name", "line_number": 4, "length": 3},
            {"record_index": 3, "header": "", "display_name": "Record 3", "line_number": 6, "length": 2},
        ],
        "total_length": 8,
    }
    assert projects.read_input(project_id, input_ref)[1] == payload
    assert projects.require_meta(project_id) == metadata
    assert http.get(f"{prefix}/workspace").json() == workspace
    assert projects.stored_run_ids(project_id) == ()
    assert projects.stored_input_references(project_id) == (input_ref,)
    listed = http.get(f"{prefix}/inputs")
    validate_response("list_project_inputs", 200, listed.json())
    assert listed.json()["inputs"] == [published]


def test_headerless_fasta_has_one_source_addressed_display_record(
    client: tuple[TestClient, ProjectManager, str],
) -> None:
    http, _, project_id = client
    published = publish(http, project_id, b"\n\nac\ndE\n", "unnamed.fa")
    response = http.post(
        f"/api/v2/projects/{project_id}/inputs/{published['project_input_ref']}:inspect",
        json={"format": "fasta"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["records"] == [{
        "record_index": 1, "header": "", "display_name": "Record 1",
        "line_number": 3, "length": 4,
    }]


@pytest.mark.parametrize(("payload", "message"), [
    (b">valid\nACD\n>invalid\nAC*\n", "FASTA record 2 at line 3"),
    (b">valid\nACD\n>empty\n", "FASTA record 2 at line 3"),
    (b"ACD\n>misplaced\nACD\n", "FASTA record 1 at line 2"),
    (b"\xff", "Sequence input must be UTF-8 text"),
])
def test_invalid_fasta_reports_source_and_never_returns_partial_records(
    client: tuple[TestClient, ProjectManager, str], payload: bytes, message: str,
) -> None:
    http, projects, project_id = client
    published = publish(http, project_id, payload, "invalid.fa")
    reference = published["project_input_ref"]
    response = http.post(
        f"/api/v2/projects/{project_id}/inputs/{reference}:inspect",
        json={"format": "fasta"},
    )
    assert response.status_code == 422, response.text
    validate_response("inspect_project_input", 422, response.json())
    error = response.json()["error"]
    assert error["code"] == "project_input_invalid"
    assert message in error["message"]
    assert error["details"] == {"project_input_ref": reference, "format": "fasta"}
    assert "records" not in response.json()
    assert projects.read_input(project_id, reference)[1] == payload


def coordinate(
    serial: int, component: str, chain: str, atom: str, element: str,
    *, record: str = "ATOM",
) -> str:
    return (
        f"{record:<6}{serial:5d} {atom:^4} {component:>3} {chain}{1:4d}    "
        f"{1.0:8.3f}{2.0:8.3f}{3.0:8.3f}{1.0:6.2f}{20.0:6.2f}"
        f"{'':10}{element:>2}{'':2}"
    )


def test_pdb_inspection_lists_ordered_coordinate_chains_before_biological_selection(
    client: tuple[TestClient, ProjectManager, str],
) -> None:
    http, projects, project_id = client
    payload = ("\r\n".join([
        coordinate(1, "ALA", "Z", "CA", "C"),
        coordinate(2, "ALA", "Z", "N", "N"),
        coordinate(3, "DA", "A", "P", "P"),
        coordinate(4, "HOH", "W", "O", "O", record="HETATM"),
        "END", "",
    ])).encode("ascii")
    published = publish(http, project_id, payload, "complex.fasta")
    reference = published["project_input_ref"]
    response = http.post(
        f"/api/v2/projects/{project_id}/inputs/{reference}:inspect",
        json={"format": "pdb"},
    )
    assert response.status_code == 200, response.text
    validate_response("inspect_project_input", 200, response.json())
    assert response.json() == {
        "project_id": project_id,
        "project_input_ref": reference,
        "content_digest": published["content_digest"],
        "format": "pdb",
        "chain_ids": ["Z", "A", "W"],
    }
    selected = select_chains(read_structure_input(payload), ("Z",))
    assert resolve_residue_axis(selected).layout.residue_ids == ("Z:1",)
    assert projects.read_input(project_id, reference)[1] == payload


def test_explicit_format_is_required_and_pdb_content_failures_remain_diagnostics(
    client: tuple[TestClient, ProjectManager, str],
) -> None:
    http, _, project_id = client
    published = publish(http, project_id, b">sequence\nACD\n", "source.pdb")
    route = f"/api/v2/projects/{project_id}/inputs/{published['project_input_ref']}:inspect"
    omitted = http.post(route, json={})
    assert omitted.status_code == 400
    validate_response("inspect_project_input", 400, omitted.json())
    assert omitted.json()["error"]["details"]["field_path"] == []
    response = http.post(route, json={"format": "pdb"})
    assert response.status_code == 422, response.text
    validate_response("inspect_project_input", 422, response.json())
    assert response.json()["error"]["code"] == "project_input_invalid"
    assert response.json()["error"]["details"]["format"] == "pdb"


def test_inspection_distinguishes_missing_project_and_project_input(
    client: tuple[TestClient, ProjectManager, str],
) -> None:
    http, _, project_id = client
    for target_project, expected_code in [
        (project_id, "project_input_not_found"),
        ("missing-project", "project_not_found"),
    ]:
        response = http.post(
            f"/api/v2/projects/{target_project}/inputs/missing-input:inspect",
            json={"format": "fasta"},
        )
        assert response.status_code == 404, response.text
        validate_response("inspect_project_input", 404, response.json())
        assert response.json()["error"]["code"] == expected_code
