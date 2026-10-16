"""Module-owned result export through the public result action interface."""
from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from core.catalog.builder import build_frozen_catalog
from modules.protein_io.package import MODULE_PACKAGE
from tests.support.application import create_application
from tests.support.public_runs import PublicRunClient


def test_result_action_converts_without_mutating_published_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(frozen_catalog_override=build_frozen_catalog((MODULE_PACKAGE,)))
    source = "ATOM      1  CA  GLY B  42A      1.000   2.000   3.000  1.00 20.00           C  \nEND\n"
    with TestClient(app) as http:
        client = PublicRunClient(http)
        project = http.post("/api/v2/projects", json={"name": "Structure export"}).json()["id"]
        prefix = f"/api/v2/projects/{project}"
        uploaded = http.post(f"{prefix}/inputs", json={
            "filename": "source.pdb", "content_base64": base64.b64encode(source.encode()).decode(),
        })
        assert uploaded.status_code == 201
        workflow = {"schema_version": "2.1.0", "workflow_id": project, "nodes": [{
            "node_id": "import", "node_type_id": "protein_io.import_structure",
            "binding_id": "protein_io.import_structure.direct",
            "node_parameters": {"project_input_ref": uploaded.json()["project_input_ref"]},
            "binding_parameters": {},
        }], "edges": []}
        commit = client.commit_workflow(project, workflow)
        receipt = client.start_run(project, commit["workflow_commit_id"], request_id="export")
        run = client.wait_terminal(project, receipt["run_id"])
        assert run["status"] == "succeeded"
        results = f"{prefix}/runs/{receipt['run_id']}"
        location = {"node_id": "import", "output_port": "structure_candidates", "value_index": 0}
        response = http.post(f"{results}/results:action", json={
            **location, "action_id": "protein_io.export_structure",
            "parameters": {"item_index": 0, "format": "mmcif"},
        })
        assert response.status_code == 200, response.text
        assert response.json()["format"] == "mmcif"
        from datatypes.structure_format import read_mmcif_atoms
        atom, = read_mmcif_atoms(response.json()["text"])
        assert (atom.chain_id, atom.residue_number, atom.insertion_code) == ("B", "42", "A")
        assert atom.coordinate == (1, 2, 3)
        original = http.post(f"{results}/results:structure", json={**location, "item_index": 0})
        assert original.json() == {"format": "pdb", "text": source}


def test_result_action_explains_unrepresentable_pdb_author_residue_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    app = create_application(frozen_catalog_override=build_frozen_catalog((MODULE_PACKAGE,)))
    source = """data_author_label
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_asym_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . GLY B 1 1 ? 1 2 3 1 20 A42 B 1
"""
    with TestClient(app, raise_server_exceptions=False) as http:
        client = PublicRunClient(http)
        project = http.post("/api/v2/projects", json={"name": "Author residue label"}).json()["id"]
        prefix = f"/api/v2/projects/{project}"
        uploaded = http.post(f"{prefix}/inputs", json={
            "filename": "source.cif", "content_base64": base64.b64encode(source.encode()).decode(),
        })
        assert uploaded.status_code == 201
        workflow = {"schema_version": "2.1.0", "workflow_id": project, "nodes": [{
            "node_id": "import", "node_type_id": "protein_io.import_structure",
            "binding_id": "protein_io.import_structure.direct",
            "node_parameters": {"project_input_ref": uploaded.json()["project_input_ref"]},
            "binding_parameters": {},
        }], "edges": []}
        commit = client.commit_workflow(project, workflow)
        receipt = client.start_run(project, commit["workflow_commit_id"], request_id="author-label")
        run = client.wait_terminal(project, receipt["run_id"])
        assert run["status"] == "succeeded"
        results = f"{prefix}/runs/{receipt['run_id']}"
        location = {"node_id": "import", "output_port": "structure_candidates", "value_index": 0}
        rejected = http.post(f"{results}/results:action", json={
            **location, "action_id": "protein_io.export_structure",
            "parameters": {"item_index": 0, "format": "pdb"},
        })
        assert rejected.status_code == 422, rejected.text
        assert "choose mmCIF" in rejected.text
        preserved = http.post(f"{results}/results:action", json={
            **location, "action_id": "protein_io.export_structure",
            "parameters": {"item_index": 0, "format": "mmcif"},
        })
        assert preserved.status_code == 200, preserved.text
        assert preserved.json() == {"format": "mmcif", "text": source}
        original = http.post(f"{results}/results:structure", json={**location, "item_index": 0})
        assert original.json() == {"format": "mmcif", "text": source}
