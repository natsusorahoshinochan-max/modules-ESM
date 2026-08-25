# SoluProt-next

Project-maintained Python 3.12+ port of SoluProt for predicting soluble protein
expression in *Escherichia coli*. This port is versioned as `soluprot 1.1.0` and
does not claim to be an official upstream SoluProt 1.1.0 release.

## Build and install

Build from this source tree on the target machine:

```bash
python3.12 -m venv .venv-build
.venv-build/bin/python -m pip install --upgrade pip build
.venv-build/bin/python -m build --wheel
```

Install the resulting wheel into the runtime environment:

```bash
runtime/bin/python -m pip install dist/soluprot-1.1.0-py3-none-any.whl
```

The wheel contains the Python implementation, both exported gradient-boosting
models, the E. coli reference database, and the personal-deployment TMHMM 2.0d
asset closure. TMHMM decoders are included for `Darwin_arm64` and
`Linux_x86_64`; the Workbench selects the decoder matching `uname -s` and
`uname -m`. USEARCH 12 remains an external target-platform executable.

## Run

```bash
soluprot \
  --i_fa sequences.fasta \
  --o_csv predictions.csv \
  --tmp_dir work \
  --usearch /absolute/path/to/usearch \
  --tmhmm /absolute/path/to/tmhmm
```

For the no-TMHMM model:

```bash
soluprot \
  --i_fa sequences.fasta \
  --o_csv predictions.csv \
  --tmp_dir work \
  --usearch /absolute/path/to/usearch \
  --no_tmhmm
```

## Test

```bash
.venv-build/bin/python -m pip install pytest
.venv-build/bin/python -m pytest -q
```

The Workbench-level real Provider acceptance remains the authoritative check of
the installed USEARCH/TMHMM combination and exact scientific outputs.

## Runtime assets

- `data/models/grad_clf_v1_tc/`: full model with TMHMM features.
- `data/models/grad_clf_v1_tc_notmhmm/`: no-TMHMM model.
- `data/Ecoli_xray_nmr_pdb_no_nesg.fa`: USEARCH reference database.
- `soluprot_assets/tmhmm-2.0d/`: shared TMHMM scripts/models plus macOS ARM64
  and Linux x86-64 decoders.

See `MODERNIZATION_CHANGES.md` for the port history and scientific runtime
changes from the legacy standalone implementation.
