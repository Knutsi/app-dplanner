// Drives the prototype with real keyboard and mouse input and photographs named states for the
// report. Any console error fails the run.
//   node tools/scenes.mjs [name-filter]      → shots/<scene>.png
import { chromium } from "playwright-core";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { serve } from "./server.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(HERE, "..", "shots");
const filter = process.argv[2] ?? "";

const settle = (page, ms = 350) => page.waitForTimeout(ms);
const row = (key) => `dp-grid [data-key="${key}"]`;

// Each scene: { name, variant, theme ("auto" follows /api/theme), size, mobile, act(page) }.
const SCENES = [
  { name: "desktop-ledger-retro82", act: async (p) => { await p.keyboard.press("j"); await p.keyboard.press("j"); } },
  {
    name: "desktop-selection-bar",
    act: async (p) => {
      for (const k of ["j", "j", "x", "j", "x", "j", "j", "x"]) await p.keyboard.press(k);
    },
  },
  {
    name: "desktop-menu-step-status",
    act: async (p) => {
      for (const k of ["j", "j", "j"]) await p.keyboard.press(k);
      await p.click("dp-menubar [role=menuitem] >> text=Step");
      await settle(p, 200);
      await p.hover("dp-menu [role=menuitem] >> text=Status");
      await settle(p, 300);
    },
  },
  {
    name: "desktop-context-menu",
    act: async (p) => {
      await p.click(row("S8"), { button: "right" });
    },
  },
  {
    name: "desktop-palette-scoped",
    act: async (p) => {
      await p.click(row("S9"), { modifiers: ["Control"] });
      await p.click(row("S10"), { modifiers: ["Control"] });
      await p.keyboard.press("Control+k");
      await settle(p, 150);
      await p.keyboard.type("stat");
    },
  },
  {
    name: "desktop-whichkey",
    act: async (p) => {
      await p.keyboard.press("j");
      await p.keyboard.press("j");
      await p.keyboard.press("s");
      await settle(p, 650);
    },
  },
  {
    name: "desktop-cheatsheet",
    act: async (p) => {
      await p.keyboard.press("j");
      await p.keyboard.press("Shift+?");
    },
  },
  {
    name: "desktop-split-follow-peek",
    size: [1440, 820],
    act: async (p) => {
      for (const k of ["j", "j", "j", "j"]) await p.keyboard.press(k);
      await p.keyboard.press("Control+Shift+\\");
      await settle(p, 200);
      await p.click(row("S13"));
      await p.keyboard.press("Space");
    },
  },
  {
    name: "desktop-agent-running",
    act: async (p) => {
      await p.click(row("S9"), { modifiers: ["Control"] });
      await p.click(row("S11"), { modifiers: ["Control"] });
      await p.keyboard.press("Shift+R");
      await p.keyboard.press("Control+j");
      await settle(p, 1600);
    },
  },
  {
    name: "desktop-echo-pointer",
    act: async (p) => {
      await p.click(row("S6"));
      await p.click("dp-toolbar [aria-label='Peek']");
      await settle(p, 200);
    },
  },
  {
    name: "desktop-preview-tab",
    act: async (p) => {
      for (const k of ["j", "j", "j", "Enter"]) await p.keyboard.press(k);
      await settle(p, 200);
    },
  },
  { name: "desktop-modeline-retro82", variant: "modeline", act: async (p) => { for (const k of ["j", "j", "j", "x", "j", "x"]) await p.keyboard.press(k); } },
  { name: "desktop-atelier-light", variant: "atelier", theme: "house:dplanner-light", scheme: "light", act: async (p) => { await p.click(row("S4")); await p.keyboard.press("Space"); } },
  { name: "desktop-ledger-light", theme: "house:dplanner-light", scheme: "light", act: async (p) => { for (const k of ["j", "j", "x", "j", "x"]) await p.keyboard.press(k); } },
  { name: "touch-list", page: "mobile.html", mobile: true, act: async () => {} },
  {
    name: "touch-selecting",
    page: "mobile.html",
    mobile: true,
    act: async (p) => {
      const box = await p.locator(".touch-row").nth(7).boundingBox();
      await p.mouse.move(box.x + 40, box.y + 20);
      await p.mouse.down();
      await settle(p, 600);
      await p.mouse.up();
      await p.locator(".touch-row").nth(9).click();
    },
  },
  {
    name: "touch-status-sheet",
    page: "mobile.html",
    mobile: true,
    act: async (p) => {
      await p.locator(".touch-row").nth(6).click();
      await settle(p, 400);
      await p.locator("dp-actionbar button >> text=Status").click();
      await settle(p, 400);
    },
  },
  { name: "touch-light-atelier", page: "mobile.html", mobile: true, variant: "atelier", theme: "house:dplanner-light", scheme: "light", act: async (p) => { await p.locator(".touch-row").nth(3).click(); } },
  { name: "theme-tokyo-night", theme: "omarchy:tokyo-night", act: async (p) => { await p.keyboard.press("j"); } },
  { name: "theme-catppuccin-latte", theme: "omarchy:catppuccin-latte", scheme: "light", act: async (p) => { await p.keyboard.press("j"); } },
  { name: "theme-gruvbox", theme: "omarchy:gruvbox", variant: "modeline", act: async (p) => { await p.keyboard.press("j"); } },
  { name: "theme-rose-pine", theme: "omarchy:rose-pine", variant: "atelier", act: async (p) => { await p.keyboard.press("j"); } },
];

const server = await serve();
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM ?? "/usr/bin/chromium" });
let failed = 0;
for (const scene of SCENES.filter((s) => s.name.includes(filter))) {
  const [width, height] = scene.size ?? (scene.mobile ? [390, 844] : [1280, 760]);
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: scene.mobile ? 3 : 2, isMobile: !!scene.mobile, hasTouch: !!scene.mobile, colorScheme: scene.scheme ?? "dark" });
  await context.addInitScript(({ variant, theme }) => {
    localStorage.setItem("dp.variant", variant);
    localStorage.setItem("dp.theme", theme);
  }, { variant: scene.variant ?? "ledger", theme: scene.theme ?? "auto" });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && !m.text().includes("404") && errors.push(m.text()));
  await page.goto(`http://localhost:${server.address().port}/${scene.page ?? "desktop.html"}`);
  await page.waitForFunction(() => window.__done === true);
  await settle(page, 300);
  await scene.act(page);
  await settle(page);
  await page.screenshot({ path: path.join(SHOTS, `${scene.name}.png`) });
  console.log(`${errors.length ? "FAIL" : "ok  "} ${scene.name}${errors.length ? `: ${errors.join(" | ")}` : ""}`);
  failed += errors.length ? 1 : 0;
  await context.close();
}
await browser.close();
server.close();
process.exit(failed ? 1 : 0);
