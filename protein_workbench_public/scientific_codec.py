"""Public wire projections for provider-independent scientific values."""

from __future__ import annotations

from core.catalog.port_contract import _observation_context_to_canonical
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
    PairwiseObservationContext,
)


def encode_observation_context(
    value: (
        IntrinsicObservationContext
        | CalibrationObservationContext
        | PairwiseObservationContext
    ),
) -> dict[str, object]:
    """Encode one admitted context for the public protocol."""
    return _observation_context_to_canonical(value)
