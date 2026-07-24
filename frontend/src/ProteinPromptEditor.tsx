import { useState, useCallback } from "react";
import "./ProteinPromptEditor.css";

const AA_CODES = [
  "A", "C", "D", "E", "F", "G", "H", "I", "K", "L",
  "M", "N", "P", "Q", "R", "S", "T", "V", "W", "Y",
];

const SS_CODES = ["H", "B", "E", "G", "I", "T", "S", "-"];

export interface ResidueRow {
  index: number;
  chain: string;
  aminoAcid: string | null;
  structureVisible: boolean;
  secondaryStructure: string | null;
  sasa: number | null;
}

export interface FunctionAnnotation {
  label: string;
  start: number;
  end: number;
}

interface Props {
  residues: ResidueRow[];
  annotations: FunctionAnnotation[];
  onResiduesChange: (residues: ResidueRow[]) => void;
  onAnnotationsChange: (annotations: FunctionAnnotation[]) => void;
}

export default function ProteinPromptEditor({
  residues,
  annotations,
  onResiduesChange,
  onAnnotationsChange,
}: Props) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [editAA, setEditAA] = useState<string>("");
  const [newLabel, setNewLabel] = useState("");
  const [newStart, setNewStart] = useState(1);
  const [newEnd, setNewEnd] = useState(1);

  const updateResidue = useCallback(
    (idx: number, field: keyof ResidueRow, value: unknown) => {
      const updated = residues.map((r, i) =>
        i === idx ? { ...r, [field]: value } : r
      );
      onResiduesChange(updated);
    },
    [residues, onResiduesChange]
  );

  const insertAfter = useCallback(
    (idx: number) => {
      const newRes: ResidueRow = {
        index: 0,
        chain: residues.length > 0 ? residues[0].chain : "A",
        aminoAcid: null,
        structureVisible: false,
        secondaryStructure: null,
        sasa: null,
      };
      const updated = [...residues];
      updated.splice(idx + 1, 0, newRes);
      // Re-index
      const reindexed = updated.map((r, i) => ({ ...r, index: i + 1 }));
      onResiduesChange(reindexed);
    },
    [residues, onResiduesChange]
  );

  const insertBefore = useCallback(
    (idx: number) => {
      if (idx === 0) {
        const newRes: ResidueRow = {
          index: 0,
          chain: residues.length > 0 ? residues[0].chain : "A",
          aminoAcid: null,
          structureVisible: false,
          secondaryStructure: null,
          sasa: null,
        };
        const updated = [newRes, ...residues];
        const reindexed = updated.map((r, i) => ({ ...r, index: i + 1 }));
        onResiduesChange(reindexed);
      } else {
        insertAfter(idx - 1);
      }
    },
    [residues, onResiduesChange, insertAfter]
  );

  const deleteSelected = useCallback(() => {
    if (selectedIndex === null || residues.length <= 1) return;
    const updated = residues.filter((_, i) => i !== selectedIndex);
    const reindexed = updated.map((r, i) => ({ ...r, index: i + 1 }));
    onResiduesChange(reindexed);
    setSelectedIndex(null);
  }, [selectedIndex, residues, onResiduesChange]);

  const maskSelected = useCallback(() => {
    if (selectedIndex === null) return;
    updateResidue(selectedIndex, "aminoAcid", null);
  }, [selectedIndex, updateResidue]);

  const setAllTo = useCallback(() => {
    if (!editAA) return;
    const updated = residues.map((r) => ({
      ...r,
      aminoAcid: editAA === "mask" ? null : editAA,
    }));
    onResiduesChange(updated);
  }, [editAA, residues, onResiduesChange]);

  const addAnnotation = useCallback(() => {
    if (!newLabel.trim()) return;
    onAnnotationsChange([
      ...annotations,
      { label: newLabel.trim(), start: newStart, end: newEnd },
    ]);
    setNewLabel("");
  }, [newLabel, newStart, newEnd, annotations, onAnnotationsChange]);

  const removeAnnotation = useCallback(
    (idx: number) => {
      onAnnotationsChange(annotations.filter((_, i) => i !== idx));
    },
    [annotations, onAnnotationsChange]
  );

  return (
    <div className="prompt-editor">
      <div className="prompt-editor-header">
        <h3>ProteinPrompt Editor</h3>
      </div>

      {/* Toolbar */}
      <div className="prompt-toolbar">
        <button onClick={() => selectedIndex !== null && insertBefore(selectedIndex)}
          disabled={selectedIndex === null}>
          Insert Before
        </button>
        <button onClick={() => selectedIndex !== null && insertAfter(selectedIndex)}
          disabled={selectedIndex === null}>
          Insert After
        </button>
        <button onClick={deleteSelected} disabled={selectedIndex === null || residues.length <= 1}>
          Delete
        </button>
        <button onClick={maskSelected} disabled={selectedIndex === null}>
          Mask
        </button>
        <span className="toolbar-sep-inline" />
        <select value={editAA} onChange={(e) => setEditAA(e.target.value)}
          className="set-all-select">
          <option value="">Set All To...</option>
          <option value="mask">(mask)</option>
          {AA_CODES.map((aa) => (
            <option key={aa} value={aa}>{aa}</option>
          ))}
        </select>
        <button onClick={setAllTo} disabled={!editAA}>Apply</button>
      </div>

      {/* Residue Table */}
      <div className="residue-table-wrap">
        <table className="residue-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Chain</th>
              <th>Amino Acid</th>
              <th>Vis</th>
              <th>2&deg; Str</th>
              <th>SASA</th>
            </tr>
          </thead>
          <tbody>
            {residues.map((r, i) => (
              <tr
                key={i}
                className={selectedIndex === i ? "selected" : ""}
                onClick={() => setSelectedIndex(i)}
              >
                <td className="idx-cell">{r.index}</td>
                <td>{r.chain}</td>
                <td>
                  <select
                    value={r.aminoAcid ?? "mask"}
                    onChange={(e) =>
                      updateResidue(i, "aminoAcid", e.target.value === "mask" ? null : e.target.value)
                    }
                  >
                    <option value="mask">(mask)</option>
                    {AA_CODES.map((aa) => (
                      <option key={aa} value={aa}>{aa}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={r.structureVisible}
                    onChange={(e) => updateResidue(i, "structureVisible", e.target.checked)}
                  />
                </td>
                <td>
                  <select
                    value={r.secondaryStructure ?? ""}
                    onChange={(e) =>
                      updateResidue(i, "secondaryStructure", e.target.value || null)
                    }
                  >
                    <option value="">--</option>
                    {SS_CODES.map((ss) => (
                      <option key={ss} value={ss}>{ss === "-" ? "coil" : ss}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="number"
                    className="sasa-input"
                    value={r.sasa ?? ""}
                    placeholder="--"
                    step="0.1"
                    onChange={(e) =>
                      updateResidue(
                        i,
                        "sasa",
                        e.target.value === "" ? null : parseFloat(e.target.value)
                      )
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Function Annotations */}
      <div className="annotations-section">
        <h4>Function Annotations</h4>
        {annotations.length === 0 && (
          <p className="empty-hint">No annotations defined.</p>
        )}
        <ul className="annotation-list">
          {annotations.map((ann, i) => (
            <li key={i}>
              <span className="ann-label">{ann.label}</span>
              <span className="ann-range">
                [{ann.start}–{ann.end}]
              </span>
              <button
                className="ann-remove-btn"
                onClick={() => removeAnnotation(i)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        <div className="annotation-add">
          <input
            type="text"
            placeholder="Label"
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
          />
          <input
            type="number"
            placeholder="Start"
            value={newStart}
            min={1}
            onChange={(e) => setNewStart(parseInt(e.target.value, 10) || 1)}
          />
          <input
            type="number"
            placeholder="End"
            value={newEnd}
            min={1}
            onChange={(e) => setNewEnd(parseInt(e.target.value, 10) || 1)}
          />
          <button onClick={addAnnotation}>Add</button>
        </div>
      </div>
    </div>
  );
}
