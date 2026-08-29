"""Provider execution contract — ESMFold2 CCD binding (#78).

The local ESMFold2 route must read CCD data only from the admitted model root.
``_admitted_ccd_root`` pre-populates the SDK's process CCD cache from the
admitted root with any ``ESMCFOLD_CCD_PATH`` override removed, so the SDK's
``load_ccd`` never reads an env-selected or downloaded root.
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import pytest


def _write_ccd(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(payload, handle)


def _reset_ccd_cache() -> None:
    import esm.models.esmfold2.conformers as conformers

    conformers._CCD_MOLECULES = None
    for cache in (
        conformers._CCD_CONFORMERS,
        conformers._CCD_ATOM_CACHE,
        conformers._CCD_BONDS_CACHE,
        conformers._CCD_LEAVING_ATOMS_CACHE,
        conformers._IDEALIZED_POS_CACHE,
        conformers._LIGAND_IDEALIZED_POS_CACHE,
    ):
        cache.clear()


def test_admitted_ccd_root_ignores_esmcfold_ccd_path_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ambient ESMCFOLD_CCD_PATH must not select another root (#78)."""
    import esm.models.esmfold2.conformers as conformers
    from modules.folding.esmfold2_local import _admitted_ccd_root

    admitted_root = tmp_path / "admitted"
    decoy_root = tmp_path / "decoy"
    _write_ccd(admitted_root / "ccd.pkl", {"comp": "admitted"})
    _write_ccd(decoy_root / "ccd.pkl", {"comp": "decoy"})

    _reset_ccd_cache()
    monkeypatch.setenv("ESMCFOLD_CCD_PATH", str(decoy_root / "ccd.pkl"))

    with _admitted_ccd_root(admitted_root):
        assert conformers._CCD_MOLECULES == {"comp": "admitted"}

    # The ambient override is restored after the scoped admission.
    assert os.environ.get("ESMCFOLD_CCD_PATH") == str(decoy_root / "ccd.pkl")


def test_admitted_ccd_root_replaces_every_foreign_cache_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All process CCD state is rebound to the one admitted model root."""
    import esm.models.esmfold2.conformers as conformers
    from modules.folding.esmfold2_local import _admitted_ccd_root

    _write_ccd(tmp_path / "ccd.pkl", {"comp": "admitted"})
    conformers._CCD_MOLECULES = {"comp": "foreign"}
    conformers._CCD_CONFORMERS["foreign"] = {"CA": object()}
    conformers._CCD_ATOM_CACHE["foreign"] = [("CA", "C", 0)]
    conformers._CCD_BONDS_CACHE["foreign"] = [("CA", "CB")]
    conformers._CCD_LEAVING_ATOMS_CACHE["foreign"] = {"OXT"}
    conformers._IDEALIZED_POS_CACHE[(0, "CA")] = None
    conformers._LIGAND_IDEALIZED_POS_CACHE[("foreign", "CA")] = None
    monkeypatch.setenv("ESMCFOLD_CCD_PATH", "/nonexistent/decoy.pkl")

    with _admitted_ccd_root(tmp_path):
        assert conformers._CCD_MOLECULES == {"comp": "admitted"}
        assert conformers._CCD_CONFORMERS == {}
        assert conformers._CCD_ATOM_CACHE == {}
        assert conformers._CCD_BONDS_CACHE == {}
        assert conformers._CCD_LEAVING_ATOMS_CACHE == {}
        assert conformers._IDEALIZED_POS_CACHE == {}
        assert conformers._LIGAND_IDEALIZED_POS_CACHE == {}

    assert os.environ.get("ESMCFOLD_CCD_PATH") == "/nonexistent/decoy.pkl"


def test_admitted_ccd_root_ignores_import_time_ccd_pickle_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ESMCFOLD_CCD_PATH captured at import must not select another root (#78)."""
    import esm.models.esmfold2.conformers as conformers
    from modules.folding.esmfold2_local import _admitted_ccd_root

    admitted_root = tmp_path / "admitted"
    decoy_root = tmp_path / "decoy"
    _write_ccd(admitted_root / "ccd.pkl", {"comp": "admitted"})
    _write_ccd(decoy_root / "ccd.pkl", {"comp": "decoy"})

    _reset_ccd_cache()
    # Simulate ESMCFOLD_CCD_PATH captured at SDK import time.
    conformers.CCD_PICKLE_PATH = decoy_root / "ccd.pkl"

    with _admitted_ccd_root(admitted_root):
        assert conformers._CCD_MOLECULES == {"comp": "admitted"}

    # The import-time capture is restored after the scoped admission.
    assert conformers.CCD_PICKLE_PATH == decoy_root / "ccd.pkl"


def test_admitted_ccd_root_restores_capture_after_load_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A load failure still restores the neutralized import-time capture."""
    import esm.models.esmfold2.conformers as conformers
    from modules.folding.esmfold2_local import _admitted_ccd_root

    _reset_ccd_cache()
    decoy = tmp_path / "decoy.pkl"
    _write_ccd(decoy, {"comp": "decoy"})
    conformers.CCD_PICKLE_PATH = decoy
    # An admitted ccd.pkl that exists but cannot be unpickled.
    bad = tmp_path / "ccd.pkl"
    bad.write_bytes(b"not a pickle")

    with pytest.raises(Exception):
        with _admitted_ccd_root(tmp_path):
            pass

    assert conformers.CCD_PICKLE_PATH == decoy
