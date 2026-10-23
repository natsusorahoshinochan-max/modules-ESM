# Recorded ESM3 structures and real TM-align results

These four complete comparison packages are copied from prototype commit
`815d4dbb`, under
`modules/filtering/prototype_evaluation_handoff/evidence/{,round2/}all-candidates/comparisons/original-full-{1,2}`.
Each package retains the actual subject/reference PDB, manifest and all-atom overlay.
Subjects are ESM3-generated 58-residue (round 1) and 59-residue (round 2) structures;
the explicitly supplied reference is 1PGA chain A, 56 residues.

TM-align 20210224 through tmtools 0.3.0 computed the recorded values. Both selections
are complete chain A. Reference-normalized TM-scores in directory order are
0.8263003040517922, 0.24736964768578332, 0.6120604009701297 and
0.6137247185464406. Tests use the complete files for a real batch comparison,
and use the saved original scores for combined threshold, sort and count rules.
The test does not invoke ESM3 or download model weights.
