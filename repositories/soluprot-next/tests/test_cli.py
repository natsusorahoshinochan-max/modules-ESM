import csv
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


def test_module_cli_help_works_without_runtime_dependencies():
    result = subprocess.run(
        [sys.executable, "-m", "soluprot_core.cli", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--i_fa" in result.stdout
    assert "--no_tmhmm" in result.stdout


@pytest.mark.skipif(importlib.util.find_spec("Bio") is None, reason="BioPython is not installed")
def test_full_cli_matches_configured_regression_fixture(tmp_path):
    usearch = os.environ.get("SOLUPROT_TEST_USEARCH") or shutil.which("usearch")
    tmhmm = os.environ.get("SOLUPROT_TEST_TMHMM") or shutil.which("tmhmm")
    if usearch is None or tmhmm is None:
        pytest.skip("configured USEARCH/TMHMM executables are not available")

    output = tmp_path / "test.csv"
    tmp_dir = tmp_path / "work"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "soluprot_core.cli",
            "--i_fa",
            "data/test.fa",
            "--o_csv",
            str(output),
            "--tmp_dir",
            str(tmp_dir),
            "--usearch",
            usearch,
            "--tmhmm",
            tmhmm,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    with open(ROOT / "data" / "test.csv", newline="") as expected_file:
        expected = list(csv.DictReader(expected_file))
    with open(output, newline="") as actual_file:
        actual = list(csv.DictReader(actual_file))
    assert [(row["fa_id"], row["soluble"]) for row in actual] == [
        (row["fa_id"], row["soluble"]) for row in expected
    ]
