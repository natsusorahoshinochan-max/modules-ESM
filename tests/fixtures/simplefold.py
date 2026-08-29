"""Shared fixtures for SimpleFold Provider resource declarations."""

from __future__ import annotations

from dataclasses import replace

from modules.folding.simplefold_asset_closure import (
    SimpleFoldProviderAssetClosure,
)


def build_fixture_simplefold_closure(
    closure: SimpleFoldProviderAssetClosure,
) -> SimpleFoldProviderAssetClosure:
    """Use an importable package for the fixture's installed source role."""
    return replace(
        closure,
        sources=tuple(
            replace(
                source,
                package_name="pytest",
                required_relative_files=(),
            )
            if source.package_name is not None
            else source
            for source in closure.sources
        ),
    )
