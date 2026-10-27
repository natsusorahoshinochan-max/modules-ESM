# Sequence solubility data

The module independently reads [`workbench.sequence`](../sequence_io/FORMAT.md#workbenchsequence). Each operation evaluates every supplied object in package order. Object identity, sequence, label, source and explicit residue correspondence remain unchanged. The selected tool must accept every sequence. Additional components, conditions, unsupported amino acids, incomplete supplied positions and missing input fail the operation.

## workbench.solubility

The JSON entry contains exactly `objects`, `evaluations` and `tool`. All referenced files belong to this package. Consumers can implement this format directly; `modules.solubility.formats.read_evaluations(package)` is the optional public Python reader. No source project, run, generation history or producer installation is needed to interpret the package.

`objects` contains the complete original sequence objects in input order. `evaluations` contains one entry per object, with:

- `object_id`: the supplied object ID.
- `reference: null`: these methods evaluate a sequence without a separate reference object.
- `region: null`: the value concerns the complete supplied sequence. Supplied `positions` retain their original sequence-to-source mapping; they are not per-residue solubility values.
- `method`: the actual method used, distinguishing SoluProt full, SoluProt no-TM and Protein-Sol.
- `values`: named metrics, each containing a finite numeric `value`, `unit` and explicit `meaning`.

`tool` contains the selected implementation `id`, effective calculation `parameters`, method-specific `context`, and `output`, a package file key containing the original tool result. SoluProt context records mode, configured model name, actual metadata classes and soluble class. Protein-Sol context records the population calibration returned by the tool and its fixed feature windows. Deployment paths and credentials are excluded.

The raw output uses temporary FASTA IDs `item0`, `item1`, … in the same order as `objects`. These IDs are local to this one tool invocation. Structured evaluation entries already identify the scientific objects explicitly. Protein-Sol's raw output also retains its feature and sliding-window profile lines: profile item `i` spans one-based sequence positions `i` through `i + 20`, with centers from 11 through `length - 10`; sequence source correspondence is read from the object's explicit `positions` when supplied.

Example entry (the package also contains `tool-output.txt`):

```json
{
  "objects": [{"id": "research-sequence", "sequence": "ACDEFGHIKLMNPQRSTVWYA"}],
  "evaluations": [{
    "object_id": "research-sequence", "reference": null, "region": null,
    "method": "Protein-Sol October 2017 sequence prediction",
    "values": {
      "scaled_solubility": {"value": 0.252, "unit": "dimensionless", "meaning": "Prediction scaled between the training low and top solubility groups"}
    }
  }],
  "tool": {"id": "workbench.protein_sol", "parameters": {"membrane_exclude": false, "histidine_charged": false},
    "context": {"population_scaled_solubility": 0.446, "feature_windows": [21, 51]}, "output": "tool-output.txt"}
}
```

Analysis and filtering consume the saved numeric metric associated with the explicitly selected object and method. Selecting another evaluation package expresses another evaluation choice. Solubility evaluation does not generate another sequence object or use existing generation scores as a substitute for the selected independent method.
