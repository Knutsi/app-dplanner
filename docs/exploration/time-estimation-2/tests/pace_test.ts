/** v5's *Pace so far*: people's finished steps against the working days they took. */

import { type Day, isoDay } from "../src/model/calendar.ts";
import { daysFor, efficiencyOf, startOf } from "../src/model/graph.ts";
import { ADOPTED, type ModelOptions } from "../src/model/options.ts";
import { asPlanned, landingOf, paceSoFar, phases, stretched } from "../src/model/simulate.ts";
import { timelineAccuracy } from "../src/sim/accuracy.ts";
import { snapshotOf, type Timeline } from "../src/sim/timeline.ts";
import { assert, assertEquals, planOf, sep } from "./helpers.ts";
import { played } from "./played.ts";

const PACED: ModelOptions = { ...ADOPTED, pace: true };

/** A, B and C each given two days, started Monday 7 Sep and done on `done`; D and E wait. */
function finished(done: Day, count = 3) {
  const titles = ["A", "B", "C"].slice(0, count);
  return planOf([...titles, "D", "E"], {
    days: { A: 2, B: 2, C: 2, D: 2, E: 2 },
    agents: ["E"],
    done: titles,
    started: Object.fromEntries(titles.map((title) => [title, sep(7)])),
    since: Object.fromEntries(titles.map((title) => [title, done])),
  });
}

const lastPace = (timeline: Timeline) => {
  const { plan, day } = timeline.frames[timeline.frames.length - 1];
  return paceSoFar(plan, stretched(daysFor, efficiencyOf(plan)), startOf(plan, day), day);
};

Deno.test("the pace is each finished step's days against the working days it took", () => {
  // Monday to Wednesday is two working days from the middle of one to the middle of the other.
  assertEquals(paceSoFar(finished(sep(9)), daysFor, sep(7), sep(15)), 1);
  assertEquals(paceSoFar(finished(sep(11)), daysFor, sep(7), sep(15)), 0.5);
});

Deno.test("no pace before five working days of work and three finished steps", () => {
  assertEquals(paceSoFar(finished(sep(9)), daysFor, sep(7), sep(11)), null);
  assertEquals(paceSoFar(finished(sep(9), 2), daysFor, sep(7), sep(15)), null);
});

Deno.test("at the pace so far a person's step takes longer; an agent's does not", () => {
  // Half the pace: D's two days take four, Tuesday to Friday, where they took to Wednesday.
  const plan = finished(sep(11));
  const args = { humans: 1, agents: 1, start: sep(7), today: sep(14) };
  const [was, is] = [ADOPTED, PACED].map((options) => phases(plan, daysFor, { ...args, options }));
  assertEquals([landingOf(was[0], "D"), landingOf(is[0], "D")], [sep(16), sep(18)]);
  assertEquals(landingOf(is[0], "E"), landingOf(was[0], "E"));
});

Deno.test("a pace within a tenth of the plan's leaves the dates as they were", () => {
  assert(asPlanned(0.95) && asPlanned(1.08) && !asPlanned(0.85) && !asPlanned(1.15));
  // Done in parallel, so the plan for one person no longer holds — but at the planned pace.
  const plan = finished(sep(9));
  const args = { humans: 1, agents: 1, start: sep(7), today: sep(15) };
  assertEquals(
    phases(plan, daysFor, { ...args, options: PACED }),
    phases(plan, daysFor, { ...args, options: ADOPTED }),
  );
});

Deno.test("By the book goes at the planned pace, and the toggle changes no date", () => {
  const { timeline } = played("by-the-book");
  assert(asPlanned(lastPace(timeline)!));
  for (const { plan, day } of timeline.frames) {
    assertEquals(snapshotOf(plan, day, PACED), snapshotOf(plan, day, ADOPTED), isoDay(day));
  }
});

Deno.test("estimates half again too short read as two thirds of the pace, and forecast closer", () => {
  let [without, paced] = [0, 0];
  for (const seed of [1, 2, 3, 7]) {
    const { timeline } = played("optimistic", ADOPTED, seed);
    const pace = lastPace(timeline)!;
    assert(0.55 < pace && pace < 0.85, `seed ${seed}: ${pace}`);
    without += timelineAccuracy(timeline, ADOPTED).whole.error;
    paced += timelineAccuracy(timeline, PACED).whole.error;
  }
  assert(paced < without * 0.75, `${paced} against ${without}`);
});
