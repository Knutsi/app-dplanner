/** v5: History — the tab as it was recorded on an earlier day, read from the records alone. */

import { type Day, fromYMD, isoDay, isWorkingDay } from "../src/model/calendar.ts";
import { ADOPTED } from "../src/model/options.ts";
import { shareOf } from "../src/model/progress.ts";
import { brief, burnup } from "../src/brief.ts";
import { lookingBack } from "../src/present.ts";
import { reachOf, type WorkMarks, workSvg } from "../src/ui/v3/work.ts";
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

Deno.test("a Work plot locked to the whole run keeps one pair of axes from the first day on", () => {
  const { timeline, viewOn } = played("scope-creep");
  const end = Math.max(...timeline.finished.values());
  const reach = reachOf(viewOn(end), null);
  const axes = (day: Day, marks: WorkMarks) => {
    const view = viewOn(day);
    const found = brief(view);
    const data = burnup(view, null, found.compared);
    const { geometry } = workSvg(data, [], view, 900, found.compared, marks);
    return [geometry.first, geometry.last, geometry.scopeY(1)];
  };
  const days = timeline.frames.map((frame) => frame.day).filter((day) =>
    day >= timeline.begin && day <= end
  );
  for (const day of days) assertEquals(axes(day, { reach }), axes(end, {}), isoDay(day));
  assert(days.some((day) => axes(day, {})[1] !== axes(end, {})[1]), "unlocked, the axes move");
});
