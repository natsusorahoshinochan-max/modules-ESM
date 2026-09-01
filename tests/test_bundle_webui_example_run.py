"""Tests for the immutable example-Run object closure bundler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.bundle_webui_example_run import _object_path, _reachable_objects


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_reachable_objects_follows_typed_manifests(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    object_root = tmp_path / "objects"
    node_digest = "1" * 64
    port_digest = "2" * 64
    value_digest = "3" * 64
    _write_json(
        run_root / "ledger" / "0001.json",
        {
            "facts": [
                {
                    "fact_type": "outputs_published",
                    "payload": {
                        "node_result_manifest": {
                            "content_digest": f"sha256:{node_digest}"
                        },
                        "outputs": [
                            {
                                "value_manifest_reference": (
                                    f"sha256:{port_digest}"
                                )
                            }
                        ],
                        "artifacts": [],
                    },
                }
            ]
        },
    )
    _write_json(
        _object_path(object_root, node_digest),
        {
            "outputs": [
                {
                    "value_manifest": {
                        "content_digest": f"sha256:{port_digest}"
                    }
                }
            ],
            "artifacts": [],
        },
    )
    _write_json(
        _object_path(object_root, port_digest),
        {
            "values": [
                {"content_digest": f"sha256:{value_digest}"}
            ]
        },
    )
    value_path = _object_path(object_root, value_digest)
    value_path.parent.mkdir(parents=True, exist_ok=True)
    value_path.write_bytes(b"value")

    assert _reachable_objects(run_root, object_root) == (
        node_digest,
        port_digest,
        value_digest,
    )


def test_reachable_objects_rejects_missing_target(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    missing_digest = "4" * 64
    _write_json(
        run_root / "ledger" / "0001.json",
        {
            "facts": [
                {
                    "fact_type": "outputs_published",
                    "payload": {
                        "node_result_manifest": {
                            "content_digest": f"sha256:{missing_digest}"
                        },
                        "outputs": [],
                        "artifacts": [],
                    },
                }
            ]
        },
    )

    with pytest.raises(FileNotFoundError, match=missing_digest):
        _reachable_objects(run_root, tmp_path / "objects")
