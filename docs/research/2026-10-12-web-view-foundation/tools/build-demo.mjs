// Bundles the prototype into ../demo/ — one module per frame, CSS inlined into each page — so
// it can travel as a few static files (the published report embeds it). A build-time tool
// only: the prototype itself runs straight from its sources with no build step.
//   node tools/build-demo.mjs
import { build } from "esbuild";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "prototype");
const OUT = path.join(HERE, "..", "demo");
fs.mkdirSync(OUT, { recursive: true });

const css = ["tokens.css", "base.css"].map((f) => fs.readFileSync(path.join(SRC, "ui", f), "utf8")).join("\n");
for (const [name, frame, start] of [
  ["desktop", "frame", "startDesktop"],
  ["touch", "touch", "startTouch"],
]) {
  const entry = `import "./shell/${frame}.js"; import { ${start} } from "./app.js"; await ${start}(); window.__done = true;`;
  const result = await build({ stdin: { contents: entry, resolveDir: SRC, sourcefile: `${name}.js` }, bundle: true, minify: true, format: "esm", write: false, target: "es2022" });
  const js = result.outputFiles[0].text;
  fs.writeFileSync(path.join(OUT, `${name}.js`), js);
  fs.writeFileSync(
    path.join(OUT, `${name}.html`),
    `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>DPlanner ${name} prototype</title><style>${css}</style></head><body><script type="module" src="${name}.js"></script></body></html>\n`,
  );
  console.log(`${name}: ${(js.length / 1024).toFixed(1)} KB min, ${(zlib.gzipSync(js, { level: 9 }).length / 1024).toFixed(1)} KB gz`);
}
