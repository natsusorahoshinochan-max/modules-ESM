from __future__ import annotations

import argparse
import os
import sys

from .exceptions import (
    DuplicatedSid,
    InvalidAlphabet,
    MissingModelFeatures,
    ModelInvalidPath,
    ModelIsNotCompatible,
    PdbDatabaseNotFound,
    ShortSequence,
    TmhmmExecutionFailed,
    TmhmmInvalidPath,
    TmhmmParsingError,
    UsearchExcecutionFailed,
    UsearchInvalidPath,
)
from .paths import Paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Protein solubility predictor SoluProt. External tool paths may be "
            "absolute, relative to the project root, or available on PATH."
        )
    )
    parser.add_argument("--i_fa", help="Input sequences in FASTA format.", required=True)
    parser.add_argument(
        "--o_csv",
        help=(
            "Prediction results in csv format. Columns: runtime_id, fa_id, "
            "soluble."
        ),
        required=True,
    )
    parser.add_argument(
        "--tmp_dir",
        required=True,
        help=(
            "Directory for temporary results and computations. Files in this "
            "directory may be overwritten."
        ),
    )
    parser.add_argument(
        "--no_tmhmm",
        default=False,
        help=(
            "Do not run TMHMM and use the slightly less accurate model trained "
            "without TMHMM features."
        ),
        action="store_true",
    )
    parser.add_argument("--model", default=None, help="Path to exported model JSON.")
    parser.add_argument("--usearch", default=None, help="Path to USEARCH executable.")
    parser.add_argument("--tmhmm", default=None, help="Path to TMHMM executable.")
    parser.add_argument(
        "--pdb",
        default=Paths.PDB_ECOLI_FA,
        help="Path to PDB FASTA file.",
    )
    parser.add_argument(
        "--check_unknown",
        default=False,
        help="Raise error if sequence contains non-standard residues.",
        action="store_true",
    )
    parser.add_argument("--no_proc", type=int, default=1, help="Number of USEARCH threads.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not os.path.isfile(args.i_fa):
        print("Invalid path to input FASTA file.", file=sys.stderr)
        return 1

    try:
        tmhmm_path = None if args.no_tmhmm else Paths.tmhmm(args.tmhmm)
        from .features import Predictor

        pred = Predictor(
            args.i_fa,
            args.tmp_dir,
            no_tmhmm=args.no_tmhmm,
            model_path=Paths.model(args.no_tmhmm, args.model),
            usearch=Paths.usearch(args.usearch),
            tmhmm=tmhmm_path,
            pdb_db=Paths.pdb_db(args.pdb),
            check_unknown=args.check_unknown,
            usearch_threads=args.no_proc,
        )
        pred.compute_features()
        res = pred.predict()
        res.to_csv(args.o_csv)
        return 0
    except UsearchInvalidPath:
        print("Path to USEARCH is invalid:", args.usearch, file=sys.stderr)
    except TmhmmInvalidPath:
        print("Path to TMHMM is invalid:", args.tmhmm, file=sys.stderr)
    except PdbDatabaseNotFound:
        print("PDB database was not found on given path:", args.pdb, file=sys.stderr)
    except ModelInvalidPath:
        print("Model does not exist or is not an exported JSON model:", args.model, file=sys.stderr)
    except InvalidAlphabet:
        print(
            "Invalid amino acid alphabet, sequences can contain only standard amino acids.",
            file=sys.stderr,
        )
    except ShortSequence:
        print(
            "Some sequences are too short, minimum length of sequence is 20 amino acids.",
            file=sys.stderr,
        )
    except DuplicatedSid:
        print(
            "Duplicated identifier in FASTA file, each sequence must contain a unique identifier.",
            file=sys.stderr,
        )
    except UsearchExcecutionFailed:
        print("Execution of USEARCH failed.", file=sys.stderr)
    except TmhmmExecutionFailed:
        print("Execution of TMHMM failed.", file=sys.stderr)
    except TmhmmParsingError:
        print("Processing of TMHMM results failed.", file=sys.stderr)
    except ModelIsNotCompatible:
        print("Loaded model cannot be used by predictor.", file=sys.stderr)
    except MissingModelFeatures:
        print("Model requires features that are not computed by predictor.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
