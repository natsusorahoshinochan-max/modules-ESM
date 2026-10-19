# Explicit prediction to structure conversion

Factory: `modules.structure_conversion:module`. This module supplies `workbench.prediction_to_structure`, accepting only `workbench.prediction` and delivering `workbench.structure` on `structure`, and `workbench.compare_structure`, accepting only `workbench.structure` on `subject` and `workbench.reference` on `reference`.

## Target format: workbench.structure

The JSON entry contains one `structure` record with required nonempty `id`, `sequence`, `file` and `format` fields, and optional text `label`. `format` is `pdb` or `mmcif`; `file` is a declared package file key containing the complete unchanged structure bytes, including original chain identifiers, residue numbers, insertion codes and other components. `sequence` is the complete protein sequence in original file order, used by the comparison consumer to require complete residue correspondence. Object identity and label survive conversion.

Optional `generation` is an object containing existing generation information. Conversion from prediction preserves its `tool: {id, parameters}` and any supplied `input` sequence object (including source and input-position correspondence) here, separate from any later comparison relationship. This format carries no confidence or supplementary prediction outputs. Those remain available in the original prediction package. A complete example is in `sample/`.

The converter independently reads the [published prediction format](../folding/FORMAT.md). It requires exactly one object, its complete sequence, a readable nonempty PDB or mmCIF file, and the prediction tool identity and parameters. Missing required content fails explicitly. It streams the full structure to a new delivered file and leaves every source file unchanged. Converting a manifest does not run prediction or rewrite structural coordinates.

## Comparison execution and installation dependency

The C-only consumer reads this structure record independently and constructs `StructureInput`, reads its independent reference with `read_reference`, then calls `compare` from `modules.structure_comparison.api`. It requires the comparison module installed from the `protein-workbench` distribution, which also ships this conversion module in this repository. It imports no prediction producer code. A separately distributed consumer reusing these APIs must declare `protein-workbench` as an installation dependency.

The consumer uses the complete-protein TM-align operation and delivers `workbench.comparison`. Method limits, output files, metric meanings and result viewer are maintained in the [comparison format](../structure_comparison/FORMAT.md).

## Application path

Use **Compare through explicit structure conversion** to upload one independent reference, insert a converter and C-only comparison node, and connect their declared ports. Connect a prediction output to the converter's `prediction` input, or choose a historical prediction package for that input. Save and run. Read the converted structure using the generic file links and open the comparison with the comparison module's saved-overlay viewer.

For the direct source-format path, use **Compare with an independent reference** from the comparison module. Connecting prediction directly to the C-only comparison is rejected by its declared input format; the user inserts conversion explicitly.
