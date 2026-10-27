# Public generation tool call

The scientific generation module owns slot `workbench.esm3.generate` and [contract.py](contract.py):

```python
generate(request: GenerateRequest, parameters: dict, runtime) -> GenerateResult
```

Implementations depend on this public contract and runtime. The node owns input package interpretation, sample count, identities, phase sequencing, delivery encoding and continuation; the Adapter owns native input encoding, model calls, output decoding and structure-file production. Tool parameter dictionaries are passed unchanged to the selected implementation; keys and defaults are documented by that tool.

`GenerateRequest.track` selects `sequence`, `structure`, `secondary_structure`, `sasa` or `function`. `tracks` carries prepared values and gaps. Sequence and secondary structure are aligned lists of one-character values or null; coordinates are aligned lists of named-atom XYZ dictionaries or null; SASA is an aligned list of actual values or null; function annotations are `{label,start,end}` with one-based inclusive bounds. Every aligned track uses the same current position count. The Adapter translates null gaps into the selected tool's masks and named atoms into its tensor representation. Editor selections, history and editable-region flags never enter this call. Structure generation supplies the accepted full sequence with the original supplied coordinates and other tracks.

`GenerateResult` returns actual portable `tracks` using the same value/gap representation, including named coordinates, a closed `values_file` relative to workdir holding all native tracks and metrics, effective `parameters`, and `actual_seed` when applicable. The operation retains the portable tracks on every generated object so editors can read results without decoding tool-private arrays. `coordinate_role` is `absent`, `returned_coordinates` or `generated_structure`. Only the last may supply `structure_file`: a completed mmCIF representing a canonical single chain with finite atoms at every position. Missing native atoms stay absent. Native outputs that cannot meet that representation keep their complete native values and omit `structure_file`; explicit coordinate conversion reports the limitation.

Every returned file belongs to the invocation workdir, is closed before return, and remains owned by the host through reception. Nodes include these files in their Delivery. Errors raise concrete exceptions; no input repair, alternate task, invented confidence or implicit tool fallback is permitted. A call performs one native generation operation and retains the tool's documented retry behavior. Runtime cancellation interrupts local workers; completed results remain eligible for explicit task acceptance. The Adapter does not manage batches or phase continuation.

The ESM3 local and Biohub implementations and their native controls are documented in [ESM3 TOOL.md](../esm3/TOOL.md). Backbone design and independent sequence scoring use the separate shared [ProteinMPNN contract](../proteinmpnn/TOOL.md#public-reusable-call), because their requests and result semantics differ.
