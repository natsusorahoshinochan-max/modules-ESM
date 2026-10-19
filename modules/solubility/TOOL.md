# Sequence solubility tools

Add **Evaluate existing sequence solubility**, bind an existing `workbench.sequence` package to its sequence input, choose an evaluator and set its tool parameters. The node evaluates complete canonical protein sequences. Results contain actual values and meanings, with the original object identity and source correspondence. See [the public format](FORMAT.md). The React node editor describes the applicable parameters and limits; the tool selector and tool parameter JSON belong to the public host interface. The result viewer displays each object's method, values, units and source.

## Deployment settings

Configure existing resources in the application's module settings. The module does not download tools, models or computing environments.

| Setting | Resource |
| --- | --- |
| `protein_sol_source` | Existing official October 2017 script directory, including the wrapper, six Perl/data companion files and `ss_propensities.txt` |
| `bash`, `perl` | Existing interpreter executables; Perl is also needed for SoluProt full's TMHMM launcher |
| `soluprot_source` | Installed maintained SoluProt port root containing `soluprot_core` and `feature_scripts` |
| `soluprot_python` | Existing Python with the port's Biopython, NumPy, pandas and tqdm dependencies |
| `usearch` | Existing USEARCH executable for SoluProt |
| `tmhmm` | Existing platform-supported TMHMM executable for SoluProt full |
| `soluprot_full_model`, `soluprot_no_tm_model` | Respective exported `model.json`, with the metadata's named arrays file beside it |
| `soluprot_database` | Existing E. coli PDB reference FASTA used by USEARCH |

## Actual methods and defaults

### SoluProt full and no-TM

The maintained [SoluProt port](../../repositories/soluprot-next/README.md) provides two distinct tools. Full calls TMHMM and uses `grad_clf_v1_tc`; no-TM passes `--no_tmhmm` and uses `grad_clf_v1_tc_notmhmm`. Select each tool and its corresponding model explicitly. Failure stops the operation.

The actual [`cli.py`](../../repositories/soluprot-next/soluprot_core/cli.py) controls the invocation: FASTA, CSV, scratch directory, model, USEARCH and reference database are passed explicitly. `threads` is a positive integer translated to `--no_proc`, default **1** from `build_parser()`. `--check_unknown` is always enabled because the task requires evaluation of the selected unchanged canonical sequence. The minimum is **20 residues**, from [`features.py`](../../repositories/soluprot-next/soluprot_core/features.py).

`soluble_probability` is the model probability, on **0–1**, of soluble expression in *Escherichia coli*. The CLI's output `soluble` column already uses the model metadata's `soluble_class`/`classes` mapping in [`model.py`](../../repositories/soluprot-next/soluprot_core/model.py). The Adapter preserves this value and records the actual mapping. The maintained port rounds its result to four decimal places in `Predictor.predict`.

### Protein-Sol

The [official source download](https://protein-sol.manchester.ac.uk/cgi-bin/utilities/download_sequence_code.php) provides `multiple_prediction_wrapper_export.sh`. Configure that extracted directory. The wrapper takes a single FASTA filename; companion scripts use their fixed feature windows and `seq_reference_data.txt` calibration.

`membrane_exclude` is a boolean, default **false** from `seq_compositions_perc_pipeline_export.pl`. True sets its actual `MEMBRANE_EXCLUDE=YES` subprocess control; the script excludes sequences whose maximum 21-residue Kyte–Doolittle window exceeds its fixed 1.6 threshold. A missing returned object causes this operation to fail explicitly. The minimum is **21 residues**, from `fasta_seq_reformat_export.pl`. That script's character cleanup is prevented from changing the selected sequence by canonical input validation before invocation. `histidine_charged` is a boolean, default **false** from both `seq_compositions_perc_pipeline_export.pl` and `seq_props_ALL_export.pl`. True passes their actual `his_charged=yes` control and treats histidine as charge +1 instead of 0 in composition and profile calculations. Whole-sequence-only auxiliary export is disabled for this task; optional STY motif neutralisation and extra vertical-output controls use their source defaults because they concern auxiliary analyses outside the exposed result. There are no CLI seed, temperature or adjustable window parameters.

`server_prediction_seq_export.pl` documents the CSV row `SEQUENCE PREDICTIONS,ID,percent-sol,scaled-sol,population-sol,pI`:

| Metric | Meaning |
| --- | --- |
| `percent_solubility` | Predicted soluble fraction on the Niwa cell-free expression percentage scale; values retain the model's actual scale, including values above 100 |
| `scaled_solubility` | `(prediction - low_group) / (top_group - low_group)`, dimensionless |
| `isoelectric_point` | Calculated sequence pI, in pH units |

The returned population-scaled value is retained as calibration context; the official reference data gives **0.446**. Fixed composition windows are **21** and **51** residues. The original complete result text preserves the additional sequence feature and 21-residue profile output.

## Public tool slot

`workbench.evaluate.sequence_solubility` takes `evaluate(request, parameters, runtime) -> SolubilityResult`. Public request/result types live in `modules.solubility.contract`. The request contains an ordered tuple of complete canonical sequences. Parameters are specific to the selected tool; unsupported names fail before process execution.

The result contains the actual method name, effective parameters, one mapping of metrics per request sequence in the same order, a completed output file relative to `runtime.workdir`, and method context. Each metric has numeric `value`, `unit` and `meaning`. A missing, repeated or unknown provider ID fails rather than partially matching objects. Exceptions fail the node. Tools honor runtime cancellation; this node has no continuation operation. Files are closed before returning and ownership transfers through the normal Delivery contract. External authors may implement this public slot and explicitly depend on this public Python contract without importing carrier internals.

Both supplied local Adapters call `protein_workbench_public.worker_process.run_worker`, which acquires the shared machine lease before starting the tool process and supervises its descendants. Configured sources remain unchanged; mutable FASTA and output files live in the carrier's operation work directory.

## Representative real verification

Prepare a JSON file with `tool`, `settings`, `objects` in the sequence format, and optional `parameters`, then run:

```bash
.venv/bin/python -m modules.solubility.verify configuration.json --output /absolute/verification-data
```

This command creates a project, supplies existing sequence objects, saves the flow, executes the selected Adapter, and reads persisted evaluation numbers. The Adapter itself uses the shared model-validation entry from [local models](../../docs/local-models.md); do not wrap this command in another lease. Use a new verification data directory for a distinct verification. The tool process runs only against explicitly configured existing resources.
