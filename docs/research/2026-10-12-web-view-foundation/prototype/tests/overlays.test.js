// The overlays — palette, which-key, cheat sheet, modeline, toasts, touch sheet — tested as
// plain components, and staged one at a time for screenshots:
//   tests/overlays.html                 runs the asserts (window.__results)
//   tests/overlays.html?scene=palette   stages one surface; &theme=house:dplanner-light for light

import "../ui/palette.js";
import "../ui/keyhelp.js";
import "../ui/statusbar.js";
import "../ui/sheet.js";
import { fuzzy } from "../ui/palette.js";
import { toast } from "../ui/toast.js";
import { chooseTheme, startThemes } from "../ui/theme.js";

const params = new URLSearchParams(location.search);
if (params.get("theme")) chooseTheme(params.get("theme"));
await startThemes();

const ran = [];
const item = (id, label, extra = {}) => ({ id, label, icon: null, keys: null, disabled: false, reason: null, checked: null, run: () => ran.push(id), ...extra });
const ITEMS = [
  item("step.rename", "Rename…", { icon: "edit", keys: "F2", detail: "Step ▸ Edit" }),
  item("step.status.done", "Mark Done", { icon: "check", keys: "s d", detail: "Step ▸ Status" }),
  item("step.status.review", "Ready for Review", { icon: "eye", keys: "s r", detail: "Step ▸ Status" }),
  item("step.delete", "Delete Steps", { icon: "trash", keys: "Delete", detail: "Step ▸ Edit", disabled: true, reason: "S1 is done — reopen it first" }),
  item("view.split", "Split Pane", { icon: "layers", keys: "Ctrl+\\", detail: "View ▸ Panes" }),
  item("go.projects", "Go to Projects", { icon: "project", keys: "g p", detail: "Go ▸ Navigate" }),
  item("go.steps", "Go to Steps", { icon: "step", keys: "g s", detail: "Go ▸ Navigate" }),
  item("go.activity", "Go to Activity", { icon: "gauge", keys: "g a", detail: "Go ▸ Navigate" }),
  item("view.theme", "Choose Theme…", { icon: "palette", keys: "Ctrl+K t", detail: "View ▸ Theme" }),
  item("help.keys", "Keyboard Shortcuts", { icon: "info", keys: "?", detail: "Help" }),
  item("app.palette", "Command Palette", { icon: "find", keys: "Ctrl+K", detail: "View ▸ Palette" }),
];
const WIDER = [...ITEMS, item("project.new", "New Project…", { icon: "plus", keys: "Ctrl+N", detail: "File ▸ Project" })];

const palette = document.body.appendChild(document.createElement("dp-palette"));
const whichkey = document.body.appendChild(document.createElement("dp-whichkey"));
const sheet = document.body.appendChild(document.createElement("dp-sheet"));
const cheat = document.body.appendChild(document.createElement("dp-cheatsheet"));
const bar = document.querySelector("dp-statusbar");
const settle = () => new Promise((r) => setTimeout(r, 30));
const type = async (input, text) => {
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await settle();
};
const key = (target, k, extra = {}) => target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...extra }));

const SECTIONS = [
  { title: "This step", items: ITEMS.slice(0, 4) },
  { title: "Go", items: ITEMS.filter((i) => i.id.startsWith("go.")) },
  { title: "View", items: ITEMS.filter((i) => i.id.startsWith("view.") || i.id.startsWith("app.")) },
  { title: "Selection", items: [item("sel.toggle", "Toggle selection", { keys: "x" }), item("sel.clear", "Clear selection", { keys: "Escape" }), item("sel.all", "Select all", { keys: "Ctrl+A" }), item("sel.extend", "Extend selection", { keys: "Shift+ArrowDown" })] },
  { title: "Move", items: [item("nav.down", "Next row", { keys: "j" }), item("nav.up", "Previous row", { keys: "k" }), item("nav.open", "Open", { keys: "Enter" }), item("nav.peek", "Peek", { keys: "Space" })] },
  { title: "Help", items: [ITEMS[9]] },
];
const STATUS = {
  mode: { name: "NAV", exits: null, tone: "nav" },
  crumbs: [{ label: "Web view", uri: "app://entity/project/web-view" }, { label: "Design system", uri: "app://entity/milestone/m-design" }, { label: "S13 Step table as a treegrid", uri: "app://entity/step/S13" }],
  right: [{ label: "Building report site · 62%", icon: "refresh", tip: "Open Activity" }, { label: "retro-82", icon: "palette", tip: "Theme follows the desktop" }],
};
Object.assign(bar, STATUS);

const scene = params.get("scene");
if (scene) {
  if (scene === "palette") {
    palette.open({ items: ITEMS, scope: "S13", placeholder: "Commands for S13" });
    await settle();
    await type(palette.input, "stat");
    bar.mode = { name: "NAV", exits: null, tone: "nav" };
  } else if (scene === "whichkey") {
    bar.mode = { name: "g…", exits: "Esc cancels", tone: "pending" };
    whichkey.prefix = "g";
    whichkey.items = [...ITEMS.filter((i) => i.keys?.startsWith("g ")), item("go.back", "Back", { keys: "g b" }), item("go.home", "Home", { keys: "g h" }), item("go.milestone", "Milestone…", { keys: "g m x" })];
  } else if (scene === "cheatsheet") {
    cheat.sections = SECTIONS;
    await settle();
    cheat.open();
  } else if (scene === "statusbar") {
    bar.mode = { name: "EDIT", exits: "Esc leaves the field", tone: "edit" };
    bar.echo = { keys: "F2", label: "Rename…", source: "pointer" };
    bar.setAttribute("verbs", "");
    bar.verbs = [item("a", "rename", { keys: "r" }), item("b", "status", { keys: "s" }), item("c", "peek", { keys: "Space" }), item("d", "split", { keys: "Ctrl+\\" })];
  } else if (scene === "toast") {
    toast("Report site published to knutsi.github.io/dplanner", { tone: "ok" });
    toast("3 steps marked Done", { undo: () => {} });
    bar.echo = { keys: "s d", label: "Mark Done", source: "key" };
  } else if (scene === "sheet") {
    document.querySelector("main").innerHTML = "<h1>S13 Step table as a treegrid</h1><p>In progress · 3 d · claude</p>";
    const bar2 = document.body.appendChild(document.createElement("dp-actionbar"));
    bar2.className = "phone";
    bar2.items = [ITEMS[0], ITEMS[1], ITEMS[2], ITEMS[5], ITEMS[4], ITEMS[9]];
    bar.hidden = true;
    await settle();
    sheet.open([[ITEMS[1], ITEMS[2]], [ITEMS[0], ITEMS[4]], [ITEMS[3]]], { title: "S13 · Step table as a treegrid" });
  }
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
  const labels = () => [...palette.querySelectorAll('[role="option"] .label')].map((l) => l.textContent);

  await test("fuzzy prefers word starts and runs", () => {
    const a = fuzzy("rv", "Ready for Review");
    const b = fuzzy("rv", "Archive");
    if (!a || !b || a.score <= b.score) throw new Error(`${a?.score} vs ${b?.score}`);
    eq(fuzzy("xyz", "Rename"), null);
    eq(fuzzy("gp", "Go to Projects").positions, [0, 6]);
  });

  await test("palette filters, highlights and runs on Enter", async () => {
    ran.length = 0;
    palette.open({ items: ITEMS });
    await settle();
    eq(labels().length, ITEMS.length, "unfiltered");
    await type(palette.input, "mark done");
    eq(labels()[0], "Mark Done");
    if (!palette.querySelector('[aria-selected="true"] mark')) throw new Error("no highlight");
    key(palette.input, "Enter");
    eq([ran, palette.dialog.open], [["step.status.done"], false]);
  });

  await test("palette arrows move, a disabled row does not run", async () => {
    ran.length = 0;
    palette.open({ items: ITEMS });
    await type(palette.input, "delete");
    eq(labels()[0], "Delete Steps");
    if (!palette.querySelector('[aria-selected="true"]').textContent.includes("reopen it first")) throw new Error("reason not shown");
    key(palette.input, "Enter");
    eq(ran, [], "ran");
    await type(palette.input, "go");
    key(palette.input, "ArrowDown");
    await settle();
    const active = palette.input.getAttribute("aria-activedescendant");
    eq(palette.querySelector(`#${active} .label`).textContent, labels()[1]);
    key(palette.input, "Escape");
    eq(palette.dialog.open, false);
  });

  await test("palette shows an empty state", async () => {
    palette.open({ items: ITEMS });
    await type(palette.input, "zzqx");
    eq(palette.querySelector(".empty")?.textContent, "No command matches “zzqx”");
    palette.close();
  });

  await test("palette scope chip widens on Backspace", async () => {
    palette.open({ items: ITEMS.slice(0, 4), scope: "S12", onWiden: () => WIDER });
    await settle();
    eq(palette.querySelector(".scope")?.textContent, "S12");
    key(palette.input, "Backspace");
    await settle();
    eq([palette.querySelector(".scope"), labels().length], [null, WIDER.length]);
    palette.close();
  });

  await test("palette returns focus where it was", async () => {
    const button = document.body.appendChild(document.createElement("button"));
    button.focus();
    palette.open({ items: ITEMS });
    palette.close();
    await settle();
    eq(document.activeElement === button, true);
    button.remove();
  });

  await test("which-key lists what the next key does", async () => {
    whichkey.prefix = "g";
    whichkey.items = ITEMS.filter((i) => i.keys?.startsWith("g "));
    await settle();
    eq([...whichkey.querySelectorAll(".next")].map((n) => n.textContent), ["p", "s", "a"]);
    whichkey.prefix = null;
    await settle();
    eq(whichkey.querySelector(".panel"), null);
  });

  await test("cheat sheet filters by label and key", async () => {
    cheat.sections = SECTIONS;
    await settle();
    cheat.open();
    await type(cheat.querySelector("input"), "peek");
    eq([...cheat.querySelectorAll("li span:last-child")].map((s) => s.textContent), ["Peek"]);
    await type(cheat.querySelector("input"), "ctrl");
    if (cheat.querySelectorAll("li").length < 3) throw new Error("key filter");
    key(cheat.querySelector("input"), "Escape");
    eq(cheat.dialog.open, false);
  });

  await test("statusbar shows mode, echo and the key a mouse user could have used", async () => {
    bar.mode = { name: "EDIT", exits: "Esc leaves the field", tone: "edit" };
    bar.echo = { keys: "F2", label: "Rename…", source: "pointer" };
    await settle();
    eq(bar.querySelector(".mode").textContent, "EDIT");
    eq(bar.querySelector(".mode").dataset.tone, "edit");
    eq(bar.querySelector(".exits").textContent, "Esc leaves the field");
    if (!bar.querySelector(".echo").textContent.includes("Rename") || !bar.querySelector(".echo kbd")) throw new Error("echo");
    bar.echo = { keys: "x", refused: "Nothing to select here" };
    await settle();
    if (!bar.querySelector(".echo.refused")) throw new Error("refusal");
    bar.echo = null;
    await settle();
    eq(bar.querySelector(".echo"), null);
    eq(bar.querySelectorAll(".crumb").length, 3);
  });

  await test("statusbar verbs show only with the verbs attribute", async () => {
    bar.verbs = [item("a", "rename", { keys: "r" })];
    await settle();
    eq(bar.querySelector(".verbs"), null);
    bar.setAttribute("verbs", "");
    await settle();
    eq(bar.querySelector(".verbs .verb").textContent.includes("rename"), true);
    bar.removeAttribute("verbs");
  });

  await test("toast undo calls back and dismisses; at most three", async () => {
    let undone = 0;
    toast("one");
    toast("two");
    toast("three", { undo: () => undone++ });
    toast("four");
    await settle();
    const stack = document.querySelector("dp-toasts");
    eq([...stack.querySelectorAll(".message")].map((m) => m.textContent), ["two", "three", "four"]);
    stack.querySelector(".undo").click();
    await new Promise((r) => setTimeout(r, 300));
    eq(undone, 1);
    eq([...stack.querySelectorAll(".message")].map((m) => m.textContent), ["two", "four"]);
    if (document.activeElement?.closest?.("dp-toasts")) throw new Error("toast took focus");
  });

  await test("toast timer pauses while hovered", async () => {
    const stack = document.querySelector("dp-toasts");
    stack.items.forEach((t) => stack.dismiss(t, false));
    toast("short", { duration: 60 });
    stack.dispatchEvent(new PointerEvent("pointerenter"));
    await new Promise((r) => setTimeout(r, 150));
    eq(stack.items.length, 1, "paused");
    stack.dispatchEvent(new PointerEvent("pointerleave"));
    await new Promise((r) => setTimeout(r, 400)); // the remaining 60 ms, then a 100 ms fade, with room
    await settle();
    eq(stack.items.length, 0, "resumed");
  });

  await test("sheet opens with groups and runs a row", async () => {
    ran.length = 0;
    sheet.open([[ITEMS[0], ITEMS[1]], [ITEMS[3]]], { title: "S12" });
    await settle();
    eq(sheet.querySelectorAll(".group").length, 2);
    eq(sheet.querySelector("h2").textContent, "S12");
    sheet.querySelectorAll(".row")[2].click(); // disabled
    eq(ran, []);
    sheet.querySelectorAll(".row")[0].click();
    eq(ran, ["step.rename"]);
    await new Promise((r) => setTimeout(r, 300));
    eq(sheet.dialog.open, false);
  });

  await test("action bar folds past five into More", async () => {
    const ab = document.body.appendChild(document.createElement("dp-actionbar"));
    ab.items = ITEMS.slice(0, 7);
    await settle();
    const labels = [...ab.querySelectorAll("button span")].map((s) => s.textContent);
    eq(labels, ["Rename…", "Mark Done", "Ready for Review", "Delete Steps", "More"]);
    ab.remove();
  });

  window.__results = results;
  window.__done = true;
}
