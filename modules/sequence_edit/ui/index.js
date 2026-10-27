import {
  TRACKS,
  COLORS,
  emptySelections,
  beginDocument,
  editState,
  selectRange,
  sequenceInput,
  updateValues,
  clearValues,
  toggleDeleted,
  insertPosition,
  replaceOperation,
} from "./state.js";
import { createMoleculeView } from "./molecule.js";
import { styles } from "./styles.js";
export const runtime = { react: 19 };

export function register({ React }) {
  const h = React.createElement,
    MoleculeView = createMoleculeView(React);
  function Editor({ context, parameters, readOnly, onClose, onDraftChange }) {
    const [session, setSession] = React.useState({ entries: [], index: -1 }),
      sessionRef = React.useRef(session);
    const [selections, setSelections] = React.useState(emptySelections),
      [active, setActive] = React.useState("residue"),
      [focus, setFocus] = React.useState({}),
      [mode, setMode] = React.useState("select");
    const [setup, setSetup] = React.useState(true),
      [busy, setBusy] = React.useState(false),
      [error, setError] = React.useState(""),
      [preview, setPreview] = React.useState(null),
      [inline, setInlineState] = React.useState(null),
      [menu, setMenu] = React.useState(null),
      [adoption, setAdoption] = React.useState(null);
    const [height, setHeight] = React.useState(333),
      [focusRequest, setFocusRequest] = React.useState(0);
    const [input, setInput] = React.useState(
        context.document?.id ?? context.inputs.source?.packages[0]?.id ?? "",
      ),
      [sequence, setSequence] = React.useState(parameters.sequence ?? ""),
      [object, setObject] = React.useState(parameters.object ?? ""),
      [chain, setChain] = React.useState(
        parameters.selection?.chains?.[0] ?? "A",
      );
    const inlineRef = React.useRef(null);
    function setInline(value) {
      inlineRef.current = value;
      setInlineState(value);
    }
    const root = React.useRef(null),
      grid = React.useRef(null),
      drag = React.useRef(null),
      anchors = React.useRef({}),
      tokens = React.useRef(new Set()),
      mounted = React.useRef(false),
      controller = React.useRef(null),
      loading = React.useRef(false),
      latest = React.useRef(null),
      revision = React.useRef(context.revision),
      expectedRevision = React.useRef(null);
    const current = session.entries[session.index],
      document = current?.document,
      rows = (preview ?? document)?.positions ?? [];
    latest.current = {
      context,
      selections,
      active,
      focus,
      input,
      sequence,
      object,
      chain,
      inline,
      adoption,
      busy,
      readOnly,
    };
    function replaceSession(next) {
      sessionRef.current = next;
      setSession(next);
    }
    const currentEntry = () =>
      sessionRef.current.entries[sessionRef.current.index];
    function push(document, source = currentEntry()?.source) {
      const old = sessionRef.current;
      replaceSession({
        entries: [...old.entries.slice(0, old.index + 1), { document, source }],
        index: old.index + 1,
      });
      setPreview(null);
      onDraftChange?.();
    }
    async function release(id) {
      if (!tokens.current.delete(id)) return;
      await context.host.cancelPreview(id).catch(() => {});
    }
    function cleanup() {
      controller.current?.abort();
      for (const token of tokens.current) void release(token);
    }
    React.useEffect(() => {
      mounted.current = true;
      return () => {
        mounted.current = false;
        cleanup();
      };
    }, []);
    React.useEffect(() => {
      if (revision.current === context.revision) return;
      revision.current = context.revision;
      if (expectedRevision.current === context.revision) {
        expectedRevision.current = null;
        return;
      }
      cleanup();
      replaceSession({ entries: [], index: -1 });
      setSetup(true);
      setError("节点输入已改变，请重新载入。");
    }, [context.revision]);
    React.useEffect(() => {
      let live = true;
      queueMicrotask(() => {
        if (
          live &&
          (context.document ||
            context.inputs.source?.packages.length ||
            typeof parameters.sequence === "string")
        )
          void load();
      });
      return () => {
        live = false;
      };
    }, []);
    React.useEffect(() => {
      const end = () => {
        drag.current = null;
      };
      window.addEventListener("pointerup", end);
      window.addEventListener("pointercancel", end);
      return () => {
        window.removeEventListener("pointerup", end);
        window.removeEventListener("pointercancel", end);
      };
    }, []);
    React.useEffect(() => {
      if (!menu) return;
      const close = () => setMenu(null);
      window.addEventListener("pointerdown", close);
      return () => window.removeEventListener("pointerdown", close);
    }, [menu]);
    async function request(name, inputs, params) {
      const abort = new AbortController();
      controller.current = abort;
      let id;
      try {
        const result = await context.host.preview(name, inputs, params, {
          signal: abort.signal,
        });
        id = result.id;
        tokens.current.add(id);
        const read = async (key) =>
          JSON.parse(
            await (
              await context.host.readPreviewFile(id, "edited", key, {
                signal: abort.signal,
              })
            ).text(),
          );
        const document = result.data.document_file
          ? await read(result.data.document_file)
          : result.data.document;
        const geometry = result.data.view_file
          ? await read(result.data.view_file)
          : [];
        if (!mounted.current || abort.signal.aborted) {
          await release(id);
          return null;
        }
        return { source: id, document: beginDocument(document), geometry };
      } catch (reason) {
        if (id) await release(id);
        if (!abort.signal.aborted && mounted.current) setError(reason.message);
        return null;
      } finally {
        if (controller.current === abort) controller.current = null;
      }
    }
    async function load() {
      if (loading.current) return;
      loading.current = true;
      setBusy(true);
      setError("");
      try {
        const state = latest.current,
          params =
            state.input === context.document?.id
              ? {}
              : {
                  ...(state.object ? { object: state.object } : {}),
                  selection: { chains: [state.chain] },
                  ...(!state.input ? { sequence: state.sequence } : {}),
                };
        const result = await request(
          "workbench.sequence_edit",
          { source: state.input ? [state.input] : [] },
          params,
        );
        if (result) {
          replaceSession({ entries: [result], index: 0 });
          setSelections(emptySelections());
          setFocus({});
          setInline(null);
          setSetup(false);
          setPreview(null);
          for (const token of tokens.current)
            if (token !== result.source) void release(token);
        }
      } finally {
        loading.current = false;
        if (mounted.current) setBusy(false);
      }
    }
    function perform(change) {
      if (latest.current.readOnly || loading.current) return;
      try {
        const before = currentEntry();
        if (!before) return;
        const next = change(before.document);
        push(next);
        setError("");
      } catch (reason) {
        setError(reason.message);
      }
    }
    function select(track, ids, additive = false) {
      setActive(track);
      setSelections((value) => ({
        ...value,
        [track]: additive ? [...new Set([...value[track], ...ids])] : ids,
      }));
      if (ids.length) setFocus((value) => ({ ...value, [track]: ids.at(-1) }));
    }
    function undo(direction) {
      if (loading.current || inline || adoption) return;
      const previous = sessionRef.current,
        next = previous.index + direction;
      if (next < 0 || next >= previous.entries.length) return;
      replaceSession({ ...previous, index: next });
      setPreview(null);
      onDraftChange?.();
    }
    function clear(track = active, ids = selections[track]) {
      if (ids.length) perform((doc) => clearValues(doc, ids, track));
    }
    function remove() {
      const ids = latest.current.selections[latest.current.active];
      if (ids.length) perform((doc) => toggleDeleted(doc, ids));
    }
    function insert() {
      const track = latest.current.active,
        id =
          latest.current.focus[track] ??
          latest.current.selections[track].at(-1);
      perform((doc) => {
        const result = insertPosition(doc, id);
        select("residue", [result.id]);
        anchors.current.residue = result.id;
        return result.document;
      });
      grid.current?.focus();
    }
    function advance(track, count = 1) {
      const doc = currentEntry()?.document;
      if (!doc) return;
      const old =
          latest.current.focus[track] ??
          latest.current.selections[track].at(-1),
        index = doc.positions.findIndex((row) => row.id === old);
      const next =
        doc.positions[Math.min(index + count, doc.positions.length - 1)];
      if (next) {
        select(track, [next.id]);
        anchors.current[track] = next.id;
        queueMicrotask(() =>
          [...(grid.current?.querySelectorAll(`[data-track="${track}"]`) ?? [])]
            .find((cell) => cell.dataset.position === next.id)
            ?.scrollIntoView({ block: "nearest", inline: "nearest" }),
        );
      }
    }
    function startInline(track, id, initial) {
      const doc = currentEntry().document;
      const ids = selections[track].includes(id)
        ? doc.positions
            .filter((row) => selections[track].includes(row.id))
            .map((row) => row.id)
        : [id];
      select(track, ids);
      setInline({
        track,
        ids,
        id,
        text:
          initial ??
          (track === "function_annotations"
            ? doc.positions.find((row) => row.id === id)[track].join(", ")
            : String(doc.positions.find((row) => row.id === id)[track] ?? "")),
      });
    }
    function commitInline() {
      if (!inlineRef.current) return true;
      const { track, ids, text } = inlineRef.current;
      let value;
      if (track === "sasa") {
        value = text.trim() === "" ? null : Number(text);
        if (value !== null && (!Number.isFinite(value) || value < 0)) {
          setError("SASA 需要非负数值。");
          return false;
        }
      } else
        value = [
          ...new Set(
            text
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean),
          ),
        ];
      perform((doc) => updateValues(doc, ids, track, value));
      setInline(null);
      return true;
    }
    function key(event) {
      if (
        event.isComposing ||
        event.altKey ||
        /INPUT|SELECT|TEXTAREA/.test(event.target.tagName)
      )
        return;
      const mod = event.ctrlKey || event.metaKey,
        k = event.key,
        track = latest.current.active,
        ids = latest.current.selections[track];
      if (mod) {
        if (k.toLowerCase() === "z") {
          event.preventDefault();
          undo(event.shiftKey ? 1 : -1);
        } else if (k.toLowerCase() === "a") {
          event.preventDefault();
          select(
            track,
            rows.map((row) => row.id),
          );
        }
        return;
      }
      if (k === "Escape") {
        setMenu(null);
        setInline(null);
        return;
      }
      if (k.startsWith("Arrow")) {
        event.preventDefault();
        let t = track;
        const index = TRACKS.findIndex(([key]) => key === track),
          id = latest.current.focus[track] ?? ids.at(-1) ?? rows[0]?.id;
        if (k === "ArrowUp" || k === "ArrowDown") {
          t =
            TRACKS[
              Math.max(
                0,
                Math.min(
                  TRACKS.length - 1,
                  index + (k === "ArrowDown" ? 1 : -1),
                ),
              )
            ][0];
          select(
            t,
            latest.current.selections[t].length
              ? latest.current.selections[t]
              : [id],
          );
          return;
        }
        const at = rows.findIndex((row) => row.id === id),
          next =
            rows[
              Math.max(
                0,
                Math.min(rows.length - 1, at + (k === "ArrowRight" ? 1 : -1)),
              )
            ];
        if (next) {
          select(
            t,
            event.shiftKey
              ? selectRange(rows, anchors.current[t] ?? id, next.id)
              : [next.id],
          );
          if (!event.shiftKey) anchors.current[t] = next.id;
        }
        return;
      }
      if (readOnly || loading.current || !ids.length) return;
      if (k === " " || k === "Backspace" || k === "Delete") {
        event.preventDefault();
        clear(track, ids);
        return;
      }
      if (k === "-" && track === "residue") {
        event.preventDefault();
        remove();
        return;
      }
      if (k === "+" && track === "residue") {
        event.preventDefault();
        insert();
        return;
      }
      if (track === "residue" && /^[a-zA-Z]$/.test(k)) {
        event.preventDefault();
        perform((doc) => sequenceInput(doc, ids, k));
        if (ids.length === 1) advance(track);
        return;
      }
      if (track === "secondary_structure" && /^[a-zA-Z]$/.test(k)) {
        event.preventDefault();
        if (!"GHITEBSC".includes(k.toUpperCase())) {
          setError("二级结构接受 G、H、I、T、E、B、S、C。");
          return;
        }
        perform((doc) => updateValues(doc, ids, track, k.toUpperCase()));
        if (ids.length === 1) advance(track);
        return;
      }
      if (track === "sasa" && /^[0-9.]$/.test(k)) {
        event.preventDefault();
        startInline(track, ids[0], k);
        return;
      }
      if (track === "function_annotations" && k.length === 1) {
        event.preventDefault();
        startInline(track, ids[0], k);
        return;
      }
      if (k === "Enter" && ["sasa", "function_annotations"].includes(track)) {
        event.preventDefault();
        startInline(track, ids[0]);
        return;
      }
      if (track === "residue" && k.length === 1) {
        event.preventDefault();
        setError("序列接受 A–Z；+ 插入、- 删除、空格清空。");
      }
    }
    function paste(event) {
      if (
        /INPUT|TEXTAREA/.test(event.target.tagName) ||
        readOnly ||
        loading.current ||
        active !== "residue"
      )
        return;
      event.preventDefault();
      perform((doc) =>
        sequenceInput(
          doc,
          selections.residue,
          event.clipboardData.getData("text/plain"),
          { paste: true },
        ),
      );
    }
    async function materialize() {
      const entry = currentEntry();
      return request(
        "workbench.sequence_edit",
        { source: [{ interaction: entry.source, output: "edited" }] },
        { operation: replaceOperation(entry.document) },
      );
    }
    async function finish() {
      if (readOnly || loading.current || !currentEntry()) return;
      if (inline && !commitInline()) return;
      loading.current = true;
      setBusy(true);
      setError("");
      try {
        const result = await materialize();
        if (!result) return;
        try {
          expectedRevision.current = context.revision + 1;
          await context.update({
            document: { interaction: result.source, output: "edited" },
          });
          tokens.current.delete(result.source);
          cleanup();
          onClose?.();
        } catch (reason) {
          expectedRevision.current = null;
          setError(`保存失败，当前编辑已保留：${reason.message}`);
        }
      } finally {
        loading.current = false;
        if (mounted.current) setBusy(false);
      }
    }
    function cancel() {
      if (loading.current) return;
      cleanup();
      onClose?.();
    }
    async function openAdoption(track) {
      setMenu(null);
      const sources = (document.structures ?? []).map((record, i) => ({
        id: `retained:${record.id}`,
        label: `原始结构 ${i + 1}`,
        structure: { retained: record.id },
        inputs: {},
      }));
      setBusy(true);
      try {
        for (const pkg of context.inputs.structures?.packages ?? []) {
          const data = JSON.parse(
            await (await context.host.readFile(pkg.id, pkg.entry)).text(),
          );
          for (const obj of data.objects ?? [])
            sources.push({
              id: `${pkg.id}:${obj.id}`,
              label: obj.name ?? obj.id,
              structure: { input: "structures", object: obj.id },
              inputs: { structures: [pkg.id] },
            });
        }
        if (!sources.length) {
          setError("请连接参考三维结构，或先从结构文件载入。");
          return;
        }
        setAdoption({
          track,
          ids: [...selections[track]],
          sources,
          source: sources[0].id,
          positions: [],
          selected: [],
          chain: "",
        });
      } catch (reason) {
        setError(reason.message);
      } finally {
        setBusy(false);
      }
    }
    async function readAdoption() {
      if (loading.current) return;
      loading.current = true;
      setBusy(true);
      const source = adoption.sources.find((s) => s.id === adoption.source);
      try {
        const entry = currentEntry(),
          result = await request(
            "workbench.sequence_structure",
            {
              source: [{ interaction: entry.source, output: "edited" }],
              ...source.inputs,
            },
            { structure: source.structure },
          );
        if (!result) return;
        const positions = [
          ...new Map(
            result.geometry.map((atom) => {
              const p = Object.fromEntries(
                [
                  "model",
                  "chain",
                  "author_number",
                  "insertion_code",
                  "residue_name",
                ].map((k) => [k, atom[k]]),
              );
              return [JSON.stringify(p), p];
            }),
          ).entries(),
        ].map(([key, p]) => ({ key, ...p }));
        setAdoption((previous) => ({
          ...previous,
          positions,
          selected: [],
          chain: positions[0]?.chain ?? "",
        }));
        await release(result.source);
      } finally {
        loading.current = false;
        setBusy(false);
      }
    }
    async function adopt() {
      if (loading.current) return;
      loading.current = true;
      setBusy(true);
      setError("");
      try {
        const prepared = await materialize();
        if (!prepared) return;
        const source = adoption.sources.find((s) => s.id === adoption.source),
          targets = document.positions.filter((row) =>
            adoption.ids.includes(row.id),
          ),
          origin = adoption.positions.filter((p) =>
            adoption.selected.includes(p.key),
          );
        const result = await request(
          "workbench.sequence_structure",
          {
            source: [{ interaction: prepared.source, output: "edited" }],
            ...source.inputs,
          },
          {
            structure: source.structure,
            operation: {
              kind: "adopt_structure",
              tracks: [adoption.track],
              mapping: targets.map((row, i) => ({
                edit_position: row.id,
                position: Object.fromEntries(
                  [
                    "model",
                    "chain",
                    "author_number",
                    "insertion_code",
                    "residue_name",
                  ].map((k) => [k, origin[i][k]]),
                ),
              })),
            },
          },
        );
        if (result) {
          push(result.document, result.source);
          setAdoption(null);
        }
      } finally {
        loading.current = false;
        setBusy(false);
      }
    }
    function cell(row, index, track) {
      const value = row[track],
        selected = selections[track].includes(row.id),
        state = editState(document, row, track),
        label = TRACKS.find(([key]) => key === track)[1],
        editing = inline?.id === row.id && inline.track === track;
      let content =
        track === "residue"
          ? (value ?? "·")
          : track === "coordinates"
            ? h("span", {
                className: `ps-coordinate${value ? "" : " ps-coordinate-empty"}`,
              })
            : track === "secondary_structure"
              ? value
                ? h("span", { className: `ps-ss ps-ss-${value}` }, value)
                : h("span", { className: "ps-missing" }, "—")
              : track === "sasa"
                ? value === null
                  ? h("span", { className: "ps-missing" }, "—")
                  : h(
                      "span",
                      { className: "ps-sasa" },
                      h("i", { style: { height: Math.min(30, value / 8) } }),
                      h("span", null, value),
                    )
                : value.length
                  ? h("span", { className: "ps-annotation" }, value.join(", "))
                  : h("span", { className: "ps-missing" }, "—");
      if (editing)
        content = h("input", {
          autoFocus: true,
          "aria-label": `${label}编辑`,
          className:
            track === "function_annotations" ? "ps-annotation-input" : "",
          value: inline.text,
          onPointerDown: (e) => e.stopPropagation(),
          onChange: (e) => setInline({ ...inline, text: e.target.value }),
          onKeyDown: (e) => {
            e.stopPropagation();
            if (e.key === "Enter") {
              if (commitInline()) grid.current?.focus();
            } else if (e.key === "Escape") {
              setInline(null);
              grid.current?.focus();
            }
          },
          onBlur: () => commitInline(),
        });
      return h(
        "div",
        {
          key: `${track}-${row.id}`,
          role: "gridcell",
          "aria-label": `${label} ${index + 1}`,
          "aria-selected": selected,
          "data-track": track,
          "data-position": row.id,
          "data-edit-state": state,
          className: `ps-cell ps-${state}${track === "residue" ? " ps-sequence" : ""}${selected ? " ps-selected" : ""}${active === track ? " ps-active-cell" : ""}${focus[track] === row.id && active === track ? " ps-cursor" : ""}`,
          title: `${label} ${index + 1}: ${track === "coordinates" ? (value ? "有坐标" : "空缺") : Array.isArray(value) ? value.join(", ") : (value ?? "空缺")}`,
          onPointerDown: (event) => {
            if (event.button !== 0 || editing) return;
            event.preventDefault();
            if (inline && !commitInline()) return;
            grid.current?.focus();
            const previous =
                event.ctrlKey || event.metaKey ? selections[track] : [],
              anchor = event.shiftKey
                ? (anchors.current[track] ?? row.id)
                : row.id;
            drag.current = { track, anchor, previous };
            select(track, selectRange(rows, anchor, row.id, previous));
            if (!event.shiftKey) anchors.current[track] = row.id;
          },
          onPointerEnter: () => {
            const g = drag.current;
            if (g?.track === track)
              select(track, selectRange(rows, g.anchor, row.id, g.previous));
          },
          onPointerUp: () => {
            drag.current = null;
          },
          onDoubleClick: () => {
            if (!readOnly && ["sasa", "function_annotations"].includes(track))
              startInline(track, row.id);
          },
          onContextMenu: (event) => {
            event.preventDefault();
            if (!selected) select(track, [row.id]);
            setMenu({
              track,
              x: Math.min(event.clientX, window.innerWidth - 200),
              y: Math.min(event.clientY, window.innerHeight - 220),
            });
          },
        },
        content,
      );
    }
    const currentRows = document?.positions ?? [],
      count = currentRows.filter((row) => !row.deleted).length,
      activeName = TRACKS.find(([key]) => key === active)[1];
    return h(
      "section",
      {
        ref: root,
        className: "ps-studio",
        "aria-label": "Protein Studio",
        "aria-busy": busy,
        onPointerUp: () => {
          drag.current = null;
        },
        onKeyDown: (event) => {
          if (
            (event.ctrlKey || event.metaKey) &&
            event.key.toLowerCase() === "z" &&
            !event.defaultPrevented &&
            !/INPUT|TEXTAREA/.test(event.target.tagName)
          ) {
            event.preventDefault();
            undo(event.shiftKey ? 1 : -1);
          }
        },
      },
      h("style", null, styles),
      h(
        "header",
        { className: "ps-header" },
        h("strong", { className: "ps-brand" }, "Protein Studio"),
        h("span", { className: "ps-object" }, `${count} 个位置`),
        h("span", { className: "ps-spacer" }),
        h(
          "button",
          { type: "button", disabled: busy, onClick: () => setSetup(true) },
          "载入输入",
        ),
        h(
          "div",
          { className: "ps-header-actions" },
          h(
            "button",
            {
              type: "button",
              className: "ps-icon",
              "aria-label": "撤销",
              disabled: busy || session.index < 1,
              onClick: () => undo(-1),
            },
            "↶",
          ),
          h(
            "button",
            {
              type: "button",
              className: "ps-icon",
              "aria-label": "重做",
              disabled: busy || session.index >= session.entries.length - 1,
              onClick: () => undo(1),
            },
            "↷",
          ),
          h(
            "button",
            { type: "button", disabled: busy, onClick: cancel },
            readOnly ? "返回画布" : "取消编辑",
          ),
          h(
            "button",
            {
              type: "button",
              className: "ps-primary",
              disabled: readOnly || busy || !document,
              onClick: finish,
            },
            "完成并返回画布",
          ),
        ),
      ),
      error &&
        h(
          "div",
          { role: "alert", className: "ps-alert" },
          error,
          h(
            "button",
            {
              type: "button",
              "aria-label": "关闭错误",
              onClick: () => setError(""),
            },
            "×",
          ),
        ),
      h(MoleculeView, {
        document: preview ?? document,
        active,
        selected: selections[active],
        coordinateSelection: selections.coordinates,
        mode,
        readOnly: readOnly || busy || !!adoption,
        onMode: (value) => {
          setMode(value);
          if (value === "move" || value === "rotate") setActive("coordinates");
        },
        onSelect: (ids, additive) => select("coordinates", ids, additive),
        onPreview: setPreview,
        onCommit: (doc) => {
          perform(() => doc);
          setPreview(null);
        },
        focusRequest,
      }),
      h("div", {
        className: "ps-divider",
        role: "separator",
        tabIndex: 0,
        "aria-label": "调整轨道高度",
        "aria-orientation": "horizontal",
        onKeyDown: (e) => {
          if (e.key === "ArrowUp") setHeight((v) => Math.min(500, v + 20));
          if (e.key === "ArrowDown") setHeight((v) => Math.max(250, v - 20));
        },
        onPointerDown: (event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          event.currentTarget.dataset.y = event.clientY;
          event.currentTarget.dataset.height = height;
        },
        onPointerMove: (event) => {
          if (event.currentTarget.hasPointerCapture?.(event.pointerId))
            setHeight(
              Math.max(
                250,
                Math.min(
                  root.current.clientHeight * 0.65,
                  Number(event.currentTarget.dataset.height) +
                    Number(event.currentTarget.dataset.y) -
                    event.clientY,
                ),
              ),
            );
        },
      }),
      h(
        "section",
        {
          className: "ps-tracks",
          style: { height },
          "aria-label": "蛋白质轨道",
        },
        h(
          "div",
          { className: "ps-track-top" },
          h(
            "strong",
            null,
            `${activeName} · ${selections[active].length} 个已选位置`,
          ),
          h(
            "button",
            {
              type: "button",
              disabled: !selections[active].length,
              onClick: () => setFocusRequest((v) => v + 1),
            },
            "定位选区",
          ),
          h("span", { className: "ps-spacer" }),
          h(
            "div",
            { className: "ps-legend" },
            ...["replaced", "cleared", "inserted", "deleted"].map((state, i) =>
              h(
                "span",
                { key: state },
                h("i", { style: { background: COLORS[state] } }),
                ["替换", "清空", "新增", "删除"][i],
              ),
            ),
          ),
        ),
        h(
          "div",
          {
            ref: grid,
            className: "ps-track-scroll",
            role: "grid",
            tabIndex: 0,
            "aria-label": "蛋白质轨道编辑",
            onKeyDown: key,
            onPaste: paste,
            onPointerUp: () => {
              drag.current = null;
            },
          },
          h(
            "div",
            {
              className: "ps-grid",
              style: { "--ps-count": Math.max(1, rows.length) },
            },
            h("div", { className: "ps-ruler ps-ruler-label" }, "位置"),
            ...rows.map((row, index) =>
              h(
                "div",
                {
                  key: row.id,
                  className: `ps-ruler${row.deleted ? " ps-deleted" : !document.baseline[row.id] ? " ps-inserted" : ""}`,
                },
                `${!document.baseline[row.id] ? "+" : ""}${index + 1}`,
              ),
            ),
            ...TRACKS.flatMap(([track, label]) => [
              h(
                "div",
                {
                  key: track,
                  className: `ps-track-label${active === track ? " ps-active" : ""}`,
                },
                h(
                  "button",
                  {
                    type: "button",
                    onClick: () => {
                      setActive(track);
                      grid.current?.focus();
                    },
                  },
                  label,
                ),
                h(
                  "small",
                  null,
                  `${currentRows.filter((row) => !row.deleted && (track === "function_annotations" ? row[track].length : row[track] !== null)).length} / ${count}`,
                ),
              ),
              ...rows.map((row, i) => cell(row, i, track)),
            ]),
          ),
        ),
      ),
      h(
        "footer",
        { className: "ps-footer" },
        h(
          "span",
          null,
          busy
            ? "正在处理…"
            : active === "residue"
              ? "字母输入 · + 插入 · - 删除 · 空格清空"
              : active === "secondary_structure"
                ? "G H I T E B S C · 空格清空"
                : "直接输入 · 空格清空 · Ctrl/⌘ Z 撤销",
        ),
        h("span", null, "中键旋转 · Shift＋中键平移 · G 移动 · R 旋转"),
      ),
      menu &&
        h(
          "div",
          {
            className: "ps-menu",
            role: "menu",
            style: { left: menu.x, top: menu.y },
            onPointerDown: (e) => e.stopPropagation(),
          },
          h(
            "button",
            {
              type: "button",
              disabled: readOnly,
              onClick: () => {
                clear(menu.track);
                setMenu(null);
              },
            },
            "清空",
            h("kbd", null, "Space"),
          ),
          menu.track === "residue" &&
            h(
              React.Fragment,
              null,
              h(
                "button",
                {
                  type: "button",
                  disabled: readOnly,
                  onClick: () => {
                    insert();
                    setMenu(null);
                  },
                },
                "插入",
                h("kbd", null, "+"),
              ),
              h(
                "button",
                {
                  type: "button",
                  disabled: readOnly,
                  onClick: () => {
                    remove();
                    setMenu(null);
                  },
                },
                "删除 / 恢复",
                h("kbd", null, "-"),
              ),
            ),
          ["coordinates", "residue"].includes(menu.track) &&
            h(
              "button",
              {
                type: "button",
                disabled: readOnly,
                onClick: () => openAdoption(menu.track),
              },
              "从结构采用",
            ),
        ),
      setup &&
        h(
          "div",
          { className: "ps-modal-layer" },
          h(
            "form",
            {
              className: "ps-modal",
              onSubmit: (e) => {
                e.preventDefault();
                void load();
              },
            },
            h("h2", null, "打开蛋白质"),
            h(
              "label",
              null,
              "来源",
              h(
                "select",
                {
                  "aria-label": "载入来源",
                  value: input,
                  disabled: busy,
                  onChange: (e) => setInput(e.target.value),
                },
                h("option", { value: "" }, "填写序列"),
                context.document &&
                  h(
                    "option",
                    { value: context.document.id },
                    "已确认的编辑成果",
                  ),
                ...(context.inputs.source?.packages ?? []).map((pkg) =>
                  h(
                    "option",
                    { key: pkg.id, value: pkg.id },
                    "节点输入 · " + pkg.format,
                  ),
                ),
                ...(context.inputs.source?.available ?? []).map((item) =>
                  h(
                    "option",
                    { key: item.package.id, value: item.package.id },
                    item.label,
                  ),
                ),
              ),
            ),
            !input &&
              h(
                "label",
                null,
                "序列",
                h("input", {
                  "aria-label": "初始序列",
                  value: sequence,
                  onChange: (e) => setSequence(e.target.value.toUpperCase()),
                }),
              ),
            h(
              "label",
              null,
              "对象",
              h("input", {
                "aria-label": "输入对象",
                placeholder: "单个对象可留空",
                value: object,
                onChange: (e) => setObject(e.target.value),
              }),
            ),
            h(
              "label",
              null,
              "链",
              h("input", {
                "aria-label": "输入链",
                value: chain,
                onChange: (e) => setChain(e.target.value),
              }),
            ),
            h(
              "nav",
              null,
              h(
                "button",
                { type: "submit", className: "ps-primary", disabled: busy },
                busy ? "正在打开…" : "打开编辑",
              ),
              document &&
                h(
                  "button",
                  {
                    type: "button",
                    disabled: busy,
                    onClick: () => setSetup(false),
                  },
                  "返回当前编辑",
                ),
              !document &&
                h(
                  "button",
                  { type: "button", disabled: busy, onClick: cancel },
                  "返回画布",
                ),
            ),
          ),
        ),
      adoption &&
        h(
          "div",
          { className: "ps-modal-layer" },
          h(
            "section",
            {
              className: "ps-modal",
              role: "dialog",
              "aria-label": "从结构采用",
            },
            h("h2", null, "从结构采用"),
            h(
              "label",
              null,
              "来源",
              h(
                "select",
                {
                  value: adoption.source,
                  disabled: busy,
                  onChange: (e) =>
                    setAdoption({
                      ...adoption,
                      source: e.target.value,
                      positions: [],
                      selected: [],
                    }),
                },
                ...adoption.sources.map((s) =>
                  h("option", { key: s.id, value: s.id }, s.label),
                ),
              ),
            ),
            h(
              "button",
              { type: "button", disabled: busy, onClick: readAdoption },
              "读取残基",
            ),
            adoption.positions.length > 0 &&
              h(
                React.Fragment,
                null,
                h(
                  "label",
                  null,
                  "链",
                  h(
                    "select",
                    {
                      value: adoption.chain,
                      disabled: busy,
                      onChange: (e) =>
                        setAdoption({
                          ...adoption,
                          chain: e.target.value,
                          selected: [],
                        }),
                    },
                    ...[...new Set(adoption.positions.map((p) => p.chain))].map(
                      (c) => h("option", { key: c, value: c }, c),
                    ),
                  ),
                ),
                h(
                  "p",
                  null,
                  `目标 ${adoption.ids.length} 个位置 · 已选 ${adoption.selected.length} 个来源残基`,
                ),
                h(
                  "div",
                  { className: "ps-source-positions" },
                  ...adoption.positions
                    .filter((p) => p.chain === adoption.chain)
                    .map((p) =>
                      h(
                        "button",
                        {
                          key: p.key,
                          type: "button",
                          disabled: busy,
                          "aria-pressed": adoption.selected.includes(p.key),
                          onClick: (e) => {
                            const all = adoption.positions.filter(
                                (p) => p.chain === adoption.chain,
                              ),
                              a = all.findIndex(
                                (p) => p.key === adoption.anchor,
                              ),
                              b = all.indexOf(p),
                              selected =
                                e.shiftKey && a >= 0
                                  ? all
                                      .slice(Math.min(a, b), Math.max(a, b) + 1)
                                      .map((p) => p.key)
                                  : adoption.selected.includes(p.key)
                                    ? adoption.selected.filter(
                                        (k) => k !== p.key,
                                      )
                                    : [...adoption.selected, p.key];
                            setAdoption({
                              ...adoption,
                              selected,
                              anchor: p.key,
                            });
                          },
                        },
                        `${p.author_number}${p.insertion_code} ${p.residue_name}`,
                      ),
                    ),
                ),
              ),
            h(
              "nav",
              null,
              h(
                "button",
                {
                  type: "button",
                  className: "ps-primary",
                  disabled:
                    busy || adoption.selected.length !== adoption.ids.length,
                  onClick: adopt,
                },
                "采用",
              ),
              h(
                "button",
                {
                  type: "button",
                  disabled: busy,
                  onClick: () => setAdoption(null),
                },
                "取消",
              ),
            ),
          ),
        ),
      busy &&
        !setup &&
        !adoption &&
        h(
          "div",
          { className: "ps-modal-layer", role: "status" },
          h("div", { className: "ps-modal" }, "正在保存编辑…"),
        ),
    );
  }
  function Action({ host }) {
    const [value, setValue] = React.useState(""),
      [error, setError] = React.useState("");
    return h(
      "section",
      null,
      h(
        "label",
        null,
        "初始序列",
        h("input", {
          value,
          disabled: host.readOnly,
          onChange: (e) => setValue(e.target.value.toUpperCase()),
        }),
      ),
      h(
        "button",
        {
          disabled: host.readOnly,
          onClick: async () => {
            try {
              await host.addNode({
                type: "workbench.edit_sequence",
                parameters: { sequence: value },
                inputs: {},
              });
            } catch (reason) {
              setError(reason.message);
            }
          },
        },
        "添加蛋白质编辑器",
      ),
      error && h("p", { role: "alert" }, error),
    );
  }
  function Viewer({ package: pkg, host }) {
    const [data, setData] = React.useState(null),
      [error, setError] = React.useState("");
    React.useEffect(() => {
      let live = true;
      host
        .readFile(pkg.id, pkg.entry)
        .then((blob) => blob.text())
        .then((text) => {
          if (live) setData(JSON.parse(text));
        })
        .catch((reason) => {
          if (live) setError(reason.message);
        });
      return () => {
        live = false;
      };
    }, [pkg.id]);
    return error
      ? h("p", { role: "alert" }, error)
      : data
        ? h(
            "section",
            null,
            h("p", null, `${data.tracks.sequence.length} 个位置`),
            h("pre", null, data.tracks.sequence.map((v) => v ?? "·").join("")),
          )
        : h("p", null, "正在读取…");
  }
  return {
    actions: [
      {
        id: "workbench.sequence_editor",
        name: "Protein Studio",
        component: Action,
      },
    ],
    editors: [
      {
        node: "workbench.edit_sequence",
        component: Editor,
        workspace: {
          title: "Protein Studio",
          openLabel: "打开 Protein Studio",
        },
      },
    ],
    viewers: [
      {
        id: "workbench.protein",
        name: "蛋白质轨道",
        formats: ["workbench.protein"],
        component: Viewer,
      },
    ],
  };
}
