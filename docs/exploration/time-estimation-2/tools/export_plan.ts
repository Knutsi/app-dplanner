/**
 * Export a real DPlanner project, and its history, for the prototype to replay.
 *
 *   deno task export <plan-repo> <project-dir> [--worktree]
 *   deno task export ~/Code/app-dplanner-planning dplanner --worktree
 *
 * It only reads. Every commit that touched the project directory is read through git's
 * plumbing (`log`, `ls-tree`, one `cat-file --batch`), never checked out, and `dplanner` is
 * never run — every verb, even a reading one, migrates and flushes the files it opens.
 * `--worktree` adds the uncommitted files on disk as a last frame.
 *
 * It writes `local/<slug>.json` and rewrites `local/plans.js` to list every export there, so
 * `index.html` picks them up from disk with no server. `local/` is gitignored: a plan may
 * belong to a client, and this repository is public.
 *
 * Which DPlanner file each field comes from (FORMAT.md has the shapes):
 *   project.dproj                     children (project order), title, id
 *   modules/estimation.json           start
 *   modules/time_estimates.json       efficiency, palette, team
 *   modules/progress_history.json     kept whole, as stored
 *   steps/<slug>/step.json            id, number, title, edges.requires, created
 *   steps/<slug>/modules/estimation.json         days, off, history (step_estimation.json before the rename)
 *   steps/<slug>/modules/step_status.json        status
 *   steps/<slug>/modules/step_milestone.json     label (step_release.json before the rename)
 *   steps/<slug>/modules/step_agent_instruction.json | .md   agent work
 *   steps/<slug>/modules/time_estimates.json     a milestone's start and colour
 */

import {
  EXPORT_FORMAT,
  type ExportFile,
  type ExportFrame,
  type PlanJson,
  type StepJson,
} from "../src/data.ts";
import type { Status } from "../src/model/graph.ts";
import { PALETTES } from "../src/model/palettes.ts";

type Json = Record<string, unknown>;
type Files = Map<string, string>; // Path under the project directory → contents.

const LOCAL = new URL("../local/", import.meta.url);
const STATUSES: Status[] = ["pending", "in-progress", "done", "blocked"];
const decoder = new TextDecoder();

async function git(repo: string, args: string[], input?: string): Promise<Uint8Array> {
  const command = new Deno.Command("git", {
    args: ["-C", repo, ...args],
    stdin: input === undefined ? "null" : "piped",
    stdout: "piped",
    stderr: "piped",
  });
  const child = command.spawn();
  if (input !== undefined) {
    const writer = child.stdin.getWriter();
    await writer.write(new TextEncoder().encode(input));
    await writer.close();
  }
  const { code, stdout, stderr } = await child.output();
  if (code !== 0) throw new Error(`git ${args[0]} failed: ${decoder.decode(stderr)}`);
  return stdout;
}

/** Every blob asked for, by object id — one `cat-file --batch` for the whole history. */
async function blobs(repo: string, ids: string[]): Promise<Map<string, string>> {
  const out = await git(repo, ["cat-file", "--batch"], ids.join("\n") + "\n");
  const found = new Map<string, string>();
  let at = 0;
  while (at < out.length) {
    const end = out.indexOf(10, at);
    const [id, kind, size] = decoder.decode(out.subarray(at, end)).split(" ");
    at = end + 1;
    if (kind === "missing") continue;
    const length = Number(size);
    found.set(id, decoder.decode(out.subarray(at, at + length)));
    at += length + 1;
  }
  return found;
}

const WANTED = /(project\.dproj|\.json|step_agent_instruction\.md)$/;

function parse(text: string | undefined): Json | null {
  if (text === undefined) return null;
  try {
    const value = JSON.parse(text);
    return typeof value === "object" && value !== null ? value : null;
  } catch {
    return null;
  }
}

const isNumber = (value: unknown): value is number => typeof value === "number";
const isText = (value: unknown): value is string => typeof value === "string";
const dayOf = (value: unknown): string | null =>
  isText(value) && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : null;

/** The plan as the model reads it, from one commit's files — each reader DPlanner's own. */
function planOf(files: Files): PlanJson | null {
  const project = parse(files.get("project.dproj"));
  if (!project) return null;
  const modules = (name: string) => parse(files.get(`modules/${name}.json`)) ?? {};
  const assumptions = modules("time_estimates");
  const efficiency = assumptions.efficiency;
  const team = assumptions.team;
  const palette = assumptions.palette;
  const steps: StepJson[] = [];
  const children = Array.isArray(project.children) ? project.children.filter(isText) : [];
  for (const slug of children) {
    const step = parse(files.get(`steps/${slug}/step.json`));
    if (!step || !isText(step.id)) continue;
    const aspect = (name: string) => parse(files.get(`steps/${slug}/modules/${name}.json`));
    const estimate = aspect("estimation") ?? aspect("step_estimation") ?? {};
    const status = aspect("step_status")?.status;
    const label = (aspect("step_milestone") ?? aspect("step_release"))?.label;
    const agent = aspect("step_agent_instruction");
    const instruction = files.get(`steps/${slug}/modules/step_agent_instruction.md`) ?? "";
    const own = aspect("time_estimates") ?? {};
    const history = Array.isArray(estimate.history) ? estimate.history as Json[] : [];
    const edges = (step.edges ?? {}) as Json;
    steps.push({
      id: step.id,
      number: isNumber(step.number) ? step.number : steps.length + 1,
      title: isText(step.title) ? step.title : slug,
      requires: Array.isArray(edges.requires) ? edges.requires.filter(isText) : [],
      estimate: isNumber(estimate.days) ? estimate.days : null,
      estimateOff: Boolean(estimate.off),
      estimateHistory: history.flatMap((row) => {
        const day = dayOf(row?.day);
        return day && isNumber(row.days) ? [[day, row.days] as [string, number]] : [];
      }),
      status: STATUSES.includes(status as Status) ? status as Status : "pending",
      milestone: isText(label) && label ? label : null,
      // enabled(): any stored mark, or a separate instruction.
      agent: Object.keys(agent ?? {}).some((key) => key !== "format") ||
        Boolean(instruction.trim()),
      created: dayOf(step.created),
      start: dayOf(own.start),
      color: isText(own.color) && /^#[0-9a-fA-F]{6}$/.test(own.color)
        ? own.color.toLowerCase()
        : null,
    });
  }
  return {
    id: isText(project.id) ? project.id : "",
    title: isText(project.title) ? project.title : "",
    start: dayOf(modules("estimation").start),
    assumptions: {
      efficiency: isNumber(efficiency) && efficiency > 0 && efficiency <= 1 ? efficiency : null,
      palette: isText(palette) && PALETTES.some((found) => found.id === palette) ? palette : null,
      team:
        Array.isArray(team) && team.length === 2 && team.every((n) => Number.isInteger(n) && n >= 1)
          ? [team[0], team[1]]
          : null,
    },
    steps,
  };
}

function frameOf(files: Files, day: string, commit: string, time: string): ExportFrame | null {
  const plan = planOf(files);
  return plan &&
    { day, commit, time, plan, history: parse(files.get("modules/progress_history.json")) };
}

async function committed(repo: string, dir: string): Promise<ExportFrame[]> {
  const log = decoder.decode(await git(repo, ["log", "--format=%H%x09%cI", "--", dir])).trim();
  const commits = log ? log.split("\n").map((line) => line.split("\t")).reverse() : [];
  const trees: [string, string, Map<string, string>][] = []; // commit, time, path → blob
  const wanted = new Set<string>();
  for (const [commit, time] of commits) {
    const listing = decoder.decode(await git(repo, ["ls-tree", "-r", "-z", commit, "--", dir]));
    const paths = new Map<string, string>();
    for (const entry of listing.split("\0").filter(Boolean)) {
      const [meta, path] = entry.split("\t");
      const [, kind, id] = meta.split(" ");
      if (kind !== "blob" || !WANTED.test(path)) continue;
      paths.set(path.slice(dir.length + 1), id);
      wanted.add(id);
    }
    trees.push([commit, time, paths]);
  }
  const contents = await blobs(repo, [...wanted]);
  return trees.flatMap(([commit, time, paths]) => {
    const files: Files = new Map([...paths].map(([path, id]) => [path, contents.get(id) ?? ""]));
    const frame = frameOf(files, time.slice(0, 10), commit, time);
    return frame ? [frame] : [];
  });
}

async function onDisk(root: string): Promise<Files> {
  const files: Files = new Map();
  const walk = async (relative: string): Promise<void> => {
    for await (const entry of Deno.readDir(`${root}/${relative}`)) {
      const path = relative ? `${relative}/${entry.name}` : entry.name;
      if (entry.isDirectory) await walk(path);
      else if (WANTED.test(path)) files.set(path, await Deno.readTextFile(`${root}/${path}`));
    }
  };
  await walk("");
  return files;
}

function localDay(when: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}

async function writeIndex(): Promise<string[]> {
  const exports: string[] = [];
  for await (const entry of Deno.readDir(LOCAL)) {
    if (entry.isFile && entry.name.endsWith(".json")) exports.push(entry.name);
  }
  exports.sort();
  const bodies = await Promise.all(exports.map((name) => Deno.readTextFile(new URL(name, LOCAL))));
  await Deno.writeTextFile(
    new URL("plans.js", LOCAL),
    "// Written by tools/export_plan.ts: every export in this folder, for index.html.\n" +
      `window.TE2_LOCAL = [\n${bodies.map((body) => body.trim()).join(",\n")}\n];\n`,
  );
  return exports;
}

async function main(): Promise<void> {
  const flags = Deno.args.filter((arg) => arg.startsWith("--"));
  const [repo, dir] = Deno.args.filter((arg) => !arg.startsWith("--"));
  if (!repo || !dir) {
    console.error("usage: deno task export <plan-repo> <project-dir> [--worktree]");
    Deno.exit(2);
  }
  const project = dir.replace(/\/+$/, "");
  const frames = await committed(repo, project);
  if (flags.includes("--worktree")) {
    const now = new Date();
    const frame = frameOf(
      await onDisk(`${repo}/${project}`),
      localDay(now),
      "worktree",
      now.toISOString(),
    );
    if (frame) frames.push(frame);
  }
  if (!frames.length) {
    console.error(`nothing to export: no commit of ${project} in ${repo} holds a project.dproj`);
    Deno.exit(1);
  }
  const slug = project.split("/").pop()!.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  const file: ExportFile = {
    format: EXPORT_FORMAT,
    title: frames[frames.length - 1].plan.title || project,
    slug,
    source: { repo, dir: project, exported: new Date().toISOString() },
    frames,
  };
  await Deno.mkdir(LOCAL, { recursive: true });
  await Deno.writeTextFile(new URL(`${slug}.json`, LOCAL), JSON.stringify(file));
  const listed = await writeIndex();
  const days = new Set(frames.map((frame) => frame.day)).size;
  console.log(
    `${file.title}: ${frames.length} frames over ${days} days → local/${slug}.json` +
      ` (local/plans.js lists ${listed.length})`,
  );
}

if (import.meta.main) await main();
