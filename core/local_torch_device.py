"""Platform policy for local Torch execution devices."""

from __future__ import annotations

import sys
from typing import Any


LOCAL_TORCH_DEVICE_POLICY = "cuda_on_linux_windows_cpu_elsewhere"


def expected_local_torch_device(platform_name: str | None = None) -> str:
    """Return the device required by the current platform."""
    current = sys.platform if platform_name is None else platform_name
    if current.startswith("linux") or current == "win32":
        return "cuda"
    return "cpu"


def local_torch_device_is_available(torch_module: Any, device: str) -> bool:
    """Probe the selected device without trying another device."""
    if device == "cpu":
        return True
    if device != "cuda" or not torch_module.cuda.is_available():
        return False
    try:
        probe = torch_module.ones(1, device="cuda")
        probe.add_(1)
        torch_module.cuda.synchronize(probe.device)
    except RuntimeError:
        return False
    return str(probe.device).startswith("cuda")
