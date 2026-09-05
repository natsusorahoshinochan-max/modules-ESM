"""SS8 and missing-value normalization (spec §6).

Prompt admission: ``-`` becomes canonical ``C``; ``_`` and raw DSSP ``P`` are
invalid prompt inputs. Observed
DSSP annotation: ``P`` -> ``C``, ``_`` -> None, ``?`` -> None, ``H/B/E/G/I/T/S/C``
pass through.
"""

from __future__ import annotations

import pytest

from modules.prompt_authoring.recipe import _normalize_ss8_token
from modules.structure_annotation.adapter import _SS8_FROM_DSSP


def test_prompt_admission_dash_becomes_canonical_c() -> None:
    assert _normalize_ss8_token("-") == "C"


def test_prompt_admission_rejects_underscore() -> None:
    with pytest.raises(ValueError):
        _normalize_ss8_token("_")


def test_prompt_admission_rejects_raw_dssp_p() -> None:
    with pytest.raises(ValueError):
        _normalize_ss8_token("P")


def test_prompt_admission_passes_canonical_states() -> None:
    for state in ("H", "B", "E", "G", "I", "T", "S", "C"):
        assert _normalize_ss8_token(state) == state


def test_dssp_observed_poly_proline_maps_to_c() -> None:
    assert _SS8_FROM_DSSP["P"] == "C"


def test_dssp_observed_missing_markers_become_null() -> None:
    assert _SS8_FROM_DSSP["_"] is None
    assert _SS8_FROM_DSSP["?"] is None


def test_dssp_observed_coil_markers_become_c() -> None:
    assert _SS8_FROM_DSSP["."] == "C"


def test_dssp_observed_canonical_states_pass_through() -> None:
    for state in ("H", "B", "E", "G", "I", "T", "S", "C"):
        assert _SS8_FROM_DSSP[state] == state
