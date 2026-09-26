/** v5: History — the tab as it was recorded on an earlier day, read from the records alone. */

import { type Day, fromYMD, isoDay, isWorkingDay } from "../src/model/calendar.ts";
import { ADOPTED } from "../src/model/options.ts";
import { shareOf } from "../src/model/progress.ts";
import { brief, burnup, type Reach, reachOf } from "../src/brief.ts";
import { lookingBack, type TimeView } from "../src/present.ts";
import { recordedBy } from "../src/sim/timeline.ts";
import { shiftsSvg } from "../src/ui/v3/shifts.ts";
import { workSvg } from "../src/ui/v3/work.ts";
import { assert, assertEquals } from "./helpers.ts";
import { played, viewOf } from "./played.ts";

/** What the key figures and the Milestones tab say: the dates, the move, the share done. */
function said(found: ReturnType<typeof brief>) {
  return {
    lands: found.whole.move.planned,
    landed: found.whole.landedBy,
    moved: found.whole.move.plan,
    done: shareOf(found.whole.own),
    milestones: found.milestones.map((scope) => [scope.key, scope.move.planned, scope.landedBy]),
  };
}

Deno.test("History shows each recorded day as the tab showed it on that day", () => {
  for (const scenario of ["optimistic", "scope-creep", "joiner"]) {
    const { timeline, recording, viewOn } = played(scenario);
    const today = fromYMD(2026, 11, 20);
    const plan = timeline.frames.find((frame) => frame.day === today)!.plan;
    const days = [...new Set(recording.rows.map((row) => row.day))].filter((day: Day) =>
      day < today && isWorkingDay(day)
    );
    assert(days.length > 20, `${scenario}: ${days.length} recorded days`);
    for (const day of days) {
      const back = viewOf(plan, today, recording, ADOPTED, day);
      assert(lookingBack(back));
      assertEquals(said(brief(back)), said(brief(viewOn(day))), `${scenario}, ${day}`);
    }
  }
});

Deno.test("today is not looking back", () => {
  assert(!lookingBack(played("by-the-book").viewOn(fromYMD(2026, 10, 20))));
});

/** Both tabs' axes for a view: the Work plot's dates and scale, and the Milestones dates. */
function axes(view: TimeView, reach?: Reach) {
  const found = brief(view);
  const data = burnup(view, null, found.compared);
  const work = workSvg(data, [], view, 900, found.compared, { reach }).geometry;
  const shifts = shiftsSvg(found, view, null, 900, reach);
  return [work.first, work.last, work.scopeY(1), shifts.first, shifts.last];
}

Deno.test("scrubbing History moves the lines, never the axes", () => {
  for (const scenario of ["scope-creep", "optimistic", "joiner"]) {
    const { timeline, recording, viewOn } = played(scenario);
    const today = fromYMD(2026, 11, 20);
    const plan = timeline.frames.find((frame) => frame.day === today)!.plan;
    const live = viewOn(today);
    const reach = reachOf([...recordedBy(recording, today).rows, live.live]);
    const held = axes(live, reach);
    const days = recording.rows.map((row) => row.day).filter((day) => day < today);
    for (const day of days) {
      const back = viewOf(plan, today, recording, ADOPTED, day);
      assertEquals(axes(back, reach), held, `${scenario}, ${isoDay(day)}`);
    }
    assert(
      days.some((day) => axes(viewOf(plan, today, recording, ADOPTED, day))[1] !== held[1]),
      `${scenario}: unheld, the axes move`,
    );
  }
});

Deno.test("locked to the whole run, the axes hold from the first day to the last", () => {
  const { timeline, recording, viewOn } = played("scope-creep");
  const days = timeline.frames.map((frame) => frame.day).filter((day) => day >= timeline.begin);
  const reach = reachOf([...recording.rows, viewOn(days[days.length - 1]).live]);
  const held = axes(viewOn(days[0]), reach);
  for (const day of days) assertEquals(axes(viewOn(day), reach), held, isoDay(day));
});
