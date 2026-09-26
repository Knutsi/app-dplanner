/**
 * The port's staffing matrix beside the real one, field by field.
 *
 *   dplanner schedule matrix <project> --json --library <a copy> > matrix.json
 *   deno task compare-matrix local/<slug>.json matrix.json
 *
 * Run the real verb against a *copy* of the plan repository: every dplanner verb migrates
 * and flushes what it opens, reading ones included. The export's last frame is compared,
 * so export with --worktree when the copy has uncommitted changes.
 */

import { isoDay, parseDay } from "../src/model/calendar.ts";
import {
  daysFor,
  efficiencyOf,
  isMilestone,
  milestoneLabel,
  placed,
  startOf,
  teamOf,
} from "../src/model/graph.ts";
import { milestoneColors } from "../src/model/palettes.ts";
import { calendarDays, cellAt, pushed, timeReport } from "../src/model/simulate.ts";
import { isExport, planFromJson } from "../src/data.ts";

const [exported, matrix] = Deno.args;
if (!exported || !matrix) {
  console.error("usage: deno task compare-matrix local/<slug>.json matrix.json");
  Deno.exit(2);
}
const file = JSON.parse(await Deno.readTextFile(exported));
if (!isExport(file)) throw new Error(`${exported} is not an export`);
const real = JSON.parse(await Deno.readTextFile(matrix));
const frame = file.frames[file.frames.length - 1];
const plan = planFromJson(frame.plan);
const today = parseDay(frame.day)!;
const report = timeReport(plan, daysFor, {
  start: startOf(plan, today),
  today,
  efficiency: efficiencyOf(plan),
})!;
const [humans, agents] = teamOf(plan);
const colors = milestoneColors(plan, plan.assumptions.palette);
const calendar = cellAt(report.calendar, humans, agents)!;

const port = {
  start: isoDay(report.start),
  efficiency: report.efficiency,
  effort: {
    agent: report.agentDays,
    human: report.humanDays,
    total: report.agentDays + report.humanDays,
  },
  floor: { calendar_days: report.calendarFloor, days: report.floor },
  has_agent_steps: report.hasAgentSteps,
  unestimated: report.unestimated,
  team: { humans, agents },
  parallel: report.parallel.map((cell) => ({
    agents: cell.agents,
    days: cell.days,
    humans: cell.humans,
  })),
  calendar: report.calendar.map((cell) => ({
    agents: cell.agents,
    days: cell.days,
    finish: cell.finish !== null ? isoDay(cell.finish) : "",
    humans: cell.humans,
  })),
  milestones: calendar.phases.filter((phase) => phase.milestone).map((phase) => ({
    asked: phase.asked !== null ? isoDay(phase.asked) : "",
    calendar_days: calendarDays(phase),
    color: colors.get(phase.milestone!.id),
    days: phase.days,
    finish: phase.finish !== null ? isoDay(phase.finish) : "",
    label: milestoneLabel(phase.milestone!),
    pushed: pushed(phase),
    start: isoDay(phase.start),
    step: phase.milestone!.id,
  })),
};

let differences = 0;
const compare = (path: string, mine: unknown, theirs: unknown) => {
  if (typeof mine === "object" && mine !== null && typeof theirs === "object" && theirs !== null) {
    for (const key of new Set([...Object.keys(mine), ...Object.keys(theirs)])) {
      if (key === "steps" || key === "project" || key === "palette") continue;
      compare(
        `${path}.${key}`,
        (mine as Record<string, unknown>)[key],
        (theirs as Record<string, unknown>)[key],
      );
    }
    return;
  }
  if (JSON.stringify(mine) !== JSON.stringify(theirs ?? "")) {
    differences += 1;
    console.log(`${path}: port ${JSON.stringify(mine)}, dplanner ${JSON.stringify(theirs)}`);
  }
};
compare("matrix", port, real);
const order = placed(plan).map((place) => place.step).filter(isMilestone).length;
console.log(
  differences
    ? `${differences} difference${differences === 1 ? "" : "s"}`
    : `the same: 12 cells in both lenses, ${order} milestones, the floors and the effort`,
);
