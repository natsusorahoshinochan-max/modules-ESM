# Backend-only deployment

This is the lightweight deployment path for a second macOS or Linux machine.
The retired frontend is not built or installed.

## 1. Install the Workbench

Use Python 3.12 and a clean checkout:

```bash
git clone <repository-url> protein-workbench
cd protein-workbench
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install '.[providers]' build
```

Install only the Provider sources and assets required by the Workflows that will
run on that machine. The complete source and asset identities are listed in
[`provider-install-contract.md`](provider-install-contract.md).

## 2. Build SoluProt-next on the target machine

Use one Provider root with the layout consumed by
`PROTEIN_WORKBENCH_SOLUPROT_ROOT`:

```bash
export PROTEIN_WORKBENCH_SOLUPROT_ROOT=/opt/protein-workbench-providers

python3.12 -m venv \
  "$PROTEIN_WORKBENCH_SOLUPROT_ROOT/var/environments/soluprot"

.venv/bin/python -m build --wheel \
  --outdir /tmp/soluprot-dist \
  repositories/soluprot-next

"$PROTEIN_WORKBENCH_SOLUPROT_ROOT/var/environments/soluprot/bin/python" \
  -m pip install /tmp/soluprot-dist/soluprot-1.1.0-py3-none-any.whl
```

Install USEARCH 12 for the target platform at:

```text
$PROTEIN_WORKBENCH_SOLUPROT_ROOT/var/tools/soluprot/usearch
```

The source-built wheel includes TMHMM 2.0d scripts, model files, and decoders for
`Darwin_arm64` and `Linux_x86_64`. The full Method selects
`decodeanhmm.<uname -s>_<uname -m>` from the installed wheel; no separate TMHMM
root is configured. SoluProt no-TM requires only USEARCH.

## 3. Configure other Providers

Set only the variables needed by the selected Workflows:

```bash
export PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT=/opt/protein-sol
export PROTEIN_WORKBENCH_PROTEINMPNN_ROOT=/opt/ProteinMPNN
export PROTEIN_WORKBENCH_MKDSSP_BINARY=/usr/local/bin/mkdssp

export PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT=/opt/models/ESMFold2
export PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT=/opt/models/ESMC-6B

export PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT=/opt/models/simplefold
export PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT=/opt/facebook-esm
export PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT=/opt/models/esm2

export PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE=/absolute/private/biohub-token
```

For local ESM-3, set `HF_HUB_CACHE` or `HF_HOME` to the cache containing the
locked snapshot. The Biohub credential file must be owned by the current user
and readable only by that user.

## 4. Start the backend

The standard CLI reads the variables above and constructs Binding-scoped
Environment Configuration automatically:

```bash
.venv/bin/protein-workbench-server --host 127.0.0.1 --port 8000
```

The server remains loopback-only. No custom launcher and no frontend process are
required.

## 5. Verify on the target machine

Run the existing tests; do not create a separate installation suite:

```bash
.venv/bin/python -m verification.backend routine
.venv/bin/python -m verification.backend deterministic-acceptance
.venv/bin/python -m verification.backend installed-soluprot
.venv/bin/python -m verification.backend installed-protein-sol
```

Run the additional existing Provider tiers corresponding to the Providers
installed on that machine. SoluProt, Protein-Sol, and mkdssp readiness use
portable runtime/version checks plus exact scientific source and asset checks;
they do not require the executable bytes to match a macOS/ARM64 machine.
