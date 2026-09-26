/** v4's Work tab: weekends, the days nothing changed, and the waits of Delay steps. */

import { fromYMD, isWorkingDay } from "../src/model/calendar.ts";
import { isMilestone } from "../src/model/graph.ts";
import { ADOPTED } from "../src/model/options.ts";
import { type Brief, brief, burnup } from "../src/brief.ts";
import { NO_EDITS, worldDelays } from "../src/sim/edits.ts";
import { SAMPLE_START, samplePlan } from "../src/sim/sample.ts";
import { record } from "../src/sim/timeline.ts";
import { DEFAULT_WORLD, run } from "../src/sim/world.ts";
import { delaySpans, type WorkMarks, workSvg } from "../src/ui/v3/work.ts";
import { assert, assertEquals } from "./helpers.ts";
import { played, viewOf } from "./played.ts";

const TODAY = fromYMD(2026, 11, 20);
const V4: WorkMarks = { weekends: true, idle: true, delays: true };
const named = (found: Brief) => found.milestones.filter((scope) => scope.key);

function drawn(view: ReturnType<ReturnType<typeof played>["viewOn"]>, marks = V4) {
  const found = brief(view);
  const data = burnup(view, null, found.compared);
  return { data, ...workSvg(data, named(found), view, 900, found.compared, marks) };
}

Deno.test("every day off is shaded, in both plots; v3 draws none of v4's marks", () => {
  const view = played("by-the-book").viewOn(TODAY);
  const { svg, geometry } = drawn(view);
  let off = 0;
  for (let day = geometry.first + 1; day <= geometry.last; day += 1) {
    if (!isWorkingDay(day)) off += 1;
  }
  const bands = svg.match(/class="weekend"/g)?.length ?? 0;
  assert(bands >= 2 * off - 4 && bands <= 2 * off, `${bands} bands for ${off} days off`);
  const plain = drawn(view, {}).svg;
  assert(!/weekend|class="idle"|delay-hatch/.test(plain), "v3 is unchanged");
});

Deno.test("the done line is dotted across each day no step changed status, solid across the rest", () => {
  const view = played("by-the-book").viewOn(TODAY);
  const { svg, data } = drawn(view);
  const path = (dotted: boolean) =>
    svg.match(
      new RegExp(
        `<path d="([^"]*)" fill="none"[^>]*${dotted ? 'class="idle"' : 'stroke-width="2"/>'}`,
      ),
    )![1];
  const across = (d: string) => d.match(/ H/g)?.length ?? 0;
  const days = TODAY - data.done[0][0];
  const active = data.active.filter((day) => day > data.done[0][0] && day <= TODAY).length;
  assertEquals(across(path(false)), active);
  assertEquals(across(path(true)), days - active);
  assert(active > 5 && days - active > 5);
});

Deno.test("a Delay still ahead is a named band through both plots", () => {
  const plan = samplePlan(1);
  const m1 = plan.steps.filter(isMilestone)[0];
  const held = plan.steps.find((step) => step.requires.includes(m1.id))!.id;
  const made = fromYMD(2026, 10, 12);
  const until = fromYMD(2026, 11, 4);
  const edits = { ...NO_EDITS, delays: [{ day: made, before: held, delay: { until } }] };
  const timeline = run(plan, {
    ...DEFAULT_WORLD,
    seed: 1,
    unestimatedEffort: 0,
    delays: worldDelays(edits, SAMPLE_START),
  }, SAMPLE_START);
  const recording = record(timeline, { options: ADOPTED, cadence: "weekdays", saved: [], seed: 1 });
  const day = fromYMD(2026, 10, 20);
  const view = viewOf(timeline.frames.find((frame) => frame.day === day)!.plan, day, recording);
  const spans = delaySpans(view);
  assertEquals(spans.map((span) => [span.title, span.to]), [["Wait until Wed 4 Nov", until - 1]]);
  const { svg } = drawn(view);
  assertEquals(svg.match(/class="delay"/g)?.length, 2);
  assert(svg.includes(">Wait until Wed 4 Nov</text>"));
});
