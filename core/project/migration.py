"""Offline whole-root copying and preparation of current saved-work readings."""

from collections.abc import Callable, Mapping
import json
import hashlib
from pathlib import Path
import shutil
import tempfile
from typing import Any

from core.execution.history_preservation import prepare_historical_reading
from core.execution.recorded_run import RecordedRun
from core.execution.results.store import ResultStore
from core.execution.results.cache import ProjectReplayIndex
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.project.storage import write_new_file_durable


DRAFT_READINGS = "draft-readings"


def _write_json(root: Path, parts: tuple[str, ...], payload: Mapping[str, Any]) -> None:
    write_new_file_durable(root, parts,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def prepare_workflow_readings(
    data_root: Path, transform: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> int:
    """Normalize all saved revisions, preserving every version and return point.

    Current application reads and writes only draft-readings. The originals in
    drafts are retained records; they are never a runtime decoding fallback.
    """
    count = 0
    for workflow_root in sorted((data_root / "projects").glob("*/workflow-v2")):
        definitions = {}
        for path in sorted((workflow_root / "commits").glob("*.json")):
            recorded = json.loads(path.read_bytes())
            commit = recorded["commit"]
            converted_commit = transform(recorded["workflow"])
            reasons = [node["preserved_configuration"]["reason"] for node in converted_commit["nodes"]
                       if node.get("preserved_configuration") is not None]
            status_name = commit["workflow_commit_id"] + ".json"
            if reasons and not (workflow_root / "commit-status" / status_name).exists():
                _write_json(workflow_root, ("commit-status", status_name),
                            {"executable": False, "reason": " ".join(dict.fromkeys(reasons))})
            for definition in commit["scientific_definitions"]:
                if definition["contract_kind"] == "node_type":
                    definitions[definition["contract_id"]] = definition["descriptor"]["node_parameters"]
        originals = sorted((workflow_root / "drafts").glob("*.json"))
        for path in originals:
            destination = workflow_root / DRAFT_READINGS / path.name
            if destination.exists():
                continue
            original = json.loads(path.read_bytes())["workflow"]
            converted = transform(original)
            for node in converted["nodes"]:
                if node.get("preserved_configuration") is not None:
                    node["preserved_configuration"]["project_input_parameters"] = [
                        name for name, declaration in definitions.get(node["node_type_id"], {}).items()
                        if declaration.get("resource_kind") == "project_input"
                    ]
            _write_json(workflow_root, (DRAFT_READINGS, path.name), {"workflow": converted})
            count += 1
        if not originals:
            continue
        workspaces = sorted((workflow_root / "workspaces").glob("*.json"))
        if workspaces:
            head = json.loads(workspaces[-1].read_bytes())
            if head["draft_revision"]:
                name = f"{head['draft_revision']:020d}.json"
                original_path = workflow_root / "drafts" / name
                if original_path.exists():
                    normalized = json.loads((workflow_root / DRAFT_READINGS / name).read_bytes())
                    if normalized != json.loads(original_path.read_bytes()):
                        revision = max(int(path.stem) for path in (workflow_root / DRAFT_READINGS).glob("*.json")) + 1
                        _write_json(workflow_root, (DRAFT_READINGS, f"{revision:020d}.json"), normalized)
                        head["draft_revision"] = revision
                        workspace_revision = int(workspaces[-1].stem) + 1
                        _write_json(workflow_root, ("workspaces", f"{workspace_revision:020d}.json"), head)
    return count


def verify_data_root(data_root: Path) -> None:
    """Read every saved input and published object before publishing the copy."""
    projects = ProjectManager(data_root / "projects", cache_root=data_root / "cache",
                              output_root=data_root / "outputs", run_root=data_root / "runs")
    results = ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects))
    for project_id in projects.stored_project_ids():
        for reference in projects.stored_input_references(project_id):
            descriptor, payload = projects.read_input(project_id, reference)
            if len(payload) != descriptor.size or "sha256:" + hashlib.sha256(payload).hexdigest() != descriptor.content_digest:
                raise ValueError("Saved Project Input failed integrity verification")
        for run_id in projects.stored_run_ids(project_id):
            reading = RecordedRun.load(projects, project_id, run_id)
            if reading is None:
                continue
            tuple(results.published_object_closure(project_id, reading.projection().publications))


def convert_data_root(
    source: Path, destination: Path,
    transform_workflow: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> Path:
    """Publish a verified new root; never change the source or active setting."""
    source = source.resolve()
    destination = destination.absolute()
    if destination.exists():
        raise FileExistsError(destination)
    if destination.resolve().is_relative_to(source):
        raise ValueError("The converted root must be outside its source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".converted-root-", dir=destination.parent))
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True)
        prepare_historical_reading(staging)
        prepare_workflow_readings(staging, transform_workflow)
        verify_data_root(staging)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination
