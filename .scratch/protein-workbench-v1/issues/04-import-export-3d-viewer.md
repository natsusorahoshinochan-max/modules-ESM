# 04 — Import/Export modules and 3D structure viewer

> **Status: superseded historical v1; do not implement.** The v1 runtime was removed. This file is retained only as historical planning evidence and creates no current compatibility requirement.

**What to build:** A user imports a PDB file through the UI, sees the 3D structure rendered in an interactive molecular viewer, and can export it back to a PDB file. They can also import a FASTA sequence. This is the first real module — the `ProteinStructure` and `ProteinSequence` types defined in ticket 01 come to life, flowing through the workbench as actual data.

**Blocked by:** 03 — Project persistence and missing-module handling.

**Status:** superseded

- [ ] `Import Structure` module: input = file path parameter, output = `protein.structure`. Reads PDB text, stores it in a `ProteinStructure` dataclass with the canonical PDB string.
- [ ] `Import Sequence` module: input = file path parameter, output = `protein.sequence`. Reads FASTA, stores sequence string and residue identifiers in a `ProteinSequence` dataclass.
- [ ] `Export Structure` module: input = `protein.structure`, output = file path (written to disk). Writes the canonical PDB string to a `.pdb` file under the project's `outputs/` directory.
- [ ] `Export Sequence` module: input = `protein.sequence`, output = file path. Writes FASTA format to a file under `outputs/`.
- [ ] REST API: `POST /api/projects/{id}/inputs` (upload file, returns a reference path). `GET /api/projects/{id}/outputs/{filename}` (download exported file).
- [ ] 3D molecular viewer in UI: embed NGL Viewer. Loads PDB string directly — no server round-trip needed for rendering. Supports standard view modes (cartoon, backbone, surface, ball+stick), rotation, zoom, pan, residue selection by clicking.
- [ ] UI: "Import" button in toolbar opens file picker (`.pdb`, `.cif`, `.fasta`). On import, an Import node appears on canvas pre-configured with the file path. The 3D viewer panel opens docked beside the canvas when a ProteinStructure is produced.
- [ ] UI: "Export" context menu on any node with a structure or sequence output port.
- [ ] Tests: Import Structure reads valid PDB → produces ProteinStructure with correct PDB string. Import Sequence reads FASTA → produces ProteinSequence. Export Structure round-trip: import → export → re-import produces identical PDB. 3D viewer renders without errors (visual smoke test).
