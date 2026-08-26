import os
import platform
from pathlib import Path
import shutil
import subprocess

import pytest

from soluprot_core.exceptions import TmhmmParsingError
from soluprot_core.parsers import tmhmm_to_df


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "decoder",
    ("decodeanhmm.Darwin_arm64", "decodeanhmm.Linux_x86_64"),
)
def test_source_distribution_contains_supported_tmhmm_decoder(decoder):
    path = ROOT / "soluprot_assets/tmhmm-2.0d/bin" / decoder

    assert path.is_file()
    assert os.access(path, os.X_OK)


def test_tmhmm_short_mode_supports_spaces_without_external_uname(tmp_path):
    source_root = ROOT / "soluprot_assets/tmhmm-2.0d"
    installed_root = tmp_path / "installed TMHMM assets"
    shutil.copytree(source_root, installed_root)
    decoder = (
        installed_root
        / "bin"
        / f"decodeanhmm.{platform.system()}_{platform.machine()}"
    )
    assert decoder.is_file()
    perl = shutil.which("perl")
    assert perl is not None

    completed = subprocess.run(
        [
            installed_root / "bin/tmhmm",
            ROOT / "data/test.fa",
            "-noplot",
            "-short",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": str(Path(perl).parent)},
    )

    assert completed.stdout.splitlines()[0] == (
        "116415\tlen=251\tExpAA=0.03\tFirst60=0.02\tPredHel=0\tTopology=o"
    )
    assert not tuple(tmp_path.glob("TMHMM_*"))


def test_tmhmm_to_df_parses_short_output(tmp_path):
    output = tmp_path / "tmhmm.out"
    output.write_text("0\tlen=25\tExpAA=1.1\tFirst60=1.1\tPredHel=0\tTopology=o\n")

    df = tmhmm_to_df(str(output), "sid")

    assert list(df.columns) == ["sid", "len", "exp_aa", "first_60", "pred_hel", "topology"]
    assert df.loc[0, "sid"] == "0"
    assert df.loc[0, "pred_hel"] == "0"


def test_tmhmm_to_df_rejects_malformed_rows(tmp_path):
    output = tmp_path / "tmhmm.out"
    output.write_text("0\tlen=25\tExpAA=1.1\n")

    with pytest.raises(TmhmmParsingError):
        tmhmm_to_df(str(output), "sid")
