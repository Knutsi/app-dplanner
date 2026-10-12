// The prototype's stand-in for a local `dplanner serve`: static files from prototype/, the
// harness's node_modules at /node_modules/, and /api/theme — the Omarchy theme the desktop is
// wearing, read the way modules/theme_omarchy/themes.py reads it, with an ETag so a poll that
// finds nothing new costs a 304.
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..", "prototype");
const MODULES = path.join(HERE, "node_modules");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json", ".png": "image/png" };
const STATE = path.join(process.env.XDG_STATE_HOME ?? path.join(os.homedir(), ".local", "state"), "omarchy", "current");

function omarchyTheme() {
  try {
    const colors = {};
    for (const line of fs.readFileSync(path.join(STATE, "theme", "colors.toml"), "utf8").split("\n")) {
      const m = line.match(/^\s*([a-z_]+)\s*=\s*"([^"]*)"/);
      if (m) colors[m[1]] = m[2];
    }
    let name = "omarchy";
    try {
      name = fs.readFileSync(path.join(STATE, "theme.name"), "utf8").trim() || name;
    } catch {}
    return colors.background && colors.foreground ? { name, colors } : null;
  } catch {
    return null; // not Omarchy, or mid-swap: the page keeps what it has
  }
}

export function serve(port = 0) {
  const server = http.createServer((req, res) => {
    const url = decodeURIComponent(req.url.split("?")[0]);
    if (url === "/api/theme") {
      const theme = omarchyTheme();
      if (!theme) return res.writeHead(404).end();
      const body = JSON.stringify(theme);
      const etag = `"${crypto.createHash("sha1").update(body).digest("hex").slice(0, 16)}"`;
      if (req.headers["if-none-match"] === etag) return res.writeHead(304).end();
      return res.writeHead(200, { "content-type": "application/json", etag }).end(body);
    }
    const file = url.startsWith("/node_modules/")
      ? path.join(MODULES, url.slice(14))
      : url.startsWith("/demo/")
        ? path.join(ROOT, "..", url) // the bundled build, from tools/build-demo.mjs
        : path.join(ROOT, url === "/" ? "desktop.html" : url);
    fs.readFile(file, (err, data) => {
      if (err) return res.writeHead(404).end();
      res.writeHead(200, { "content-type": TYPES[path.extname(file)] ?? "application/octet-stream" }).end(data);
    });
  });
  return new Promise((resolve) => server.listen(port, () => resolve(server)));
}
