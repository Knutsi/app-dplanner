import { catalogue } from "../ui/theme.js";
import { contextMenu } from "../ui/menu.js";
import { tooltips } from "../ui/tooltip.js";
import "../ui/toolbar.js";

// A theme by query (?theme=omarchy:retro-82), else the house theme for the scheme.
const light = matchMedia("(prefers-color-scheme: light)").matches;
const wanted = new URLSearchParams(location.search).get("theme") ?? (light ? "house:dplanner-light" : "house:dplanner-dark");
const theme = catalogue().flatMap((g) => g.themes).find((t) => t.id === wanted);
for (const [k, v] of Object.entries(theme.colors)) document.documentElement.style.setProperty(`--om-${k}`, v);
document.documentElement.dataset.mode = (theme.colors.mode ?? "dark") === "light" ? "light" : "dark";
const variant = new URLSearchParams(location.search).get("variant");
if (variant) document.documentElement.dataset.variant = variant;

tooltips();
const ran = [];
const item = (id, label, extra = {}) => ({ id, label, icon: null, keys: null, run: () => ran.push(id), ...extra });
let wrap = true;

const fileGroups = () => [
  [item("new", "New Project…", { icon: "plus", keys: "Ctrl+N" }), item("open", "Open Library…", { icon: "folder", keys: "Ctrl+O" })],
  [
    item("export", "Export", {
      icon: "external",
      submenu: [[item("html", "Report as HTML", { keys: "Ctrl+E" }), item("pdf", "Report as PDF"), item("xlsx", "Tables as Workbook")]],
    }),
    item("archive", "Archive Project", { icon: "archive", disabled: true, reason: "Steps are still in progress" }),
  ],
  [item("close", "Close Window", { keys: "Alt+W" })],
];
const editGroups = () => [
  [item("undo", "Undo Set Status", { icon: "undo", keys: "Ctrl+Z" }), item("redo", "Redo", { icon: "redo", keys: "Ctrl+Shift+Z", disabled: true, reason: "Nothing to redo" })],
  [item("copy-link", "Copy Link to Step", { icon: "link", keys: "Ctrl+Shift+C" }), item("select-all", "Select All", { keys: "Ctrl+A" })],
];
const viewGroups = () => [
  [item("palette", "Command Palette…", { icon: "palette", keys: "Ctrl+K" })],
  [item("wrap", "Wrap Titles", { checked: wrap, run: () => (wrap = !wrap) }), item("peek", "Peek", { icon: "eye", keys: "Space" })],
  [item("goto", "Go to Projects", { keys: "g p" })],
];
const bar = document.getElementById("bar");
bar.menus = [
  { name: "File", groups: fileGroups },
  { name: "Edit", groups: editGroups },
  { name: "View", groups: viewGroups },
  { name: "Step", groups: () => [[item("rename", "Rename…", { icon: "edit", keys: "F2" })]] },
  { name: "Help", groups: () => [[item("keys", "Keyboard Shortcuts", { keys: "?" })]] },
];

let showLinks = true;
const tools = document.getElementById("tools");
const bands = () => [
  { name: "Create", items: [item("t-new", "New Step", { icon: "plus", keys: "n" }), item("t-divide", "Divide", { icon: "divide-horizontal", keys: "d" }), item("t-connect", "Connect", { icon: "connect", keys: "c" })] },
  { name: "Edit", items: [item("t-rename", "Rename", { icon: "edit", keys: "F2" }), item("t-move", "Move", { icon: "move", keys: "m" }), item("t-delete", "Delete", { icon: "trash", keys: "Delete", disabled: true, reason: "Select a step first" })] },
  { name: "Look", items: [item("t-links", "Show Links", { icon: "link", checked: showLinks, run: () => ((showLinks = !showLinks), (tools.bands = bands())) }), item("t-find", "Find", { icon: "find", keys: "Ctrl+F" }), item("t-frame", "Frame All", { icon: "frame", keys: "f" })] },
];
tools.bands = bands();

const select = (count, via = "pointer") => {
  tools.via = via;
  tools.selection = count
    ? {
        count,
        noun: "step",
        items: [
          item("s-status", "Set Status", { icon: "check", keys: "s" }),
          item("s-assign", "Assign", { icon: "person", keys: "a" }),
          item("s-milestone", "Milestone", { icon: "tag" }),
          item("s-link", "Copy Links", { icon: "link", keys: "Ctrl+Shift+C" }),
          item("s-archive", "Archive", { icon: "archive" }),
        ],
        clear: () => select(0),
      }
    : null;
};

const target = document.getElementById("target");
const contextGroups = () => [[item("c-open", "Open", { icon: "read", keys: "Enter" }), item("c-rename", "Rename…", { icon: "edit", keys: "F2" })], [item("c-link", "Copy Link", { icon: "link" })], [item("c-delete", "Delete", { icon: "trash", keys: "Delete" })]];
target.addEventListener("contextmenu", (e) => contextMenu(e, contextGroups()));

// For screenshots: node tools/run.mjs "tests/menus.html?shot" --eval "demo.openFile()"
window.demo = {
  select,
  async openFile() {
    document.getElementById("content").focus();
    key("f", { altKey: true, code: "KeyF" });
    await frames(2);
    key("ArrowDown");
    key("ArrowDown");
    key("ArrowRight");
  },
  async context() {
    target.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 700, clientY: 160 }));
  },
};

// ---------------------------------------------------------------- tests

const results = [];
const test = async (name, fn) => {
  try {
    await fn();
    results.push(`ok   ${name}`);
  } catch (e) {
    results.push(`FAIL ${name}: ${e.message}`);
  }
  document.querySelectorAll("dp-menu").forEach((m) => m.isOpen && m.close("close"));
};
const eq = (a, b, what = "") => {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${what} expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
};
const frames = (n = 1) => new Promise((r) => (function next(k) { k ? requestAnimationFrame(() => next(k - 1)) : r(); })(n));
function key(k, opts = {}) {
  const target = document.activeElement ?? document.body;
  const event = new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, composed: true, ...opts });
  target.dispatchEvent(event);
  return event;
}
const openMenus = () => [...document.querySelectorAll("dp-menu")].filter((m) => m.isOpen);
const focusedLabel = () => document.activeElement?.querySelector?.(".label")?.textContent ?? document.activeElement?.textContent?.trim();

if (!location.search.includes("shot")) {
  const content = document.getElementById("content");
  await Promise.all([bar.updateComplete, tools.updateComplete]);

  await test("Alt+F opens File with its first item focused", async () => {
    content.focus();
    key("f", { altKey: true, code: "KeyF" });
    eq(openMenus().length, 1, "open menus");
    eq(focusedLabel(), "New Project…");
  });

  await test("arrows move and wrap; disabled items stay reachable", async () => {
    content.focus();
    key("f", { altKey: true, code: "KeyF" });
    key("ArrowDown");
    key("ArrowDown");
    key("ArrowDown");
    eq(focusedLabel(), "Archive Project");
    key("ArrowDown");
    key("ArrowDown");
    eq(focusedLabel(), "New Project…", "wrapped");
    key("ArrowUp");
    eq(focusedLabel(), "Close Window", "wrapped up");
  });

  await test("ArrowRight opens a submenu at its first item, ArrowLeft returns", async () => {
    content.focus();
    key("f", { altKey: true, code: "KeyF" });
    key("ArrowDown");
    key("ArrowDown");
    eq(focusedLabel(), "Export");
    key("ArrowRight");
    eq([openMenus().length, focusedLabel()], [2, "Report as HTML"]);
    key("ArrowLeft");
    eq([openMenus().length, focusedLabel()], [1, "Export"]);
  });

  await test("Escape closes to the menubar item, a second Escape returns to the content", async () => {
    content.focus();
    key("f", { altKey: true, code: "KeyF" });
    key("Escape");
    eq([openMenus().length, document.activeElement.textContent.trim()], [0, "File"]);
    key("Escape");
    eq(document.activeElement, content);
  });

  await test("ArrowRight at the edge of a menu moves to the next menu", async () => {
    content.focus();
    key("f", { altKey: true, code: "KeyF" });
    key("ArrowRight");
    await bar.updateComplete;
    eq([openMenus().length, focusedLabel()], [1, "Undo Set Status"]);
    eq(bar.querySelector('[aria-expanded="true"]').textContent.trim(), "Edit");
    key("ArrowLeft");
    await bar.updateComplete;
    eq(bar.querySelector('[aria-expanded="true"]').textContent.trim(), "File");
  });

  await test("Enter runs an item, closes, and gives focus back to the content", async () => {
    ran.length = 0;
    content.focus();
    key("f", { altKey: true, code: "KeyF" });
    key("ArrowDown");
    key("Enter");
    eq([ran, openMenus().length, document.activeElement === content], [["open"], 0, true]);
  });

  await test("a disabled item does not run, and says why", async () => {
    ran.length = 0;
    content.focus();
    key("f", { altKey: true, code: "KeyF" });
    const archive = [...openMenus()[0].querySelectorAll(".item")].find((r) => r.textContent.includes("Archive"));
    archive.click();
    eq([ran, openMenus().length, archive.getAttribute("aria-description")], [[], 1, "Steps are still in progress"]);
  });

  await test("type-ahead jumps to a label", async () => {
    content.focus();
    key("e", { altKey: true, code: "KeyE" });
    key("s");
    eq(focusedLabel(), "Select All");
  });

  await test("a checked item is a menuitemcheckbox with its state", async () => {
    content.focus();
    key("v", { altKey: true, code: "KeyV" });
    const row = [...openMenus()[0].querySelectorAll(".item")].find((r) => r.textContent.includes("Wrap"));
    eq([row.getAttribute("role"), row.getAttribute("aria-checked")], ["menuitemcheckbox", "true"]);
  });

  await test("right-click opens at the pointer; Shift+F10 under the target", async () => {
    target.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 300, clientY: 200 }));
    const menu = openMenus()[0];
    const r = menu.getBoundingClientRect();
    eq([Math.round(r.left), Math.round(r.top)], [300, 200], "position");
    key("Escape");
    eq(openMenus().length, 0);
    target.focus();
    target.dispatchEvent(new KeyboardEvent("contextmenu", { bubbles: true, cancelable: true }));
    const keyed = openMenus()[0];
    eq(Math.round(keyed.getBoundingClientRect().top), Math.round(target.getBoundingClientRect().bottom), "under the target");
    eq(focusedLabel(), "Open", "focused first item");
  });

  await test("a click outside closes the menu", async () => {
    content.focus();
    key("f", { altKey: true, code: "KeyF" });
    content.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    eq(openMenus().length, 0);
  });

  await test("toolbar: one Tab stop and arrow keys", async () => {
    await tools.updateComplete;
    const stops = [...tools.querySelectorAll("[data-roving]")].filter((b) => b.tabIndex === 0);
    eq(stops.length, 1, "tab stops");
    stops[0].focus();
    key("ArrowRight");
    eq(document.activeElement.getAttribute("aria-label"), "Divide");
    key("End");
    eq(document.activeElement.getAttribute("aria-label"), "Frame All");
  });

  await test("toolbar: a toggle shows its pressed state, a disabled verb its reason", async () => {
    const links = tools.querySelector('[data-id="t-links"]');
    const del = tools.querySelector('[data-id="t-delete"]');
    eq([links.getAttribute("aria-pressed"), del.dataset.tip], ["true", "Delete — Select a step first"]);
    links.click();
    await tools.updateComplete;
    eq(tools.querySelector('[data-id="t-links"]').getAttribute("aria-pressed"), "false");
  });

  await test("selection bar replaces the toolbar, × clears it", async () => {
    const height = tools.querySelector(".strip").getBoundingClientRect().height;
    select(3);
    await tools.updateComplete;
    const strip = tools.querySelector(".strip");
    eq(strip.querySelector(".count").textContent.replace(/\s+/g, " ").trim(), "3 steps selected");
    eq(strip.getBoundingClientRect().height, height, "same height");
    eq(strip.querySelectorAll(".labelled").length, 5, "labelled bulk verbs");
    eq(tools.querySelector("[aria-live]").textContent, "3 steps selected");
    strip.querySelector(".clear").click();
    await tools.updateComplete;
    eq(tools.querySelector(".count"), null);
  });

  await test("the selection bar does not strand focus when it goes", async () => {
    select(2);
    await tools.updateComplete;
    tools.querySelector(".clear").focus();
    tools.querySelector(".clear").click();
    await tools.updateComplete;
    eq(document.activeElement, content);
  });

  await test("overflow folds whole bands into More", async () => {
    tools.style.width = "190px";
    await frames(3);
    const hidden = [...tools.querySelectorAll(".band")].filter((b) => b.hidden).length;
    const more = tools.querySelector(".more");
    if (!hidden) throw new Error("no band folded");
    eq(more.hidden, false, "more hidden");
    eq(tools.querySelector(".strip").scrollWidth <= tools.querySelector(".strip").clientWidth, true, "no overflow");
    more.click();
    const labels = [...openMenus()[0].querySelectorAll(".label")].map((l) => l.textContent);
    if (!labels.includes("Frame All")) throw new Error(`More holds ${labels}`);
    tools.style.width = "";
    await frames(3);
    eq([...tools.querySelectorAll(".band")].filter((b) => b.hidden).length, 0, "unfolded");
  });

  window.__results = results;
  window.__done = true;
}
