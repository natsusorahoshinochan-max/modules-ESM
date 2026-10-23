# Public generation tool call

The scientific generation module owns slot `workbench.esm3.generate` and [contract.py](contract.py):

```python
generate(request: GenerateRequest, parameters: dict, runtime) -> GenerateResult
```

Implementations depend on this public contract and runtime. The node owns input package interpretation, sample count, identities, phase sequencing, delivery encoding and continuation; the Adapter owns native input encoding, model calls, output decoding and structure-file production. Tool parameter dictionaries are passed unchanged to the selected implementation; keys and defaults are documented by that tool.

`GenerateRequest.track` selects `sequence`, `structure`, `secondary_structure`, `sasa` or `function`. `tracks` contains explicit sequence/Prompt and any aligned additional tracks accepted by the selected tool. A complete edited input additionally supplies `target_file`, a closed mmCIF path relative to `runtime.workdir`, and `conditions` with `sequence: [{position,residue}]` and `coordinates: [{position,atoms}]`. Positions are one-based target `label_seq_id`. The file carries the entire target, including positions without atoms; the selections specify which residues/atoms constrain this call. Sequence generation uses selected residues and `_` elsewhere. Structure generation explicitly supplies the accepted full sequence and retains the original selected coordinate conditions. Native atom arrays never cross this request boundary for edited targets.

`GenerateResult` returns actual `tracks` excluding coordinate arrays, a closed `values_file` relative to workdir holding all native tracks and metrics, effective `parameters`, and `actual_seed` when applicable. `coordinate_role` is `absent`, `input_conditions` or `generated_structure`. Only the last may supply `structure_file`: a completed mmCIF representing a canonical single chain with finite atoms at every position. Missing native atoms stay absent. Native outputs that cannot meet that representation keep their complete native values and omit `structure_file`; explicit coordinate conversion reports the limitation.

Every returned file belongs to the invocation workdir, is closed before return, and remains owned by the host through reception. Nodes include these files in their Delivery. Errors raise concrete exceptions; no input repair, alternate task, invented confidence or implicit tool fallback is permitted. A call performs one native generation operation and retains the tool's documented retry behavior. Runtime cancellation interrupts local workers; completed results remain eligible for explicit task acceptance. The Adapter does not manage batches or phase continuation.

The ESM3 local and Biohub implementations and their native controls are documented in [ESM3 TOOL.md](../esm3/TOOL.md). Backbone design and independent sequence scoring use the separate shared [ProteinMPNN contract](../proteinmpnn/TOOL.md#public-reusable-call), because their requests and result semantics differ.
