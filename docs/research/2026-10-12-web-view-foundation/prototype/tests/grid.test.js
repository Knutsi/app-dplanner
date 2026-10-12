// The step table's grid on sample data, and a scripted pass over its keyboard and pointer
// contract. ?show leaves it in a picturable state (selection and focus) without running tests.
import "../ui/grid.js";
import { html } from "../engine/template.js";
import { statusMark, ownerChip, estimate, relativeTime, progressBar } from "../ui/marks.js";

const now = Date.parse("2026-10-12T09:00:00Z");
const H = 3600000;
const GROUPS = [
  ["Engine", [
    ["S1", "Signals core with version-pull", "done", 1, "claude", 30],
    ["S2", "Template holes and the tag scanner", "done", 2, "claude", 26],
    ["S3", "Keyed repeat that moves only what moved", "ready-to-merge", 1, "codex", 5],
    ["S4", "Base element: props, attributes, one render", "ready-for-review", 1, "claude", 3],
    ["S5", "Adopt server-rendered HTML without re-rendering", "pending", 3, "knut", 50],
    ["S21", "Dispose effects with the rows that own them", "in-progress", 1, "claude", 1],
    ["S22", "Benchmark against lit-html 3.3.0", "done", 1, "claude", 20],
    ["S23", "Trusted Types policy for the template parser", "pending", 1, "codex", 70],
    ["S24", "A hole inside <textarea> refuses with a remedy", "done", 0.5, "claude", 22],
    ["S25", "Element holes for refs", "done", 0.5, "claude", 21],
    ["S26", "Microtask-coalesced renders", "done", 0.5, "codex", 40],
    ["S27", "Layer check for engine → ui → shell → features", "in-progress", 0.5, "claude", 2],
  ]],
  ["Design system", [
    ["S6", "Tokens, roles and three variants", "in-progress", 2, "claude", 1],
    ["S7", "Omarchy theme bridge and /api/theme", "in-progress", 1, "claude", 4],
    ["S8", "Menubar and menus with the APG contract", "in-progress", 3, "codex", 6],
    ["S9", "Context menu, Shift+F10 and long-press", "pending", 1, "codex", 80],
    ["S10", "Selection bar in the toolbar's place", "pending", 1, "claude", 80],
    ["S11", "Command palette scoped to the selection", "pending", 2, "claude", 90],
    ["S12", "Which-key panel and the ? sheet", "pending", 1, "knut", 90],
    ["S13", "Step table as a treegrid", "in-progress", 3, "claude", 0.3],
    ["S14", "Motion tokens and the changed-flash", "ready-for-review", 1, "claude", 8],
    ["S28", "Tooltips with warm re-show", "pending", 0.5, "codex", 100],
    ["S29", "Toasts with Undo that pause on hover", "pending", 0.5, "claude", 100],
    ["S30", "Held-Ctrl key badges", "ready-to-merge", 0.5, "claude", 12],
  ]],
  ["Report site", [
    ["S15", "Read plan repositories in CI", "blocked", 2, "knut", 30],
    ["S16", "Project overview page", "pending", 2, "claude", 120],
    ["S17", "Step peek and detail pane", "pending", 2, "claude", 120],
    ["S18", "Activity feed from the event stream", "pending", 3, "codex", 120],
    ["S19", "Touch companion for review and status", "pending", 3, "knut", 140],
    ["S20", "Publish to GitHub Pages", "pending", 1, "claude", 140],
    ["S31", "Search across projects", "pending", 2, null, 160],
    ["S32", "Milestone colours from the theme map", "pending", 1, "codex", 160],
    ["S33", "Read-only banner when the ref is stale", "pending", 0.5, "claude", 160],
    ["S34", "Permalinks from app:// URIs", "pending", 1, "claude", 160],
    ["S35", "Print stylesheet for the overview", "pending", 0.5, null, 200],
  ]],
];

const data = new Map();
const expanded = new Set(GROUPS.map(([name]) => name));
let sort = null;

for (const [name, steps] of GROUPS)
  for (const [key, title, status, days, owner, hoursAgo] of steps) data.set(key, { key, title, status, days, owner, updated: now - hoursAgo * H, group: name });

const ORDER = ["pending", "in-progress", "ready-for-review", "ready-to-merge", "done", "blocked"];
const compare = {
  key: (a, b) => Number(a.key.slice(1)) - Number(b.key.slice(1)),
  title: (a, b) => a.title.localeCompare(b.title),
  status: (a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status),
  owner: (a, b) => (a.owner ?? "~").localeCompare(b.owner ?? "~"),
  days: (a, b) => a.days - b.days,
  updated: (a, b) => b.updated - a.updated,
};

function rows() {
  const out = [];
  for (const [name, steps] of GROUPS) {
    const items = steps.map(([key]) => data.get(key));
    const done = items.filter((s) => s.status === "done").length;
    out.push({ key: name, level: 1, kind: "group", expandable: true, expanded: expanded.has(name), cells: { title: name, count: items.length, done, days: items.reduce((n, s) => n + s.days, 0) } });
    if (!expanded.has(name)) continue;
    if (sort) items.sort((a, b) => compare[sort.key](a, b) * (sort.dir === "asc" ? 1 : -1));
    for (const s of items) out.push({ key: s.key, level: 2, kind: "step", cells: s });
  }
  return out;
}

const COLUMNS = [
  { key: "status", label: "", width: "calc(var(--icon) + 2 * var(--pad) + 6px)", sortable: true, render: (r) => (r.kind === "group" ? null : statusMark(r.cells.status)) },
  { key: "key", label: "Key", width: "52px", sortable: true, render: (r) => (r.kind === "group" ? null : html`<span class="dim">${r.cells.key}</span>`) },
  { key: "title", label: "Title", width: "minmax(240px, 1fr)", sortable: true, tree: true, render: (r) => r.cells.title },
  { key: "progress", label: "Progress", width: "120px", render: (r) => (r.kind === "group" ? progressBar(r.cells.done / r.cells.count) : null) },
  { key: "owner", label: "Owner", width: "104px", sortable: true, render: (r) => (r.kind === "group" ? html`<span class="dim">${r.cells.done}/${r.cells.count} done</span>` : ownerChip(r.cells.owner)) },
  { key: "days", label: "Estimate", width: "76px", align: "end", sortable: true, render: (r) => estimate(r.cells.days) },
  { key: "updated", label: "Updated", width: "76px", align: "end", sortable: true, render: (r) => (r.kind === "group" ? null : html`<span class="mark-num dim">${relativeTime(r.cells.updated, now)}</span>`) },
];
const grid = document.getElementById("grid");
grid.columns = COLUMNS;
grid.rows = rows();
const log = [];
for (const type of ["dp-focus", "dp-select", "dp-toggle", "dp-sort", "dp-open", "dp-context"]) grid.addEventListener(type, (e) => log.push({ type, detail: e.detail }));
grid.addEventListener("dp-toggle", (e) => {
  expanded.has(e.detail.key) ? expanded.delete(e.detail.key) : expanded.add(e.detail.key);
  grid.rows = rows();
});
grid.addEventListener("dp-sort", (e) => {
  sort = e.detail;
  grid.rows = rows();
});
window.grid = grid;

const params = new URLSearchParams(location.search);
if (params.has("show")) {
  grid.focus();
  grid.selected = new Set(["S7", "S8", "S13"]);
  grid.focusKey = params.get("focus") ?? "S8";
  grid.changed = new Set();
  window.__done = true;
} else {
  const results = [];
  const test = async (name, fn) => {
    try {
      await fn();
      results.push(`ok   ${name}`);
    } catch (e) {
      results.push(`FAIL ${name}: ${e.message}`);
    }
  };
  const eq = (a, b, what = "") => {
    if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${what} expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
  };
  const key = (k, o = {}) => grid.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...o }));
  const settle = () => new Promise((r) => setTimeout(r, 0));
  const last = (type) => log.filter((l) => l.type === type).at(-1)?.detail;

  grid.focus();
  await settle();

  await test("the grid is one tab stop with aria-activedescendant", async () => {
    eq([grid.tabIndex, grid.getAttribute("role"), grid.hasAttribute("data-nav")], [0, "treegrid", true]);
    grid.focus(); // arriving with nothing focused lands on the first row
    await settle();
    eq(grid.focusKey, "Engine");
    eq(grid.getAttribute("aria-activedescendant"), grid.rowId("Engine"));
  });

  await test("j/k and arrows move focus, emitting dp-focus", async () => {
    key("j");
    key("ArrowDown");
    key("k");
    await settle();
    eq([grid.focusKey, last("dp-focus").key], ["S1", "S1"]);
    eq(grid.rowElement("S1").classList.contains("focus"), true);
  });

  await test("x toggles selection of the focused row; groups do not select", async () => {
    key("x");
    await settle();
    eq([...grid.selected], ["S1"]);
    eq(grid.rowElement("S1").getAttribute("aria-selected"), "true");
    key("x");
    eq([...grid.selected], []);
  });

  await test("Space is left to the shell (Peek)", async () => {
    const e = new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true });
    grid.dispatchEvent(e);
    eq([e.defaultPrevented, grid.selected.size], [false, 0]);
  });

  await test("Shift+Down extends from the anchor", async () => {
    key("x");
    key("ArrowDown", { shiftKey: true });
    key("ArrowDown", { shiftKey: true });
    await settle();
    eq([...grid.selected], ["S1", "S2", "S3"]);
    eq(last("dp-select").via, "key");
  });

  await test("Ctrl+A selects every visible step", async () => {
    key("a", { ctrlKey: true });
    eq(grid.selected.size, 35);
  });

  await test("a click focuses, Ctrl+click toggles, Shift+click ranges", async () => {
    const press = (k, o = {}) => grid.rowElement(k).querySelector(".cell:nth-child(3)").dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0, ...o }));
    press("S6");
    eq(grid.focusKey, "S6");
    grid.selected = new Set();
    press("S7", { ctrlKey: true });
    press("S9", { ctrlKey: true });
    eq([...grid.selected], ["S7", "S9"]);
    press("S11", { shiftKey: true });
    eq([...grid.selected], ["S9", "S10", "S11"]);
    eq(last("dp-select").via, "pointer");
    grid.selected = new Set();
  });

  await test("Left on a step goes to its group; Left on an open group collapses it", async () => {
    grid.focusKey = "S2";
    await settle();
    key("ArrowLeft");
    eq(grid.focusKey, "Engine");
    key("ArrowLeft");
    await settle();
    eq(last("dp-toggle").key, "Engine");
    eq(grid.rows.some((r) => r.key === "S1"), false);
    eq(grid.rowElement("Engine").getAttribute("aria-expanded"), "false");
    key("ArrowRight");
    await settle();
    eq(grid.rows.some((r) => r.key === "S1"), true);
  });

  await test("Enter opens, Shift+F10 asks for a context menu", async () => {
    grid.focusKey = "S4";
    await settle();
    key("Enter");
    key("F10", { shiftKey: true });
    eq([last("dp-open").key, last("dp-context").key], ["S4", "S4"]);
  });

  await test("a header click sorts, and rows keep their DOM across the sort", async () => {
    const before = grid.rowElement("S13");
    grid.querySelector('.head [data-col="title"]').dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
    await settle();
    eq(last("dp-sort"), { key: "title", dir: "asc" });
    eq(grid.querySelector('.head [data-col="title"]').getAttribute("aria-sort"), "ascending");
    if (grid.rowElement("S13") !== before) throw new Error("row rebuilt by the sort");
    const keys = [...grid.querySelectorAll(".row")].map((r) => r.dataset.key);
    eq(keys.slice(0, 3), ["Engine", "S24", "S5"]); // "A hole…" before "Adopt…"
  });

  await test("keys the grid does not own pass through", async () => {
    const e = new KeyboardEvent("keydown", { key: "r", bubbles: true, cancelable: true });
    grid.dispatchEvent(e);
    eq(e.defaultPrevented, false);
  });

  await test("a right-click selects the row it lands on", async () => {
    grid.selected = new Set(["S1"]);
    await settle();
    grid.rowElement("S12").dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    eq([[...grid.selected], grid.focusKey, last("dp-context").key], [["S12"], "S12", "S12"]);
  });

  window.__results = results;
  window.__done = true;
}
