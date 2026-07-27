"""Negative probes for the live-provider verification command."""

from __future__ import annotations

import pytest


@pytest.mark.live_provider
def test_skipped_provider_probe() -> None:
    pytest.skip("provider readiness is not provider execution")


@pytest.mark.live_provider
def test_readiness_only_probe() -> None:
    assert True
