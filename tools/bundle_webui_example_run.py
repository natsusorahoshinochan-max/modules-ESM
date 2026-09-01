"""Copy one successful real WebUI example Run into the shipped fixture."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any, Literal


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".scratch" / "webui-example-run-generation-14"
RUN_ID = "run-29cd5f76ce43448b8f5b4a924d9ef58d"
DESTINATION = ROOT / "examples" / "v2" / "webui-3gb1-run"

_ObjectKind = Literal["node_manifest", "port_manifest", "raw"]


def _object_path(root: Path, digest: str) -> Path:
    return root / "v1" / "sha256" / digest[:2] / digest[2:]


def _digest(reference: str) -> str:
    return reference.removeprefix("sha256:")


def _reachable_objects(run_root: Path, object_root: Path) -> tuple[str, ...]:
    pending: list[tuple[str, _ObjectKind]] = []
    for ledger_path in sorted((run_root / "ledger").glob("*.json")):
        transaction = json.loads(ledger_path.read_text(encoding="utf-8"))
        for fact in transaction["facts"]:
            if fact["fact_type"] != "outputs_published":
                continue
            publication = fact["payload"]
            pending.append(
                (
                    _digest(publication["node_result_manifest"]["content_digest"]),
                    "node_manifest",
                )
            )
            pending.extend(
                (
                    _digest(output["value_manifest_reference"]),
                    "port_manifest",
                )
                for output in publication["outputs"]
            )
            pending.extend(
                (_digest(artifact["content_digest"]), "raw")
                for artifact in publication["artifacts"]
            )

    reachable: set[str] = set()
    while pending:
        digest, kind = pending.pop()
        if digest in reachable:
            continue
        object_path = _object_path(object_root, digest)
        if not object_path.is_file():
            raise FileNotFoundError(
                f"Run object {kind} sha256:{digest} is absent at {object_path}"
            )
        reachable.add(digest)
        if kind == "raw":
            continue
        manifest: dict[str, Any] = json.loads(
            object_path.read_text(encoding="utf-8")
        )
        if kind == "node_manifest":
            pending.extend(
                (
                    _digest(output["value_manifest"]["content_digest"]),
                    "port_manifest",
                )
                for output in manifest["outputs"]
            )
            pending.extend(
                (_digest(artifact["body"]["content_digest"]), "raw")
                for artifact in manifest["artifacts"]
            )
            continue
        pending.extend(
            (_digest(value["content_digest"]), "raw")
            for value in manifest["values"]
        )
    return tuple(sorted(reachable))


def main() -> None:
    source_run = SOURCE / "runs" / "webui-3gb1-example" / RUN_ID
    source_objects = SOURCE / "outputs" / "webui-3gb1-example" / "objects"
    shutil.copytree(
        source_run,
        DESTINATION / "run",
    )
    for digest in _reachable_objects(source_run, source_objects):
        source_path = _object_path(source_objects, digest)
        destination_path = _object_path(DESTINATION / "objects", digest)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)


if __name__ == "__main__":
    main()
