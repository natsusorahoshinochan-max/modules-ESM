# Representative real FASTA journey evidence

This is the small real-Provider acceptance run for P7's first journey in
`2026-09-17-webui-full-integration-plan.md`. It does not alter the canonical
acceptance workflows or replace their Provider gates. The other two journeys
start from a personal copy of the WebUI example, edit its Prompt, explicitly
reduce the representative sample counts, and start a fresh real Run through
the built WebUI.

## Scientific definition

The input is exactly `modules/solubility/fixtures/protein_sol_input.fasta`:
the existing Protein-Sol acceptance records `116415` and `ubiquitin`, in that
order. Their bytes are uploaded through the public immutable Project Input
operation. The production FASTA inspector and `protein_io.import_sequences`
own parsing; this command does not construct Candidates itself.

| Node | Binding and declared decision |
| --- | --- |
| import-fasta | `protein_io.import_sequences.direct`; two independent ordered sequence Candidates |
| score-solubility | `solubility.protein_sol.local`, Method `solubility.protein_sol.sequence_prediction_2017` |
| prefilter-solubility | `selection.filter.direct`; Metric `solubility.protein_sol_scaled`, partition `protein_sol_scaled`, canonical dimensionless value >= 0.446 |
| fold | `folding.fold.esmfold2_remote`, Method `folding.fold.esmfold2_fast_biohub_2026_05`; effective seed 2719001, one sample per admitted sequence |
| materialize-confidence | `structure_prediction.materialize_confidence.direct`; joins the actual confidence facts and structure Candidates |
| rank-confidence | `selection.sort.direct`; mean-residue pLDDT Utility `structure.plddt.mean_residue.esmfold2_fast_biohub_2026_05.percent_to_unit`, weight 1; descending Utility and ascending Candidate identity for ties |
| postfilter-confidence | `selection.filter.direct`; exact mean-residue pLDDT >= 70 on its canonical dimensionless 0–100 scale, applied to the original fold population |
| passing-ranked-candidates | `collection_ops.intersect_candidates.direct`; rank-confidence is candidates_a (order authority), postfilter-confidence is candidates_b, retaining passing exact Candidates in ranked order |

The prefilter explicitly selects the calibration Context
`population_scaled_solubility`, value 0.446, dimensionless, population
`niwa_non_membrane_2396`. The current Protein-Sol acceptance fixture records
scaled values 0.252 and 0.761; this explains the chosen representative input,
but the journey consumes fresh Provider observations and never injects those
expected values. The postfilter and ranking select intrinsic mean-residue
pLDDT from partition `prediction_confidence` and the exact remote folding
Method. Other metrics published in each Score Collection are explicitly
outside the selector and ignored. Missing exact observations are errors.

This journey connects ranking and the postfilter to `fold.structure_candidates`
and uses an explicit intersection to display both the threshold result and the
final ranked result. Other Selection Nodes may consume a downstream Candidate
stage and the original Scores, matching complete Candidate Data References.
The intersection applies the original-population predicate to the ranked subset
without changing Candidate identity, content, lineage, metadata or rank order.
It does not rematerialize Scores or invoke another Provider. The final
collection is `passing-ranked-candidates.candidates`; the raw threshold result
remains separately visible as `postfilter-confidence.candidates`.

The threshold 70 is an explicit journey selection criterion, not a universal
claim that retained proteins are scientifically suitable. Actual empty
Selections remain empty. Provider failures, a zero-sized prefilter that
prevents folding, or changed observations remain evidence; the command never
lowers thresholds, substitutes sequences, retries Providers, or treats an
incomplete Run as completed. There is no unresolved scientific mapping or
automatic residue correspondence in this journey.

## Public operations and retained evidence

`python -m verification.webui_journey_evidence` is a repository verification
command, using the development environment and the existing fixture file. It
requires a fresh data directory and fresh evidence directory. It loads the
normal execution profile and production application, including the same
bundled example resource as the later installed backend. The personal FASTA
Project begins without a Run. Installing the protected resource does not call a
Provider and avoids creating a different example Commit before that backend
starts.

`prepare` uses the actual public HTTP operations through an in-process HTTP
client: create Project, publish and inspect Input, save Draft and commit
Workflow. It does not start a Run. The built WebUI opens the resulting Project
and starts the actual full Run. `report` connects to that running server's
public HTTP API to read a terminal projection and published Candidate pages;
it does not create another runtime on the same data directory. It requires a
full Run and reads its original public Commit snapshot, comparing the Workflow
and scientific definitions with the preparation receipt. The WebUI may create
a new Commit ID for that same Workflow; the report preserves both the prepared
and actual Run Commit IDs. The optional `run` subcommand is an
alternative script route that prepares a new Project and starts its Run,
collecting public WebSocket events through termination. There are no test
Bindings or Provider substitutes. Do not execute both paths for this evidence.

The data directory retains the original immutable Input, Draft, verified
Commit scientific definitions, complete Run Ledger, published typed values,
artifacts, Candidate lineage, Scores and Selection evidence. The evidence
directory contains the actual request Workflow, Input inspection, Commit
receipt, admission, final public projection, stage pages and a small
`report.json` with Project/Run/Commit IDs. The receipt is saved immediately
after script Run admission (the optional `run` path also saves its public
events), so a later failure is still locatable. No environment or
credential values are copied into the report. These files are navigation
evidence; they do not replace the durable owner records in the data directory.

Run serially after the shared implementation is frozen:

```bash
.venv/bin/python -m verification.webui_journey_evidence prepare \
  --data-root /root/work/webui-integration-20260917/fasta-journey-data \
  --profile /root/work/protein-clean-20260907/evidence/execution-profile-proxy.json \
  --evidence-directory /root/work/webui-integration-20260917/evidence/fasta-journey
```

For browser acceptance, start the normal server with
`PROTEIN_WORKBENCH_DATA_ROOT` set to that same data directory and open the
reported personal Project. Inspect the two import Candidates, prefilter,
fold lineage, real Scores, ranked and postfiltered results. Exercise ZIP
export on sequence-only import results, folded structures, and a mixed
selection; compare the export manifest's exact references against the stage
pages. Use the returned Project ID as
`PROTEIN_WORKBENCH_REAL_FASTA_PROJECT_ID` and the built WebUI's URL as
`PROTEIN_WORKBENCH_REAL_UI_URL` for the real browser acceptance. After it has
finished, read the actual Run against the live backend:

```bash
.venv/bin/python -m verification.webui_journey_evidence report \
  --base-url http://127.0.0.1:8000 \
  --run-id RUN_ID_FROM_BROWSER \
  --evidence-directory /root/work/webui-integration-20260917/evidence/fasta-journey
```

Preparation alone does not claim the browser/ZIP journey has been executed.
