"""Binding-owned platform policy for local Torch execution devices."""

from __future__ import annotations

import sys
from typing import Any


LOCAL_TORCH_DEVICE_POLICY = "cuda_on_linux_windows_cpu_elsewhere"


def expected_local_torch_device(platform_name: str | None = None) -> str:
    """Resolve the concrete device required by the local Binding policy."""
    current_platform = sys.platform if platform_name is None else platform_name
    if current_platform.startswith("linux") or current_platform == "win32":
        return "cuda"
    return "cpu"


def local_torch_device_is_available(torch_module: Any, device: str) -> bool:
    """Observe whether the exact policy-selected Torch device is usable."""
    if device == "cpu":
        return True
    if device != "cuda":
        return False
    if not torch_module.cuda.is_available():
        return False
    try:
        probe = torch_module.ones(1, device=device)
        probe.add_(1)
        torch_module.cuda.synchronize(probe.device)
    except RuntimeError:
        return False
    return str(probe.device).startswith("cuda")
