import os
from pathlib import Path

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
