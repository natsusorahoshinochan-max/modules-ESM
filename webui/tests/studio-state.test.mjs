import test from "node:test";
import assert from "node:assert/strict";
import {
  beginDocument,
  editState,
  sequenceInput,
  insertPosition,
  toggleDeleted,
  clearValues,
  updateValues,
  selectRange,
  transformed,
  replaceOperation,
} from "../../modules/sequence_edit/ui/state.js";
const fixture = () =>
  beginDocument({
    id: "protein",
    sequence: "ACD",
    random_operations: [],
    positions: [..."ACD"].map((residue, i) => ({
      id: `p${i}`,
      residue,
      coordinates:
        i === 1 ? null : { N: [i, 0, 0], CA: [i, 1, 0], C: [i, 2, 0] },
      secondary_structure: null,
      sasa: null,
      function_annotations: [],
    })),
  });
test("sequence codes preserve X, U/O and B/Z/J, rejecting non-symbol paste without mutations", () => {
  let doc = fixture();
  for (const letter of "abcdefghijklmnopqrstuvwxyz") {
    doc = sequenceInput(doc, ["p0"], letter);
    assert.equal(doc.positions[0].residue, letter.toUpperCase());
  }
  for (const invalid of ["A-C", "A+C", "A*", "A2", "α"])
    assert.throws(() => sequenceInput(doc, ["p0"], invalid, { paste: true }));
  assert.equal(doc.positions.length, 3);
  assert.equal(doc.positions[0].residue, "Z");
  doc = sequenceInput(fixture(), ["p0"], "a c\nd", { paste: true });
  assert.equal(doc.sequence, "ACD");
  assert.throws(() =>
    sequenceInput(fixture(), ["p0"], "AAAA", { paste: true }),
  );
  assert.equal(fixture().sequence, "ACD");
});
test("track ranges and edits remain independent and clearing differs from deletion", () => {
  let doc = fixture();
  const seq = selectRange(doc.positions, "p0", "p1"),
    ss = selectRange(doc.positions, "p1", "p2");
  doc = clearValues(doc, seq, "residue");
  doc = updateValues(doc, ss, "secondary_structure", "H");
  assert.deepEqual(
    doc.positions.map((p) => p.residue),
    [null, null, "D"],
  );
  assert.deepEqual(
    doc.positions.map((p) => p.secondary_structure),
    [null, "H", "H"],
  );
  assert.deepEqual(
    doc.positions[0].coordinates,
    fixture().positions[0].coordinates,
  );
  assert.equal(editState(doc, doc.positions[0], "residue"), "cleared");
  assert.equal(editState(doc, doc.positions[0], "coordinates"), "normal");
  assert.equal(
    editState(doc, doc.positions[1], "secondary_structure"),
    "replaced",
  );
});
test("soft deletion persists content and direct input restores all other values", () => {
  let doc = updateValues(fixture(), ["p0"], "sasa", 22);
  doc = toggleDeleted(doc, ["p0"]);
  assert.equal(doc.positions.length, 3);
  assert.equal(editState(doc, doc.positions[0], "sasa"), "deleted");
  doc = sequenceInput(doc, ["p0"], "G");
  assert.equal(doc.positions[0].deleted, false);
  assert.equal(doc.positions[0].sasa, 22);
  assert.equal(editState(doc, doc.positions[0], "residue"), "replaced");
  doc = sequenceInput(doc, ["p0"], "A");
  assert.equal(editState(doc, doc.positions[0], "residue"), "normal");
});
test("inserted positions stay green after editing and restore; numbering preserves columns", () => {
  const insertion = insertPosition(fixture(), "p0");
  let doc = insertion.document;
  assert.equal(doc.positions.length, 4);
  assert.equal(doc.positions[1].coordinates, null);
  assert.equal(editState(doc, doc.positions[1], "residue"), "inserted");
  doc = sequenceInput(doc, [insertion.id], "U");
  doc = toggleDeleted(doc, [insertion.id]);
  assert.equal(editState(doc, doc.positions[1], "residue"), "deleted");
  doc = toggleDeleted(doc, [insertion.id]);
  assert.equal(editState(doc, doc.positions[1], "residue"), "inserted");
  assert.equal(doc.positions[1].residue, "U");
  assert.equal(replaceOperation(doc).rows.length, 4);
});
test("coordinate transforms move entire residues, leave missing coordinates and other tracks intact", () => {
  const before = fixture(),
    moved = transformed(before, ["p0", "p1"], [2, 3, 4]);
  assert.deepEqual(moved.positions[0].coordinates, {
    N: [2, 3, 4],
    CA: [2, 4, 4],
    C: [2, 5, 4],
  });
  assert.equal(moved.positions[1].coordinates, null);
  assert.deepEqual(moved.positions[2], before.positions[2]);
  assert.equal(moved.sequence, before.sequence);
  const rotated = transformed(before, ["p0"], [0, 0, 0], [0, 0, 1], Math.PI);
  assert.ok(Math.abs(rotated.positions[0].coordinates.N[1] - 2) < 1e-10);
  assert.deepEqual(before.positions[0].coordinates.N, [0, 0, 0]);
});
