// The layer rules, checked: who may import whom (ui/README.md). The web counterpart of
// DPlanner's tests/test_architecture.py — if it fails, fix the dependency, not the rule.
//   node prototype/tests/layers.test.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

// layer -> the layers it may import
const ALLOWED = {
  engine: ["engine"],
  ui: ["engine", "ui"],
  data: ["engine", "data"],
  shell: ["engine", "ui", "shell"], // the shell knows no plan data: features bring it
  features: ["engine", "ui", "shell", "data", "features"], // its own feature only, checked below
  root: ["engine", "ui", "shell", "data", "features"],
};

const layerOf = (file) => {
  const top = path.relative(ROOT, file).split(path.sep)[0];
  return top in ALLOWED ? top : top.endsWith(".js") ? "root" : null;
};
const featureOf = (file) => path.relative(ROOT, file).split(path.sep)[1];

function* sources(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory() && entry.name !== "tests") yield* sources(full);
    else if (entry.name.endsWith(".js")) yield full;
  }
}

const problems = [];
let checked = 0;
for (const file of sources(ROOT)) {
  const from = layerOf(file);
  if (!from) continue;
  const text = fs.readFileSync(file, "utf8");
  for (const [, spec] of text.matchAll(/^\s*import\s+(?:[^"']*?\s+from\s+)?["']([^"']+)["']/gm)) {
    checked++;
    if (!spec.startsWith(".")) {
      problems.push(`${path.relative(ROOT, file)} imports a package (${spec}): no runtime dependencies`);
      continue;
    }
    const target = path.resolve(path.dirname(file), spec);
    const to = layerOf(target);
    if (!ALLOWED[from].includes(to)) problems.push(`${path.relative(ROOT, file)} (${from}) may not import ${path.relative(ROOT, target)} (${to})`);
    if (from === "features" && to === "features" && featureOf(file) !== featureOf(target))
      problems.push(`${path.relative(ROOT, file)} reaches into another feature: ${path.relative(ROOT, target)}`);
    if (from === "shell" && path.basename(target) === "frame.js" && path.basename(file) !== "frame.js")
      problems.push(`${path.relative(ROOT, file)} imports the desktop frame; put what it needs in the workspace`);
  }
}

// Light DOM shares one stylesheet, so a component's CSS must not claim a bare one-word class:
// `.row`, `.bar`, `.detail` each broke another component before this check existed. A rule
// starts with its element name (`dp-menu .row`), `:root`, or a prefixed class (`.mark-bar`).
for (const file of sources(ROOT)) {
  const text = fs.readFileSync(file, "utf8");
  for (const [, block] of text.matchAll(/css`([\s\S]*?)`/g))
    for (const line of block.split("\n")) {
      const bare = /^\s*\.([a-z]+)(?![\w-])[^{]*\{/.exec(line);
      if (bare && bare[1] !== "glyph" && bare[1] !== "changed") problems.push(`${path.relative(ROOT, file)}: CSS rule on the bare class .${bare[1]} — scope it under the element or prefix it`);
    }
}

if (problems.length) {
  console.log(problems.join("\n"));
  process.exit(1);
}
console.log(`ok   ${checked} imports follow the layers`);
