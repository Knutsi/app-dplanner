/**
 * The months — `time_estimates/months.py`: each stretch a band of days in its milestone's
 * colour, the landing day near solid, weekends pale, today outlined. Clicking a day moves
 * the project's start there (a what-if here, a stored write in DPlanner).
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

function tooltip(day: Day, band: Band | undefined, today: Day): string {
  let said = `${weekdayName(day)} ${formatDate(day, today)}`;
  if (!band) said += " — click to start the work here";
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

export function monthsView(
  view: TimeView,
  emphasis: string | null,
  offset: number,
  onDay: (day: Day) => void,
): HTMLElement {
  const bands: Band[] = view.stretches
    .filter(({ phase }) => phase.finish !== null)
    .map(({ phase, key, label, color }) => ({
      key,
      label,
      start: phase.start,
      finish: phase.finish!,
      color,
      lands: phase.milestone !== null,
    }));
  const [first, count] = monthSpan(view.report.start, view.cell.finish);
  const grid = h("div", { class: "months" });
  for (let index = 0; index < count; index += 1) {
    const month = addMonths(first, index + offset);
    const [year, number] = ymd(month);
    const name = year === ymd(view.today)[0]
      ? MONTHS[number - 1]
      : `${MONTHS[number - 1].slice(0, 3)} '${String(year % 100).padStart(2, "0")}`;
    const days = h("div", { class: "days" });
    for (let blank = 0; blank < weekday(month); blank += 1) {
      days.append(h("span", { class: "day blank" }));
    }
    for (let day = month; ymd(day)[1] === number; day += 1) {
      const band = bands.find((one) => one.start <= day && day <= one.finish);
      const faded = emphasis !== null && band && band.key !== emphasis ? 0.4 : 1;
      const cell = h("button", {
        class: `day${isWorkingDay(day) ? "" : " weekend"}${day === view.today ? " today" : ""}`,
        title: tooltip(day, band, view.today),
        onclick: () => onDay(day),
      }, String(ymd(day)[2]));
      if (band) {
        const strength = day === band.finish && band.lands
          ? 220
          : day === view.report.start
          ? 130
          : isWorkingDay(day)
          ? 64
          : 24;
        cell.style.background = alpha(band.color, (strength / 255) * faded);
        if (strength === 220) cell.classList.add("lands");
      }
      days.append(cell);
    }
    grid.append(h("div", { class: "month" }, h("div", { class: "month-name" }, name), days));
  }
  return grid;
}
