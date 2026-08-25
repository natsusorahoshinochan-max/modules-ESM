# SoluProt-next

Project-maintained Python 3.12+ port of SoluProt for predicting soluble protein
expression in *Escherichia coli*. This port is versioned as `soluprot 1.1.0` and
does not claim to be an official upstream SoluProt 1.1.0 release.

## Build and install

Stage and build the source on the target machine while keeping the build
environment, intermediate files, and artifacts outside the checkout:

```bash
export SOLUPROT_BUILD_ROOT="$(mktemp -d)"
cp -R . "$SOLUPROT_BUILD_ROOT/source"
python3.12 -m venv "$SOLUPROT_BUILD_ROOT/environment"
"$SOLUPROT_BUILD_ROOT/environment/bin/python" -m pip install --upgrade pip build pytest
"$SOLUPROT_BUILD_ROOT/environment/bin/python" -m build --wheel \
  --outdir "$SOLUPROT_BUILD_ROOT/dist" "$SOLUPROT_BUILD_ROOT/source"
"$SOLUPROT_BUILD_ROOT/environment/bin/python" -m pip install \
  "$SOLUPROT_BUILD_ROOT/dist/soluprot-1.1.0-py3-none-any.whl"
```

Install the resulting wheel into the runtime environment:

```bash
export SOLUPROT_RUNTIME="$HOME/soluprot-runtime"
python3.12 -m venv "$SOLUPROT_RUNTIME"
"$SOLUPROT_RUNTIME/bin/python" -m pip install \
  "$SOLUPROT_BUILD_ROOT/dist/soluprot-1.1.0-py3-none-any.whl"
```

The wheel contains the Python implementation, both exported gradient-boosting
models, the E. coli reference database, and the Workbench-owned TMHMM 2.0d
asset closure. TMHMM decoders are included only for `Darwin_arm64` and
`Linux_x86_64`; the Workbench selects the exact decoder for the current
supported platform. Intel macOS and Linux ARM64 are not supported by the full
Method. USEARCH 12 remains an external target-platform executable.

The wheel currently retains the `py3-none-any` filename because its Python
packages have no CPython ABI extension and one wheel deliberately carries both
decoder data files. That filename is not a platform-support claim: readiness
admits only the two platform pairs above. A future decoder inventory or
target-specific wheel policy requires an explicit packaging-contract change.

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
(
  cd "$SOLUPROT_BUILD_ROOT/source"
  "$SOLUPROT_BUILD_ROOT/environment/bin/python" -m pytest -q tests
)
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
