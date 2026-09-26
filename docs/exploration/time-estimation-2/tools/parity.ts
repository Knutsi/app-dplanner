/**
 * How the port's snapshots compare with the rows DPlanner recorded, day by day.
 *
 *   deno task parity local/dplanner.json
 */

import { isoDay } from "../src/model/calendar.ts";
import { isExport } from "../src/data.ts";
import { parity, parityWords, replay } from "../src/sim/replay.ts";

const [path] = Deno.args;
if (!path) {
  console.error("usage: deno task parity local/<slug>.json");
  Deno.exit(2);
}
const file = JSON.parse(await Deno.readTextFile(path));
if (!isExport(file)) {
  console.error(`${path} is not an export (tools/export_plan.ts writes one)`);
  Deno.exit(2);
}
const results = parity(replay(file));
for (const result of results) {
  console.log(`${isoDay(result.day)}  ${result.same ? "same" : "DIFFERENT"}`);
  for (const line of result.differences) console.log(`    ${line}`);
}
console.log(parityWords(results));
