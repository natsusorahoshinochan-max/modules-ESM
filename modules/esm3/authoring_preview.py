"""Explain the ESM3 Adapter's actual conditioning without invoking a model."""
from typing import Any

from datatypes.prompt import ProteinPrompt
from .adapter import describe_conditioning
from .implementation import describe_generation_compatibility


def describe_prompt(prompt: ProteinPrompt) -> dict[str, Any]:
    return {
        **describe_conditioning(prompt),
        "operations": describe_generation_compatibility(prompt),
    }
