/**
 * Days, working days and how a date is worded — `domain/schedule.py`'s calendar half.
 *
 * A day is an integer: days since 1970-01-01, read as a calendar date with no time zone.
 * That keeps every comparison and subtraction exact, which a `Date` carrying a clock never is.
 * ISO strings appear only at the edges (files, exports).
 */

export type Day = number;

const MS_PER_DAY = 86_400_000;
export const SATURDAY = 5; // Python's date.weekday(): Monday is 0.
export const WORKING_DAYS_PER_WEEK = 5;
export const WEEKS_ABOVE_DAYS = 7.0;

export function fromYMD(year: number, month: number, day: number): Day {
  return Math.round(Date.UTC(year, month - 1, day) / MS_PER_DAY);
}

export function ymd(day: Day): [number, number, number] {
  const when = new Date(day * MS_PER_DAY);
  return [when.getUTCFullYear(), when.getUTCMonth() + 1, when.getUTCDate()];
}

export function parseDay(iso: string): Day | null {
  const found = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!found) return null;
  const [year, month, day] = [Number(found[1]), Number(found[2]), Number(found[3])];
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const result = fromYMD(year, month, day);
  return ymd(result)[2] === day ? result : null;
}

export function isoDay(day: Day): string {
  const [year, month, date] = ymd(day);
  return `${year}-${String(month).padStart(2, "0")}-${String(date).padStart(2, "0")}`;
}

/** 0 for Monday … 6 for Sunday, as Python's `date.weekday()`. 1970-01-01 was a Thursday. */
export function weekday(day: Day): number {
  return (((day + 3) % 7) + 7) % 7;
}

export function isWorkingDay(day: Day): boolean {
  return weekday(day) < SATURDAY;
}

/** `next_working_day`: the day itself, or the Monday after a weekend. */
export function nextWorkingDay(day: Day): Day {
  let when = day;
  while (weekday(when) >= SATURDAY) when += 1;
  return when;
}

/**
 * `working_days_after`: the date working day `days` falls on, the start counted as day one.
 * A fraction rounds up. `guard` is the epsilon a model variant subtracts before rounding
 * (options.ts); the faithful port passes 0, which is DPlanner's bare `ceil`.
 */
export function workingDaysAfter(start: Day, days: number, guard = 0): Day {
  const when = nextWorkingDay(start);
  const whole = Math.max(1, Math.ceil(days - guard)) - 1;
  const weeks = Math.floor(whole / WORKING_DAYS_PER_WEEK);
  let remainder = whole % WORKING_DAYS_PER_WEEK;
  if (weekday(when) + remainder >= SATURDAY) remainder += 2;
  return when + 7 * weeks + remainder;
}

/** `working_days_between`: working days from `start` through `finish`, both counted. */
export function workingDaysBetween(start: Day, finish: Day): number {
  let count = 0;
  for (let when = start; when <= finish; when += 1) {
    if (isWorkingDay(when)) count += 1;
  }
  return count;
}

export const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function twoDigitYear(year: number): string {
  return String(year % 100).padStart(2, "0");
}

/** `format_date`: "23 September", or "14 Feb '27" in another year than `today`'s. */
export function formatDate(day: Day, today: Day): string {
  const [year, month, date] = ymd(day);
  if (year === ymd(today)[0]) return `${date} ${MONTHS[month - 1]}`;
  return `${date} ${MONTHS[month - 1].slice(0, 3)} '${twoDigitYear(year)}`;
}

/** `short_date`: "23 Sep", with the year when it is not `today`'s. */
export function shortDate(day: Day, today: Day): string {
  const [year, month, date] = ymd(day);
  const name = MONTHS[month - 1].slice(0, 3);
  if (year === ymd(today)[0]) return `${date} ${name}`;
  return `${date} ${name} '${twoDigitYear(year)}`;
}

export function weekdayName(day: Day): string {
  return WEEKDAYS[weekday(day)];
}

/** Python's `f"{n:g}"`: six significant digits, no trailing zeros. */
export function g(value: number): string {
  if (Number.isInteger(value)) return String(value);
  return String(Number(value.toPrecision(6)));
}

/**
 * Python's `round(value, digits)`: exact ties go to the even neighbour. A tie is only
 * possible when the float is exactly halfway, which toFixed alone would round up.
 */
export function pyRound(value: number, digits: number): number {
  const scale = 10 ** digits;
  const scaled = value * scale;
  if (Number.isInteger(scaled * 2) && !Number.isInteger(scaled)) {
    const floor = Math.floor(scaled);
    return (floor % 2 === 0 ? floor : floor + 1) / scale;
  }
  return Number(value.toFixed(digits));
}

/** `format_days`: "3d", or "2.4w" once there are more than seven days. */
export function formatDays(days: number | null): string {
  if (days === null) return "";
  if (days > WEEKS_ABOVE_DAYS) return `${g(pyRound(days / WORKING_DAYS_PER_WEEK, 1))}w`;
  return `${g(days)}d`;
}

/** `format_day_count`: "1 day", "2.5 days". */
export function formatDayCount(days: number): string {
  return days === 1 ? `${g(days)} day` : `${g(days)} days`;
}

/** `volume_words`: "12 days over 7 steps, 1 unestimated". */
export function volumeWords(days: number, steps: number, unestimated: number): string {
  const tail = unestimated ? `, ${unestimated} unestimated` : "";
  return `${formatDayCount(days)} over ${steps} step${steps === 1 ? "" : "s"}${tail}`;
}

/** A share as Python's `f"{share:.0%}"`. */
export function percent(share: number): string {
  return `${g(pyRound(share * 100, 0))}%`;
}

// -- the axis of a chart over dates ------------------------------------------------------------

export type Tick = [Day, string];

function dayLabel(day: Day): string {
  const [, month, date] = ymd(day);
  return `${date} ${MONTHS[month - 1].slice(0, 3)}`;
}

function monthLabel(day: Day): string {
  return MONTHS[ymd(day)[1] - 1].slice(0, 3);
}

function withYears(ticks: Tick[]): Tick[] {
  return ticks.map(([when, label], index) => {
    if (index && ymd(when)[0] !== ymd(ticks[index - 1][0])[0]) {
      return [when, `${label} '${twoDigitYear(ymd(when)[0])}`];
    }
    return [when, label];
  });
}

/** `axis_ticks`: every day, else every Monday, else every month's first, thinned to fit. */
export function axisTicks(first: Day, last: Day, room: number): Tick[] {
  const days: Day[] = [];
  for (let when = first; when <= last; when += 1) days.push(when);
  if (days.length <= room) return withYears(days.map((when) => [when, dayLabel(when)]));
  const mondays = days.filter((when) => weekday(when) === 0);
  if (mondays.length && mondays.length <= room) {
    return withYears(mondays.map((when) => [when, dayLabel(when)]));
  }
  const months = days.filter((when) => ymd(when)[2] === 1);
  const every = Math.max(1, Math.ceil(months.length / Math.max(1, room)));
  const ticks = withYears(
    months.filter((_, index) => index % every === 0).map((when) => [when, monthLabel(when)]),
  );
  return ticks.length ? ticks : [[first, dayLabel(first)]];
}
