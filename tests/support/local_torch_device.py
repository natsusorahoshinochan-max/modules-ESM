"""Device isolation for provider-free runtime tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def provider_free_cpu_device_policy(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the CPU seam unless the test explicitly exercises a Provider."""
    if request.node.get_closest_marker("local_provider") is not None:
        return
    import core.local_torch_device as local_torch_device

    monkeypatch.setattr(local_torch_device.sys, "platform", "darwin")
