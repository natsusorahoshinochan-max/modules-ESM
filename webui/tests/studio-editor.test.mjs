import { i18n, setLocale } from './helpers/language-runtime.mjs'
setLocale('zh-CN')
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM, VirtualConsole } from "jsdom";
import React, { act } from "react";
import { createRoot } from "react-dom/client";

const dom = new JSDOM('<div id="app"></div>', {
  url: "http://localhost/",
  virtualConsole: new VirtualConsole(),
});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver = class {
  observe() {}
  disconnect() {}
};
dom.window.HTMLElement.prototype.scrollIntoView = () => {};
// WebGL is exercised in the real browser. Here its absence verifies the track-only fallback.
const { register } = await import("../../modules/sequence_edit/ui.js");
const Editor = register({ React, i18n }).editors[0].component;
const seed = {
  positions: [..."ACDE"].map((residue, i) => ({
    id: `r${i}`,
    residue,
    coordinates: null,
    secondary_structure: null,
    sasa: null,
    function_annotations: [],
  })),
};
const flush = () => new Promise((resolve) => setImmediate(resolve));
const cell = (label) =>
  document.querySelector(`[role="gridcell"][aria-label="${label}"]`);
const button = (label) =>
  [...document.querySelectorAll("button")].find(
    (el) => el.textContent === label,
  );
async function event(el, type, init = {}) {
  await act(async () => {
    el.dispatchEvent(
      type.startsWith("key")
        ? new window.KeyboardEvent(type, { bubbles: true, ...init })
        : new window.MouseEvent(type, { bubbles: true, ...init }),
    );
    await flush();
  });
}
async function select(label) {
  await event(cell(label), "pointerdown", { button: 0 });
  await event(cell(label), "pointerup", { button: 0 });
}
async function key(value, extra = {}) {
  await event(document.querySelector('[role="grid"]'), "keydown", {
    key: value,
    ...extra,
  });
}
async function setup({ failSave = false } = {}) {
  const calls = [],
    updates = [],
    cancelled = [];
  let closed = 0;
  const context = {
    revision: 1,
    inputs: {},
    document: { id: "accepted" },
    host: {
      preview: async (name, inputs, params, { signal }) => {
        calls.push({ name, inputs, params });
        await flush();
        if (signal.aborted) throw new Error("aborted");
        return {
          id: `draft-${calls.length}`,
          data: { document: structuredClone(seed) },
        };
      },
      cancelPreview: async (id) => {
        cancelled.push(id);
      },
    },
    update: async (value) => {
      if (failSave) throw new Error("storage unavailable");
      updates.push(value);
    },
  };
  const root = createRoot(document.getElementById("app"));
  await act(async () => {
    root.render(
      React.createElement(
        React.StrictMode,
        null,
        React.createElement(Editor, {
          context,
          parameters: {},
          onClose: () => {
            closed++;
          },
        }),
      ),
    );
    await flush();
    await flush();
  });
  await act(async () => {
    await flush();
    await flush();
  });
  return {
    calls,
    updates,
    cancelled,
    get closed() {
      return closed;
    },
    async dispose() {
      await act(async () => {
        root.unmount();
        await flush();
      });
    },
  };
}

test("StrictMode opens the accepted document once; typing stays local and rapid letters advance", async () => {
  const app = await setup();
  try {
    assert.equal(app.calls.length, 1);
    assert.equal(document.querySelectorAll('[role="gridcell"]').length, 20);
    assert.equal(button("打开编辑"), undefined);
    await select("序列 1");
    await key("u");
    await key("o");
    await key("x");
    assert.equal(
      [1, 2, 3].map((i) => cell(`序列 ${i}`).textContent).join(""),
      "UOX",
    );
    assert.equal(app.calls.length, 1);
    await key("z", { ctrlKey: true });
    assert.equal(cell("序列 3").textContent, "D");
    await key("z", { ctrlKey: true, shiftKey: true });
    assert.equal(cell("序列 3").textContent, "X");
  } finally {
    await app.dispose();
  }
});

test("save failure preserves edits; cancel never adopts them", async () => {
  const app = await setup({ failSave: true });
  try {
    await select("序列 2");
    await key(" ");
    await event(button("完成并返回画布"), "click");
    assert.match(
      document.querySelector(".ps-alert").textContent,
      /保存失败.*已保留/,
    );
    assert.equal(cell("序列 2").dataset.editState, "cleared");
    assert.equal(app.closed, 0);
    assert.equal(app.calls[1].params.operation.rows[1].residue, null);
    await event(button("取消编辑"), "click");
    assert.equal(app.closed, 1);
    assert.equal(app.updates.length, 0);
    assert.deepEqual(app.cancelled.sort(), ["draft-1", "draft-2"]);
  } finally {
    await app.dispose();
  }
});

test("deleted positions remain visible and direct input restores before one final adoption", async () => {
  const app = await setup();
  try {
    await select("序列 2");
    await key("-");
    assert.equal(cell("序列 2").dataset.editState, "deleted");
    assert.equal(document.querySelectorAll('[role="gridcell"]').length, 20);
    await key("g");
    assert.equal(cell("序列 2").textContent, "G");
    assert.equal(cell("序列 2").dataset.editState, "replaced");
    await select("序列 4");
    await key("-");
    await event(button("完成并返回画布"), "click");
    assert.equal(app.calls.length, 2);
    assert.equal(app.calls[1].params.operation.rows[3].deleted, true);
    assert.equal(app.updates.length, 1);
    assert.equal(app.closed, 1);
  } finally {
    await app.dispose();
  }
});

test("inline Escape cancels and Enter commits one undo step", async () => {
  const app = await setup();
  try {
    await select("SASA 2");
    await key("4");
    const input = document.querySelector('input[aria-label="SASA编辑"]');
    assert.equal(input.value, "4");
    await event(input, "keydown", { key: "Escape" });
    assert.equal(cell("SASA 2").dataset.editState, "normal");
    await select("SASA 2");
    await key("5");
    await event(
      document.querySelector('input[aria-label="SASA编辑"]'),
      "keydown",
      { key: "Enter" },
    );
    assert.equal(cell("SASA 2").textContent, "5");
    await key("z", { ctrlKey: true });
    assert.equal(cell("SASA 2").dataset.editState, "normal");
  } finally {
    await app.dispose();
  }
});

test("show changes is a display preference and leaves protein edits and history untouched", async () => {
  const app = await setup();
  try {
    const toggle = button("显示修改");
    const before = [...document.querySelectorAll('[role="gridcell"]')].map(el => el.textContent);
    const undo = document.querySelector('button[aria-label="撤销"]');
    assert.equal(toggle.getAttribute('aria-pressed'), 'false');
    await event(toggle, 'click');
    assert.equal(toggle.getAttribute('aria-pressed'), 'true');
    await event(toggle, 'click');
    assert.equal(toggle.getAttribute('aria-pressed'), 'false');
    assert.deepEqual([...document.querySelectorAll('[role="gridcell"]')].map(el => el.textContent), before);
    assert.equal(undo.disabled, true);
    assert.equal(app.calls.length, 1);
    assert.equal(app.updates.length, 0);
  } finally {
    await app.dispose();
  }
});
