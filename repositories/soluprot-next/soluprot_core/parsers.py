from __future__ import annotations

import pandas as pd

from .exceptions import TmhmmParsingError


def tmhmm_to_df(tmhmm_path: str, id_col: str) -> pd.DataFrame:
    f_count = 5
    df_dict = {id_col: [], "len": [], "ExpAA": [], "First60": [], "PredHel": [], "Topology": []}
    with open(tmhmm_path, "r") as tm_f:
        for line in tm_f:
            line = line.rstrip()
            values = line.split("\t")
            seq_id, features = values[0], values[1:]
            df_dict[id_col].append(seq_id)
            for feature in features:
                key, val = feature.split("=")
                df_dict[key].append(val)
            if len(features) != f_count:
                raise TmhmmParsingError()
    df = pd.DataFrame(df_dict)
    df.rename(
        columns={
            "ExpAA": "exp_aa",
            "First60": "first_60",
            "PredHel": "pred_hel",
            "Topology": "topology",
        },
        inplace=True,
    )
    return df

