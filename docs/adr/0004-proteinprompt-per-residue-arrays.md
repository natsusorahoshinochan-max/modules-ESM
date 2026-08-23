---
status: accepted
---

# ProteinPrompt uses per-residue arrays with optional values

Each track in ProteinPrompt stores an array of length equal to the target layout,
where each position holds either a concrete value or a sentinel meaning unspecified
/ masked / not visible. The tracks are fully independent: sequence specification,
structure visibility, secondary structure status, and SASA status each have their
own array.

The SASA array is not an arbitrary non-negative conditioning scale. Every
present value is absolute per-residue solvent-accessible surface area in square
angstroms, without normalization. This quantity contract belongs to the exact
nominal `protein.prompt` and `prompt_authoring.track.sasa` Port Types. A Method
may record that it preserves or produces this unit, but Method metadata does not
define the meaning of a value accepted by either Port.

The aligned representation keeps residue identity and insertion or deletion
behavior explicit without maintaining a second packed-position index.
