# Backend-only deployment

This deployment contract targets a second macOS or Linux machine. No frontend
is built or installed. The bundled full SoluProt Method is supported only on
macOS ARM64 and Linux x86-64 because those are the decoder pairs carried by its
wheel and subject to their target-machine Provider gates.

## 1. Install the Workbench

Use Python 3.12, `uv`, and the current checkout. Install the project and the
Provider and verification dependencies required by this deployment contract:

```bash
git clone <repository-url> protein-workbench
cd protein-workbench
uv sync --frozen --extra dev --extra providers
```

Select stable absolute data and Provider roots outside the checkout. These shell
variables are operator-selected examples, not universal installation locations:

```bash
export PROTEIN_WORKBENCH_DATA_ROOT="$HOME/protein-workbench-data"
export WORKBENCH_PROVIDER_ROOT="$HOME/protein-workbench-providers"
```

The server derives its Project, Cache, output, Run, and Provider runtime roots
from `PROTEIN_WORKBENCH_DATA_ROOT`; it does not derive storage from the process
working directory.

Install only the Provider sources and assets required by the Workflows that will
run on that machine. The required operational locations and resource roles are listed in
[`provider-install-contract.md`](provider-install-contract.md).

## 2. Build SoluProt-next on the target machine

Use one Provider root with the layout consumed by
`PROTEIN_WORKBENCH_SOLUPROT_ROOT`:

```bash
export PROTEIN_WORKBENCH_SOLUPROT_ROOT="$WORKBENCH_PROVIDER_ROOT/soluprot"

python3.12 -m venv \
  "$PROTEIN_WORKBENCH_SOLUPROT_ROOT/var/environments/soluprot"

uv build --wheel \
  --out-dir /tmp/soluprot-dist \
  repositories/soluprot-next

"$PROTEIN_WORKBENCH_SOLUPROT_ROOT/var/environments/soluprot/bin/python" \
  -m pip install /tmp/soluprot-dist/soluprot-1.1.0-py3-none-any.whl
```

Install USEARCH 12 for the target platform at:

```text
$PROTEIN_WORKBENCH_SOLUPROT_ROOT/var/tools/soluprot/usearch
```

The source-built wheel includes TMHMM 2.0d scripts, model files, and decoders for
`Darwin_arm64` and `Linux_x86_64`. The full Method selects the exact decoder for
the current supported platform from the installed wheel; no separate TMHMM root
is configured. Intel macOS and Linux ARM64 are not supported by the full Method.
SoluProt no-TM requires only USEARCH and does not enter TMHMM.

## 3. Configure other Providers

Set only the variables needed by the selected Workflows:

```bash
export PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT="$WORKBENCH_PROVIDER_ROOT/protein-sol"
export PROTEIN_WORKBENCH_PROTEINMPNN_ROOT="$WORKBENCH_PROVIDER_ROOT/ProteinMPNN"
export PROTEIN_WORKBENCH_MKDSSP_BINARY="$(command -v mkdssp)"

export PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT="$WORKBENCH_PROVIDER_ROOT/models/ESMFold2"
export PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT="$WORKBENCH_PROVIDER_ROOT/models/ESMC-6B"

export PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT="$WORKBENCH_PROVIDER_ROOT/models/simplefold"
export PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT="$WORKBENCH_PROVIDER_ROOT/facebook-esm"
export PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT="$WORKBENCH_PROVIDER_ROOT/models/esm2"

export PROTEIN_WORKBENCH_ESM3_MODEL_ROOT="$WORKBENCH_PROVIDER_ROOT/models/esm3-sm-open-v1-47f0545"
export PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE="$HOME/protein-workbench-private/biohub-token"
```

Every configured root is expanded once and must be absolute. Local ESM-3 reads
the configured snapshot directly from `PROTEIN_WORKBENCH_ESM3_MODEL_ROOT`; it does
not inspect `HF_HUB_CACHE`, `HF_HOME`, or their internal cache layout. The
Biohub credential file must be owned by the current user and readable only by
that user.

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
installed on that machine. SoluProt, Protein-Sol, and mkdssp Readiness checks
their declared configured paths, required files, package discoverability, and
executable presence. It does not import or load models, execute binaries, hash
source or assets, require Git/PEP 610 identity, or require executable bytes to
match a macOS/ARM64 machine; real-Provider tiers validate the scientific routes.
