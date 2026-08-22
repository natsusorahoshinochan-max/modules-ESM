"""Shared fixtures for exact SimpleFold Provider Asset Closures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from modules.folding.simplefold_asset_closure import (
    SimpleFoldProviderAssetClosure,
)


def build_fixture_simplefold_closure(
    closure: SimpleFoldProviderAssetClosure,
    file_sha256: Mapping[str, str],
) -> SimpleFoldProviderAssetClosure:
    """Replace production proofs with exact files and installed fixture source."""
    return replace(
        closure,
        files=tuple(
            replace(
                entry,
                sha256=file_sha256[entry.runtime_filename],
            )
            for entry in closure.files
        ),
        sources=tuple(
            replace(
                source,
                package_name="fixture",
                environment_key=None,
                runtime_group=None,
                reviewed_files=(),
                source_tree_sha256=None,
            )
            for source in closure.sources
        ),
    )


def install_fixture_source_runtime_group(
    monkeypatch: object,
    adapter_module: object,
) -> None:
    """Supply the source group removed from fixture source declarations."""
    original = adapter_module.bind_simplefold_provider_asset_closure

    def bind(
        closure: object,
        environment: Mapping[str, object],
    ):
        bound = original(closure, environment)
        source_root = environment["esm2_source_root"]
        assert isinstance(source_root, Path)
        return replace(
            bound,
            groups=(*bound.groups, ("esm2_source", source_root)),
        )

    monkeypatch.setattr(  # type: ignore[attr-defined]
        adapter_module,
        "bind_simplefold_provider_asset_closure",
        bind,
    )
