"""Durable provenance contracts for immutable Project Inputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.project import (
    CANONICAL_3GB1_PROJECT_ID,
    ProjectInputIntegrityError,
    ProjectManager,
)


_ATOM_DIGEST = (
    "sha256:e38fba8177fbb677bd5efb444debe1f1e99a26da2f3c93ae4fb06347f00fb378"
)


def test_project_input_filename_survives_manager_restart(tmp_path: Path) -> None:
    project_root = tmp_path / "projects"
    projects = ProjectManager(project_root)
    project = projects.create("durable input provenance")

    published = projects.publish_input(
        project.id,
        "input-1",
        b"ATOM\n",
        filename="来源结构 A.pdb",
    )
    restarted = ProjectManager(project_root)
    recovered, payload = restarted.read_input(project.id, "input-1")

    assert published == {
        "project_input_ref": "input-1",
        "filename": "来源结构 A.pdb",
        "size": 5,
        "content_digest": _ATOM_DIGEST,
    }
    assert recovered == published
    assert payload == b"ATOM\n"


def test_project_input_publication_is_immutable_as_one_snapshot(
    tmp_path: Path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("immutable input snapshot")
    projects.publish_input(
        project.id,
        "input-1",
        b"ATOM\n",
        filename="first.pdb",
    )

    with pytest.raises(FileExistsError):
        projects.publish_input(
            project.id,
            "input-1",
            b"CHANGED\n",
            filename="second.pdb",
        )

    recovered, payload = projects.read_input(project.id, "input-1")
    assert recovered["filename"] == "first.pdb"
    assert recovered["content_digest"] == _ATOM_DIGEST
    assert payload == b"ATOM\n"


def test_project_input_read_rejects_payload_that_disagrees_with_descriptor(
    tmp_path: Path,
) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("input integrity")
    projects.publish_input(
        project.id,
        "input-1",
        b"ATOM\n",
        filename="source.pdb",
    )
    projects.input_path(project.id, "input-1").write_bytes(b"HETATM\n")

    with pytest.raises(ProjectInputIntegrityError) as rejected:
        ProjectManager(tmp_path / "projects").read_input(
            project.id,
            "input-1",
        )
    assert rejected.value.project_input_ref == "input-1"


def test_project_input_read_rejects_nonclosed_descriptor(tmp_path: Path) -> None:
    projects = ProjectManager(tmp_path / "projects")
    project = projects.create("closed input descriptor")
    projects.publish_input(
        project.id,
        "input-1",
        b"ATOM\n",
        filename="source.pdb",
    )
    descriptor_path = (
        projects.input_path(project.id, "input-1").parent
        / "descriptor.json"
    )
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["legacy_filename"] = "source.pdb"
    descriptor_path.write_text(
        json.dumps(
            descriptor,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProjectInputIntegrityError) as rejected:
        projects.read_input(project.id, "input-1")
    assert rejected.value.project_input_ref == "input-1"


def test_canonical_seed_uses_the_same_durable_input_descriptor(
    tmp_path: Path,
) -> None:
    source = tmp_path / "3GB1-source.pdb"
    source.write_bytes(b"ATOM\n")
    project_root = tmp_path / "projects"
    projects = ProjectManager(project_root)

    installed = projects.ensure_seed_project_v2(
        input_sources={"3GB1.pdb": source},
    )
    recovered, payload = ProjectManager(project_root).read_input(
        CANONICAL_3GB1_PROJECT_ID,
        "3GB1.pdb",
    )

    assert installed is not None
    assert recovered == {
        "project_input_ref": "3GB1.pdb",
        "filename": "3GB1-source.pdb",
        "size": 5,
        "content_digest": _ATOM_DIGEST,
    }
    assert payload == b"ATOM\n"
