// Serves prototype/ (and tools/node_modules at /node_modules/) and opens one page in Chromium.
//   node tools/run.mjs <page under prototype/> [--wait] [--shot out.png] [--size 1280x800]
//        [--scale 2] [--scheme dark|light] [--mobile] [--eval "js"] [--after ms] [--delay ms] [--log] [--full]
// --wait waits for window.__done and prints window.__results as JSON.
import { chromium } from "playwright-core";
import { serve } from "./server.mjs";

const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i < 0 ? null : args[i + 1]; };

const server = await serve();

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM ?? "/usr/bin/chromium" });
const [w, h] = (opt("--size") ?? "1280x800").split("x").map(Number);
const context = await browser.newContext({
  viewport: { width: w, height: h },
  deviceScaleFactor: Number(opt("--scale") ?? 1),
  hasTouch: args.includes("--mobile"),
  isMobile: args.includes("--mobile"),
  colorScheme: opt("--scheme") ?? "dark",
});
const page = await context.newPage();
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error" && m.text().includes("404")) return; // the favicon
  if (m.type() === "error" || m.type() === "warning") errors.push(`${m.type()}: ${m.text()}`);
  else if (args.includes("--log")) console.log(m.text());
});
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
await page.goto(`http://localhost:${server.address().port}/${args[0]}`);
if (args.includes("--wait")) {
  await page.waitForFunction(() => window.__done === true, null, { timeout: 300000 });
  console.log(JSON.stringify(await page.evaluate(() => window.__results), null, 1));
} else await page.waitForTimeout(Number(opt("--delay") ?? 400));
const script = opt("--eval");
if (script) {
  const out = await page.evaluate(script);
  if (out !== undefined) console.log(out);
  await page.waitForTimeout(Number(opt("--after") ?? 300));
}
if (opt("--shot")) await page.screenshot({ path: opt("--shot"), fullPage: args.includes("--full") });
if (errors.length) console.error(errors.join("\n"));
await browser.close();
server.close();
