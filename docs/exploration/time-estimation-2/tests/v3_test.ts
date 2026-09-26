/** v3's two tabs: the shift view's marks, and the Work tab's two plots on one scale. */

import { fromYMD, shortDate } from "../src/model/calendar.ts";
import { type Brief, brief, burnup } from "../src/brief.ts";
import { shiftsSvg } from "../src/ui/v3/shifts.ts";
import { scopeFills, scopeMarks, stepAt, workSvg } from "../src/ui/v3/work.ts";
import { assert, assertEquals } from "./helpers.ts";
import { played } from "./played.ts";

/** The milestones, without the rest of the work that belongs to none. */
const named = (found: Brief) => found.milestones.filter((scope) => scope.key);

/** Each milestone's row of the shift view, as its own piece of markup. */
function rowsOf(svg: string): string[] {
  return svg.split(`<g class="shift-row"`).slice(1).map((row) => row.slice(0, row.indexOf("</g>")));
}

Deno.test("a day's scope changes make one mark, pointing the way the day went in sum", () => {
  const marks = scopeMarks([
    { day: 10, steps: 2, days: 3 },
    { day: 10, steps: -1, days: -1 },
    { day: 12, steps: 1, days: -2 },
    { day: 14, steps: 1, days: 0 },
    { day: 15, steps: 1, days: 2 },
    { day: 15, steps: -1, days: -2 },
  ]);
  assertEquals(marks.map(({ day, direction }) => [day, direction]), [[10, "up"], [12, "down"], [
    14,
    "up",
  ]]);
  assertEquals([marks[0].steps, marks[0].days], [1, 2]);
});

Deno.test("the scope is shaded from the day compared with: warm above the baseline, cool below", () => {
  const fills = scopeFills(
    [[0, 4], [5, 5], [8, 4], [10, 3]],
    4,
    2,
    12,
    (day) => day * 10,
    (v) => 100 - v * 10,
  );
  assertEquals(fills.map((fill) => fill.match(/scope-(up|down)-fill/)![1]), ["up", "down"]);
  assert(fills[0].includes(`x="50" y="50" width="30" height="10"`), fills[0]);
  assert(fills[1].includes(`x="100" y="60" width="20" height="10"`), fills[1]);
  assertEquals(scopeFills([[0, 5]], 4, 6, 6, (day) => day, (v) => v), []);
});

Deno.test("a step curve reads the last point at or before a day, and nothing before its first", () => {
  const points: [number, number][] = [[3, 1], [5, 4], [9, 2]];
  assertEquals([stepAt(points, 2), stepAt(points, 3), stepAt(points, 7), stepAt(points, 30)], [
    null,
    1,
    4,
    2,
  ]);
});

Deno.test("scope creep: one arrow per day the scope moved, each just under the scope line", () => {
  const view = played("scope-creep").viewOn(fromYMD(2026, 11, 20));
  const found = brief(view);
  const data = burnup(view, null, found.compared);
  const marks = scopeMarks(data.jumps);
  assert(marks.some((mark) => mark.direction === "up"));
  const { svg, geometry } = workSvg(data, named(found), view, 900, found.compared);
  const drawn = [...svg.matchAll(/<path d="([^"]+)" class="scope-(up|down)-glyph scope-mark">/g)];
  assertEquals(drawn.map((one) => one[2]), marks.map((mark) => mark.direction));
  drawn.forEach(([, path], index) => {
    const ys = [...path.matchAll(/(-?[\d.]+),(-?[\d.]+)/g)].map((point) => Number(point[2]));
    const line = geometry.scopeY(stepAt(data.scope, marks[index].day)!);
    const below = Math.min(...ys) - line;
    assert(below > 0 && below < 12, `mark ${index} sits ${below} under its line`);
  });
});

Deno.test("the two plots share one scale: a day of work is the same height in each", () => {
  const view = played("scope-creep").viewOn(fromYMD(2026, 11, 20));
  const found = brief(view);
  const { geometry } = workSvg(
    burnup(view, null, found.compared),
    named(found),
    view,
    900,
    found.compared,
  );
  assertEquals(geometry.scopeY(0) - geometry.scopeY(10), geometry.workY(0) - geometry.workY(10));
});

Deno.test("by the book, every milestone ends in a check once the work is done", () => {
  const { timeline, viewOn } = played("by-the-book");
  const view = viewOn(timeline.frames[timeline.frames.length - 1].day);
  const found = brief(view);
  const rows = rowsOf(shiftsSvg(found, view, null, 900).svg);
  assertEquals(rows.length, named(found).length);
  for (const row of rows) {
    assert(row.includes("landed-check"), "a done milestone carries its check");
  }
});

Deno.test("optimistic estimates: late work moves the plan's own date, and the row's arrow shows it", () => {
  const today = fromYMD(2026, 11, 20);
  const view = played("optimistic").viewOn(today);
  const found = brief(view);
  const { svg, rows } = shiftsSvg(found, view, null, 900);
  const scopes = named(found);
  const m2 = scopes.findIndex((scope) => scope.label === "M2");
  const { then, planned } = scopes[m2].move;
  assert(then! < today && planned! > today, "M2 was due before today, and is re-planned after it");
  const row = rowsOf(svg)[m2];
  assert(!row.includes("landed-check"));
  assert(row.includes(`>${shortDate(then!, today)}<`), "labelled with where it was");
  assert(
    row.includes(`>${shortDate(scopes[m2].move.planned!, today)}<`),
    "labelled with the plan's date",
  );
  assert(!svg.includes("~"), "no date at today's pace");
  assertEquals(rows[m2].key, scopes[m2].key);
});

Deno.test("the work done plot marks every milestone: a check on the done line, or a dot on the schedule", () => {
  const today = fromYMD(2026, 11, 20);
  const view = played("optimistic").viewOn(today);
  const found = brief(view);
  const scopes = named(found);
  const data = burnup(view, null, found.compared);
  const { svg, geometry } = workSvg(data, scopes, view, 900, found.compared);
  const marks = svg.split(`<g class="milestone-mark">`).slice(1).map((mark) =>
    mark.slice(0, mark.indexOf("</g>"))
  );
  assertEquals(marks.length, scopes.length);
  marks.forEach((mark, index) => {
    const scope = scopes[index];
    const cy = Number(mark.match(/<circle cx="[^"]+" cy="([^"]+)"/)![1]);
    if (scope.landedBy !== null) {
      assert(mark.includes("landed-check"), `${scope.label} is done`);
      assertEquals(cy, Math.round(geometry.workY(stepAt(data.done, scope.landedBy)!) * 10) / 10);
    } else {
      assert(!mark.includes("landed-check"), `${scope.label} is not done`);
      assertEquals(
        cy,
        Math.round(geometry.workY(stepAt(data.promised, scope.move.planned!)!) * 10) / 10,
      );
    }
  });
  assert(
    marks.some((mark) => mark.includes("landed-check")) &&
      marks.some((mark) => !mark.includes("landed-check")),
  );
});
