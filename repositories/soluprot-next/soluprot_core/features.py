from __future__ import annotations

import os
import subprocess as sb
import sys
from itertools import combinations_with_replacement

import numpy as np
import pandas as pd
from Bio import SeqIO
from Bio.SeqUtils import ProtParam

from feature_scripts.blast6_to_max_id_csv import process_blast6

from .exceptions import (
    DuplicatedSid,
    InvalidAlphabet,
    MissingModelFeatures,
    ShortSequence,
    TmhmmExecutionFailed,
    UsearchExcecutionFailed,
)
from .model import ExportedGradientBoostingModel
from .parsers import tmhmm_to_df


AA = "ACDEFGHIKLMNPQRSTVWY"


class Predictor:
    PRE_MONOMERS = "monomers"
    PRE_DIMERS = "dimers_comb"
    PRE_PHYSICO_CHEM = "physico_chemical"
    PRE_IDENTITY = "ecoli_usearch_identity"
    PRE_TMHMM = "tmhmm"
    MIN_SEQ_LENGTH = 20

    def __init__(
        self,
        fasta_file: str,
        tmp_dir: str,
        no_tmhmm: bool,
        model_path: str,
        usearch: str,
        pdb_db: str,
        tmhmm: str | None,
        usearch_threads: int = 1,
        check_unknown: bool = True,
    ):
        self.model = ExportedGradientBoostingModel.load(model_path)
        self.seq = self._load_sequences(fasta_file, check_unknown)
        self.features = pd.DataFrame(index=self.seq.index)
        self.tmp_dir = os.path.abspath(tmp_dir)
        os.makedirs(self.tmp_dir, exist_ok=True)
        self.fasta_path: str | None = None
        self.usearch_threads = usearch_threads
        self.usearch = usearch
        self.pdb_db = pdb_db
        self.tmhmm = tmhmm
        self.no_tmhmm = no_tmhmm

    def _load_sequences(self, fasta_file: str, check_unknown: bool) -> pd.DataFrame:
        fa_id: list[str] = []
        sequences: list[str] = []
        for record in SeqIO.parse(fasta_file, "fasta"):
            fa_id.append(record.id)
            sequence = "".join(_filter_sequence(str(record.seq), check_unknown))
            if len(sequence) < self.MIN_SEQ_LENGTH:
                raise ShortSequence()
            sequences.append(sequence)

        seq = pd.DataFrame({"sequence": sequences, "fa_id": fa_id}, index=range(len(sequences)))
        seq.index = seq.index.astype(str)
        seq.index.name = "sid"
        if seq.index.nunique() != seq.index.shape[0]:
            raise DuplicatedSid()
        return seq

    def file_path(self, file_name: str) -> str:
        return os.path.join(self.tmp_dir, file_name)

    def compute_features(self) -> None:
        self.create_fasta("query.fa")
        self._add_monomers()
        self._add_dimers()
        self._add_physico_chemical()
        if not self.no_tmhmm:
            self._add_tmhmm()
        self._add_usearch_identity()

    def predict(self, round_to: int = 4) -> pd.DataFrame:
        if len(self.features.columns) != len(self.model.order):
            raise MissingModelFeatures()
        is_null = self.features.isnull().any(axis=1)
        null_features = self.features[is_null]
        for index, row in null_features.iterrows():
            for col in null_features.columns:
                if pd.isnull(row[col]):
                    print(
                        "Warning: feature {f} can not be calculated for "
                        "sequence with id {id}, mean of training set will be "
                        "used.".format(f=col, id=index),
                        file=sys.stderr,
                    )
                    self.features.at[index, col] = self.model.features_mean[col]

        pred = self.model.predict(self.features)
        pred = np.round(pred, round_to)
        pred = np.where(pred < 0, 0, pred)
        pred = np.where(pred > 1, 1, pred)
        results = pd.DataFrame({"soluble": pred}, index=self.features.index)
        results = results.join(self.seq["fa_id"])
        results.index.name = "runtime_id"
        return results[["fa_id", "soluble"]]

    def _join(self, feature: pd.DataFrame, prefix: str) -> None:
        feature.index = feature.index.astype(str)
        feature = feature.rename(columns={col: f"{prefix}_{col}" for col in feature.columns})
        cols = feature.columns[feature.columns.isin(self.model.order)]
        feature = feature[cols]
        self.features = self.features.join(feature, how="left")

    def _add_monomers(self) -> None:
        print("Computing monomers")
        monomers = pd.DataFrame(index=self.features.index, columns=list(AA))
        for index, row in self.seq.iterrows():
            analysis = ProtParam.ProteinAnalysis(row["sequence"])
            monomers.loc[index] = amino_acids_percent(analysis)
        self._join(monomers, self.PRE_MONOMERS)

    def _add_dimers(self) -> None:
        print("Computing dimers")
        dim = DimerComb()
        dimers_comb = pd.DataFrame(index=self.features.index, columns=dim.combs)
        for index, row in self.seq.iterrows():
            dimers_comb.loc[index] = dim.get_comb_ratio(row["sequence"])
        self._join(dimers_comb, self.PRE_DIMERS)

    def _add_physico_chemical(self) -> None:
        print("Computing physico-chemical features")
        cols = [
            "fracnumcharge",
            "kr_ratio",
            "aa_helix",
            "aa_sheet",
            "aa_turn",
            "molecular_weight",
            "aromaticity",
            "avg_molecular_weight",
            "flexibility",
            "gravy",
            "isoelectric_point",
            "instability_index",
        ]
        physico_chem = pd.DataFrame(index=self.features.index, columns=cols)
        for index, row in self.seq.iterrows():
            pc_row = dict.fromkeys(cols, np.nan)
            analysis = ProtParam.ProteinAnalysis(row["sequence"])
            aa_freq = amino_acids_percent(analysis)
            pc_row["fracnumcharge"] = fracnumcharge(aa_freq)
            pc_row["kr_ratio"] = kr_ratio(aa_freq)
            h, s, t = secondary_structure_fraction(analysis)
            pc_row["aa_helix"] = h
            pc_row["aa_sheet"] = s
            pc_row["aa_turn"] = t
            pc_row["molecular_weight"] = analysis.molecular_weight()
            length = analysis.length
            pc_row["avg_molecular_weight"] = pc_row["molecular_weight"] / length
            pc_row["aromaticity"] = analysis.aromaticity()
            pc_row["flexibility"] = np.mean(analysis.flexibility())
            pc_row["gravy"] = analysis.gravy()
            pc_row["isoelectric_point"] = analysis.isoelectric_point()
            pc_row["instability_index"] = analysis.instability_index()
            physico_chem.loc[index] = pc_row
        self._join(physico_chem, self.PRE_PHYSICO_CHEM)

    def _add_usearch_identity(self, b6: str = "identity.b6") -> None:
        print("Computing identity")
        if self.fasta_path is None:
            raise UsearchExcecutionFailed()
        b6_path = self.file_path(b6)
        check_remove_file(b6_path)
        usearch_arguments = [
            self.fasta_path,
            "-db",
            self.pdb_db,
            "-id",
            "0.0",
            "-blast6out",
            b6_path,
            "-threads",
            str(self.usearch_threads),
            "-top_hits_only",
        ]
        try:
            sb.run(
                [self.usearch, "-usearch_global"] + usearch_arguments,
                check=True,
                stdout=sb.DEVNULL,
                stderr=sb.DEVNULL,
            )
        except sb.CalledProcessError as error:
            raise UsearchExcecutionFailed() from error
        if not os.path.exists(b6_path):
            raise UsearchExcecutionFailed()
        identity = process_blast6(b6_path, "sid", "identity")
        identity.set_index("sid", inplace=True)
        self._join(identity, self.PRE_IDENTITY)

    def _add_tmhmm(self, tmhmm: str = "tmhmm.tmhmm") -> None:
        print("Computing transmembrane regions")
        if self.fasta_path is None or self.tmhmm is None:
            raise TmhmmExecutionFailed()
        tmhmm_path = self.file_path(tmhmm)
        check_remove_file(tmhmm_path)
        try:
            with open(tmhmm_path, "w") as tm_f:
                sb.run(
                    [self.tmhmm, self.fasta_path, "-noplot", "-short"],
                    check=True,
                    stdout=tm_f,
                )
        except sb.CalledProcessError:
            raise TmhmmExecutionFailed()
        if not os.path.exists(tmhmm_path):
            raise TmhmmExecutionFailed()
        tm_df = tmhmm_to_df(tmhmm_path, "sid")
        tm_df.set_index("sid", inplace=True)
        self._join(tm_df, self.PRE_TMHMM)

    def create_fasta(self, file_name: str) -> None:
        file_path = self.file_path(file_name)
        with open(file_path, "w") as f_fasta:
            for index, row in self.seq.iterrows():
                f_fasta.write(f">{index}\n{row['sequence']}\n")
        self.fasta_path = file_path


class DimerComb:
    def __init__(self) -> None:
        self.combs = ["".join(c) for c in combinations_with_replacement(AA, 2)]

    def get_comb_ratio(self, sequence: str) -> dict[str, float]:
        dimers = dict.fromkeys(self.combs, 0)
        dim = sequence[0:1]
        for j in range(1, len(sequence)):
            dim += sequence[j]
            comb = dim
            reflect_dim = dim[::-1]
            if reflect_dim in dimers:
                comb = reflect_dim
            if comb in dimers:
                dimers[comb] += 1
            dim = sequence[j]
        dimers.update((comb, count / (len(sequence) - 1)) for comb, count in dimers.items())
        return dimers


def _filter_sequence(sequence: str, check_unknown: bool):
    for aa in sequence:
        if aa not in AA:
            if check_unknown:
                raise InvalidAlphabet()
        else:
            yield aa


def fracnumcharge(aa_freq: dict[str, float]) -> float:
    return aa_freq["R"] + aa_freq["K"] + aa_freq["D"] + aa_freq["E"]


def kr_ratio(aa_freq: dict[str, float]) -> float:
    if aa_freq["R"] == 0:
        return np.nan
    return aa_freq["K"] / aa_freq["R"]


def amino_acids_percent(analysis) -> dict[str, float]:
    if hasattr(analysis, "get_amino_acids_percent"):
        return analysis.get_amino_acids_percent()
    values = dict(analysis.amino_acids_percent)
    if sum(values.values()) > 1.5:
        values = {key: value / 100.0 for key, value in values.items()}
    return values


def secondary_structure_fraction(analysis) -> tuple[float, float, float]:
    return analysis.secondary_structure_fraction()


def check_remove_file(file_path: str) -> None:
    if os.path.exists(file_path):
        os.remove(file_path)
