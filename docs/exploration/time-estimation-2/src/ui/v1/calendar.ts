/**
 * The months — `time_estimates/months.py`: each stretch a band of days in its milestone's
 * colour, the landing day near solid, weekends pale, today outlined. Clicking a day moves
 * the project's start there (a what-if here, a stored write in DPlanner) where the design
 * offers it; v5 has no what-ifs, so its days are read, not clicked.
 *
 * The bands are the stretches of the plan shown (`view.now`): today's, or a day History looks
 * back to. A wait (a Delay step's) hatches the days it holds.
 *
 * v5 shows six months in larger cells, each milestone's name on the day it lands.
 */

import {
  type Day,
  formatDate,
  fromYMD,
  isWorkingDay,
  MONTHS,
  weekday,
  weekdayName,
  workingDaysBetween,
  ymd,
} from "../../model/calendar.ts";
import { alpha } from "../../model/palettes.ts";
import { landingIn } from "../../model/progress.ts";
import type { TimeView } from "../../present.ts";
import { h } from "../markup.ts";

const SHOWN_AT_LEAST = 6;
const SHOWN_AT_MOST = 12;

interface Band {
  key: string;
  label: string;
  start: Day;
  finish: Day;
  color: string;
  lands: boolean;
}

function addMonths(day: Day, count: number): Day {
  const [year, month] = ymd(day);
  const total = year * 12 + (month - 1) + count;
  return fromYMD(Math.floor(total / 12), (total % 12) + 1, 1);
}

/** `_month_span`: one month before the start, six at least, the landing in view, twelve at most. */
function monthSpan(start: Day, finish: Day | null): [Day, number] {
  const begin = addMonths(start, -1);
  const last = addMonths(finish ?? start, 1);
  const [[y1, m1], [y2, m2]] = [ymd(begin), ymd(last)];
  const count = (y2 - y1) * 12 + (m2 - m1) + 1;
  return [begin, Math.max(SHOWN_AT_LEAST, Math.min(SHOWN_AT_MOST, count))];
}

/** A Delay step's wait: the days it holds. */
export interface Wait {
  title: string;
  from: Day;
  to: Day;
}

function tooltip(day: Day, band: Band | undefined, today: Day, clickable: boolean): string {
  let said = `${weekdayName(day)} ${formatDate(day, today)}`;
  if (!band) said += clickable ? " — click to start the work here" : "";
  else if (day === band.finish && band.lands) said += ` — ${band.label} lands`;
  else if (!isWorkingDay(day)) said += " — weekend, not counted";
  else {
    const worked = workingDaysBetween(band.start, day);
    const total = workingDaysBetween(band.start, band.finish);
    said += ` — ${band.label}${
      day === band.start ? " starts," : ","
    } working day ${worked} of ${total}`;
  }
  return day === today ? `${said} · today` : said;
}

export interface MonthsOptions {
  onDay?: (day: Day) => void; // Clicking a day starts the work there.
  waits?: readonly Wait[];
  months?: number; // How many to show, where the span of the work would otherwise decide.
  named?: boolean; // Each milestone's name on the day it lands.
}

export function monthsView(
  view: TimeView,
  emphasis: string | null,
  offset: number,
  { onDay, waits = [], months, named = false }: MonthsOptions = {},
): HTMLElement {
  const today = view.now.day;
  const bands: Band[] = view.now.stretches
    .filter((stretch) => stretch.finish !== null)
    .map((stretch) => {
      const named = view.stretches.find((one) => one.key === stretch.key);
      return {
        key: stretch.key,
        label: named?.label ?? stretch.key,
        start: stretch.start,
        finish: stretch.finish!,
        color: named?.color ?? "#888888",
        lands: stretch.key !== "",
      };
    });
  const [first, span] = monthSpan(view.report.start, landingIn(view.now, null));
  const count = months ?? span;
  const grid = h("div", { class: "months" });
  for (let index = 0; index < count; index += 1) {
    const month = addMonths(first, index + offset);
    const [year, number] = ymd(month);
    const name = year === ymd(today)[0]
      ? MONTHS[number - 1]
      : `${MONTHS[number - 1].slice(0, 3)} '${String(year % 100).padStart(2, "0")}`;
    const days = h("div", { class: "days" });
    for (let blank = 0; blank < weekday(month); blank += 1) {
      days.append(h("span", { class: "day blank" }));
    }
    for (let day = month; ymd(day)[1] === number; day += 1) {
      const band = bands.find((one) => one.start <= day && day <= one.finish);
      const faded = emphasis !== null && band && band.key !== emphasis ? 0.4 : 1;
      const wait = waits.find((one) => one.from < day && day <= one.to);
      const cell = h(onDay ? "button" : "span", {
        class: `day${isWorkingDay(day) ? "" : " weekend"}${day === today ? " today" : ""}${
          wait ? " waiting" : ""
        }`,
        title: tooltip(day, band, today, Boolean(onDay)) + (wait ? ` — ${wait.title}` : ""),
        ...(onDay ? { onclick: () => onDay(day) } : {}),
      }, String(ymd(day)[2]));
      if (named && band?.lands && day === band.finish) {
        cell.append(h("span", { class: "day-name" }, band.label));
      }
      if (band) {
        const strength = day === band.finish && band.lands
          ? 220
          : day === view.report.start
          ? 130
          : isWorkingDay(day)
          ? 64
          : 24;
        cell.style.backgroundColor = alpha(band.color, (strength / 255) * faded);
        if (strength === 220) cell.classList.add("lands");
      }
      days.append(cell);
    }
    grid.append(h("div", { class: "month" }, h("div", { class: "month-name" }, name), days));
  }
  return grid;
}
