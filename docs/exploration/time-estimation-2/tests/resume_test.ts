/**
 * The v4 model, `resume`: the plan's own dates stand while reality matches them; otherwise
 * the rest of the work resumes from tomorrow, work in flight credited (ISSUES F5).
 */

import { type Day, fromYMD, weekday } from "../src/model/calendar.ts";
import { daysFor, isMilestone } from "../src/model/graph.ts";
import { ADOPTED, type ModelOptions } from "../src/model/options.ts";
import { landingIn } from "../src/model/progress.ts";
import { brief } from "../src/brief.ts";
import { timelineAccuracy } from "../src/sim/accuracy.ts";
import { SAMPLE_START, samplePlan } from "../src/sim/sample.ts";
import { scenarioById } from "../src/sim/scenarios.ts";
import { snapshotOf, type Timeline } from "../src/sim/timeline.ts";
import { DEFAULT_WORLD, run } from "../src/sim/world.ts";
import { landingOf, parallelFinish, phases } from "../src/model/simulate.ts";
import { assert, assertEquals, planOf, sep } from "./helpers.ts";
import { played } from "./played.ts";

const SEEDS = [1, 2, 3, 7, 11, 42];
const RESTART: ModelOptions = { ...ADOPTED, replan: "restart" };

function playedOut(id: string, seed: number): Timeline {
  const scenario = scenarioById(id);
  return run(samplePlan(seed), { ...DEFAULT_WORLD, ...scenario.world, seed }, SAMPLE_START);
}

/** A's four days are under way, B's two wait on it; one person, dated from Monday 7 Sep. */
function underWay(since: Day, today: Day) {
  const plan = planOf(["A", "B"], {
    chain: true,
    days: { A: 4, B: 2 },
    running: ["A"],
    since: { A: since },
  });
  const dated = phases(plan, daysFor, {
    humans: 1,
    agents: 1,
    start: sep(7),
    today,
    options: ADOPTED,
  });
  return ["A", "B"].map((id) => landingOf(dated[0], id));
}

Deno.test("by the book, every forecast is the real landing, every day: the date never moves", () => {
  for (const seed of SEEDS) {
    const { whole, milestones } = timelineAccuracy(playedOut("by-the-book", seed), ADOPTED);
    assertEquals([whole.error, whole.movement], [0, 0], `seed ${seed}, the whole plan`);
    assertEquals([milestones.error, milestones.movement], [0, 0], `seed ${seed}, milestones`);
  }
});

Deno.test("v3's restart draws the saw-tooth on the same days that resume holds still", () => {
  const { whole } = timelineAccuracy(playedOut("by-the-book", 1), RESTART);
  assert(whole.movement > 20 && whole.moves > 10, JSON.stringify(whole));
});

Deno.test("the screenshot: by the book on Sunday 11 October, the plan still lands 2 December", () => {
  const found = brief(played("by-the-book").viewOn(fromYMD(2026, 10, 11)));
  assertEquals(found.whole.move.planned, fromYMD(2026, 12, 2));
  assertEquals(found.whole.move.plan, 0);
});

Deno.test("while work in flight is on plan, the plan's own dates stand", () => {
  // Wednesday: A started Monday as planned, and lands Thursday; B lands Monday.
  assertEquals(underWay(sep(7), sep(9)), [sep(10), sep(14)]);
});

Deno.test("work that started late resumes from tomorrow, credited with the days spent on it", () => {
  // A started Tuesday, a day late. From Thursday it has 4 − 1.5 days left: Monday; B Wednesday.
  assertEquals(underWay(sep(8), sep(9)), [sep(14), sep(16)]);
});

Deno.test("work still open after its estimate has half a day left, from tomorrow", () => {
  // Friday: A should have landed Thursday. It lands Monday; B two days later.
  assertEquals(underWay(sep(7), sep(11)), [sep(14), sep(16)]);
});

Deno.test("a weekend moves nothing: Friday, Saturday and Sunday read the same", () => {
  const friday = underWay(sep(8), sep(11));
  assertEquals(underWay(sep(8), sep(12)), friday);
  assertEquals(underWay(sep(8), sep(13)), friday);
  const timeline = playedOut("optimistic", 1);
  let [lastFriday, said] = [0, ""];
  for (const frame of timeline.frames.filter((one) => one.day >= timeline.begin)) {
    const landing = String(landingIn(snapshotOf(frame.plan, frame.day, ADOPTED)!, null));
    if (weekday(frame.day) === 4) [lastFriday, said] = [frame.day, landing];
    if (weekday(frame.day) > 4 && lastFriday) assertEquals(landing, said, `${frame.day}`);
  }
});

Deno.test("work in flight keeps its worker: it goes first, whatever waits behind it", () => {
  const plan = planOf(["A", "B"], { days: { A: 1, B: 5 } });
  const fresh = parallelFinish(plan.steps, daysFor, 1, 1)!;
  const resumed = parallelFinish(plan.steps, daysFor, 1, 1, new Set(["A"]))!;
  assertEquals([fresh.starts.get("B"), fresh.starts.get("A")], [0, 5]);
  assertEquals([resumed.starts.get("A"), resumed.starts.get("B")], [0, 1]);
});

Deno.test("a lower budget never re-dates work that is done, nor holds the rest behind it", () => {
  const timeline = playedOut("by-the-book", 1);
  const today = fromYMD(2026, 11, 2);
  const plan = timeline.frames.find((frame) => frame.day === today)!.plan;
  const slow = { ...plan, assumptions: { ...plan.assumptions, efficiency: 0.1 } };
  const m1 = plan.steps.filter(isMilestone)[0];
  const [m2] = plan.steps.filter(isMilestone).slice(1);
  const resumed = snapshotOf(slow, today, ADOPTED)!;
  const restarted = snapshotOf(slow, today, RESTART)!;
  assertEquals(landingIn(resumed, m1.id), timeline.finished.get(m1.id));
  assert(landingIn(resumed, m2.id)! < landingIn(restarted, m2.id)!, "M2 no longer waits on M1");
});

Deno.test("a plan finished late never holds again: at the end, the landing is the real one", () => {
  const { timeline, viewOn } = played("optimistic");
  const end = timeline.frames[timeline.frames.length - 1].day;
  const found = brief(viewOn(end));
  const truth = Math.max(...timeline.finished.values());
  assertEquals(found.whole.move.planned, truth);
  assert(found.whole.move.plan! > 10, `moved ${found.whole.move.plan} against the start`);
});
