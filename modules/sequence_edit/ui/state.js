const messages = {
  "sequence": {
    "zh-CN": "序列",
    "en": "Sequence"
  },
  "3d_coordinates": {
    "zh-CN": "三维坐标",
    "en": "3D coordinates"
  },
  "secondary_structure": {
    "zh-CN": "二级结构",
    "en": "Secondary structure"
  },
  "function_annotations": {
    "zh-CN": "功能注释",
    "en": "Function annotations"
  },
  "the_number_of_values_does_not_match": {
    "zh-CN": "填写内容与选中位置数量不一致。",
    "en": "The number of values does not match the selected positions."
  },
  "use_amino_acid_letters_a_z_paste": {
    "zh-CN": "仅接受氨基酸单字母 A–Z；粘贴不执行 +、- 或清空操作。",
    "en": "Use amino-acid letters A–Z; paste does not insert, delete or clear positions."
  },
  "select_sequence_positions_first": {
    "zh-CN": "请先选择序列位置。",
    "en": "Select sequence positions first."
  },
  "paste_length_does_not_match_available_positions": {
    "zh-CN": "粘贴长度与可填写位置不一致；用 + 明确增加位置。",
    "en": "Paste length does not match available positions; use + to insert positions."
  },
  "paste_length_does_not_match_selected_positions": {
    "zh-CN": "粘贴长度与选中位置不一致。",
    "en": "Paste length does not match selected positions."
  }
};
/** Studio state stays local until Done. Downstream receives only live rows. */
export const TRACKS = [
  ["residue", messages.sequence],
  ["coordinates", messages["3d_coordinates"]],
  ["secondary_structure", messages.secondary_structure],
  ["sasa", "SASA"],
  ["function_annotations", messages.function_annotations],
];
export const COLORS = {
  normal: "#94cff0",
  replaced: "#f5cc80",
  cleared: "#ced2d8",
  inserted: "#99d8b0",
  deleted: "#f1a0a8",
};
export const emptySelections = () =>
  Object.fromEntries(TRACKS.map(([key]) => [key, []]));
export const copy = (value) => structuredClone(value);
export const activeRows = (document) =>
  document.positions.filter((row) => !row.deleted);
export const xyz = (row) => Object.values(row.coordinates ?? {});
export const rowValues = (row) =>
  Object.fromEntries(TRACKS.map(([key]) => [key, copy(row[key])]));
export function beginDocument(document) {
  const result = copy(document);
  result.baseline ??= Object.fromEntries(
    result.positions.map((row) => [row.id, rowValues(row)]),
  );
  return result;
}
export function editState(document, row, track) {
  if (row.deleted) return "deleted";
  const original = document.baseline?.[row.id];
  if (!original) return "inserted";
  if (JSON.stringify(original[track]) === JSON.stringify(row[track]))
    return "normal";
  return row[track] === null ||
    (Array.isArray(row[track]) && !row[track].length)
    ? "cleared"
    : "replaced";
}
export function changed(document, mutate) {
  const next = copy(document);
  mutate(next);
  next.sequence = next.positions.map((row) => row.residue ?? "_").join("");
  return next;
}
export function updateValues(document, ids, track, values) {
  const selected = new Set(ids),
    ordered = document.positions.filter((row) => selected.has(row.id));
  if (
    Array.isArray(values) &&
    track !== "function_annotations" &&
    values.length !== ordered.length
  )
    throw messageError("the_number_of_values_does_not_match");
  return changed(document, (next) => {
    let index = 0;
    for (const row of next.positions)
      if (selected.has(row.id)) {
        row.deleted = false;
        row[track] = copy(
          Array.isArray(values) && track !== "function_annotations"
            ? values[index++]
            : values,
        );
      }
  });
}
export function clearValues(document, ids, track) {
  return updateValues(
    document,
    ids,
    track,
    track === "function_annotations" ? [] : null,
  );
}
export function toggleDeleted(document, ids) {
  const selected = new Set(ids),
    restore = document.positions
      .filter((row) => selected.has(row.id))
      .every((row) => row.deleted);
  return changed(document, (next) => {
    for (const row of next.positions)
      if (selected.has(row.id)) row.deleted = !restore;
  });
}
export function insertPosition(document, afterId) {
  const id = globalThis.crypto.randomUUID(),
    index = document.positions.findIndex((row) => row.id === afterId) + 1;
  const next = changed(document, (value) =>
    value.positions.splice(index, 0, {
      id,
      residue: null,
      coordinates: null,
      secondary_structure: null,
      sasa: null,
      function_annotations: [],
      deleted: false,
    }),
  );
  return { document: next, id };
}
export function selectRange(rows, anchor, target, previous = []) {
  let a = rows.findIndex((row) => row.id === anchor),
    b = rows.findIndex((row) => row.id === target);
  if (b < 0) return previous;
  if (a < 0) a = b;
  return [
    ...new Set([
      ...previous,
      ...rows.slice(Math.min(a, b), Math.max(a, b) + 1).map((row) => row.id),
    ]),
  ];
}
export function parseSequence(text) {
  const input = text.replace(/\s/g, "");
  if (!input || !/^[A-Za-z]+$/.test(input))
    throw messageError("use_amino_acid_letters_a_z_paste");
  return [...input.toUpperCase()];
}
export function sequenceInput(document, ids, text, { paste = false } = {}) {
  const values = parseSequence(text),
    ordered = document.positions.filter((row) => ids.includes(row.id));
  if (!ordered.length) throw messageError("select_sequence_positions_first");
  let targets = ordered;
  if (paste && ordered.length === 1) {
    const index = document.positions.indexOf(ordered[0]);
    targets = document.positions.slice(index, index + values.length);
  }
  if (values.length !== 1 && values.length !== targets.length)
    throw messageError("paste_length_does_not_match_available_positions");
  if (paste && values.length !== targets.length)
    throw messageError("paste_length_does_not_match_selected_positions");
  return updateValues(
    document,
    targets.map((row) => row.id),
    "residue",
    values.length === 1 ? values[0] : values,
  );
}
export const add = (a, b) => a.map((v, i) => v + b[i]);
export const sub = (a, b) => a.map((v, i) => v - b[i]);
export const mul = (a, s) => a.map((v) => v * s);
export const dot = (a, b) => a.reduce((sum, v, i) => sum + v * b[i], 0);
export const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
export const unit = (a) => mul(a, 1 / (Math.hypot(...a) || 1));
export const centroid = (points) =>
  points.length
    ? mul(points.reduce(add, [0, 0, 0]), 1 / points.length)
    : [0, 0, 0];
export function transformed(
  document,
  ids,
  translation = [0, 0, 0],
  axis = [0, 0, 1],
  angle = 0,
) {
  const points = document.positions
      .filter((row) => ids.includes(row.id))
      .flatMap(xyz),
    center = centroid(points),
    u = unit(axis),
    c = Math.cos(angle),
    s = Math.sin(angle);
  return changed(document, (next) => {
    for (const row of next.positions)
      if (ids.includes(row.id) && row.coordinates) {
        row.deleted = false;
        row.coordinates = Object.fromEntries(
          Object.entries(row.coordinates).map(([name, p]) => {
            const v = sub(p, center);
            return [
              name,
              add(
                add(center, translation),
                add(
                  add(mul(v, c), mul(cross(u, v), s)),
                  mul(u, dot(u, v) * (1 - c)),
                ),
              ),
            ];
          }),
        );
      }
  });
}
export function replaceOperation(document) {
  return {
    kind: "replace_rows",
    rows: document.positions.map((row) => ({
      id: row.id,
      deleted: !!row.deleted,
      ...rowValues(row),
    })),
  };
}

function messageError(key, values = {}) { return Object.assign(new Error(messages[key].en.replace(/\{(\w+)\}/g, (match, key) => Object.hasOwn(values, key) ? String(values[key]) : match)), {displayMessage: messages[key], values}); }
