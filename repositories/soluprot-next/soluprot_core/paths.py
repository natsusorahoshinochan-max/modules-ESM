from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Type

from .exceptions import (
    ModelInvalidPath,
    PdbDatabaseNotFound,
    TmhmmInvalidPath,
    UsearchInvalidPath,
)


ROOT = Path(__file__).resolve().parent.parent


class Paths:
    """Resolve packaged data and explicitly installed external tools."""

    MODEL = "data/models/grad_clf_v1_tc/model.json"
    MODEL_NO_TMHMM = "data/models/grad_clf_v1_tc_notmhmm/model.json"
    PDB_ECOLI_FA = "data/Ecoli_xray_nmr_pdb_no_nesg.fa"

    @staticmethod
    def abs_path(path: str | os.PathLike[str]) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return (ROOT / candidate).resolve()

    @staticmethod
    def check_file(path: str | os.PathLike[str], exc: Exception) -> str:
        resolved = Paths.abs_path(path)
        if not resolved.exists() or resolved.is_dir():
            raise exc
        return str(resolved)

    @staticmethod
    def check_executable(path: str | os.PathLike[str], exc: Exception) -> str:
        resolved = Path(Paths.check_file(path, exc))
        if not os.access(resolved, os.X_OK):
            raise exc
        return str(resolved)

    @staticmethod
    def command(
        cmd: str,
        explicit_path: str | None,
        exc_type: Type[Exception],
    ) -> str:
        if explicit_path:
            return Paths.check_executable(explicit_path, exc_type())

        path_cmd = shutil.which(cmd)
        if path_cmd:
            return path_cmd

        raise exc_type()

    @staticmethod
    def model(no_tmhmm: bool, model_path: str | None = None) -> str:
        if model_path is not None:
            return Paths.check_file(model_path, ModelInvalidPath())
        return Paths.check_file(
            Paths.MODEL_NO_TMHMM if no_tmhmm else Paths.MODEL,
            ModelInvalidPath(),
        )

    @staticmethod
    def pdb_db(path: str | None = None) -> str:
        return Paths.check_file(path or Paths.PDB_ECOLI_FA, PdbDatabaseNotFound())

    @staticmethod
    def usearch(path: str | None = None) -> str:
        return Paths.command("usearch", path, UsearchInvalidPath)

    @staticmethod
    def tmhmm(path: str | None = None) -> str:
        return Paths.command("tmhmm", path, TmhmmInvalidPath)
