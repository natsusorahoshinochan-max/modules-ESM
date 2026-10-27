import { createViewer } from "3dmol/build/3Dmol.es6.js";
import { assignPDBBonds } from "3dmol/src/parsers/utils/assignPDBBonds";
import { computeSecondaryStructure } from "3dmol/src/parsers/utils/computeSecondaryStructure";
import {
  COLORS,
  editState,
  xyz,
  centroid,
  add,
  sub,
  mul,
  unit,
  cross,
  dot,
  transformed,
} from "./state.js";

const RESN = {
  A: "ALA",
  C: "CYS",
  D: "ASP",
  E: "GLU",
  F: "PHE",
  G: "GLY",
  H: "HIS",
  I: "ILE",
  K: "LYS",
  L: "LEU",
  M: "MET",
  N: "ASN",
  P: "PRO",
  Q: "GLN",
  R: "ARG",
  S: "SER",
  T: "THR",
  V: "VAL",
  W: "TRP",
  Y: "TYR",
  U: "SEC",
  O: "PYL",
  X: "UNK",
  B: "ASX",
  Z: "GLX",
  J: "XLE",
};
const point = (p) => ({ x: p[0], y: p[1], z: p[2] });
const vector = (p) => [p.x, p.y, p.z];
const AXES = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };
const AXIS_COLORS = { x: "#d85d68", y: "#469a61", z: "#4779ce" };
const STRUCTURE_COLORS = {
  base: COLORS.normal,
  selected: "#ab8be8",
  deleted: COLORS.deleted,
};

export function molecularAtoms(document) {
  // Display-only atoms; molecular inference never writes into any protein track.
  const atoms = [];
  let segment = 0,
    previous = null;
  for (const [index, row] of document.positions.entries()) {
    const ca = row.coordinates?.CA;
    if (!ca) {
      segment++;
      previous = null;
    } else if (previous && Math.hypot(...sub(ca, previous)) > 4.8) segment++;
    for (const [name, p] of Object.entries(row.coordinates ?? {}))
      atoms.push({
        ...point(p),
        serial: atoms.length + 1,
        index: atoms.length,
        atom: name,
        elem: name.replace(/^\d+/, "").slice(0, 1),
        resn: RESN[row.residue] ?? "UNK",
        resi: index + 1,
        chain: `A${segment}`,
        hetflag: false,
        bonds: [],
        bondOrder: [],
        ss: "c",
        properties: { position: row.id },
      });
    if (ca) previous = ca;
  }
  assignPDBBonds(atoms, {});
  computeSecondaryStructure(atoms, 3.2);
  return atoms;
}

export function createMoleculeView(React) {
  const h = React.createElement;
  return function MoleculeView({
    document,
    active,
    selected,
    coordinateSelection,
    mode,
    onMode,
    onSelect,
    onPreview,
    onCommit,
    readOnly,
    focusRequest,
  }) {
    const mount = React.useRef(null),
      surface = React.useRef(null),
      viewer = React.useRef(null),
      model = React.useRef(null),
      gesture = React.useRef(null),
      latest = React.useRef(null),
      lastPointer = React.useRef(null);
    const [error, setError] = React.useState(""),
      [representation, setRepresentation] = React.useState("cartoon"),
      [sidechains, setSidechains] = React.useState(false),
      [showChanges, setShowChanges] = React.useState(false),
      [projection, setProjection] = React.useState({ points: [], gizmo: [] }),
      [box, setBox] = React.useState(null),
      [transformMode, setTransformMode] = React.useState(null);
    latest.current = {
      document,
      active,
      selected,
      coordinateSelection,
      mode,
      onMode,
      onSelect,
      onPreview,
      onCommit,
      readOnly,
      representation,
      sidechains,
    };
    const coordinateRows = () =>
      latest.current.document?.positions.filter(
        (row) =>
          latest.current.coordinateSelection.includes(row.id) &&
          row.coordinates,
      ) ?? [];
    function refreshOverlay() {
      const v = viewer.current,
        rect = surface.current?.getBoundingClientRect();
      if (!v || !rect || !latest.current.document) return;
      const projected = latest.current.document.positions.flatMap((row) => {
        const atoms = Object.entries(row.coordinates ?? {});
        if (!atoms.length) return [];
        return atoms.map(([name, p]) => {
          const screen = v.modelToScreen(point(p));
          return {
            id: row.id,
            name,
            x: screen.x - window.scrollX - rect.left,
            y: screen.y - window.scrollY - rect.top,
          };
        });
      });
      const points = coordinateRows().flatMap(xyz),
        center = centroid(points),
        gizmo = [];
      if (points.length) {
        const c = v.modelToScreen(point(center)),
          offset = v.screenOffsetToModel(60, 0),
          radius = Math.max(0.8, Math.hypot(offset.x, offset.y, offset.z));
        const origin = {
          x: c.x - window.scrollX - rect.left,
          y: c.y - window.scrollY - rect.top,
        };
        for (const [axis, dir] of Object.entries(AXES)) {
          const end = v.modelToScreen(point(add(center, mul(dir, radius))));
          const u = axis === "x" ? [0, 1, 0] : [1, 0, 0],
            w = cross(dir, u);
          const ring = Array.from({ length: 49 }, (_, i) => {
            const a = (i * Math.PI) / 24,
              p = v.modelToScreen(
                point(
                  add(
                    center,
                    mul(add(mul(u, Math.cos(a)), mul(w, Math.sin(a))), radius),
                  ),
                ),
              );
            return `${p.x - window.scrollX - rect.left},${p.y - window.scrollY - rect.top}`;
          }).join(" ");
          gizmo.push({
            axis,
            origin,
            end: {
              x: end.x - window.scrollX - rect.left,
              y: end.y - window.scrollY - rect.top,
            },
            ring,
          });
        }
      }
      setProjection({ points: projected, gizmo });
    }
    React.useEffect(() => {
      try {
        viewer.current = createViewer(mount.current, {
          backgroundColor: "#fafbfc",
          antialias: true,
        });
        if (!viewer.current) throw new Error("WebGL unavailable");
        viewer.current.setProjection("orthographic");
      } catch (reason) {
        setError("三维视图无法启动，请检查 WebGL。轨道仍可编辑。");
        return;
      }
      const observer = new ResizeObserver(() => {
        viewer.current?.resize();
        refreshOverlay();
      });
      observer.observe(mount.current);
      return () => {
        observer.disconnect();
        viewer.current?.clear();
        mount.current?.replaceChildren();
        viewer.current = null;
        model.current = null;
      };
    }, []);
    React.useEffect(() => {
      const v = viewer.current;
      if (!v || !document) return;
      try {
        const fitted = !!model.current,
          view = v.getView();
        v.removeAllModels();
        model.current = v.addModel();
        model.current.addAtoms(molecularAtoms(document));
        const rows = new Map(document.positions.map((row) => [row.id, row]));
        const atoms = model.current.selectedAtoms({}),
          backboneCounts = new Map();
        for (const atom of atoms)
          if (atom.atom === "CA")
            backboneCounts.set(
              atom.chain,
              (backboneCounts.get(atom.chain) ?? 0) + 1,
            );
        for (const atom of atoms) {
          const row = rows.get(atom.properties.position),
            state = editState(document, row, active),
            color = row.deleted
              ? STRUCTURE_COLORS.deleted
              : selected.includes(row.id)
                ? STRUCTURE_COLORS.selected
                : showChanges && state !== "normal"
                  ? COLORS[state]
                  : STRUCTURE_COLORS.base;
          const common = { color, opacity: 1 };
          const trace =
            representation === "trace" ||
            (!row.coordinates?.O && representation === "cartoon");
          atom.style =
            representation === "sticks"
              ? { stick: { ...common, radius: 0.17 } }
              : representation === "ballstick"
                ? {
                    stick: { ...common, radius: 0.12 },
                    sphere: { ...common, scale: 0.24 },
                  }
                : {
                    cartoon: {
                      ...common,
                      style: trace ? "trace" : "rectangle",
                      arrows: true,
                      thickness: trace ? 0.35 : 0.3,
                      gapcutoff: 0,
                    },
                  };
          // A solitary residue/partial atom set still has a selectable visible representation.
          if (
            !row.coordinates?.CA ||
            (["cartoon", "trace"].includes(representation) &&
              backboneCounts.get(atom.chain) === 1)
          )
            atom.style = {
              stick: { ...common, radius: 0.12 },
              sphere: { ...common, scale: 0.24 },
            };
          if (
            sidechains &&
            selected.includes(row.id) &&
            !["N", "CA", "C", "O"].includes(atom.atom)
          )
            atom.style = {
              ...atom.style,
              stick: { ...common, radius: 0.17 },
              sphere: { ...common, scale: 0.2 },
            };
        }
        v.render();
        if (fitted) v.setView(view);
        else if (model.current.selectedAtoms({}).length) {
          v.zoomTo();
          v.zoom(0.65);
        }
        refreshOverlay();
      } catch (reason) {
        setError(`三维显示失败：${reason.message}`);
      }
    }, [
      document,
      active,
      selected,
      coordinateSelection,
      representation,
      sidechains,
      showChanges,
    ]);
    React.useEffect(() => {
      if (!focusRequest) return;
      focusSelected();
    }, [focusRequest]);
    React.useEffect(() => {
      refreshOverlay();
    }, [mode]);
    function focusSelected() {
      const v = viewer.current;
      if (!v) return;
      const atoms =
        model.current
          ?.selectedAtoms({})
          .filter((atom) =>
            latest.current.selected.includes(atom.properties.position),
          ) ?? [];
      if (atoms.length) {
        v.zoomTo(
          {
            predicate: (atom) =>
              latest.current.selected.includes(atom.properties.position),
          },
          180,
        );
        setTimeout(refreshOverlay, 200);
      }
    }
    function relative(event) {
      const rect = surface.current.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    }
    function startTransform(kind, axis = null, event = null, keyboard = false) {
      if (latest.current.readOnly) return;
      const rows = coordinateRows();
      if (!rows.length) return;
      const p = event
        ? relative(event)
        : (lastPointer.current ?? {
            x: surface.current.clientWidth / 2,
            y: surface.current.clientHeight / 2,
          });
      gesture.current = {
        type: "transform",
        kind,
        axis,
        origin: p,
        last: p,
        base: latest.current.document,
        ids: rows.map((row) => row.id),
        keyboard,
      };
      setTransformMode({ kind, axis });
      onMode(kind);
      surface.current.focus();
    }
    function endTransform(commit) {
      const g = gesture.current;
      if (g?.type !== "transform") return;
      gesture.current = null;
      setTransformMode(null);
      if (commit && g.result) latest.current.onCommit(g.result);
      latest.current.onPreview(null);
    }
    function transformAt(p) {
      const g = gesture.current,
        v = viewer.current;
      if (g?.type !== "transform" || !v) return;
      g.last = p;
      const dx = p.x - g.origin.x,
        dy = p.y - g.origin.y;
      let translation = [0, 0, 0],
        axis = g.axis
          ? AXES[g.axis]
          : unit(
              cross(
                vector(v.screenOffsetToModel(1, 0)),
                vector(v.screenOffsetToModel(0, -1)),
              ),
            ),
        angle = 0;
      if (g.kind === "move") {
        const delta = vector(v.screenOffsetToModel(dx, dy));
        translation = g.axis
          ? mul(AXES[g.axis], dot(delta, AXES[g.axis]))
          : delta;
      } else angle = ((dx - dy) * Math.PI) / 180;
      g.result = transformed(g.base, g.ids, translation, axis, angle);
      latest.current.onPreview(g.result);
    }
    function down(event) {
      surface.current.focus();
      if (event.button === 2) {
        if (gesture.current?.type === "transform") {
          event.preventDefault();
          endTransform(false);
        }
        return;
      }
      if (
        gesture.current?.type === "transform" &&
        gesture.current.keyboard &&
        event.button === 0
      ) {
        endTransform(true);
        return;
      }
      const p = relative(event);
      lastPointer.current = p;
      event.currentTarget.setPointerCapture?.(event.pointerId);
      if (event.button === 1) {
        event.preventDefault();
        gesture.current = { type: event.shiftKey ? "pan" : "orbit", last: p };
        return;
      }
      if (event.button !== 0) return;
      if ((mode === "move" || mode === "rotate") && !readOnly) {
        startTransform(mode, null, event);
        return;
      }
      gesture.current = {
        type: mode === "box" ? "box" : "select",
        origin: p,
        last: p,
        additive: event.shiftKey,
      };
    }
    function move(event) {
      const p = relative(event);
      lastPointer.current = p;
      const g = gesture.current,
        v = viewer.current;
      if (!g || !v) return;
      if (g.type === "transform") {
        transformAt(p);
        return;
      }
      if (g.type === "orbit") {
        v.rotate((p.x - g.last.x) * 0.45, "vy");
        v.rotate((p.y - g.last.y) * 0.45, "vx");
        refreshOverlay();
      }
      if (g.type === "pan") {
        v.translate(p.x - g.last.x, -(p.y - g.last.y));
        refreshOverlay();
      }
      if (g.type === "box")
        setBox({
          left: Math.min(p.x, g.origin.x),
          top: Math.min(p.y, g.origin.y),
          width: Math.abs(p.x - g.origin.x),
          height: Math.abs(p.y - g.origin.y),
        });
      g.last = p;
    }
    function up(event) {
      const g = gesture.current;
      if (!g) return;
      if (g.type === "transform") {
        if (!g.keyboard) endTransform(true);
        return;
      }
      gesture.current = null;
      setBox(null);
      if (g.type === "box") {
        const a = g.origin,
          b = g.last;
        onSelect(
          [
            ...new Set(
              projection.points
                .filter(
                  (p) =>
                    p.x >= Math.min(a.x, b.x) &&
                    p.x <= Math.max(a.x, b.x) &&
                    p.y >= Math.min(a.y, b.y) &&
                    p.y <= Math.max(a.y, b.y),
                )
                .map((p) => p.id),
            ),
          ],
          g.additive,
        );
        return;
      }
      if (
        g.type === "select" &&
        Math.hypot(g.last.x - g.origin.x, g.last.y - g.origin.y) < 5
      ) {
        const p = relative(event),
          nearest = projection.points
            .map((atom) => ({
              ...atom,
              distance: Math.hypot(p.x - atom.x, p.y - atom.y),
            }))
            .sort((a, b) => a.distance - b.distance)[0];
        onSelect(nearest?.distance < 20 ? [nearest.id] : [], g.additive);
      }
    }
    function key(event) {
      const g = gesture.current,
        key = event.key.toLowerCase();
      if (event.ctrlKey || event.metaKey) return;
      if (key === "escape" && g?.type === "transform") {
        event.preventDefault();
        endTransform(false);
      } else if (key === "enter" && g?.type === "transform") {
        event.preventDefault();
        endTransform(true);
      } else if (
        "xyz".includes(key) &&
        key.length === 1 &&
        g?.type === "transform"
      ) {
        event.preventDefault();
        g.axis = key;
        setTransformMode({ kind: g.kind, axis: key });
        transformAt(g.last);
      } else if ((key === "g" || key === "r") && !readOnly) {
        event.preventDefault();
        startTransform(key === "g" ? "move" : "rotate", null, null, true);
      }
    }
    const hasCoordinates = coordinateRows().length > 0,
      selectedSet = new Set(selected),
      selectedPoints = projection.points.filter(
        (p) =>
          selectedSet.has(p.id) &&
          (p.name === "CA" ||
            !document?.positions.find((row) => row.id === p.id)?.coordinates
              ?.CA),
      );
    return h(
      "div",
      { className: "ps-viewport", "aria-label": "蛋白质三维视图" },
      h("div", { ref: mount, className: "ps-molecule" }),
      h(
        "div",
        {
          ref: surface,
          className: "ps-view-surface",
          tabIndex: 0,
          role: "application",
          "aria-label": "三维编辑区域",
          onPointerDown: down,
          onPointerMove: move,
          onPointerUp: up,
          onPointerCancel: () => {
            endTransform(false);
            gesture.current = null;
            setBox(null);
          },
          onContextMenu: (event) => {
            event.preventDefault();
            endTransform(false);
          },
          onKeyDown: key,
          onWheel: (event) => {
            event.preventDefault();
            viewer.current?.zoom(Math.exp(-event.deltaY * 0.001));
            refreshOverlay();
          },
        },
        h(
          "svg",
          { className: "ps-view-overlay", "aria-hidden": true },
          ...selectedPoints.map((p, i) =>
            h("circle", {
              key: `sel-${i}`,
              cx: p.x,
              cy: p.y,
              r: 9,
              fill: "none",
              stroke: "#8058c4",
              strokeWidth: 1.5,
            }),
          ),
          ...(["move", "rotate"].includes(mode) && !readOnly
            ? projection.gizmo.map((g) =>
                h(
                  "g",
                  {
                    key: g.axis,
                    style: { pointerEvents: "auto", cursor: "grab" },
                    onPointerDown: (event) => {
                      event.stopPropagation();
                      event.currentTarget.setPointerCapture?.(event.pointerId);
                      startTransform(mode, g.axis, event);
                    },
                    onPointerMove: move,
                    onPointerUp: () => endTransform(true),
                  },
                  mode === "move"
                    ? h(
                        React.Fragment,
                        null,
                        h("line", {
                          x1: g.origin.x,
                          y1: g.origin.y,
                          x2: g.end.x,
                          y2: g.end.y,
                          stroke: AXIS_COLORS[g.axis],
                          strokeWidth: 3,
                        }),
                        h("circle", {
                          cx: g.end.x,
                          cy: g.end.y,
                          r: 6,
                          fill: AXIS_COLORS[g.axis],
                        }),
                        h(
                          "text",
                          {
                            x: g.end.x + 9,
                            y: g.end.y + 4,
                            fill: AXIS_COLORS[g.axis],
                          },
                          g.axis.toUpperCase(),
                        ),
                      )
                    : h("polyline", {
                        points: g.ring,
                        fill: "none",
                        stroke: AXIS_COLORS[g.axis],
                        strokeWidth: 3,
                      }),
                ),
              )
            : []),
        ),
        box && h("div", { className: "ps-box", style: box }),
      ),
      h(
        "nav",
        { className: "ps-view-tools", "aria-label": "三维工具" },
        ...[
          ["select", "↖", "选择"],
          ["box", "⬚", "框选"],
          ["move", "✥", "移动"],
          ["rotate", "⟳", "旋转"],
        ].map(([key, icon, label]) =>
          h(
            "button",
            {
              key,
              type: "button",
              "aria-pressed": mode === key,
              disabled:
                ["move", "rotate"].includes(key) &&
                (!hasCoordinates || readOnly),
              onClick: () => {
                endTransform(false);
                onMode(key);
                surface.current?.focus();
              },
            },
            h("span", null, icon),
            label,
          ),
        ),
      ),
      h(
        "div",
        { className: "ps-camera-tools" },
        h(
          "select",
          {
            "aria-label": "显示方式",
            value: representation,
            onChange: (event) => setRepresentation(event.target.value),
          },
          h("option", { value: "cartoon" }, "飘带图"),
          h("option", { value: "trace" }, "主链轨迹"),
          h("option", { value: "sticks" }, "棒状图"),
          h("option", { value: "ballstick" }, "球棍图"),
        ),
        h(
          "button",
          {
            type: "button",
            "aria-pressed": sidechains,
            onClick: () => setSidechains((value) => !value),
          },
          "侧链",
        ),
        h(
          "button",
          {
            type: "button",
            "aria-pressed": showChanges,
            onClick: () => setShowChanges((value) => !value),
          },
          "显示修改",
        ),
        h(
          "button",
          {
            type: "button",
            disabled: !selectedPoints.length,
            onClick: focusSelected,
          },
          "聚焦选区",
        ),
        h(
          "button",
          {
            type: "button",
            onClick: () => {
              viewer.current?.zoomTo();
              viewer.current?.zoom(0.65);
              refreshOverlay();
            },
          },
          "适应全部",
        ),
      ),
      error && h("p", { role: "alert", className: "ps-view-error" }, error),
      !error &&
        !document?.positions.some((row) => row.coordinates) &&
        h("div", { className: "ps-empty" }, "暂无三维坐标"),
      transformMode &&
        h(
          "span",
          { className: "ps-transform-status" },
          `${transformMode.kind === "move" ? "移动" : "旋转"}${transformMode.axis ? " · " + transformMode.axis.toUpperCase() : ""} · Enter 确认 · Esc 取消`,
        ),
    );
  };
}
