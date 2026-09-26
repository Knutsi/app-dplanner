(() => {
  // src/model/calendar.ts
  var MS_PER_DAY = 864e5;
  var SATURDAY = 5;
  var WORKING_DAYS_PER_WEEK = 5;
  var WEEKS_ABOVE_DAYS = 7;
  function fromYMD(year, month, day) {
    return Math.round(Date.UTC(year, month - 1, day) / MS_PER_DAY);
  }
  function ymd(day) {
    const when = new Date(day * MS_PER_DAY);
    return [
      when.getUTCFullYear(),
      when.getUTCMonth() + 1,
      when.getUTCDate()
    ];
  }
  function parseDay(iso) {
    const found = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    if (!found) return null;
    const [year, month, day] = [
      Number(found[1]),
      Number(found[2]),
      Number(found[3])
    ];
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    const result = fromYMD(year, month, day);
    return ymd(result)[2] === day ? result : null;
  }
  function isoDay(day) {
    const [year, month, date] = ymd(day);
    return `${year}-${String(month).padStart(2, "0")}-${String(date).padStart(2, "0")}`;
  }
  function weekday(day) {
    return ((day + 3) % 7 + 7) % 7;
  }
  function isWorkingDay(day) {
    return weekday(day) < SATURDAY;
  }
  function nextWorkingDay(day) {
    let when = day;
    while (weekday(when) >= SATURDAY) when += 1;
    return when;
  }
  function workingDaysAfter(start2, days, guard = 0) {
    const when = nextWorkingDay(start2);
    const whole = Math.max(1, Math.ceil(days - guard)) - 1;
    const weeks = Math.floor(whole / WORKING_DAYS_PER_WEEK);
    let remainder = whole % WORKING_DAYS_PER_WEEK;
    if (weekday(when) + remainder >= SATURDAY) remainder += 2;
    return when + 7 * weeks + remainder;
  }
  function addWorkingDays(day, count2) {
    let when = day;
    for (let left = count2; left > 0; ) {
      when += 1;
      if (isWorkingDay(when)) left -= 1;
    }
    return when;
  }
  function workingDaysBetween(start2, finish) {
    let count2 = 0;
    for (let when = start2; when <= finish; when += 1) {
      if (isWorkingDay(when)) count2 += 1;
    }
    return count2;
  }
  var MONTHS = [
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
    "December"
  ];
  var WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday"
  ];
  function twoDigitYear(year) {
    return String(year % 100).padStart(2, "0");
  }
  function formatDate(day, today) {
    const [year, month, date] = ymd(day);
    if (year === ymd(today)[0]) return `${date} ${MONTHS[month - 1]}`;
    return `${date} ${MONTHS[month - 1].slice(0, 3)} '${twoDigitYear(year)}`;
  }
  function shortDate(day, today) {
    const [year, month, date] = ymd(day);
    const name = MONTHS[month - 1].slice(0, 3);
    if (year === ymd(today)[0]) return `${date} ${name}`;
    return `${date} ${name} '${twoDigitYear(year)}`;
  }
  function weekdayName(day) {
    return WEEKDAYS[weekday(day)];
  }
  function g(value) {
    if (Number.isInteger(value)) return String(value);
    return String(Number(value.toPrecision(6)));
  }
  function pyRound(value, digits) {
    const scale = 10 ** digits;
    const scaled = value * scale;
    if (Number.isInteger(scaled * 2) && !Number.isInteger(scaled)) {
      const floor = Math.floor(scaled);
      return (floor % 2 === 0 ? floor : floor + 1) / scale;
    }
    return Number(value.toFixed(digits));
  }
  function formatDays(days) {
    if (days === null) return "";
    if (days > WEEKS_ABOVE_DAYS) return `${g(pyRound(days / WORKING_DAYS_PER_WEEK, 1))}w`;
    return `${g(days)}d`;
  }
  function percent(share) {
    return `${g(pyRound(share * 100, 0))}%`;
  }
  function dayLabel(day) {
    const [, month, date] = ymd(day);
    return `${date} ${MONTHS[month - 1].slice(0, 3)}`;
  }
  function monthLabel(day) {
    return MONTHS[ymd(day)[1] - 1].slice(0, 3);
  }
  function withYears(ticks2) {
    return ticks2.map(([when, label2], index) => {
      if (index && ymd(when)[0] !== ymd(ticks2[index - 1][0])[0]) {
        return [
          when,
          `${label2} '${twoDigitYear(ymd(when)[0])}`
        ];
      }
      return [
        when,
        label2
      ];
    });
  }
  function axisTicks(first, last, room) {
    const days = [];
    for (let when = first; when <= last; when += 1) days.push(when);
    if (days.length <= room) return withYears(days.map((when) => [
      when,
      dayLabel(when)
    ]));
    const mondays = days.filter((when) => weekday(when) === 0);
    if (mondays.length && mondays.length <= room) {
      return withYears(mondays.map((when) => [
        when,
        dayLabel(when)
      ]));
    }
    const months = days.filter((when) => ymd(when)[2] === 1);
    const every = Math.max(1, Math.ceil(months.length / Math.max(1, room)));
    const ticks2 = withYears(months.filter((_, index) => index % every === 0).map((when) => [
      when,
      monthLabel(when)
    ]));
    return ticks2.length ? ticks2 : [
      [
        first,
        dayLabel(first)
      ]
    ];
  }

  // src/model/graph.ts
  var DONE = "done";
  var DEFAULT_EFFICIENCY = 0.5;
  var DEFAULT_TEAM = [
    1,
    1
  ];
  var HUMANS = [
    1,
    2,
    3
  ];
  var AGENTS = [
    1,
    2,
    3,
    4
  ];
  var daysFor = (step2) => step2.estimateOff ? null : step2.estimate;
  var isAgent = (step2) => step2.agent;
  var isMilestone = (step2) => Boolean(step2.milestone);
  var isDelay = (step2) => step2.delay !== null;
  var startFor = (step2) => step2.start;
  function efficiencyOf(plan) {
    return plan.assumptions.efficiency ?? DEFAULT_EFFICIENCY;
  }
  function teamOf(plan) {
    return plan.assumptions.team ?? DEFAULT_TEAM;
  }
  function startOf(plan, today) {
    return plan.start ?? today;
  }
  function stepKey(step2) {
    return `S${step2.number}`;
  }
  function milestoneLabel(step2) {
    return step2.milestone || step2.title;
  }
  function idsOf(steps) {
    return new Set(steps.map((step2) => step2.id));
  }
  function byId(plan) {
    return new Map(plan.steps.map((step2) => [
      step2.id,
      step2
    ]));
  }
  function depths(plan) {
    const known = /* @__PURE__ */ new Map();
    const index = byId(plan);
    const depthOf = (id, seen) => {
      const found = known.get(id);
      if (found !== void 0) return found;
      if (seen.has(id)) return 0;
      const resolved = (index.get(id)?.requires ?? []).filter((target) => index.has(target));
      const next = new Set(seen).add(id);
      const depth = resolved.length ? 1 + Math.max(...resolved.map((target) => depthOf(target, next))) : 0;
      known.set(id, depth);
      return depth;
    };
    for (const step2 of plan.steps) depthOf(step2.id, /* @__PURE__ */ new Set());
    return known;
  }
  function cyclic(plan) {
    const ids = idsOf(plan.steps);
    const pending = new Map(plan.steps.map((step2) => [
      step2.id,
      new Set(step2.requires.filter((t) => ids.has(t)))
    ]));
    let shed = true;
    while (shed) {
      shed = false;
      for (const [id, waiting] of [
        ...pending
      ]) {
        if (!waiting.size) {
          pending.delete(id);
          for (const others of pending.values()) others.delete(id);
          shed = true;
        }
      }
    }
    return plan.steps.filter((step2) => pending.has(step2.id));
  }
  function waves(plan) {
    if (!plan.steps.length) return [];
    const byDepth = depths(plan);
    const grouped = Array.from({
      length: Math.max(0, ...byDepth.values()) + 1
    }, () => []);
    for (const step2 of plan.steps) grouped[byDepth.get(step2.id) ?? 0].push(step2);
    return grouped;
  }
  function placed(plan) {
    const result = [];
    waves(plan).forEach((wave, number) => {
      for (const step2 of wave) result.push({
        index: result.length + 1,
        wave: number + 1,
        step: step2
      });
    });
    return result;
  }
  function cone(plan, stepId, stopsAt) {
    const index = byId(plan);
    const reached = /* @__PURE__ */ new Set();
    const stopped = /* @__PURE__ */ new Set();
    const visit = (current) => {
      for (const targetId of index.get(current)?.requires ?? []) {
        const target = index.get(targetId);
        if (!target || reached.has(targetId) || stopped.has(targetId)) continue;
        if (stopsAt && stopsAt(target)) {
          stopped.add(targetId);
          continue;
        }
        reached.add(targetId);
        visit(targetId);
      }
    };
    visit(stepId);
    return {
      steps: plan.steps.filter((step2) => reached.has(step2.id)),
      boundaries: plan.steps.filter((step2) => stopped.has(step2.id))
    };
  }

  // src/model/options.ts
  var FAITHFUL = {
    epsilon: false,
    carry: false,
    replan: "off",
    pace: false
  };
  var ADOPTED = {
    epsilon: true,
    carry: true,
    replan: "resume",
    pace: false
  };
  var GUARD = 1e-9;
  function guardOf(options) {
    return options.epsilon ? GUARD : 0;
  }
  var VARIANTS = [];

  // src/model/palettes.ts
  var PALETTES = [
    {
      id: "viridis",
      name: "Viridis",
      stops: [
        "#482878",
        "#3e4989",
        "#31688e",
        "#26828e",
        "#1f9e89",
        "#35b779",
        "#6ece58"
      ]
    },
    {
      id: "mako",
      name: "Mako",
      stops: [
        "#2f1c4f",
        "#3b3f7c",
        "#3b5f92",
        "#3c7da0",
        "#47a1ad",
        "#6dc1ae"
      ]
    },
    {
      id: "crest",
      name: "Crest",
      stops: [
        "#2a4e7d",
        "#2d5f8c",
        "#37739c",
        "#3f87a3",
        "#4b9ba2",
        "#5fae9d",
        "#7fbf98"
      ]
    },
    {
      id: "plasma",
      name: "Plasma",
      stops: [
        "#46039f",
        "#7201a8",
        "#9c179e",
        "#bd3786",
        "#d8576b",
        "#ed7953",
        "#fb9f3a"
      ]
    },
    {
      id: "magma",
      name: "Magma",
      stops: [
        "#3b0f70",
        "#641a80",
        "#8c2981",
        "#b73779",
        "#de4968",
        "#f7705c",
        "#fe9f6d"
      ]
    },
    {
      id: "inferno",
      name: "Inferno",
      stops: [
        "#420a68",
        "#781c6d",
        "#a52c60",
        "#cf4446",
        "#ed6925",
        "#fb9b06"
      ]
    },
    {
      id: "rocket",
      name: "Rocket",
      stops: [
        "#2c1439",
        "#5b1a4c",
        "#8a1f55",
        "#b7284e",
        "#dc4b3b",
        "#f07a3a",
        "#f8a952"
      ]
    },
    {
      id: "flare",
      name: "Flare",
      stops: [
        "#5d3444",
        "#77384f",
        "#913c56",
        "#a94057",
        "#be4a54",
        "#cf5b4f",
        "#da6f52",
        "#e79a6d"
      ]
    },
    {
      id: "cividis",
      name: "Cividis",
      stops: [
        "#123570",
        "#3b496c",
        "#575d6d",
        "#707173",
        "#8a8678",
        "#a59c74",
        "#c3b369"
      ]
    }
  ];
  var WHOLE_COLOR = "#5f87d7";
  var REMAINDER_COLOR = "#8b8f96";
  function paletteById(id) {
    return PALETTES.find((found) => found.id === id) ?? PALETTES[0];
  }
  function mix(low, high, share) {
    let out = "#";
    for (const offset of [
      1,
      3,
      5
    ]) {
      const [start2, end] = [
        parseInt(low.slice(offset, offset + 2), 16),
        parseInt(high.slice(offset, offset + 2), 16)
      ];
      out += pyRound(start2 + (end - start2) * share, 0).toString(16).padStart(2, "0");
    }
    return out;
  }
  function shade(found, position) {
    const stops = found.stops;
    const place = Math.min(Math.max(position, 0), 1) * (stops.length - 1);
    const index = Math.min(Math.floor(place), stops.length - 2);
    return mix(stops[index], stops[index + 1], place - index);
  }
  function shades(found, count2) {
    return Array.from({
      length: count2
    }, (_, index) => shade(found, (index + 0.5) / count2));
  }
  function milestoneColors(plan, paletteId) {
    const ordered = placed(plan).map((place) => place.step).filter(isMilestone);
    if (!ordered.length) return /* @__PURE__ */ new Map();
    const dealt = shades(paletteById(paletteId), ordered.length);
    return new Map(ordered.map((step2, index) => [
      step2.id,
      step2.color ?? dealt[index]
    ]));
  }
  function phaseColors(stretches, colors) {
    return stretches.map((phase, index) => phase.milestone ? colors.get(phase.milestone.id) ?? WHOLE_COLOR : index ? REMAINDER_COLOR : WHOLE_COLOR);
  }
  function alpha(hex, opacity) {
    const [r, g2, b] = [
      1,
      3,
      5
    ].map((offset) => parseInt(hex.slice(offset, offset + 2), 16));
    return `rgba(${r}, ${g2}, ${b}, ${opacity})`;
  }

  // src/model/simulate.ts
  function parallelFinish(steps, daysFor2, humans, agents, running = /* @__PURE__ */ new Set(), waits = plainWaits) {
    if (humans < 1 || agents < 1) throw new Error("a pool with work in it needs at least one worker");
    if (!steps.length) return null;
    const order = new Map(steps.map((step2, index) => [
      step2.id,
      index
    ]));
    const byId2 = new Map(steps.map((step2) => [
      step2.id,
      step2
    ]));
    const days = new Map(steps.map((step2) => [
      step2.id,
      costOf(step2, daysFor2)
    ]));
    const waiting = /* @__PURE__ */ new Map();
    const dependents = new Map(steps.map((step2) => [
      step2.id,
      []
    ]));
    for (const step2 of steps) {
      const requires = new Set(step2.requires.filter((target) => order.has(target)));
      waiting.set(step2.id, requires);
      for (const target of requires) dependents.get(target).push(step2.id);
    }
    const tails = tailsOf(steps, days, dependents);
    const free = /* @__PURE__ */ new Map([
      [
        true,
        agents
      ],
      [
        false,
        humans
      ]
    ]);
    const pool = new Map(steps.map((step2) => [
      step2.id,
      isAgent(step2)
    ]));
    const ready = /* @__PURE__ */ new Map([
      [
        true,
        []
      ],
      [
        false,
        []
      ]
    ]);
    let busy = [];
    const landings2 = /* @__PURE__ */ new Map();
    const starts = /* @__PURE__ */ new Map();
    let now = 0;
    const release = (id) => {
      const step2 = byId2.get(id);
      if (isDelay(step2)) {
        starts.set(id, now);
        busy.push([
          waits(step2, now),
          id
        ]);
      } else {
        ready.get(pool.get(id)).push(id);
      }
    };
    for (const step2 of steps) {
      if (!waiting.get(step2.id).size) release(step2.id);
    }
    let remaining2 = steps.length;
    const priority = (a, b) => Number(running.has(b)) - Number(running.has(a)) || tails.get(b) - tails.get(a) || order.get(a) - order.get(b);
    while (remaining2) {
      for (const lane of [
        true,
        false
      ]) {
        const queue = ready.get(lane);
        while (queue.length && free.get(lane)) {
          queue.sort(priority);
          const id = queue.shift();
          free.set(lane, free.get(lane) - 1);
          starts.set(id, now);
          busy.push([
            now + (days.get(id) ?? 0),
            id
          ]);
        }
      }
      if (!busy.length) break;
      now = Math.min(...busy.map(([finish]) => finish));
      const landed = busy.filter(([finish]) => finish <= now);
      busy = busy.filter(([finish]) => finish > now);
      for (const [finish, id] of landed) {
        landings2.set(id, finish);
        if (!isDelay(byId2.get(id))) free.set(pool.get(id), free.get(pool.get(id)) + 1);
        remaining2 -= 1;
        for (const after of dependents.get(id)) {
          const left = waiting.get(after);
          left.delete(id);
          if (!left.size) release(after);
        }
      }
    }
    return {
      days: now,
      unestimated: [
        ...days.values()
      ].filter((value) => value === null).length,
      landings: landings2,
      starts,
      tails
    };
  }
  function waitDays(step2) {
    return step2.delay && "days" in step2.delay ? step2.delay.days : 0;
  }
  var plainWaits = (step2, at) => at + waitDays(step2);
  function costOf(step2, daysFor2) {
    return isDelay(step2) ? waitDays(step2) : daysFor2(step2);
  }
  function chainTails(steps, daysFor2) {
    const order = new Set(steps.map((step2) => step2.id));
    const dependents = new Map(steps.map((step2) => [
      step2.id,
      []
    ]));
    for (const step2 of steps) {
      for (const target of new Set(step2.requires)) {
        if (order.has(target)) dependents.get(target).push(step2.id);
      }
    }
    return tailsOf(steps, new Map(steps.map((step2) => [
      step2.id,
      costOf(step2, daysFor2)
    ])), dependents);
  }
  function tailsOf(steps, days, dependents) {
    const tails = /* @__PURE__ */ new Map();
    const tailOf = (id, seen) => {
      const known = tails.get(id);
      if (known !== void 0) return known;
      if (seen.has(id)) return 0;
      const next = new Set(seen).add(id);
      const ahead = Math.max(0, ...dependents.get(id).map((after) => tailOf(after, next)));
      const tail = (days.get(id) ?? 0) + ahead;
      tails.set(id, tail);
      return tail;
    };
    for (const step2 of steps) tailOf(step2.id, /* @__PURE__ */ new Set());
    return tails;
  }
  function landingOf(phase, id) {
    const fact = phase.facts.get(id);
    if (fact !== void 0) return fact;
    return dayAt(phase, phase.landings.get(id) ?? 0);
  }
  function startDayOf(phase, id) {
    return phase.facts.get(id) ?? dayAt(phase, phase.starts.get(id) ?? 0);
  }
  function dayAt(phase, offset) {
    const at = phase.lead + offset;
    return at > 0 ? workingDaysAfter(phase.start, at, phase.guard) : phase.start;
  }
  function pushed(phase) {
    return phase.asked !== null && phase.start > nextWorkingDay(phase.asked);
  }
  function calendarDays(phase) {
    return phase.finish !== null ? workingDaysBetween(phase.start, phase.finish) : 0;
  }
  function groups(plan) {
    const milestones2 = placed(plan).map((place) => place.step).filter(isMilestone);
    const taken = /* @__PURE__ */ new Set();
    const found = [];
    for (const closing of milestones2) {
      const reached = cone(plan, closing.id, isMilestone).steps;
      const own = new Set(reached.map((step2) => step2.id).filter((id) => !taken.has(id)));
      own.add(closing.id);
      for (const id of own) taken.add(id);
      found.push([
        closing,
        plan.steps.filter((step2) => own.has(step2.id))
      ]);
    }
    const rest = plan.steps.filter((step2) => !taken.has(step2.id));
    if (rest.length) found.push([
      null,
      rest
    ]);
    return found;
  }
  function phases(plan, daysFor2, args) {
    const options = args.options ?? FAITHFUL;
    if (options.replan !== "resume") return scheduled(plan, daysFor2, args, options);
    const planned = scheduled(plan, daysFor2, args, options);
    if (holds(planned, args.today)) return planned;
    const pace = options.pace ? paceSoFar(plan, daysFor2, args.start, args.today) : null;
    const costs = pace === null || asPlanned(pace) ? daysFor2 : paced(daysFor2, pace);
    return resumed(plan, costs, args, options);
  }
  var PACE_AFTER = 5;
  var PACE_STEPS = 3;
  var PACE_BAND = 0.1;
  function asPlanned(pace) {
    return Math.abs(Math.log(pace)) < Math.log(1 + PACE_BAND);
  }
  function paceSoFar(plan, daysFor2, start2, today) {
    if (today < start2 || workingDaysBetween(start2, today) <= PACE_AFTER) return null;
    let [given, took, count2] = [
      0,
      0,
      0
    ];
    for (const step2 of plan.steps) {
      const days = daysFor2(step2);
      if (days === null || isDelay(step2) || isAgent(step2) || step2.status !== DONE) continue;
      if (step2.started === null || step2.since === null) continue;
      given += days;
      took += workingDaysBetween(step2.started, step2.since) - 2 * HALF;
      count2 += 1;
    }
    return count2 < PACE_STEPS || took <= 0 ? null : Math.min(4, Math.max(0.25, given / took));
  }
  function paced(daysFor2, pace) {
    return (step2) => {
      const days = daysFor2(step2);
      return days === null || isDelay(step2) || isAgent(step2) ? days : days / pace;
    };
  }
  function scheduled(plan, daysFor2, args, options) {
    const result = [];
    let clock = {
      when: args.start,
      lead: 0
    };
    let replanned = false;
    for (const [index, [milestone, steps]] of groups(plan).entries()) {
      let costs = daysFor2;
      if (options.replan === "restart" && !replanned && steps.some((step2) => step2.status !== DONE)) {
        replanned = true;
        if (args.today > clock.when) clock = {
          when: args.today,
          lead: 0
        };
      }
      if (options.replan === "restart" && replanned) {
        costs = (step2) => {
          const days = daysFor2(step2);
          return days !== null && step2.status === DONE ? 0 : days;
        };
      }
      const [phase, next] = dated(milestone, steps, steps, costs, clock, index === 0, args, options);
      result.push(phase);
      clock = next;
    }
    return result;
  }
  function holds(planned, today) {
    return planned.every((phase) => phase.steps.every((step2) => {
      if (step2.created !== null && startDayOf(phase, step2.id) < step2.created) return false;
      if (isDelay(step2)) return true;
      const lands = landingOf(phase, step2.id);
      if (step2.status === DONE !== lands <= today) return false;
      if (step2.status === DONE && step2.since !== null && step2.since !== lands) return false;
      const started = step2.status === "in-progress" || step2.status === "blocked";
      return !started || step2.since === null || step2.since <= startDayOf(phase, step2.id);
    }));
  }
  var HALF = 0.5;
  function resumed(plan, daysFor2, args, options) {
    const result = [];
    let clock = null;
    const spentSince = (day) => day === null || day > args.today ? 0 : workingDaysBetween(day, args.today) - HALF;
    const was = plan.assumptions.efficiencyWas;
    const worked = (step2) => {
      const whole = spentSince(step2.since);
      if (!was || isAgent(step2) || step2.since === null || was.until <= step2.since) return whole;
      const after = was.until > args.today ? 0 : workingDaysBetween(was.until, args.today);
      return (whole - after) * (was.efficiency / efficiencyOf(plan)) + after;
    };
    const byId2 = new Map(plan.steps.map((step2) => [
      step2.id,
      step2
    ]));
    const waited = (step2) => {
      const before = step2.requires.map((id) => byId2.get(id)).filter((one) => one !== void 0);
      if (before.some((one) => one.status !== DONE)) return 0;
      const done = before.map((one) => one.since).filter((day) => day !== null);
      const last = done.length ? Math.max(...done) : null;
      if (step2.created !== null && (last === null || step2.created > last)) {
        return step2.created > args.today ? 0 : workingDaysBetween(step2.created, args.today);
      }
      return spentSince(last);
    };
    for (const [milestone, steps] of groups(plan)) {
      const done = steps.filter((step2) => step2.status === DONE);
      const facts = new Map(done.map((step2) => [
        step2.id,
        step2.since ?? args.today
      ]));
      const left = steps.filter((step2) => step2.status !== DONE);
      if (!left.some((step2) => !isDelay(step2))) {
        result.push(finished(milestone, steps, facts, args.today, options));
        continue;
      }
      clock ??= {
        when: nextWorkingDay(args.today + 1),
        lead: 0
      };
      const running = new Set(left.filter((step2) => step2.status === "in-progress").map((step2) => step2.id));
      const costs = (step2) => {
        const days = daysFor2(step2);
        return days === null || !running.has(step2.id) ? days : Math.max(HALF, days - worked(step2));
      };
      const [phase, next] = dated(milestone, steps, left, costs, clock, false, args, options, {
        running,
        facts,
        waited
      });
      result.push(phase);
      clock = next;
    }
    return result;
  }
  function finished(milestone, steps, facts, today, options) {
    const days = facts.size ? [
      ...facts.values()
    ] : [
      today
    ];
    return {
      milestone,
      steps,
      days: 0,
      start: Math.min(...days),
      finish: Math.max(...days),
      asked: milestone ? startFor(milestone) : null,
      unestimated: 0,
      landings: /* @__PURE__ */ new Map(),
      starts: /* @__PURE__ */ new Map(),
      lead: 0,
      guard: guardOf(options),
      facts,
      began: Math.min(...days)
    };
  }
  function dated(milestone, steps, members, costs, clock, first, args, options, extra = {}) {
    const guard = guardOf(options);
    const asked = milestone ? startFor(milestone) : null;
    let begins = asked !== null && (first || asked >= clock.when) ? asked : clock.when;
    let used = begins === clock.when ? clock.lead : 0;
    if (nextWorkingDay(begins) !== begins) used = 0;
    begins = nextWorkingDay(begins);
    const waits = (step2, at) => {
      const delay = step2.delay;
      if ("days" in delay) return at + Math.max(0, delay.days - (extra.waited?.(step2) ?? 0));
      const opens = nextWorkingDay(delay.until);
      const offset = opens <= begins ? 0 : workingDaysBetween(begins, opens) - 1 - used;
      return Math.max(at, offset);
    };
    const run2 = parallelFinish(members, costs, args.humans, args.agents, extra.running, waits);
    const finish = run2.days > 0 ? workingDaysAfter(begins, used + run2.days, guard) : null;
    const started = members.filter((step2) => extra.running?.has(step2.id)).map((step2) => step2.since);
    const known = [
      ...extra.facts?.values() ?? [],
      ...started
    ].filter((day) => day !== null);
    const phase = {
      milestone,
      steps,
      days: run2.days,
      start: begins,
      finish,
      asked,
      unestimated: run2.unestimated,
      landings: run2.landings,
      starts: run2.starts,
      lead: used,
      guard,
      facts: extra.facts ?? /* @__PURE__ */ new Map(),
      began: Math.min(begins, ...known)
    };
    if (finish === null) return [
      phase,
      {
        when: begins,
        lead: used
      }
    ];
    if (!options.carry) return [
      phase,
      {
        when: nextWorkingDay(finish + 1),
        lead: 0
      }
    ];
    const total = used + run2.days;
    const part = total - Math.floor(total + GUARD);
    return [
      phase,
      {
        when: finish,
        lead: part > GUARD ? part : 1
      }
    ];
  }
  function stretched(daysFor2, efficiency) {
    return (step2) => {
      const days = daysFor2(step2);
      if (days === null || isAgent(step2)) return days;
      return days / efficiency;
    };
  }
  function criticalPath(plan, daysFor2) {
    if (!plan.steps.length) return null;
    const order = new Map(plan.steps.map((step2, index2) => [
      step2.id,
      index2
    ]));
    const index = new Map(plan.steps.map((step2) => [
      step2.id,
      step2
    ]));
    const finishes = /* @__PURE__ */ new Map();
    const towards = /* @__PURE__ */ new Map();
    const finishOf = (id, seen) => {
      const known = finishes.get(id);
      if (known !== void 0) return known;
      if (seen.has(id)) return 0;
      const step2 = index.get(id);
      const own = daysFor2(step2) ?? 0;
      const resolved = step2.requires.filter((target) => order.has(target)).sort((a, b) => order.get(a) - order.get(b));
      let best = null;
      let upstream = 0;
      const next = new Set(seen).add(id);
      for (const target of resolved) {
        const candidate = finishOf(target, next);
        if (candidate > upstream) [upstream, best] = [
          candidate,
          target
        ];
      }
      finishes.set(id, own + upstream);
      towards.set(id, best);
      return own + upstream;
    };
    for (const step2 of plan.steps) finishOf(step2.id, /* @__PURE__ */ new Set());
    let last = plan.steps[0];
    for (const step2 of plan.steps) {
      if (finishes.get(step2.id) > finishes.get(last.id)) last = step2;
    }
    const chain = [];
    for (let at = last.id; at !== null; at = towards.get(at) ?? null) {
      chain.push(index.get(at));
    }
    chain.reverse();
    return {
      days: finishes.get(last.id),
      steps: chain,
      unestimated: chain.filter((step2) => daysFor2(step2) === null).length
    };
  }
  function cellFor(plan, daysFor2, humans, agents, args) {
    const common = {
      humans,
      agents,
      start: args.start,
      today: args.today,
      options: args.options
    };
    const raw = phases(plan, daysFor2, {
      ...common,
      options: {
        ...args.options ?? FAITHFUL,
        replan: "off"
      }
    });
    const slow = phases(plan, stretched(daysFor2, args.efficiency), common);
    const landing = [
      ...slow
    ].reverse().find((phase) => phase.finish !== null)?.finish ?? null;
    return [
      {
        humans,
        agents,
        days: raw.reduce((sum, phase) => sum + phase.days, 0),
        finish: null,
        phases: raw
      },
      {
        humans,
        agents,
        days: landing !== null ? workingDaysBetween(slow[0].start, landing) : 0,
        finish: landing,
        phases: slow
      }
    ];
  }
  function timeReport(plan, daysFor2, args) {
    if (!plan.steps.length) return null;
    let humanDays = 0;
    let agentDays = 0;
    for (const step2 of plan.steps) {
      if (isAgent(step2)) agentDays += daysFor2(step2) ?? 0;
      else humanDays += daysFor2(step2) ?? 0;
    }
    const hasAgentSteps = plan.steps.some(isAgent);
    const loop = cyclic(plan);
    const base = {
      start: args.start,
      efficiency: args.efficiency,
      humanDays,
      agentDays,
      hasAgentSteps
    };
    if (loop.length) {
      return {
        ...base,
        unestimated: plan.steps.filter((step2) => daysFor2(step2) === null).length,
        floor: 0,
        calendarFloor: 0,
        parallel: [],
        calendar: [],
        cycle: loop
      };
    }
    const path = criticalPath(plan, daysFor2);
    const calendarPath = criticalPath(plan, stretched(daysFor2, args.efficiency));
    const parallel = [];
    const calendar2 = [];
    for (const humans of HUMANS) {
      for (const agents of AGENTS) {
        const [raw, slow] = cellFor(plan, daysFor2, humans, agents, args);
        parallel.push(raw);
        calendar2.push(slow);
      }
    }
    return {
      ...base,
      start: calendar2[0].phases[0].start,
      unestimated: calendar2[0].phases.reduce((sum, phase) => sum + phase.unestimated, 0),
      floor: path ? path.days : 0,
      calendarFloor: calendarPath ? Math.ceil(calendarPath.days - 1e-9) : 0,
      parallel,
      calendar: calendar2,
      cycle: []
    };
  }
  function cellAt(cells, humans, agents) {
    return cells.find((cell) => cell.humans === humans && cell.agents === agents);
  }

  // src/model/progress.ts
  var ON_PLAN = 5e-3;
  var SAME_SHARE = 2e-3;
  var EMPTY_TALLY = {
    steps: 0,
    done: 0,
    days: 0,
    doneDays: 0,
    changed: 0
  };
  function addTally(a, b) {
    return {
      steps: a.steps + b.steps,
      done: a.done + b.done,
      days: a.days + b.days,
      doneDays: a.doneDays + b.doneDays,
      changed: a.changed + b.changed
    };
  }
  function shareOf(tally2) {
    return tally2.days ? tally2.doneDays / tally2.days : null;
  }
  function remainingOf(tally2) {
    return tally2.days - tally2.doneDays;
  }
  function toward(snapshot, key) {
    let total = EMPTY_TALLY;
    for (const stretch of snapshot.stretches) {
      total = addTally(total, stretch.tally);
      if (stretch.key === key) return total;
    }
    return key === null ? total : EMPTY_TALLY;
  }
  function has(snapshot, key) {
    return key === null || snapshot.stretches.some((stretch) => stretch.key === key);
  }
  function landingIn(snapshot, key) {
    if (key === null) {
      return [
        ...snapshot.stretches
      ].reverse().find((s) => s.finish !== null)?.finish ?? null;
    }
    return snapshot.stretches.find((s) => s.key === key)?.finish ?? null;
  }
  function sameStretch(a, b) {
    return a.key === b.key && a.start === b.start && a.finish === b.finish && a.tally.steps === b.tally.steps && a.tally.done === b.tally.done && a.tally.days === b.tally.days && a.tally.doneDays === b.tally.doneDays && a.tally.changed === b.tally.changed && a.landings.length === b.landings.length && a.landings.every((knot, index) => {
      const other = b.landings[index];
      return knot.day === other.day && knot.steps === other.steps && knot.days === other.days;
    });
  }
  function samePlan(a, b) {
    return a.stretches.length === b.stretches.length && a.stretches.every((stretch, index) => sameStretch(stretch, b.stretches[index]));
  }
  function landingShift(then, now) {
    if (now >= then) return workingDaysBetween(then, now) - 1;
    return -(workingDaysBetween(now, then) - 1);
  }
  function spanOf(snapshot, key) {
    const found = snapshot?.stretches.find((stretch) => stretch.key === key);
    return found && found.finish !== null ? [
      found.start,
      found.finish
    ] : null;
  }
  function standingWords(standing2) {
    if (standing2 === null) return "";
    if (Math.abs(standing2) < ON_PLAN) return "on plan";
    return `${standing2 > 0 ? "ahead" : "behind"} ${percent(Math.abs(standing2))}`;
  }
  function shiftWords(label2, then, now, basis, today) {
    if (now === null) return `${label2} \u2014 nothing estimated, so no date`;
    const said = `${label2} lands ${formatDate(now, today)}`;
    if (!basis) return said;
    if (then === null) return `${said} \u2014 not in ${basis}`;
    const moved = landingShift(then, now);
    if (moved === 0) return `${said} \u2014 unchanged since ${basis}`;
    const size = Math.abs(moved);
    return `${said} \u2014 ${size} working day${size === 1 ? "" : "s"} ${moved > 0 ? "later" : "earlier"} than ${basis} said (${formatDate(then, today)})`;
  }
  function scopeWords(basis) {
    return basis ? `Scope change \u2014 versus ${basis}` : "Scope change \u2014 nothing to compare with";
  }
  function calendarPhases(plan, args) {
    return phases(plan, stretched(daysFor, args.efficiency), {
      humans: args.humans,
      agents: args.agents,
      start: args.start,
      today: args.today,
      options: args.options
    });
  }
  function take(plan, args) {
    if (!plan.steps.length || cyclic(plan).length) return null;
    return snapshotFrom(calendarPhases(plan, args), args.today);
  }
  function snapshotFrom(dated3, today) {
    return {
      day: today,
      stretches: dated3.map((phase) => ({
        key: phase.milestone ? phase.milestone.id : "",
        tally: tally(phase.steps, daysFor, today),
        start: phase.began,
        finish: phase.finish,
        landings: landings(phase)
      })),
      title: "",
      note: ""
    };
  }
  function landings(phase, days = daysFor) {
    const byDay = /* @__PURE__ */ new Map();
    for (const step2 of phase.steps) {
      if (isDelay(step2)) continue;
      const when = landingOf(phase, step2.id);
      const found = byDay.get(when) ?? {
        day: when,
        steps: 0,
        days: 0
      };
      byDay.set(when, {
        day: when,
        steps: found.steps + 1,
        days: found.days + (days(step2) ?? 0)
      });
    }
    return [
      ...byDay.keys()
    ].sort((a, b) => a - b).map((when) => byDay.get(when));
  }
  function tally(steps, days = daysFor, today) {
    let total = EMPTY_TALLY;
    for (const step2 of steps) {
      if (isDelay(step2)) continue;
      const cost = days(step2) ?? 0;
      const landed = step2.status === DONE;
      total = addTally(total, {
        steps: 1,
        done: landed ? 1 : 0,
        days: cost,
        doneDays: landed ? cost : 0,
        changed: today !== void 0 && step2.since === today ? 1 : 0
      });
    }
    return total;
  }
  function through(snapshot, key) {
    const chosen = [];
    for (const stretch of snapshot.stretches) {
      chosen.push(stretch);
      if (stretch.key === key) break;
    }
    return chosen;
  }
  function idle(snapshot, key) {
    const chosen = through(snapshot, key);
    const spans = [];
    for (let index = 1; index < chosen.length; index += 1) {
      const [previous, following] = [
        chosen[index - 1],
        chosen[index]
      ];
      if (previous.finish === null) continue;
      if (following.start > nextWorkingDay(previous.finish + 1)) {
        spans.push([
          previous.finish,
          following.start
        ]);
      }
    }
    return spans;
  }
  function expected(snapshot, key) {
    if (!has(snapshot, key)) return [];
    const chosen = through(snapshot, key);
    const whole = chosen.reduce((sum, stretch) => stretch.landings.reduce((inner, knot) => inner + knot.days, sum), 0);
    if (!whole) return [];
    const landed = /* @__PURE__ */ new Map();
    for (const stretch of chosen) {
      for (const knot of stretch.landings) {
        landed.set(knot.day, (landed.get(knot.day) ?? 0) + knot.days);
      }
    }
    const resumes = new Set(idle(snapshot, key).map(([, start2]) => start2));
    const points = [
      [
        chosen[0].start,
        0
      ]
    ];
    let running = 0;
    const days = [
      .../* @__PURE__ */ new Set([
        ...landed.keys(),
        ...resumes
      ])
    ].sort((a, b) => a - b);
    for (const when of days) {
      if (resumes.has(when)) points.push([
        when,
        points[points.length - 1][1]
      ]);
      const add = landed.get(when);
      if (add !== void 0) {
        running += add;
        points.push([
          when,
          Math.min(running / whole, 1)
        ]);
      }
    }
    return points;
  }
  function until(history2, now) {
    const rows = history2.filter((row) => now === null || row.day <= now.day);
    return now === null ? rows : [
      ...rows,
      now
    ];
  }
  function actual(history2, now, key) {
    const points = [];
    for (const row of until(history2, now)) {
      if (!has(row, key)) continue;
      const share = shareOf(toward(row, key));
      if (share === null) continue;
      if (points.length && points[points.length - 1][0] === row.day) {
        points[points.length - 1] = [
          row.day,
          share
        ];
      } else {
        points.push([
          row.day,
          share
        ]);
      }
    }
    return points;
  }
  function baseline(history2, basis, today = null) {
    const before = history2.filter((row) => row.day <= basis);
    if (before.length) return before[before.length - 1];
    const first = history2[0] ?? null;
    if (first === null || today !== null && first.day >= today) return null;
    return first;
  }
  function changesSince(steps, since) {
    const added = [];
    const estimates = [];
    for (const step2 of steps) {
      if (step2.created !== null && step2.created > since) {
        added.push([
          step2,
          daysFor(step2)
        ]);
        continue;
      }
      const later = step2.estimateHistory.filter(([when]) => when > since);
      if (later.length) estimates.push([
        step2,
        later[0][0],
        later[0][1],
        daysFor(step2)
      ]);
    }
    return {
      added,
      estimates,
      since
    };
  }
  function recorded(history2, taken) {
    const now = {
      ...taken,
      title: "",
      note: ""
    };
    const rows = [
      ...history2
    ];
    const last = rows[rows.length - 1];
    if (last && last.day === now.day) {
      if (samePlan(last, now)) return null;
      rows[rows.length - 1] = now;
      return rows;
    }
    if (last && samePlan(last, now)) return null;
    rows.push(now);
    return rows;
  }
  function findSaved(saved, title3) {
    const wanted = title3.trim().toLowerCase();
    return saved.find((row) => row.title.toLowerCase() === wanted) ?? null;
  }
  function savedWith(saved, now, title3, note = "") {
    const named = title3.trim();
    if (!named) throw new Error("a saved snapshot needs a title");
    if (findSaved(saved, named)) throw new Error(`a snapshot called "${named}" is already saved`);
    return [
      ...saved,
      {
        ...now,
        title: named,
        note: note.trim()
      }
    ];
  }
  var AT_START = {
    kind: "start"
  };
  var LIVE = {
    kind: "now"
  };
  function resolve(pick, history2, saved, live, start2) {
    if (pick.kind === "now") return live;
    if (pick.kind === "saved") return findSaved(saved, pick.title);
    const when = pick.kind === "start" ? start2 : pick.day;
    return baseline(history2, when, live !== null ? live.day : null);
  }
  function pickWords(pick, found, today) {
    if (pick.kind === "now") return "now";
    if (pick.kind === "saved") {
      return found ? `${pick.title} (${formatDate(found.day, today)})` : "";
    }
    const when = pick.kind === "day" ? pick.day : null;
    const asked = when !== null ? `the plan at ${formatDate(when, today)}` : "the plan at start";
    if (found === null) return "";
    if (when !== null && found.day === when) return asked;
    return `${asked}, recorded ${formatDate(found.day, today)}`;
  }
  function shortPickWords(pick, today) {
    if (pick.kind === "now") return "Now";
    if (pick.kind === "start") return "Plan at start";
    if (pick.kind === "saved") return pick.title;
    return formatDate(pick.day, today);
  }
  function stepCurve(rows, valueOf) {
    const points = [];
    for (const row of rows) {
      const value = valueOf(toward(row, null));
      const last = points[points.length - 1];
      if (last && last[0] === row.day) {
        points[points.length - 1] = [
          row.day,
          value
        ];
        continue;
      }
      if (last) points.push([
        row.day,
        last[1]
      ]);
      points.push([
        row.day,
        value
      ]);
    }
    return points;
  }
  function volume(history2, now) {
    return stepCurve(until(history2, now), (reached) => reached.days);
  }
  function remaining(history2, now) {
    return stepCurve(until(history2, now), remainingOf);
  }
  function niceCeiling(value, steps = [
    1,
    2,
    5,
    10
  ]) {
    if (value <= 1) return 1;
    const magnitude = 10 ** Math.floor(Math.log10(value));
    for (const step2 of steps) {
      if (step2 * magnitude >= value) return step2 * magnitude;
    }
    return 10 * magnitude;
  }
  function volumeScale(total, left) {
    return niceCeiling(Math.max(0, ...[
      ...total,
      ...left
    ].map(([, value]) => value)));
  }
  function shareAt(points, when) {
    if (!points.length) return null;
    if (when <= points[0][0]) {
      return when === points[0][0] || points.length === 1 ? points[0][1] : null;
    }
    for (let index = 1; index < points.length; index += 1) {
      const [[left, low], [right, high]] = [
        points[index - 1],
        points[index]
      ];
      if (left <= when && when <= right) {
        const span = right - left;
        const share = span ? (when - left) / span : 1;
        return low + (high - low) * share;
      }
    }
    return points[points.length - 1][1];
  }
  function changeRuns(plan, base, same = SAME_SHARE) {
    const days = [
      .../* @__PURE__ */ new Set([
        ...plan.map(([d]) => d),
        ...base.map(([d]) => d)
      ])
    ].sort((a, b) => a - b);
    const samples = [];
    for (const when of days) {
      const [above, below] = [
        shareAt(plan, when),
        shareAt(base, when)
      ];
      if (above !== null && below !== null) samples.push([
        when,
        above,
        below
      ]);
    }
    const runs = [];
    for (const sample of samples) {
      const [, above, below] = sample;
      const sign = Math.abs(above - below) <= same ? 0 : above > below ? 1 : -1;
      const last = runs[runs.length - 1];
      if (last && last[0] === sign) {
        last[1].push(sample);
      } else if (last) {
        const crossing = crossingOf(last[1][last[1].length - 1], sample);
        last[1].push(crossing);
        runs.push([
          sign,
          [
            crossing,
            sample
          ]
        ]);
      } else {
        runs.push([
          sign,
          [
            sample
          ]
        ]);
      }
    }
    return runs.filter(([, run2]) => run2.length >= 2);
  }
  function crossingOf(left, right) {
    const [[dayA, aboveA, belowA], [dayB, aboveB, belowB]] = [
      left,
      right
    ];
    const [gapA, gapB] = [
      aboveA - belowA,
      aboveB - belowB
    ];
    const total = gapA - gapB;
    const share = !total ? 0.5 : Math.max(0, Math.min(1, gapA / total));
    return [
      dayA + pyRound((dayB - dayA) * share, 0),
      aboveA + (aboveB - aboveA) * share,
      belowA + (belowB - belowA) * share
    ];
  }
  function standing(plan, landed, today) {
    const [promised, reached] = [
      shareAt(plan, today),
      shareAt(landed, today)
    ];
    return promised === null || reached === null ? null : reached - promised;
  }
  function count(value) {
    return typeof value === "number" && Number.isInteger(value) ? value : 0;
  }
  function amount(value) {
    return typeof value === "number" ? value : 0;
  }
  function text(value) {
    return typeof value === "string" ? value.trim() : "";
  }
  function stretchFrom(row) {
    const start2 = typeof row.start === "string" ? parseDay(row.start) : null;
    if (start2 === null) return null;
    const finish = typeof row.finish === "string" ? parseDay(row.finish) : null;
    const knots = Array.isArray(row.landings) ? row.landings : [];
    return {
      key: typeof row.milestone === "string" ? row.milestone : "",
      tally: {
        steps: count(row.steps),
        done: count(row.done),
        days: amount(row.days),
        doneDays: amount(row.done_days),
        changed: count(row.changed)
      },
      start: start2,
      finish,
      landings: knots.flatMap((knot) => {
        const when = typeof knot?.date === "string" ? parseDay(knot.date) : null;
        return when === null ? [] : [
          {
            day: when,
            steps: count(knot.steps),
            days: amount(knot.days)
          }
        ];
      })
    };
  }
  function readRows(entry, key) {
    const raw = entry?.[key];
    if (!Array.isArray(raw)) return [];
    const rows = [];
    for (const row of raw) {
      if (typeof row !== "object" || row === null || typeof row.day !== "string") continue;
      const day = parseDay(row.day);
      if (day === null || !Array.isArray(row.stretches)) continue;
      const parsed = row.stretches.filter((s) => typeof s === "object" && s).map(stretchFrom);
      if (parsed.some((stretch) => stretch === null)) continue;
      const snapshot = {
        day,
        stretches: parsed,
        title: text(row.title),
        note: text(row.note)
      };
      if (key === "saved" && !snapshot.title) continue;
      rows.push(snapshot);
    }
    return rows;
  }
  function rowJson(row) {
    return {
      day: isoDay(row.day),
      stretches: row.stretches.map((s) => ({
        ...s.key ? {
          milestone: s.key
        } : {},
        steps: s.tally.steps,
        done: s.tally.done,
        days: s.tally.days,
        done_days: s.tally.doneDays,
        ...s.tally.changed ? {
          changed: s.tally.changed
        } : {},
        start: isoDay(s.start),
        ...s.finish !== null ? {
          finish: isoDay(s.finish)
        } : {},
        ...s.landings.length ? {
          landings: s.landings.map((k) => ({
            date: isoDay(k.day),
            steps: k.steps,
            days: k.days
          }))
        } : {}
      }))
    };
  }

  // src/data.ts
  var EXPORT_FORMAT = "te2-export/1";
  var dayOrNull = (value) => value ? parseDay(value) : null;
  function delayFromJson(json) {
    if (!json) return null;
    if ("days" in json) return {
      days: json.days
    };
    const until2 = parseDay(json.until);
    return until2 === null ? null : {
      until: until2
    };
  }
  function planFromJson(json) {
    return {
      ...json,
      start: dayOrNull(json.start),
      steps: json.steps.map((step2) => ({
        ...step2,
        estimateHistory: step2.estimateHistory.flatMap(([day, days]) => {
          const when = parseDay(day);
          return when === null ? [] : [
            [
              when,
              days
            ]
          ];
        }),
        created: dayOrNull(step2.created),
        start: dayOrNull(step2.start),
        since: dayOrNull(step2.since ?? null),
        started: dayOrNull(step2.started ?? null),
        delay: delayFromJson(step2.delay)
      }))
    };
  }
  function isExport(value) {
    return typeof value === "object" && value !== null && value.format === EXPORT_FORMAT && Array.isArray(value.frames);
  }

  // src/present.ts
  var ALL_KEY = "*";
  var ALL_LABEL = "All milestones";
  var WHOLE_LABEL = "All work";
  var REMAINDER_LABEL = "Remaining work";
  function lookingBack(view) {
    return view.now !== view.live;
  }
  function dayWord(view) {
    return lookingBack(view) ? shortDate(view.now.day, view.today) : "today";
  }
  function applyWhatIf(plan, whatIf3, today) {
    const begins = whatIf3.begins ?? {};
    const stored = plan.assumptions.efficiency;
    const changed = whatIf3.efficiency !== void 0 && whatIf3.efficiency !== stored;
    return {
      ...plan,
      start: whatIf3.start ?? plan.start,
      assumptions: {
        ...plan.assumptions,
        efficiency: whatIf3.efficiency ?? stored,
        palette: whatIf3.palette ?? plan.assumptions.palette,
        team: whatIf3.team ?? plan.assumptions.team,
        ...changed ? {
          efficiencyWas: {
            until: today + 1,
            efficiency: stored ?? DEFAULT_EFFICIENCY
          }
        } : {}
      },
      steps: plan.steps.map((step2) => step2.id in begins ? {
        ...step2,
        start: begins[step2.id]
      } : step2)
    };
  }
  function labelOf(phase, all) {
    if (phase.milestone) return milestoneLabel(phase.milestone);
    return all.every((other) => other.milestone === null) ? WHOLE_LABEL : REMAINDER_LABEL;
  }
  function present(stored, today, recording2, state, options) {
    const plan = applyWhatIf(stored, state.whatIf, today);
    const start2 = startOf(plan, today);
    const report = timeReport(plan, daysFor, {
      start: start2,
      today,
      efficiency: efficiencyOf(plan),
      options
    });
    if (!report) return null;
    const team2 = teamOf(plan);
    const cell = cellAt(report.calendar, ...team2) ?? report.calendar[0];
    const colors = milestoneColors(plan, plan.assumptions.palette);
    const phases2 = cell?.phases ?? [];
    const shades2 = phaseColors(phases2, colors);
    const stretches = phases2.map((phase, index) => ({
      phase,
      key: phase.milestone ? phase.milestone.id : "",
      label: labelOf(phase, phases2),
      color: shades2[index]
    }));
    const live = snapshotFrom(phases2, today);
    const unestimated = plan.steps.filter((step2) => daysFor(step2) === null);
    const found = (pick) => resolve(pick, recording2.rows, recording2.saved, live, start2);
    const now = found(state.now) ?? live;
    const then = found(state.then);
    const basis = pickWords(state.then, then, now.day);
    const asOf = state.now.kind === "now" ? "" : pickWords(state.now, now, live.day);
    const promised = expected(now, null);
    const landed = actual(recording2.rows, now, null);
    const picked = stretches.some((one) => one.key && one.key === state.picked) ? state.picked : null;
    const chart2 = {
      today: now.day,
      expected: promised,
      actual: landed,
      baseline: then ? expected(then, null) : [],
      basis,
      asOf,
      finish: landingIn(now, null),
      baselineFinish: then ? landingIn(then, null) : null,
      idle: idle(now, null),
      segments: stretches.map((one) => {
        const [was, is] = [
          spanOf(then, one.key),
          spanOf(now, one.key)
        ];
        return {
          key: one.key,
          label: one.label,
          color: one.color,
          now: is,
          then: was,
          words: shiftWords(one.label, was?.[1] ?? null, is?.[1] ?? null, basis, today)
        };
      }),
      emphasis: picked,
      volume: volume(recording2.rows, now),
      remaining: remaining(recording2.rows, now),
      marks: recording2.saved.map((row) => [
        row.day,
        row.title
      ]),
      standing: standing(promised, landed, now.day)
    };
    return {
      today,
      plan,
      report,
      team: team2,
      cell,
      stretches,
      entries: entries(stretches, live, cell, start2),
      unestimated,
      live,
      now,
      then,
      chart: chart2,
      recording: recording2,
      start: start2,
      pace: paceSoFar(plan, stretched(daysFor, efficiencyOf(plan)), start2, today)
    };
  }
  function entries(stretches, live, cell, start2) {
    const found = stretches.map(({ phase, key, label: label2, color }) => ({
      key,
      label: label2,
      title: phase.milestone && phase.milestone.title !== label2 ? phase.milestone.title : "",
      badge: phase.milestone ? stepKey(phase.milestone) : "",
      color,
      asked: phase.asked,
      begins: phase.start,
      finish: phase.finish,
      days: calendarDays(phase),
      steps: phase.steps.length,
      pushed: pushed(phase) ? phase.asked : null,
      landed: toward(live, phase.milestone ? phase.milestone.id : null),
      setsProject: false
    }));
    if (found.some((entry) => entry.badge)) {
      found.unshift({
        key: ALL_KEY,
        label: ALL_LABEL,
        title: "",
        badge: "",
        color: WHOLE_COLOR,
        asked: start2,
        begins: start2,
        finish: cell.finish,
        days: cell.days,
        steps: stretches.reduce((sum, one) => sum + one.phase.steps.length, 0),
        pushed: null,
        landed: toward(live, null),
        setsProject: true
      });
    } else if (found.length) {
      found[0] = {
        ...found[0],
        asked: start2,
        begins: start2,
        setsProject: true
      };
    }
    return found;
  }

  // src/sim/rng.ts
  function rng(seed) {
    let state = seed >>> 0;
    return () => {
      state = state + 1831565813 >>> 0;
      let t = state;
      t = Math.imul(t ^ t >>> 15, t | 1);
      t ^= t + Math.imul(t ^ t >>> 7, t | 61);
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function seedOf(seed, name) {
    let hash = (seed ^ 2166136261) >>> 0;
    for (let index = 0; index < name.length; index += 1) {
      hash = Math.imul(hash ^ name.charCodeAt(index), 16777619) >>> 0;
    }
    return hash;
  }
  function normal(random) {
    const u = Math.max(random(), 1e-12);
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * random());
  }
  function lognormal(random, sigma) {
    return sigma ? Math.exp(sigma * normal(random) - sigma * sigma / 2) : 1;
  }
  function choose(random, items) {
    return items[Math.floor(random() * items.length)];
  }

  // src/sim/timeline.ts
  var CADENCES = [
    {
      key: "weekdays",
      label: "every working day"
    },
    {
      key: "daily",
      label: "every day, weekends too"
    },
    {
      key: "twice-weekly",
      label: "Mondays and Thursdays"
    },
    {
      key: "sparse",
      label: "one day in three, at random"
    },
    {
      key: "stored",
      label: "as DPlanner recorded it"
    }
  ];
  function recorderRan(cadence, day, seed) {
    if (cadence === "daily") return true;
    if (cadence === "weekdays") return isWorkingDay(day);
    if (cadence === "twice-weekly") return weekday(day) === 0 || weekday(day) === 3;
    if (cadence === "sparse") {
      return isWorkingDay(day) && rng(seedOf(seed, `record-${day}`))() < 1 / 3;
    }
    return false;
  }
  function snapshotOf(plan, today, options = FAITHFUL) {
    const [humans, agents] = teamOf(plan);
    return take(plan, {
      humans,
      agents,
      start: startOf(plan, today),
      efficiency: efficiencyOf(plan),
      today,
      options
    });
  }
  function record(timeline3, spec) {
    if (spec.cadence === "stored") {
      const last = timeline3.frames[timeline3.frames.length - 1]?.stored;
      return {
        rows: last?.rows ?? [],
        saved: last?.saved ?? []
      };
    }
    let rows = [];
    let saved = [];
    for (const frame of timeline3.frames) {
      const wanted = spec.saved.filter((one) => one.day === frame.day);
      const ran = recorderRan(spec.cadence, frame.day, spec.seed);
      if (!ran && !wanted.length) continue;
      const taken = snapshotOf(frame.plan, frame.day, spec.options);
      if (!taken) continue;
      if (ran) rows = recorded(rows, taken) ?? rows;
      for (const one of wanted) {
        try {
          saved = savedWith(saved, taken, one.title, one.note);
        } catch {
        }
      }
    }
    return {
      rows,
      saved
    };
  }
  function recordedBy(recording2, day) {
    return {
      rows: recording2.rows.filter((row) => row.day <= day),
      saved: recording2.saved.filter((row) => row.day <= day)
    };
  }

  // src/sim/replay.ts
  function replay(file) {
    const byDay = /* @__PURE__ */ new Map();
    for (const frame of file.frames) {
      const day = parseDay(frame.day);
      if (day !== null) byDay.set(day, frame);
    }
    const days = [
      ...byDay.keys()
    ].sort((a, b) => a - b);
    const frames = [];
    const finished2 = /* @__PURE__ */ new Map();
    let before = null;
    for (let day = days[0]; day <= days[days.length - 1]; day += 1) {
      const found = byDay.get(day);
      if (!found) {
        frames.push({
          ...before,
          day,
          events: []
        });
        continue;
      }
      const plan = dated2(planFromJson(found.plan), before, day);
      const events2 = describe(before, plan.steps, found.commit);
      for (const step2 of plan.steps) {
        const was = before?.plan.steps.find((other) => other.id === step2.id);
        if (step2.status === DONE && was?.status !== DONE) finished2.set(step2.id, day);
        if (step2.status !== DONE) finished2.delete(step2.id);
      }
      before = {
        day,
        plan,
        events: events2,
        stored: {
          rows: readRows(found.history, "days"),
          saved: readRows(found.history, "saved")
        }
      };
      frames.push(before);
    }
    const first = frames[0].plan.start ?? frames[0].day;
    return {
      title: file.title,
      frames,
      begin: first,
      finished: finished2,
      kind: "replay"
    };
  }
  function dated2(plan, before, day) {
    if (!before) return plan;
    const old = new Map(before.plan.steps.map((step2) => [
      step2.id,
      step2
    ]));
    return {
      ...plan,
      steps: plan.steps.map((step2) => {
        const was = old.get(step2.id);
        const going = step2.status === "in-progress" || step2.status === "blocked";
        return {
          ...step2,
          since: step2.since ?? (was && was.status === step2.status ? was.since : day),
          started: step2.started ?? was?.started ?? (going && was?.status === "pending" ? day : null)
        };
      })
    };
  }
  function describe(before, steps, commit) {
    const events2 = [
      commit === "worktree" ? "uncommitted changes on disk" : `commit ${commit.slice(0, 7)}`
    ];
    if (!before) return events2;
    const old = new Map(before.plan.steps.map((step2) => [
      step2.id,
      step2
    ]));
    for (const step2 of steps) {
      const was = old.get(step2.id);
      if (!was) events2.push(`S${step2.number} ${step2.title} added`);
      else if (was.status !== step2.status) {
        events2.push(`S${step2.number} ${was.status} \u2192 ${step2.status}`);
      } else if (was.estimate !== step2.estimate) {
        events2.push(`S${step2.number} re-estimated ${was.estimate ?? "\u2013"} \u2192 ${step2.estimate ?? "\u2013"}`);
      }
    }
    const now = new Set(steps.map((step2) => step2.id));
    for (const step2 of before.plan.steps) {
      if (!now.has(step2.id)) events2.push(`S${step2.number} removed`);
    }
    return events2;
  }
  function parity(timeline3) {
    const found = [];
    for (const frame of timeline3.frames) {
      const stored = frame.stored?.rows.find((row) => row.day === frame.day);
      if (!stored || !frame.events.length) continue;
      const mine = snapshotOf(frame.plan, frame.day);
      if (!mine) continue;
      const apart = differences(stored, mine);
      found.push({
        day: frame.day,
        same: !apart.length,
        differences: apart
      });
    }
    return found;
  }
  function differences(stored, mine) {
    const [a, b] = [
      rowJson(stored).stretches,
      rowJson(mine).stretches
    ];
    const found = [];
    for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
      const [x, y] = [
        a[index],
        b[index]
      ];
      if (!x || !y) {
        found.push(`stretch ${index + 1}: ${x ? "only DPlanner has it" : "only the port has it"}`);
        continue;
      }
      for (const field of [
        "milestone",
        "steps",
        "done",
        "days",
        "done_days",
        "start",
        "finish"
      ]) {
        if (JSON.stringify(x[field]) !== JSON.stringify(y[field])) {
          found.push(`stretch ${index + 1} ${field}: DPlanner ${JSON.stringify(x[field])}, port ${JSON.stringify(y[field])}`);
        }
      }
      if (JSON.stringify(x.landings) !== JSON.stringify(y.landings)) {
        found.push(`stretch ${index + 1}: landing knots differ`);
      }
    }
    return found;
  }
  function parityWords(results) {
    if (!results.length) return "no day has both a stored row and a commit to compare";
    const same = results.filter((one) => one.same).length;
    return `${same} of ${results.length} recorded days match DPlanner's own row` + (same < results.length ? ` (differs on ${results.filter((one) => !one.same).map((one) => isoDay(one.day)).join(", ")})` : "");
  }

  // src/sim/sample.ts
  var SAMPLE_START = fromYMD(2026, 10, 5);
  var VERBS = [
    "Model",
    "Wire",
    "Draw",
    "Store",
    "Import",
    "Export",
    "Validate",
    "Test",
    "Measure",
    "Document",
    "Cache",
    "Index"
  ];
  var NOUNS = [
    "the ledger",
    "the parser",
    "the report",
    "the gateway",
    "the settings",
    "the importer",
    "the calendar",
    "the audit log",
    "the search",
    "the sync",
    "the dashboard",
    "the onboarding"
  ];
  var HUMAN = [
    "Review the design",
    "Decide the data model",
    "Usability walkthrough",
    "Security review",
    "Write the migration guide",
    "Pair on the hard part"
  ];
  var SAMPLE_SHAPE = {
    milestones: 4,
    branches: [
      2,
      3
    ],
    chain: [
      2,
      4
    ],
    agentShare: 0.75,
    unestimated: 2
  };
  function between(random, [least, most]) {
    return least + Math.floor(random() * (most - least + 1));
  }
  function samplePlan(seed, shape = SAMPLE_SHAPE) {
    const random = rng(seed);
    const steps = [];
    const add = (title3, fields = {}) => {
      const step2 = {
        id: `s${steps.length + 1}`,
        number: steps.length + 1,
        title: title3,
        requires: [],
        estimate: null,
        estimateOff: false,
        estimateHistory: [],
        status: "pending",
        milestone: null,
        agent: false,
        created: SAMPLE_START - 7,
        start: null,
        color: null,
        since: null,
        started: null,
        delay: null,
        ...fields
      };
      steps.push(step2);
      return step2;
    };
    const origin = add("Project start", {
      estimate: 0
    });
    let previous = origin;
    for (let index = 1; index <= shape.milestones; index += 1) {
      const ends = [];
      for (let branch = 0; branch < between(random, shape.branches); branch += 1) {
        let at = previous.id;
        for (let link = 0; link < between(random, shape.chain); link += 1) {
          const agent = random() < shape.agentShare;
          const step2 = agent ? add(`${choose(random, VERBS)} ${choose(random, NOUNS)}`, {
            agent: true,
            estimate: choose(random, [
              0.25,
              0.25,
              0.5,
              0.5,
              0.75,
              1,
              1.5
            ])
          }) : add(choose(random, HUMAN), {
            estimate: choose(random, [
              1,
              1,
              2,
              2,
              3,
              5
            ])
          });
          step2.requires = [
            at
          ];
          at = step2.id;
        }
        ends.push(at);
      }
      previous = add(`Release ${index}`, {
        milestone: `M${index}`,
        estimateOff: true,
        requires: ends
      });
    }
    const sized = steps.filter((step2) => step2.estimate && step2 !== origin);
    for (let left = shape.unestimated; left > 0 && sized.length; left -= 1) {
      sized.splice(Math.floor(random() * sized.length), 1)[0].estimate = null;
    }
    return {
      id: `sample-${seed}`,
      title: `Sample plan (seed ${seed})`,
      start: SAMPLE_START,
      assumptions: {
        efficiency: 0.5,
        palette: null,
        team: [
          1,
          2
        ]
      },
      steps
    };
  }

  // src/sim/scenarios.ts
  var SAVED_BY_DEFAULT = [
    {
      after: 0,
      title: "Kickoff review",
      note: "The plan as it was presented on the first day."
    },
    {
      after: 21,
      title: "Three-week check-in",
      note: "Where we thought we were after three weeks."
    }
  ];
  var SCENARIOS = [
    {
      id: "by-the-book",
      name: "By the book",
      breaks: "nothing \u2014 every step takes exactly its estimate and nothing happens to the plan",
      look: "Progress reads \u201Cbehind\u201D while every step is exactly on time \u2014 the plan line is drawn straight between landings, progress only counts at one (P1). Track record: flat forecasts, but M2\u2013M4 land a day or two before them \u2014 the model's own rounding (Q3); switch on \u201CCarry part-days\u201D and they meet.",
      world: {
        unestimatedEffort: 0
      }
    },
    {
      id: "unsized",
      name: "Unsized steps",
      breaks: "a step nobody estimated costs nothing \u2014 each really takes two days",
      look: "The banner counts them as 0d (together with the milestones, I2), and the forecast believes it: the milestones holding them land 2\u20133 days late while Progress reads about on plan.",
      world: {
        unestimatedEffort: 2
      }
    },
    {
      id: "optimistic",
      name: "Optimistic estimates",
      breaks: "the estimates are right \u2014 human work really takes 1.5\xD7 its estimate",
      look: "Progress falls far behind, yet the milestone table keeps its dates \u2014 past ones included \u2014 and Milestone shifts shows nothing, because the forecast never reads what has landed (F1). Track record: flat lines, every milestone weeks late. Try \u201CRe-plan from today\u201D.",
      world: {
        humanBias: 1.5,
        noise: 0.25
      }
    },
    {
      id: "scope-creep",
      name: "Scope creep",
      breaks: "the plan is complete \u2014 about three steps every two weeks are added to the milestone being worked",
      look: "Volume: the total climbs while remaining barely falls. Scope change: red where the plan now promises less than it did. Progress reads about on plan throughout \u2014 the plan now absorbs whatever was added, and each day's share was of that day's own total (P2).",
      world: {
        scopePerWeek: 1.5
      }
    },
    {
      id: "learning",
      name: "Learning re-estimates",
      breaks: "the first estimates are final \u2014 they are 1.5\xD7 too low, and every week the team re-estimates the three largest waiting steps",
      look: "Milestone shifts and Scope change move in steps on re-estimate days. Track record: the forecasts climb toward the truth and overshoot it \u2014 a waiting step can be re-estimated twice.",
      world: {
        humanBias: 1.5,
        reestimateEvery: 5,
        reestimateFactor: 1.5
      }
    },
    {
      id: "joiner",
      name: "Someone joins",
      breaks: "the team stays as it is \u2014 a second person and a third agent join on day 14",
      look: "Every landing jumps earlier on day 14. Scope change against the plan at start reads as \u201Cpulled in\u201D, though no scope changed: a record freezes its day's team (R2).",
      world: {
        budgets: [
          {
            after: 14,
            humans: 2,
            agents: 3
          }
        ]
      }
    },
    {
      id: "blocked",
      name: "A blocked step",
      breaks: "nothing waits \u2014 the longest-running step is blocked for six working days on day 8",
      look: "The step reads \u201Cblocked\u201D, and the forecast does not care: status is only ever read as done or not done (F4). Progress falls behind; the landings do not move.",
      world: {
        block: {
          after: 8,
          days: 6
        }
      }
    },
    {
      id: "work-ahead",
      name: "Team works ahead",
      breaks: "milestones run in sequence \u2014 idle people start the next milestone's ready work",
      look: "Little changes here, and not always for the better: someone busy on the next milestone is not free when this one's next step becomes ready, so a milestone can land later (Q1). The model shows neither.",
      world: {
        workAhead: true
      }
    },
    {
      id: "undated",
      name: "Undated project",
      breaks: "the plan has a start date \u2014 nobody set one, so it starts \u201Ctoday\u201D, every day",
      look: "Every landing slides a working day each day and a row is written daily; Progress reads far ahead, and \u201CPlan at start\u201D resolves to today's own record \u2014 the plan compared with itself (F2).",
      world: {
        dated: false
      }
    },
    {
      id: "sparse",
      name: "Window rarely open",
      breaks: "the recorder sees every day \u2014 the window is opened on Mondays and Thursdays",
      look: "Records: most days have no row. Progress: the actual line is straight segments drawn through days nothing was recorded (R1).",
      world: {
        humanBias: 1.3,
        noise: 0.3
      },
      cadence: "twice-weekly"
    },
    {
      id: "supervision",
      name: "Agents need supervision",
      breaks: "agent work costs no human time \u2014 each running agent step takes a quarter of a person's day",
      look: "Human steps slow down whenever agents run; the forecast, which prices the two pools apart, never sees it (S1). The later milestones slip three or four days.",
      world: {
        agentLoad: 0.25
      }
    },
    {
      id: "realistic",
      name: "A realistic mix",
      breaks: "several at once \u2014 optimistic estimates, noise, some scope creep, occasional re-estimates",
      look: "What a real project probably looks like. Compare the model variants in Track record.",
      world: {
        humanBias: 1.3,
        agentBias: 1.1,
        noise: 0.35,
        scopePerWeek: 1,
        reestimateEvery: 10,
        reestimateFactor: 1.25
      }
    }
  ];
  function scenarioById(id) {
    return SCENARIOS.find((found) => found.id === id) ?? SCENARIOS[0];
  }

  // src/sim/edits.ts
  var NO_EDITS = {
    budgets: [],
    delays: []
  };
  function budgetOf(plan) {
    const [humans, agents] = teamOf(plan);
    return {
      humans,
      agents,
      efficiency: efficiencyOf(plan)
    };
  }
  var sameBudget = (a, b) => a.humans === b.humans && a.agents === b.agents && Math.abs(a.efficiency - b.efficiency) < 1e-9;
  function rebudget(edits, day, budget, before) {
    const others = edits.budgets.filter((one) => one.day !== day);
    const budgets = sameBudget(budget, before) ? others : [
      ...others,
      {
        day,
        ...budget
      }
    ];
    return {
      ...edits,
      budgets: budgets.sort((a, b) => a.day - b.day)
    };
  }
  function worldBudgets(edits, begin) {
    return edits.budgets.map(({ day, ...budget }) => ({
      after: day - begin,
      ...budget
    }));
  }
  function worldDelays(edits, begin) {
    return edits.delays.map(({ day, ...delay }) => ({
      after: day - begin,
      ...delay
    }));
  }
  function edited(timeline3, edits) {
    if (!edits.budgets.length && !edits.delays.length) return timeline3;
    return {
      ...timeline3,
      frames: timeline3.frames.map((frame) => {
        const made = edits.budgets.filter((one) => one.day <= frame.day);
        const budget = made.at(-1);
        const delays = edits.delays.filter((one) => one.day <= frame.day);
        if (!budget && !delays.length) return frame;
        const before = [
          budgetOf(frame.plan),
          ...made
        ].map((one) => one.efficiency);
        const changed = before.findLastIndex((focus2, at) => at > 0 && focus2 !== before[at - 1]);
        const assumptions = budget ? {
          ...frame.plan.assumptions,
          team: [
            budget.humans,
            budget.agents
          ],
          efficiency: budget.efficiency,
          ...changed > 0 ? {
            efficiencyWas: {
              until: made[changed - 1].day,
              efficiency: before[changed - 1]
            }
          } : {}
        } : frame.plan.assumptions;
        const steps = delays.reduce((held, edit) => insertDelay(held, edit), frame.plan.steps);
        return {
          ...frame,
          plan: {
            ...frame.plan,
            assumptions,
            steps
          }
        };
      })
    };
  }
  function waitTitle(delay) {
    if ("days" in delay) return `Wait ${delay.days} working day${delay.days === 1 ? "" : "s"}`;
    return `Wait until ${weekdayName(delay.until).slice(0, 3)} ${shortDate(delay.until, delay.until)}`;
  }
  var delayId = (edit) => `wait-${isoDay(edit.day)}-${edit.before}`;
  function insertDelay(steps, edit) {
    const at = steps.findIndex((step2) => step2.id === edit.before);
    const id = delayId(edit);
    if (at < 0 || steps.some((step2) => step2.id === id)) return [
      ...steps
    ];
    const held = steps[at];
    const delay = {
      id,
      number: Math.max(...steps.map((step2) => step2.number)) + 1,
      title: waitTitle(edit.delay),
      requires: held.requires,
      estimate: null,
      estimateOff: true,
      estimateHistory: [],
      status: "pending",
      milestone: null,
      agent: false,
      created: edit.day,
      start: null,
      color: null,
      since: null,
      started: null,
      delay: edit.delay
    };
    return [
      ...steps.slice(0, at),
      delay,
      {
        ...held,
        requires: [
          id
        ]
      },
      ...steps.slice(at + 1)
    ];
  }
  function budgetsToHash(budgets) {
    return budgets.map((one) => `${isoDay(one.day)}:${one.humans}+${one.agents}@${Math.round(one.efficiency * 100)}`).join(";");
  }
  function delaysToHash(delays) {
    return delays.map((one) => `${isoDay(one.day)}:${one.before}:${"days" in one.delay ? `days:${one.delay.days}` : `until:${isoDay(one.delay.until)}`}`).join(";");
  }
  function delaysFromHash(text2) {
    return (text2 ?? "").split(";").flatMap((part) => {
      const found = part.match(/^(\d{4}-\d\d-\d\d):([^:;]+):(until|days):([\d.-]+)$/);
      const day = found ? parseDay(found[1]) : null;
      if (!found || day === null) return [];
      if (found[3] === "days") {
        const days = Number(found[4]);
        return days > 0 ? [
          {
            day,
            before: found[2],
            delay: {
              days
            }
          }
        ] : [];
      }
      const until2 = parseDay(found[4]);
      return until2 === null ? [] : [
        {
          day,
          before: found[2],
          delay: {
            until: until2
          }
        }
      ];
    });
  }
  function budgetsFromHash(text2) {
    return (text2 ?? "").split(";").flatMap((part) => {
      const found = part.match(/^(\d{4}-\d\d-\d\d):(\d+)[+ ](\d+)@(\d+)$/);
      const day = found ? parseDay(found[1]) : null;
      if (!found || day === null) return [];
      const [humans, agents, percent2] = found.slice(2).map(Number);
      return humans >= 1 && agents >= 1 && percent2 > 0 ? [
        {
          day,
          humans,
          agents,
          efficiency: percent2 / 100
        }
      ] : [];
    }).sort((a, b) => a.day - b.day);
  }

  // src/sim/world.ts
  var DEFAULT_WORLD = {
    seed: 7,
    humanBias: 1,
    agentBias: 1,
    noise: 0,
    unestimatedEffort: 1,
    focus: null,
    agentLoad: 0,
    scopePerWeek: 0,
    reestimateEvery: 0,
    reestimateFactor: 1.5,
    budgets: [],
    delays: [],
    block: null,
    workAhead: false,
    dated: true,
    lead: 3,
    tail: 5,
    maxDays: 400
  };
  var EPSILON = 1e-9;
  function run(start2, params, begin) {
    const world = new World(start2, params, begin);
    return world.play();
  }
  var World = class {
    params;
    begin;
    steps;
    plan;
    effort;
    progress;
    blockedUntil;
    finished;
    // A Delay is a timer, never a worker: when it ends, in working days since work began.
    waits;
    over;
    humans;
    agents;
    random;
    events;
    today;
    constructor(start2, params, begin) {
      this.params = params;
      this.begin = begin;
      this.effort = /* @__PURE__ */ new Map();
      this.progress = /* @__PURE__ */ new Map();
      this.blockedUntil = /* @__PURE__ */ new Map();
      this.finished = /* @__PURE__ */ new Map();
      this.waits = /* @__PURE__ */ new Map();
      this.over = /* @__PURE__ */ new Set();
      this.events = [];
      this.steps = start2.steps.map((step2) => ({
        ...step2,
        status: "pending"
      }));
      this.plan = {
        ...start2,
        start: params.dated ? begin : null
      };
      this.today = begin;
      const [humans, agents] = teamOf(start2);
      this.humans = Array(humans).fill(null);
      this.agents = Array(agents).fill(null);
      this.random = rng(seedOf(params.seed, "events"));
      for (const step2 of this.steps) this.effortOf(step2);
    }
    play() {
      const frames = [];
      let workday = 0;
      let doneOn = null;
      for (let day = this.begin - this.params.lead; day - this.begin <= this.params.maxDays; day += 1) {
        this.events = [];
        this.today = day;
        if (day >= this.begin) {
          this.scheduled(day - this.begin, day);
          if (isWorkingDay(day)) {
            workday += 1;
            if (workday > 1) this.changePlan(day, workday);
            this.work(day);
          }
        }
        frames.push({
          day,
          plan: {
            ...this.plan,
            steps: [
              ...this.steps
            ]
          },
          events: this.events
        });
        if (doneOn === null && this.steps.every((step2) => isDelay(step2) || step2.status === DONE)) {
          doneOn = day;
        }
        if (doneOn !== null && day >= doneOn + this.params.tail) break;
      }
      return {
        title: this.plan.title,
        frames,
        begin: this.begin,
        finished: new Map(this.finished),
        kind: "scenario"
      };
    }
    // -- the plan changing under the team ----------------------------------------------------------
    /** A change to a step; one to its status is stamped with the day, as DPlanner would. */
    update(id, patch) {
      const index = this.steps.findIndex((step2) => step2.id === id);
      const was = this.steps[index];
      const moved = patch.status !== void 0 && patch.status !== was.status;
      const begins = patch.status === "in-progress" && was.started === null;
      this.steps[index] = {
        ...was,
        ...patch,
        ...moved ? {
          since: this.today
        } : {},
        ...begins ? {
          started: this.today
        } : {}
      };
      return this.steps[index];
    }
    scheduled(offset, day) {
      for (const change of this.params.budgets.filter((one) => one.after === offset)) {
        const [was, efficiency] = [
          efficiencyOf(this.plan),
          change.efficiency ?? efficiencyOf(this.plan)
        ];
        this.plan = {
          ...this.plan,
          assumptions: {
            ...this.plan.assumptions,
            team: [
              change.humans,
              change.agents
            ],
            efficiency,
            ...efficiency !== was ? {
              efficiencyWas: {
                until: day,
                efficiency: was
              }
            } : {}
          }
        };
        this.humans = resized(this.humans, change.humans);
        this.agents = resized(this.agents, change.agents);
        this.events.push(`the team becomes ${change.humans} ${change.humans === 1 ? "person" : "people"} + ${change.agents} agent${change.agents === 1 ? "" : "s"}${change.efficiency !== void 0 ? ` at ${Math.round(change.efficiency * 100)}% focus` : ""}`);
      }
      for (const change of this.params.delays.filter((one) => one.after === offset)) {
        const edit = {
          day,
          before: change.before,
          delay: change.delay
        };
        this.steps = insertDelay(this.steps, edit);
        const added = this.steps.find((step2) => step2.id === delayId(edit));
        if (added) this.events.push(`${stepKey(added)} ${added.title} added`);
      }
      const block = this.params.block;
      if (block && offset === block.after) {
        const tails = this.tails();
        const running = [
          ...this.humans,
          ...this.agents
        ].filter((id) => id !== null);
        const critical = running.sort((a, b) => (tails.get(b) ?? 0) - (tails.get(a) ?? 0))[0];
        if (critical) {
          this.release(critical);
          this.blockedUntil.set(critical, workingDaysAfter(day, block.days + 1));
          const step2 = this.update(critical, {
            status: "blocked"
          });
          this.events.push(`${stepKey(step2)} ${step2.title} is blocked for ${block.days} working days`);
        }
      }
      for (const [id, until2] of this.blockedUntil) {
        if (until2 <= day) {
          this.blockedUntil.delete(id);
          const step2 = this.update(id, {
            status: this.progress.get(id) ? "in-progress" : "pending"
          });
          this.events.push(`${stepKey(step2)} is unblocked`);
        }
      }
    }
    changePlan(day, workday) {
      const current = this.currentStretch();
      if (!current) return;
      const [milestone, members] = current;
      if (this.params.scopePerWeek && this.random() < this.params.scopePerWeek / 5) {
        const agent = this.random() < 0.7;
        const id = `added-${this.steps.length + 1}`;
        const work = members.filter((step3) => step3 !== milestone);
        const after = work.length ? choose(this.random, work) : null;
        const step2 = {
          id,
          number: Math.max(...this.steps.map((one) => one.number)) + 1,
          title: `Added: ${choose(this.random, [
            "handle",
            "support",
            "fix",
            "cover"
          ])} ${choose(this.random, [
            "an edge case",
            "a second format",
            "the empty state",
            "an old import",
            "a review comment"
          ])}`,
          requires: after ? [
            after.id
          ] : [],
          estimate: agent ? choose(this.random, [
            0.25,
            0.5,
            1
          ]) : choose(this.random, [
            1,
            2,
            3
          ]),
          estimateOff: false,
          estimateHistory: [],
          status: "pending",
          milestone: null,
          agent,
          created: day,
          start: null,
          color: null,
          since: null,
          started: null,
          delay: null
        };
        this.steps.push(step2);
        this.effortOf(step2);
        if (milestone) this.update(milestone.id, {
          requires: [
            ...milestone.requires,
            id
          ]
        });
        this.events.push(`${stepKey(step2)} added (${step2.estimate}d, ${agent ? "agent" : "human"})`);
      }
      if (this.params.reestimateEvery && workday % this.params.reestimateEvery === 0) {
        const waiting = members.filter((step2) => step2.status === "pending" && daysFor(step2)).sort((a, b) => daysFor(b) - daysFor(a)).slice(0, 3);
        for (const step2 of waiting) {
          const was = step2.estimate;
          const estimate = Math.max(0.25, Math.round(was * this.params.reestimateFactor / 0.25) * 0.25);
          if (estimate === was) continue;
          const history2 = step2.estimateHistory.some(([when]) => when === day) ? step2.estimateHistory : [
            ...step2.estimateHistory,
            [
              day,
              was
            ]
          ];
          this.update(step2.id, {
            estimate,
            estimateHistory: history2
          });
          this.events.push(`${stepKey(step2)} re-estimated ${was}d \u2192 ${estimate}d`);
        }
      }
    }
    // -- the team working --------------------------------------------------------------------------
    effortOf(step2) {
      const known = this.effort.get(step2.id);
      if (known !== void 0) return known;
      const days = daysFor(step2) ?? (step2.estimateOff ? 0 : this.params.unestimatedEffort);
      const bias = step2.agent ? this.params.agentBias : this.params.humanBias;
      const luck = lognormal(rng(seedOf(this.params.seed, step2.id)), this.params.noise);
      const effort = days * bias * luck;
      this.effort.set(step2.id, effort);
      return effort;
    }
    tails() {
      const plan = {
        ...this.plan,
        steps: this.steps
      };
      const calendar2 = stretched(daysFor, efficiencyOf(plan));
      const found = /* @__PURE__ */ new Map();
      for (const [, members] of groups(plan)) {
        for (const [id, tail] of chainTails(members, calendar2)) found.set(id, tail);
      }
      return found;
    }
    currentStretch() {
      return groups({
        ...this.plan,
        steps: this.steps
      }).find(([, members]) => members.some((step2) => !isDelay(step2) && step2.status !== DONE));
    }
    release(id) {
      this.humans = this.humans.map((held) => held === id ? null : held);
      this.agents = this.agents.map((held) => held === id ? null : held);
    }
    work(day) {
      const plan = {
        ...this.plan,
        steps: this.steps
      };
      const stretches = groups(plan);
      const stretchOf = /* @__PURE__ */ new Map();
      stretches.forEach(([, members], index) => members.forEach((step2) => stretchOf.set(step2.id, index)));
      const opens = stretches.map(([milestone]) => milestone?.start ?? null);
      const tails = this.tails();
      const order = new Map(this.steps.map((step2, index) => [
        step2.id,
        index
      ]));
      const done = (id) => this.find(id).status === DONE || this.over.has(id);
      const known = new Set(this.steps.map((step2) => step2.id));
      const current = () => stretches.findIndex(([, members]) => members.some((step2) => !isDelay(step2) && !done(step2.id)));
      const base = workingDaysBetween(this.begin, day) - 1;
      const running = () => new Set([
        ...this.humans,
        ...this.agents
      ].filter((id) => id !== null));
      const focus2 = this.params.focus ?? efficiencyOf(plan);
      const eligible = (agent) => {
        const busy = running();
        const now = current();
        if (now < 0) return void 0;
        return this.steps.filter((step2) => {
          const stretch = stretchOf.get(step2.id);
          return !isDelay(step2) && step2.agent === agent && step2.status !== DONE && step2.status !== "blocked" && !busy.has(step2.id) && (this.params.workAhead || stretch === now) && (opens[stretch] === null || opens[stretch] <= day) && step2.requires.every((id) => !known.has(id) || done(id));
        }).sort((a, b) => stretchOf.get(a.id) - stretchOf.get(b.id) || tails.get(b.id) - tails.get(a.id) || order.get(a.id) - order.get(b.id))[0];
      };
      const land = (id) => {
        this.release(id);
        this.finished.set(id, day);
        const step2 = this.update(id, {
          status: DONE
        });
        this.events.push(`${stepKey(step2)} ${step2.title} done`);
      };
      const waitFor = (now) => {
        let ended = false;
        const stretch = current();
        for (const step2 of this.steps) {
          if (!step2.delay || this.over.has(step2.id)) continue;
          if (!this.waits.has(step2.id)) {
            const mine = stretchOf.get(step2.id);
            if (mine === void 0 || !this.params.workAhead && mine !== stretch) continue;
            if (!step2.requires.every((id) => !known.has(id) || done(id))) continue;
            const delay = step2.delay;
            const opens2 = "days" in delay ? now + delay.days : workingDaysBetween(this.begin, nextWorkingDay(delay.until)) - 1;
            this.waits.set(step2.id, opens2);
          }
          if (this.waits.get(step2.id) <= now + EPSILON) {
            this.over.add(step2.id);
            this.finished.set(step2.id, day);
            ended = true;
          }
        }
        return ended;
      };
      let time = 0;
      const assign = () => {
        for (; ; ) {
          let moved = waitFor(base + time);
          for (const [lane, agent] of [
            [
              this.agents,
              true
            ],
            [
              this.humans,
              false
            ]
          ]) {
            for (let slot = 0; slot < lane.length; slot += 1) {
              if (lane[slot] !== null) continue;
              const step2 = eligible(agent);
              if (!step2) break;
              moved = true;
              if (step2.status === "pending") this.update(step2.id, {
                status: "in-progress"
              });
              if (this.effortOf(step2) - (this.progress.get(step2.id) ?? 0) <= EPSILON) land(step2.id);
              else lane[slot] = step2.id;
            }
          }
          if (!moved) return;
        }
      };
      for (let guard = 0; guard < 1e4; guard += 1) {
        assign();
        const busyAgents = this.agents.filter((id) => id !== null).length;
        const human = Math.max(0.05, focus2 - this.params.agentLoad * busyAgents / Math.max(1, this.humans.length));
        const busy = [
          ...this.agents.filter((id) => id !== null).map((id) => [
            id,
            1
          ]),
          ...this.humans.filter((id) => id !== null).map((id) => [
            id,
            human
          ])
        ];
        const ending = [
          ...this.waits
        ].filter(([id]) => !this.over.has(id)).map(([, end]) => end - base - time).filter((left) => left > EPSILON && left <= 1 - time + EPSILON);
        if (!busy.length && !ending.length || time >= 1 - EPSILON) return;
        const step2 = Math.min(1 - time, ...ending, ...busy.map(([id, rate]) => (this.effortOf(this.find(id)) - (this.progress.get(id) ?? 0)) / rate));
        for (const [id, rate] of busy) {
          this.progress.set(id, (this.progress.get(id) ?? 0) + rate * step2);
        }
        time += step2;
        for (const [id] of busy) {
          if (this.effortOf(this.find(id)) - this.progress.get(id) <= EPSILON) land(id);
        }
      }
    }
    find(id) {
      return this.steps.find((step2) => step2.id === id);
    }
  };
  function resized(lane, size) {
    const kept = [
      ...lane
    ];
    while (kept.length > size) {
      const free = kept.indexOf(null);
      kept.splice(free >= 0 ? free : kept.length - 1, 1);
    }
    while (kept.length < size) kept.push(null);
    return kept;
  }

  // src/ui/markup.ts
  var INK = "var(--ink)";
  var SECONDARY = "var(--secondary)";
  var SURFACE = "var(--surface)";
  var PLAN = "#5f87d7";
  var GOOD = "#78c88c";
  var BAD = "#dc6e6e";
  var ATTENTION = "#dcaa5a";
  var ESCAPES = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;"
  };
  function esc(text2) {
    return text2.replace(/[&<>"]/g, (char) => ESCAPES[char]);
  }
  function n(value) {
    return String(Math.round(value * 10) / 10);
  }
  function clip(text2, room) {
    return text2.length <= room ? text2 : text2.slice(0, room - 1).trimEnd() + "\u2026";
  }
  function textWidth(text2, font = 11) {
    return text2.length * font * 0.56;
  }
  function h(tag, props = {}, ...children) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === void 0 || value === null || value === false) continue;
      if (key.startsWith("on") && typeof value === "function") {
        element.addEventListener(key.slice(2), value);
      } else if (key === "html") {
        element.innerHTML = String(value);
      } else if (key in element && key !== "list" && typeof value !== "string") {
        element[key] = value;
      } else {
        element.setAttribute(key, value === true ? "" : String(value));
      }
    }
    for (const child of children) {
      if (child === null || child === void 0 || child === false) continue;
      element.append(child);
    }
    return element;
  }

  // src/ui/v1/charts.ts
  var PAGES = [
    {
      page: "shift",
      label: "Milestone shifts"
    },
    {
      page: "progress",
      label: "Progress"
    },
    {
      page: "volume",
      label: "Volume"
    },
    {
      page: "all",
      label: "All"
    }
  ];
  var PAGE_PLOTS = {
    shift: [
      "shift"
    ],
    progress: [
      "status",
      "scope"
    ],
    volume: [
      "volume",
      "remaining"
    ],
    all: [
      "status",
      "scope",
      "shift",
      "volume",
      "remaining"
    ]
  };
  var PLOT_H = 120;
  var SHIFT_ROW_H = 26;
  var TITLE_H = 18;
  var PLOT_GAP = 22;
  var CHART_TOP = 6;
  var CHART_BOTTOM = 26;
  var GUTTER_MIN = 46;
  var GUTTER_MAX = 150;
  var GUTTER_PAD = 12;
  var CHART_RIGHT = 16;
  var TICK_ROOM = 64;
  var PAD_DAYS = 1;
  var LINE_W = 2;
  var MARKER = 4;
  var LANDING_MARK = 3.5;
  var ARROW_HEAD = 5;
  var FADE = 0.3;
  var bottom = (panel) => panel.top + panel.height;
  function milestones(data) {
    return data.segments.filter((segment) => segment.key);
  }
  function extent(data) {
    const days = [
      data.today,
      ...data.expected.map(([d]) => d),
      ...data.actual.map(([d]) => d)
    ];
    days.push(...data.baseline.map(([d]) => d), ...data.volume.map(([d]) => d), ...data.remaining.map(([d]) => d));
    days.push(...data.marks.map(([d]) => d));
    for (const when of [
      data.finish,
      data.baselineFinish
    ]) if (when !== null) days.push(when);
    for (const segment of data.segments) {
      for (const span of [
        segment.now,
        segment.then
      ]) if (span) days.push(span[0], span[1]);
    }
    const [first, last] = [
      Math.min(...days) - PAD_DAYS,
      Math.max(...days) + PAD_DAYS
    ];
    return [
      first,
      last > first ? last : first + 1
    ];
  }
  function geometry(data, page, width) {
    const rows = milestones(data).length;
    const scale = volumeScale(data.volume, data.remaining);
    const panels = [];
    let cursor = CHART_TOP + TITLE_H;
    for (const kind of PAGE_PLOTS[page]) {
      const height = kind === "shift" ? Math.max(1, rows) * SHIFT_ROW_H : PLOT_H;
      panels.push({
        kind,
        top: cursor,
        height,
        scale: kind === "volume" || kind === "remaining" ? scale : 1
      });
      cursor += height + PLOT_GAP + TITLE_H;
    }
    const widest = Math.max(0, ...milestones(data).map((segment) => textWidth(clip(segment.label, 20))));
    const left = Math.min(GUTTER_MAX, Math.max(GUTTER_MIN, widest + GUTTER_PAD));
    const right = width - CHART_RIGHT;
    const [first, last] = extent(data);
    const span = last - first;
    return {
      first,
      last,
      left,
      right,
      panels,
      x: (day) => left + (day - first) / span * (right - left),
      y: (panel, value) => panel.top + (1 - Math.max(0, Math.min(1, panel.scale ? value / panel.scale : 0))) * panel.height,
      day: (x) => Math.round(first + (x - left) / (right - left) * span)
    };
  }
  function chartHeight(g2) {
    return bottom(g2.panels[g2.panels.length - 1]) + CHART_BOTTOM;
  }
  function chartSvg(data, page, width, id) {
    const g2 = geometry(data, page, width);
    const height = chartHeight(g2);
    const ticks2 = axisTicks(g2.first, g2.last, Math.floor((g2.right - g2.left) / TICK_ROOM));
    const out = [
      `<svg class="chart" viewBox="0 0 ${n(width)} ${n(height)}" width="${n(width)}" height="${n(height)}" font-size="11">`
    ];
    const emphasised = data.segments.find((segment) => segment.key && segment.key === data.emphasis) ?? null;
    for (const [index, panel] of g2.panels.entries()) {
      out.push(`<g class="plot plot-${panel.kind}">`, title(data, panel, g2), grid(data, panel, g2, ticks2));
      const body2 = panel.kind === "status" ? statusPlot(data, panel, g2) : panel.kind === "scope" ? scopePlot(data, panel, g2) : panel.kind === "shift" ? shiftPlot(data, panel, g2, emphasised) : amountPlot(data, panel, g2);
      if (emphasised && (panel.kind === "status" || panel.kind === "scope")) {
        const spans = [
          emphasised.now,
          ...panel.kind === "scope" ? [
            emphasised.then
          ] : []
        ].filter((span) => span !== null);
        const clipId = `${id}-clip-${index}`;
        out.push(`<defs><clipPath id="${clipId}">`);
        for (const [from, to] of spans) {
          out.push(`<rect x="${n(g2.x(from) - 2)}" y="${n(panel.top - 20)}" width="${n(g2.x(to) - g2.x(from) + 4)}" height="${n(panel.height + 40)}"/>`);
        }
        out.push(`</clipPath></defs>`);
        out.push(`<g opacity="${FADE}">${body2}</g><g clip-path="url(#${clipId})">${body2}</g>`);
      } else {
        out.push(body2);
      }
      out.push(`</g>`);
    }
    const [top, end] = [
      g2.panels[0].top,
      bottom(g2.panels[g2.panels.length - 1])
    ];
    for (const [when, name] of data.marks) {
      if (when < g2.first || when > g2.last) continue;
      const at = g2.x(when);
      const room = g2.right - at > textWidth(clip(name, 18)) + 8;
      out.push(`<g class="mark"><line x1="${n(at)}" x2="${n(at)}" y1="${n(top)}" y2="${n(end)}" style="stroke:${INK}" stroke-opacity="0.45" stroke-dasharray="4 3"/><text x="${n(room ? at + 4 : at - 4)}" y="${n(top + 10)}" text-anchor="${room ? "start" : "end"}" style="fill:${SECONDARY}">${esc(clip(name, 18))}</text><title>saved as ${esc(name)}</title></g>`);
    }
    if (emphasised?.now) {
      const at = g2.x(emphasised.now[1]);
      out.push(`<line x1="${n(at)}" x2="${n(at)}" y1="${n(top)}" y2="${n(end)}" stroke="${emphasised.color}" stroke-opacity="0.6"/>`);
    }
    if (data.today >= g2.first && data.today <= g2.last) {
      const at = g2.x(data.today);
      out.push(`<line class="today" x1="${n(at)}" x2="${n(at)}" y1="${n(top)}" y2="${n(end)}" style="stroke:${SECONDARY}"/>`);
    }
    for (const [when, label2] of ticks2) {
      out.push(`<text class="axis" x="${n(g2.x(when))}" y="${n(end + 15)}" text-anchor="middle" style="fill:${SECONDARY}">${esc(label2)}</text>`);
    }
    out.push(`<line class="hover" x1="0" x2="0" y1="${n(top)}" y2="${n(end)}" style="stroke:${INK}" stroke-opacity="0.5" visibility="hidden"/>`);
    out.push("</svg>");
    return {
      svg: out.join(""),
      geometry: g2
    };
  }
  function title(data, panel, g2) {
    const y = panel.top - TITLE_H / 2;
    const name = panel.kind === "status" ? data.asOf ? `Progress \u2014 as of ${data.asOf}` : "Progress" : panel.kind === "scope" ? scopeWords(data.basis) : panel.kind === "shift" ? "Milestones" : panel.kind === "volume" ? "Scope volume" : "Remaining work";
    const out = [
      `<text class="plot-title" x="${n(g2.left)}" y="${n(y)}" dominant-baseline="central" font-size="12" font-weight="600" style="fill:${INK}">${esc(name)}</text>`
    ];
    const keys = legend(data, panel);
    const width = keys.reduce((sum, [label2]) => sum + 24 + textWidth(label2) + 18, 0);
    if (keys.length && width <= g2.right - g2.left - textWidth(name, 12) - 24) {
      let cursor = g2.right - width + 18;
      for (const [label2, mark] of keys) {
        out.push(`<g class="legend">${mark(cursor, y)}<text x="${n(cursor + 24)}" y="${n(y)}" dominant-baseline="central" style="fill:${SECONDARY}">${esc(label2)}</text></g>`);
        cursor += 24 + textWidth(label2) + 18;
      }
    }
    return out.join("");
  }
  function legend(data, panel) {
    const line = (color, opacity = 1, dash = "") => (x, y) => `<line x1="${n(x)}" x2="${n(x + 18)}" y1="${n(y)}" y2="${n(y)}" style="stroke:${color}" stroke-opacity="${opacity}" stroke-width="2"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`;
    const patch = (color) => (x, y) => `<rect x="${n(x)}" y="${n(y - 5)}" width="18" height="10" rx="2" fill="${color}" fill-opacity="0.3"/>`;
    const dot = (fill, ring) => (x, y) => `<circle cx="${n(x + 9)}" cy="${n(y)}" r="4" style="fill:${fill};stroke:${ring}" stroke-width="1.5"/>`;
    if (panel.kind === "status") {
      return [
        [
          "Plan",
          line(PLAN)
        ],
        [
          "Actual",
          line(INK)
        ],
        ...data.idle.length ? [
          [
            "No work planned",
            line(PLAN, 1, "0.1 4")
          ]
        ] : []
      ];
    }
    if (panel.kind === "scope") {
      return [
        ...data.baseline.length ? [
          [
            "Plan then",
            line(PLAN, 0.6, "6 4")
          ]
        ] : [],
        [
          "Plan now",
          line(PLAN)
        ],
        [
          "Pulled in",
          patch(ATTENTION)
        ],
        [
          "Slipped",
          patch(BAD)
        ]
      ];
    }
    if (panel.kind === "shift") {
      const compared2 = data.segments.some((segment) => segment.then !== null);
      return compared2 ? [
        [
          "Then",
          dot(SURFACE, SECONDARY)
        ],
        [
          "Now",
          dot(SECONDARY, SECONDARY)
        ]
      ] : [];
    }
    if (panel.kind === "volume") return [
      [
        "Estimated days",
        line(PLAN)
      ]
    ];
    return [
      [
        "Total",
        line(PLAN, 0.55, "6 4")
      ],
      [
        "Remaining",
        line(PLAN)
      ]
    ];
  }
  function grid(data, panel, g2, ticks2) {
    const out = [];
    if (panel.kind === "shift") {
      const rows = milestones(data);
      if (!rows.length) {
        out.push(`<text x="${n(g2.left)}" y="${n(panel.top + SHIFT_ROW_H / 2)}" dominant-baseline="central" style="fill:${SECONDARY}">No milestones yet</text>`);
      }
      rows.forEach((_, index) => {
        const row = panel.top + (index + 0.5) * SHIFT_ROW_H;
        out.push(`<line x1="${n(g2.left)}" x2="${n(g2.right)}" y1="${n(row)}" y2="${n(row)}" style="stroke:${INK}" stroke-opacity="0.1"/>`);
      });
    } else {
      for (const share of [
        0,
        0.25,
        0.5,
        0.75,
        1
      ]) {
        const at = g2.y(panel, share * panel.scale);
        out.push(`<line x1="${n(g2.left)}" x2="${n(g2.right)}" y1="${n(at)}" y2="${n(at)}" style="stroke:${INK}" stroke-opacity="0.12"/>`);
        if (share === 0 || share === 0.5 || share === 1) {
          const label2 = panel.scale === 1 ? percent(share) : formatDays(share * panel.scale);
          out.push(`<text x="${n(g2.left - 8)}" y="${n(at)}" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${label2}</text>`);
        }
      }
    }
    for (const [when] of ticks2) {
      out.push(`<line x1="${n(g2.x(when))}" x2="${n(g2.x(when))}" y1="${n(panel.top)}" y2="${n(bottom(panel))}" style="stroke:${INK}" stroke-opacity="0.12"/>`);
    }
    return out.join("");
  }
  function polyline(points, panel, g2, color, extra = "") {
    const coords = points.map(([when, value]) => `${n(g2.x(when))},${n(g2.y(panel, value))}`).join(" ");
    return `<polyline points="${coords}" fill="none" style="stroke:${color}" stroke-width="${LINE_W}" stroke-linejoin="round" stroke-linecap="round"${extra}/>`;
  }
  function marker(x, y, fill, ring) {
    return `<circle cx="${n(x)}" cy="${n(y)}" r="${MARKER}" style="fill:${fill};stroke:${ring}" stroke-width="2"/>`;
  }
  function slice(points, since, until2) {
    if (until2 <= since) return [];
    const cut = points.filter(([when]) => since < when && when < until2);
    const [head, tail] = [
      shareAt(points, since),
      shareAt(points, until2)
    ];
    if (head !== null) cut.unshift([
      since,
      head
    ]);
    if (tail !== null) cut.push([
      until2,
      tail
    ]);
    return cut;
  }
  function planLine(data, points, panel, g2) {
    const runs = data.segments.filter((segment) => segment.now !== null);
    if (!runs.length) return polyline(points, panel, g2, PLAN);
    const out = [];
    let previous = null;
    for (const segment of runs) {
      const [start2, finish] = segment.now;
      const cut = slice(points, previous ?? start2, finish);
      if (cut.length >= 2) out.push(polyline(cut, panel, g2, segment.color));
      previous = finish;
    }
    for (const [since, until2] of data.idle) {
      const level = shareAt(points, since);
      if (level === null) continue;
      const y = g2.y(panel, level);
      out.push(`<line x1="${n(g2.x(since))}" x2="${n(g2.x(until2))}" y1="${n(y)}" y2="${n(y)}" style="stroke:${SURFACE}" stroke-width="${LINE_W + 1}"/><line x1="${n(g2.x(since))}" x2="${n(g2.x(until2))}" y1="${n(y)}" y2="${n(y)}" style="stroke:${PLAN}" stroke-width="${LINE_W}" stroke-dasharray="0.1 4" stroke-linecap="round"/>`);
    }
    return out.join("");
  }
  function statusPlot(data, panel, g2) {
    const out = [];
    if (data.expected.length) {
      out.push(planLine(data, data.expected, panel, g2));
      let reached = -Infinity;
      for (const segment of milestones(data)) {
        const share2 = segment.now ? shareAt(data.expected, segment.now[1]) : null;
        if (!segment.now || share2 === null) continue;
        const [at, level] = [
          g2.x(segment.now[1]),
          g2.y(panel, share2)
        ];
        out.push(`<circle cx="${n(at)}" cy="${n(level)}" r="${LANDING_MARK}" fill="${segment.color}"/>`);
        const name = clip(segment.label, 16);
        if (at - textWidth(name) - 6 < reached) continue;
        out.push(`<text x="${n(at - 6)}" y="${n(Math.max(panel.top + 6, level - 12))}" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${esc(name)}</text>`);
        reached = at - 6;
      }
      const [when, share] = data.expected[data.expected.length - 1];
      const last = data.segments.filter((segment) => segment.now).pop()?.color ?? PLAN;
      out.push(marker(g2.x(when), g2.y(panel, share), last, SURFACE));
    }
    if (data.actual.length) {
      out.push(polyline(data.actual, panel, g2, INK));
      const [when, share] = data.actual[data.actual.length - 1];
      out.push(marker(g2.x(when), g2.y(panel, share), INK, SURFACE));
      const words2 = standingWords(data.standing);
      if (words2) {
        const flipped = g2.x(when) + 8 + textWidth(words2) > g2.right;
        out.push(`<text class="standing" x="${n(g2.x(when) + (flipped ? -8 : 8))}" y="${n(g2.y(panel, share))}" dominant-baseline="central" text-anchor="${flipped ? "end" : "start"}" style="fill:${INK}" font-weight="600">${esc(words2)}</text>`);
      }
    }
    return out.join("");
  }
  function scopePlot(data, panel, g2) {
    const out = [];
    if (data.expected.length && data.baseline.length) {
      for (const [sign, run2] of changeRuns(data.expected, data.baseline)) {
        if (sign === 0) {
          const line = run2.map(([when, high]) => `${n(g2.x(when))},${n(g2.y(panel, high))}`).join(" ");
          out.push(`<polyline points="${line}" fill="none" stroke="${GOOD}" stroke-width="${LINE_W + 1}" stroke-opacity="0.8" stroke-linecap="round"/>`);
          continue;
        }
        const ring = [
          ...run2.map(([when, high]) => `${n(g2.x(when))},${n(g2.y(panel, high))}`),
          ...[
            ...run2
          ].reverse().map(([when, , low]) => `${n(g2.x(when))},${n(g2.y(panel, low))}`)
        ];
        out.push(`<polygon points="${ring.join(" ")}" fill="${sign > 0 ? ATTENTION : BAD}" fill-opacity="0.25"/>`);
      }
    }
    if (data.expected.length) {
      out.push(planLine(data, data.expected, panel, g2));
      const [when, share] = data.expected[data.expected.length - 1];
      out.push(marker(g2.x(when), g2.y(panel, share), PLAN, SURFACE));
    }
    if (data.baseline.length) {
      out.push(polyline(data.baseline, panel, g2, "#3f5f9f", ` stroke-dasharray="6 4" stroke-opacity="0.75"`));
      const [when, share] = data.baseline[data.baseline.length - 1];
      out.push(marker(g2.x(when), g2.y(panel, share), SURFACE, PLAN));
    }
    return out.join("");
  }
  function shiftPlot(data, panel, g2, emphasised) {
    const out = [];
    milestones(data).forEach((segment, index) => {
      const row = panel.top + (index + 0.5) * SHIFT_ROW_H;
      const faded = emphasised && emphasised !== segment ? ` opacity="${FADE}"` : "";
      out.push(`<g class="shift"${faded}><title>${esc(segment.words)}</title>`);
      const [then, now] = [
        segment.then?.[1] ?? null,
        segment.now?.[1] ?? null
      ];
      if (now !== null) {
        out.push(`<line x1="${n(g2.x(now))}" x2="${n(g2.x(now))}" y1="${n(row)}" y2="${n(bottom(panel))}" stroke="${segment.color}" stroke-opacity="0.35"/>`);
      }
      out.push(`<text x="${n(g2.left - 8)}" y="${n(row)}" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${esc(clip(segment.label, 20))}</text>`);
      if (then !== null && now !== null && then !== now) {
        out.push(arrow(g2.x(then), g2.x(now), row, segment.color));
      }
      if (then !== null) {
        out.push(`<circle cx="${n(g2.x(then))}" cy="${n(row)}" r="${MARKER + (then === now ? 1.5 : 0)}" style="fill:${SURFACE}" stroke="${segment.color}" stroke-width="1.5"/>`);
      }
      if (now !== null) {
        out.push(`<circle cx="${n(g2.x(now))}" cy="${n(row)}" r="${LANDING_MARK}" fill="${segment.color}"/>`);
      }
      for (const [text2, at] of rowDates(then, now, data.today, g2)) {
        out.push(`<text x="${n(at)}" y="${n(row)}" dominant-baseline="central" style="fill:${SECONDARY}">${esc(text2)}</text>`);
      }
      out.push(`</g>`);
    });
    return out.join("");
  }
  function rowDates(then, now, today, g2) {
    const found = [];
    const spots = now !== null ? [
      [
        now,
        then
      ]
    ] : [];
    if (then !== null && then !== now) spots.push([
      then,
      now
    ]);
    for (const [when, other] of spots) {
      const text2 = shortDate(when, today);
      const width = textWidth(text2);
      const mark = g2.x(when);
      const away = other !== null && g2.x(other) > mark ? -1 : 1;
      for (const way of [
        away,
        -away
      ]) {
        const start2 = way > 0 ? mark + LANDING_MARK + 5 : mark - LANDING_MARK - 5 - width;
        if (start2 < g2.left || start2 + width > g2.right) continue;
        if (other !== null) {
          const keep = g2.x(other);
          if (start2 < keep + LANDING_MARK + 5 && keep - LANDING_MARK - 5 < start2 + width) continue;
        }
        found.push([
          text2,
          start2
        ]);
        break;
      }
    }
    return found;
  }
  function arrow(start2, end, row, color) {
    const way = end >= start2 ? 1 : -1;
    const tip = end - way * (LANDING_MARK + 1);
    const head = `M${n(tip)},${n(row)} L${n(tip - way * ARROW_HEAD)},${n(row - ARROW_HEAD * 0.55)} L${n(tip - way * ARROW_HEAD)},${n(row + ARROW_HEAD * 0.55)} Z`;
    return `<line x1="${n(start2)}" x2="${n(tip)}" y1="${n(row)}" y2="${n(row)}" stroke="${color}" stroke-width="1.5" stroke-opacity="0.8"/><path d="${head}" fill="${color}" fill-opacity="0.8"/>`;
  }
  function amountPlot(data, panel, g2) {
    const out = [];
    const own = panel.kind === "volume" ? data.volume : data.remaining;
    if (panel.kind === "remaining" && data.volume.length) {
      out.push(polyline(data.volume, panel, g2, PLAN, ` stroke-dasharray="6 4" stroke-opacity="0.55"`));
    }
    if (own.length) {
      out.push(polyline(own, panel, g2, PLAN));
      const [when, value] = own[own.length - 1];
      out.push(marker(g2.x(when), g2.y(panel, value), PLAN, SURFACE));
    }
    return out.join("");
  }
  function readout(data, kind, day) {
    const at = (points) => shareAt(points, day);
    const share = (label2, value) => value === null ? [] : [
      `${label2}: ${percent(value)} of days`
    ];
    const days = (label2, value) => value === null ? [] : [
      `${label2}: ${formatDays(value)}`
    ];
    const saved = data.marks.filter(([when]) => when === day).map(([, name]) => `saved as ${name}`);
    if (kind === "status") {
      return [
        ...share("plan now", at(data.expected)),
        ...share("actual", at(data.actual)),
        ...saved
      ];
    }
    if (kind === "scope") {
      return [
        ...share("plan now", at(data.expected)),
        ...share(data.basis || "then", at(data.baseline)),
        ...saved
      ];
    }
    if (kind === "shift") {
      return [
        ...data.segments.filter((s) => s.key).map((s) => s.words),
        ...saved
      ];
    }
    const total = at(data.volume);
    const left = at(data.remaining);
    return [
      ...days("scope", total),
      ...left !== null && total !== null ? [
        `remaining: ${formatDays(left)} \xB7 done ${formatDays(total - left)}`
      ] : [],
      ...saved
    ];
  }

  // src/ui/figures.ts
  var MONDAY = fromYMD(2026, 9, 7);
  var TODAY = MONDAY + 4;
  function step(id, number, title3, estimate, requires, milestone = null) {
    return {
      id,
      number,
      title: title3,
      requires,
      estimate: milestone ? null : estimate,
      estimateOff: milestone !== null,
      estimateHistory: [],
      status: "pending",
      milestone,
      agent: false,
      created: MONDAY - 3,
      start: null,
      color: null,
      since: null,
      started: null,
      delay: null
    };
  }
  function planOn(day) {
    const steps = [
      step("design", 1, "Design", 1, []),
      step("build", 2, "Build", 2, [
        "design"
      ]),
      step("v1", 3, "Release 1", 0, [
        "build"
      ], "v1"),
      step("polish", 4, "Polish", 3, [
        "v1"
      ]),
      step("docs", 5, "Docs", 2, [
        "v1"
      ]),
      step("v2", 6, "Release 2", 0, [
        "polish",
        "docs"
      ], "v2")
    ];
    if (day >= MONDAY + 3) {
      steps.splice(5, 0, {
        ...step("import", 7, "Fix the import", 2, [
          "v1"
        ]),
        created: MONDAY + 3
      });
      steps[6] = {
        ...steps[6],
        requires: [
          ...steps[6].requires,
          "import"
        ]
      };
    }
    const done = {
      design: MONDAY,
      build: MONDAY + 2,
      v1: MONDAY + 2
    };
    const status = (one) => done[one.id] !== void 0 && done[one.id] <= day ? "done" : one.id === "polish" && day >= MONDAY + 3 ? "in-progress" : "pending";
    return {
      id: "example",
      title: "Example",
      start: MONDAY,
      assumptions: {
        efficiency: 1,
        palette: "viridis",
        team: [
          1,
          1
        ]
      },
      steps: steps.map((one) => ({
        ...one,
        status: status(one)
      }))
    };
  }
  function example() {
    const days = [
      MONDAY,
      MONDAY + 1,
      MONDAY + 2,
      MONDAY + 3,
      TODAY
    ];
    const timeline3 = {
      title: "Example",
      frames: days.map((day) => ({
        day,
        plan: planOn(day),
        events: []
      })),
      begin: MONDAY,
      finished: /* @__PURE__ */ new Map(),
      kind: "scenario"
    };
    const recorded2 = record({
      ...timeline3,
      frames: timeline3.frames.filter((frame) => frame.day !== MONDAY + 1)
    }, {
      options: FAITHFUL,
      cadence: "daily",
      saved: [
        {
          day: MONDAY,
          title: "Kickoff review",
          note: ""
        }
      ],
      seed: 1
    });
    const upToToday = recordedBy(recorded2, TODAY);
    return {
      timeline: timeline3,
      view: (then, now = LIVE) => present(planOn(TODAY), TODAY, upToToday, {
        picked: null,
        then,
        now,
        lens: "calendar",
        page: "progress",
        whatIf: {}
      }, FAITHFUL)
    };
  }
  function chart(view, page, holder) {
    const width = Math.max(480, Math.min(780, holder.clientWidth - 24));
    holder.innerHTML = chartSvg(view.chart, page, width, `figure-${page}`).svg;
  }
  function picksSvg(rows, saved, live) {
    const [width, left, right, top, row] = [
      940,
      250,
      580,
      34,
      30
    ];
    const first = MONDAY - 4;
    const x = (day) => left + (day - first) / (TODAY - first) * (right - left);
    const picks = [
      [
        "Plan at start",
        AT_START,
        MONDAY
      ],
      [
        "Day\u2026 8 September",
        {
          kind: "day",
          day: MONDAY + 1
        },
        MONDAY + 1
      ],
      [
        "Plan at start, if the start were 3 Sep",
        AT_START,
        MONDAY - 4
      ],
      [
        "Kickoff review",
        {
          kind: "saved",
          title: "Kickoff review"
        },
        MONDAY
      ],
      [
        "Now",
        LIVE,
        TODAY
      ]
    ];
    const height = top + picks.length * row + 36;
    const out = [
      `<svg class="chart" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" font-size="12">`
    ];
    for (let day = first; day <= TODAY; day += 1) {
      out.push(`<text x="${n(x(day))}" y="12" text-anchor="middle" style="fill:${SECONDARY}">${weekdayName(day).slice(0, 2)} ${shortDate(day, TODAY).split(" ")[0]}</text>`);
      const has2 = rows.some((one) => one.day === day) || day === TODAY;
      out.push(`<circle cx="${n(x(day))}" cy="24" r="${has2 ? 5 : 3}" style="fill:${has2 ? INK : "none"};stroke:${SECONDARY}"><title>${has2 ? day === TODAY ? "today: the live plan" : "a record" : "no record"}</title></circle>`);
    }
    picks.forEach(([label2, pick, asked], index) => {
      const y = top + (index + 1) * row;
      const found = resolve(pick, rows, saved, live, pick.kind === "start" ? asked : MONDAY);
      const words2 = pickWords(pick, found, TODAY) || "nothing to compare with";
      out.push(`<text x="0" y="${y}" dominant-baseline="central" style="fill:${INK}">${esc(label2)}</text>`);
      out.push(`<circle cx="${n(x(asked))}" cy="${y}" r="3" style="fill:none;stroke:${INK}"/>`);
      if (found) {
        out.push(`<line x1="${n(x(asked))}" x2="${n(x(found.day))}" y1="${y}" y2="${y}" style="stroke:${INK}" stroke-width="1.5"/>`);
        out.push(`<circle cx="${n(x(found.day))}" cy="${y}" r="5" style="fill:${INK}"/>`);
      }
      out.push(`<text x="${right + 24}" y="${y}" dominant-baseline="central" style="fill:${SECONDARY}">${esc(`\u2192 ${words2}`)}</text>`);
    });
    out.push(`<text x="${left}" y="${height - 6}" style="fill:${SECONDARY}">\u25CB the day asked for \xB7 \u25CF the record that answers \xB7 Tuesday has no record: the window was closed</text>`);
    out.push("</svg>");
    return out.join("");
  }
  function recordTable(row, plan) {
    const label2 = (key) => plan.steps.find((one) => one.id === key)?.milestone ?? "after the last milestone";
    return h("table", {}, h("thead", {}, h("tr", {}, ...[
      "Stretch",
      "Steps",
      "Done",
      "Days",
      "Done days",
      "Starts",
      "Lands",
      "What lands when"
    ].map((name) => h("th", {}, name)))), h("tbody", {}, ...row.stretches.map((stretch) => h("tr", {}, h("td", {}, label2(stretch.key)), h("td", {
      class: "number"
    }, String(stretch.tally.steps)), h("td", {
      class: "number"
    }, String(stretch.tally.done)), h("td", {
      class: "number"
    }, `${g(stretch.tally.days)}d`), h("td", {
      class: "number"
    }, `${g(stretch.tally.doneDays)}d`), h("td", {}, shortDate(stretch.start, TODAY)), h("td", {}, stretch.finish !== null ? shortDate(stretch.finish, TODAY) : "\u2014"), h("td", {}, stretch.landings.map((knot) => `${shortDate(knot.day, TODAY)}: ${g(knot.days)}d`).join(" \xB7 "))))));
  }
  function doubledTable() {
    return h("table", {}, h("thead", {}, h("tr", {}, ...[
      "Day",
      "Estimated days in the plan",
      "Done",
      "Progress (share)",
      "Still to do"
    ].map((name) => h("th", {}, name)))), h("tbody", {}, h("tr", {}, h("td", {}, "Monday"), h("td", {
      class: "number"
    }, "10d"), h("td", {
      class: "number"
    }, "5d"), h("td", {
      class: "number"
    }, "50%"), h("td", {
      class: "number"
    }, "5d")), h("tr", {}, h("td", {}, "Tuesday, after 10 days of work were added"), h("td", {
      class: "number"
    }, "20d"), h("td", {
      class: "number"
    }, "10d"), h("td", {
      class: "number"
    }, "50%"), h("td", {
      class: "number"
    }, "10d"))));
  }
  function renderFigures() {
    const { timeline: timeline3, view } = example();
    const atStart = view(AT_START);
    const rows = atStart.recording.rows;
    const fill = (name, make) => {
      for (const holder of document.querySelectorAll(`[data-figure="${name}"]`)) {
        make(holder);
      }
    };
    fill("record", (holder) => {
      const thursday = rows.find((one) => one.day === MONDAY + 3);
      holder.replaceChildren(recordTable(thursday, timeline3.frames[3].plan));
    });
    fill("picks", (holder) => holder.innerHTML = picksSvg(rows, atStart.recording.saved, atStart.live));
    fill("progress", (holder) => chart(atStart, "progress", holder));
    fill("shift", (holder) => chart(atStart, "shift", holder));
    fill("volume", (holder) => chart(atStart, "volume", holder));
    fill("doubled", (holder) => holder.replaceChildren(doubledTable()));
    fill("words", (holder) => {
      const shifts = atStart.chart.segments.filter((one) => one.key).map((one) => one.words);
      holder.replaceChildren(h("ul", {}, h("li", {}, `Scope change heading: \u201C${atStart.chart.basis ? `Scope change \u2014 versus ${atStart.chart.basis}` : "nothing to compare with"}\u201D`), ...shifts.map((text2) => h("li", {}, text2))));
    });
    fill("recorded-days", (holder) => holder.textContent = rows.map((one) => `${weekdayName(one.day).slice(0, 3)} ${shortDate(one.day, TODAY)}`).join(", "));
  }

  // src/ui/debugger/records.ts
  function stretchText(row, key, today) {
    const stretch = row.stretches.find((one) => one.key === key);
    if (!stretch) return "";
    const { steps, done, days, doneDays } = stretch.tally;
    const finish = stretch.finish !== null ? shortDate(stretch.finish, today) : "undated";
    return `${done}/${steps} steps \xB7 ${formatDays(doneDays) || "0d"} of ${formatDays(days) || "0d"} \xB7 ${shortDate(stretch.start, today)} \u2192 ${finish}`;
  }
  function recordsView(timeline3, recording2, index, parity2) {
    const today = timeline3.frames[index].day;
    const plan = timeline3.frames[timeline3.frames.length - 1].plan;
    const keys = [
      ...placed(plan).map((place) => place.step).filter(isMilestone).map((step2) => [
        step2.id,
        milestoneLabel(step2)
      ])
    ];
    const rows = recording2.rows.filter((row) => row.day <= today);
    if (rows.some((row) => row.stretches.some((stretch) => !stretch.key))) {
      keys.push([
        "",
        "Remaining work"
      ]);
    }
    const byDay = new Map(rows.map((row) => [
      row.day,
      row
    ]));
    const table = h("table", {
      class: "records"
    }, h("thead", {}, h("tr", {}, h("th", {}, "Day"), h("th", {}, "What happened"), ...keys.map(([, label2]) => h("th", {}, label2)))));
    const body2 = h("tbody");
    for (const frame of timeline3.frames.slice(0, index + 1).reverse()) {
      const row = byDay.get(frame.day);
      const found = parity2?.find((one) => one.day === frame.day);
      body2.append(h("tr", {
        class: row ? "" : "absent"
      }, h("td", {
        class: "day"
      }, `${weekdayName(frame.day).slice(0, 3)} ${shortDate(frame.day, today)}`, found ? h("div", {
        class: `parity ${found.same ? "same" : "different"}`,
        title: found.differences.join("\n")
      }, found.same ? "= DPlanner's row" : "\u2260 DPlanner's row") : null), h("td", {
        class: "events"
      }, frame.events.join("; ") || ""), ...row ? keys.map(([key]) => h("td", {
        class: "cell"
      }, stretchText(row, key, today))) : [
        h("td", {
          colspan: keys.length || 1,
          class: "absent"
        }, "no row \u2014 the window was closed, or nothing had changed")
      ]));
    }
    table.append(body2);
    const latest = rows[rows.length - 1];
    return h("div", {
      class: "records-tab"
    }, h("p", {
      class: "lede"
    }, `${rows.length} automatic row${rows.length === 1 ? "" : "s"} and ${recording2.saved.filter((row) => row.day <= today).length} saved snapshot(s) by ${shortDate(today, today)}. `, "A row is written on a day the recorder ran and the plan it would record differs from the last one; the last write of a day wins.", parity2 ? ` Replay: ${parityWords(parity2)}.` : ""), savedList(recording2, today), table, latest ? h("details", {}, h("summary", {}, `The latest row as progress_history.json stores it (${isoDay(latest.day)})`), h("pre", {}, JSON.stringify(rowJson(latest), null, 2))) : null);
  }
  function savedList(recording2, today) {
    const saved = recording2.saved.filter((row) => row.day <= today);
    if (!saved.length) return null;
    return h("ul", {
      class: "saved"
    }, ...saved.map((row) => h("li", {}, h("b", {}, row.title), ` \xB7 ${shortDate(row.day, today)}`, row.note ? ` \u2014 ${row.note}` : "")));
  }

  // src/ui/v1/calendar.ts
  var SHOWN_AT_LEAST = 6;
  var SHOWN_AT_MOST = 12;
  function addMonths(day, count2) {
    const [year, month] = ymd(day);
    const total = year * 12 + (month - 1) + count2;
    return fromYMD(Math.floor(total / 12), total % 12 + 1, 1);
  }
  function monthSpan(start2, finish) {
    const begin = addMonths(start2, -1);
    const last = addMonths(finish ?? start2, 1);
    const [[y1, m1], [y2, m2]] = [
      ymd(begin),
      ymd(last)
    ];
    const count2 = (y2 - y1) * 12 + (m2 - m1) + 1;
    return [
      begin,
      Math.max(SHOWN_AT_LEAST, Math.min(SHOWN_AT_MOST, count2))
    ];
  }
  function tooltip(day, band, today, clickable) {
    let said = `${weekdayName(day)} ${formatDate(day, today)}`;
    if (!band) said += clickable ? " \u2014 click to start the work here" : "";
    else if (day === band.finish && band.lands) said += ` \u2014 ${band.label} lands`;
    else if (!isWorkingDay(day)) said += " \u2014 weekend, not counted";
    else {
      const worked = workingDaysBetween(band.start, day);
      const total = workingDaysBetween(band.start, band.finish);
      said += ` \u2014 ${band.label}${day === band.start ? " starts," : ","} working day ${worked} of ${total}`;
    }
    return day === today ? `${said} \xB7 today` : said;
  }
  function monthsView(view, emphasis, offset, { onDay, waits = [], months, named = false } = {}) {
    const today = view.now.day;
    const bands = view.now.stretches.filter((stretch) => stretch.finish !== null).map((stretch) => {
      const named2 = view.stretches.find((one) => one.key === stretch.key);
      return {
        key: stretch.key,
        label: named2?.label ?? stretch.key,
        start: stretch.start,
        finish: stretch.finish,
        color: named2?.color ?? "#888888",
        lands: stretch.key !== ""
      };
    });
    const [first, span] = monthSpan(view.report.start, landingIn(view.now, null));
    const count2 = months ?? span;
    const grid2 = h("div", {
      class: "months"
    });
    for (let index = 0; index < count2; index += 1) {
      const month = addMonths(first, index + offset);
      const [year, number] = ymd(month);
      const name = year === ymd(today)[0] ? MONTHS[number - 1] : `${MONTHS[number - 1].slice(0, 3)} '${String(year % 100).padStart(2, "0")}`;
      const days = h("div", {
        class: "days"
      });
      for (let blank = 0; blank < weekday(month); blank += 1) {
        days.append(h("span", {
          class: "day blank"
        }));
      }
      for (let day = month; ymd(day)[1] === number; day += 1) {
        const band = bands.find((one) => one.start <= day && day <= one.finish);
        const faded = emphasis !== null && band && band.key !== emphasis ? 0.4 : 1;
        const wait = waits.find((one) => one.from < day && day <= one.to);
        const cell = h(onDay ? "button" : "span", {
          class: `day${isWorkingDay(day) ? "" : " weekend"}${day === today ? " today" : ""}${wait ? " waiting" : ""}`,
          title: tooltip(day, band, today, Boolean(onDay)) + (wait ? ` \u2014 ${wait.title}` : ""),
          ...onDay ? {
            onclick: () => onDay(day)
          } : {}
        }, String(ymd(day)[2]));
        if (named && band?.lands && day === band.finish) {
          cell.append(h("span", {
            class: "day-name"
          }, band.label));
        }
        if (band) {
          const strength = day === band.finish && band.lands ? 220 : day === view.report.start ? 130 : isWorkingDay(day) ? 64 : 24;
          cell.style.backgroundColor = alpha(band.color, strength / 255 * faded);
          if (strength === 220) cell.classList.add("lands");
        }
        days.append(cell);
      }
      grid2.append(h("div", {
        class: "month"
      }, h("div", {
        class: "month-name"
      }, name), days));
    }
    return grid2;
  }

  // src/ui/v1/timetab.ts
  function timeTab(view, state, on) {
    if (view.report.cycle.length) {
      const names = view.report.cycle.map((step2) => step2.title || "an untitled step").join(", ");
      return h("div", {
        class: "time"
      }, toolbar(view, state, on), h("div", {
        class: "banner error"
      }, `\u25CF These steps wait on each other, so nothing can be dated: ${names}. Unlink one to time the plan.`));
    }
    const left = h("div", {
      class: "left"
    }, staffing(view, state.lens, (team2) => on.whatIf({
      team: team2
    })), milestoneTable(view, state, on));
    const right = h("div", {
      class: "right"
    }, banner(view), pager(on), monthsView(view, state.picked, on.offset, {
      onDay: (day) => on.whatIf({
        start: day
      })
    }), plots(view, state, on));
    return h("div", {
      class: "time"
    }, toolbar(view, state, on), h("div", {
      class: "split"
    }, left, right));
  }
  function toolbar(view, state, on) {
    const efficiency = Math.round((view.plan.assumptions.efficiency ?? DEFAULT_EFFICIENCY) * 100);
    const focus2 = h("select", {
      title: "Human focus: how much of a person's working day this project gets",
      onchange: (event) => on.whatIf({
        efficiency: Number(event.target.value) / 100
      })
    });
    for (let value = 10; value <= 100; value += 5) {
      focus2.append(h("option", {
        value: String(value),
        selected: value === efficiency
      }, `${value}% focus`));
    }
    const palette = h("select", {
      title: "Milestone colours: the project's map",
      onchange: (event) => on.whatIf({
        palette: event.target.value
      })
    });
    for (const found of PALETTES) {
      palette.append(h("option", {
        value: found.id,
        selected: found.id === paletteById(view.plan.assumptions.palette).id
      }, found.name));
    }
    const stops = paletteById(view.plan.assumptions.palette).stops;
    const swatch = h("span", {
      class: "swatch",
      style: `background: linear-gradient(90deg, ${stops.join(", ")})`
    });
    const lens = h("span", {
      class: "segmented"
    }, h("button", {
      class: state.lens === "calendar" ? "on" : "",
      onclick: () => on.view({
        lens: "calendar"
      })
    }, "Calendar days"), h("button", {
      class: state.lens === "project" ? "on" : "",
      onclick: () => on.view({
        lens: "project"
      })
    }, "Project days"));
    const whatIfs = describeWhatIf(state.whatIf, view);
    return h("div", {
      class: "strip"
    }, saveButton(view, on.save), h("span", {
      class: "divider"
    }), focus2, lens, swatch, palette, h("span", {
      class: "divider"
    }), h("span", {
      class: "label"
    }, "Compare"), picker(view, state.then, "then", (pick) => on.view({
      then: pick
    })), h("span", {
      class: "label"
    }, "with"), picker(view, state.now, "now", (pick) => on.view({
      now: pick
    })), whatIfs ? h("span", {
      class: "what-if",
      title: "These act on this day's live plan only; the recorded history keeps what was stored."
    }, `what-if: ${whatIfs}`, h("button", {
      class: "link",
      onclick: () => on.whatIf(null)
    }, "reset")) : null);
  }
  function describeWhatIf(whatIf3, view) {
    const parts = [];
    if (whatIf3.efficiency !== void 0) parts.push(`focus ${percent(whatIf3.efficiency)}`);
    if (whatIf3.team) parts.push(`team ${whatIf3.team[0]}+${whatIf3.team[1]}`);
    if (whatIf3.palette) parts.push(`colours ${paletteById(whatIf3.palette).name}`);
    if (whatIf3.start !== void 0) parts.push(`start ${shortDate(whatIf3.start, view.today)}`);
    const begins = Object.keys(whatIf3.begins ?? {}).length;
    if (begins) parts.push(`${begins} milestone date${begins === 1 ? "" : "s"}`);
    return parts.join(", ");
  }
  function saveButton(view, save, off) {
    const title3 = h("input", {
      type: "text",
      placeholder: `What we thought on ${formatDate(view.today, view.today)}`
    });
    const note = h("textarea", {
      rows: 3,
      placeholder: "What the occasion was, for whoever compares against it"
    });
    const refusal = h("div", {
      class: "refusal"
    });
    const panel = h("div", {
      class: "popover",
      hidden: true
    }, h("div", {
      class: "caption"
    }, "Title"), title3, refusal, h("div", {
      class: "caption"
    }, "Note"), note, h("div", {
      class: "footer"
    }, h("button", {
      onclick: () => panel.hidden = true
    }, "Cancel"), h("button", {
      class: "primary",
      onclick: () => {
        const refused = save(title3.value, note.value);
        refusal.textContent = refused ?? "";
      }
    }, "Save")));
    return h("span", {
      class: "anchor"
    }, h("button", {
      title: off ?? "Save Snapshot\u2026 \u2014 keep the plan as it stands today under a title",
      disabled: Boolean(off),
      onclick: () => panel.hidden = !panel.hidden
    }, "\u{1F4F7} Save snapshot\u2026"), panel);
  }
  function picker(view, pick, side, chosen) {
    const saved = view.recording.saved;
    const select = h("select", {
      title: side === "then" ? pickWords(pick, view.then, view.now.day) || "Nothing recorded to compare with yet" : pickWords(pick, view.now, view.live.day) || "the plan now",
      onchange: (event) => {
        const value = event.target.value;
        if (value === "default") chosen(side === "then" ? {
          kind: "start"
        } : {
          kind: "now"
        });
        else if (value === "day") {
          chosen({
            kind: "day",
            day: pick.kind === "day" ? pick.day : view.today - 7
          });
        } else chosen({
          kind: "saved",
          title: value.slice(6)
        });
      }
    });
    select.append(h("option", {
      value: "default",
      selected: pick.kind === "start" || pick.kind === "now"
    }, side === "then" ? "Plan at start" : "Now"));
    for (const row of saved) {
      select.append(h("option", {
        value: `saved:${row.title}`,
        selected: pick.kind === "saved" && pick.title.toLowerCase() === row.title.toLowerCase(),
        title: row.note
      }, `${row.title} \xB7 ${shortDate(row.day, view.today)}`));
    }
    select.append(h("option", {
      value: "day",
      selected: pick.kind === "day"
    }, pick.kind === "day" ? shortPickWords(pick, view.today) : "Day\u2026"));
    if (pick.kind !== "day") return select;
    const day = h("input", {
      type: "date",
      value: isoDay(pick.day),
      onchange: (event) => {
        const when = parseDay(event.target.value);
        if (when !== null) chosen({
          kind: "day",
          day: when
        });
      }
    });
    return h("span", {
      class: "picker"
    }, select, day);
  }
  function staffing(view, lens, onTeam) {
    const cells = lens === "calendar" ? view.report.calendar : view.report.parallel;
    const agents = view.report.hasAgentSteps ? AGENTS : [
      1
    ];
    const values = HUMANS.flatMap((humans) => agents.map((a) => cellAt(cells, humans, a).days));
    const [least, most] = [
      Math.min(...values),
      Math.max(...values)
    ];
    const grid2 = h("div", {
      class: "staffing",
      style: `grid-template-columns: auto repeat(${agents.length}, 72px)`
    });
    grid2.append(h("span"));
    for (const a of agents) {
      grid2.append(h("span", {
        class: "head"
      }, view.report.hasAgentSteps ? `${a} agent${a === 1 ? "" : "s"}` : "any agents"));
    }
    for (const humans of HUMANS) {
      grid2.append(h("span", {
        class: "head row"
      }, `${humans} human${humans === 1 ? "" : "s"}`));
      for (const a of agents) {
        const cell = cellAt(cells, humans, a);
        const calendar2 = cellAt(view.report.calendar, humans, a);
        const parallel = cellAt(view.report.parallel, humans, a);
        const tint = most > least ? 18 + (cell.days - least) / (most - least) * 70 : 18;
        const chosen = view.team[0] === humans && (view.team[1] === a || !view.report.hasAgentSteps);
        grid2.append(h("button", {
          class: `tile${chosen ? " chosen" : ""}`,
          style: `background: rgba(95, 135, 215, ${(tint / 255).toFixed(3)})`,
          title: [
            `${humans} ${humans === 1 ? "person" : "people"} + ${a} agent${a === 1 ? "" : "s"}`,
            `${formatDays(parallel.days)} of project time`,
            `${formatDays(calendar2.days)} of calendar time at ${percent(view.report.efficiency)} focus`,
            calendar2.finish !== null ? `lands ${formatDate(calendar2.finish, view.today)}` : "nothing estimated to land"
          ].join("\n"),
          onclick: () => onTeam([
            humans,
            view.report.hasAgentSteps ? a : view.team[1]
          ])
        }, formatDays(cell.days)));
      }
    }
    return grid2;
  }
  function milestoneTable(view, state, on) {
    const table = h("table", {
      class: "milestones"
    }, h("thead", {}, h("tr", {}, ...[
      "Milestone",
      "Begins",
      "Lands",
      "Days",
      "Landed"
    ].map((name) => h("th", {}, name)))));
    const body2 = h("tbody");
    for (const entry of view.entries) {
      const picked = entry.key === ALL_KEY || entry.key === "" ? state.picked === null : state.picked === entry.key;
      const share = shareOf(entry.landed);
      const own = entry.setsProject ? view.plan.start !== null : entry.asked !== null;
      const begins = h("input", {
        type: "date",
        class: own ? "own" : "sequence",
        value: isoDay(entry.setsProject ? view.start : entry.asked ?? entry.begins),
        disabled: !entry.setsProject && !entry.badge,
        title: entry.setsProject ? "The project's start" : own ? "A date of its own" : "The day the sequence gives it",
        onclick: (event) => event.stopPropagation(),
        onchange: (event) => {
          const when = parseDay(event.target.value);
          if (entry.setsProject && when !== null) on.whatIf({
            start: when
          });
          else if (entry.badge) on.whatIf({
            begins: {
              ...state.whatIf.begins,
              [entry.key]: when
            }
          });
        }
      });
      body2.append(h("tr", {
        class: `${picked ? "picked" : ""}${entry.key === ALL_KEY ? " whole" : ""}`,
        title: `${entry.label}
${entry.steps} steps \xB7 lands ${entry.finish !== null ? formatDate(entry.finish, view.today) : "\u2014"}` + (entry.pushed !== null ? `
asked to begin ${formatDate(entry.pushed, view.today)}, but the previous milestone lands later` : ""),
        onclick: () => on.view({
          picked: entry.badge ? entry.key : null
        })
      }, h("td", {}, h("span", {
        class: "badge",
        style: `background:${entry.color}`
      }, entry.badge || ""), h("span", {}, entry.label), entry.title ? h("div", {
        class: "subtitle"
      }, entry.title) : null), h("td", {}, begins), h("td", {}, `${entry.pushed !== null ? "\u26A0 " : ""}${entry.finish !== null ? formatDate(entry.finish, view.today) : "\u2014"}`), h("td", {
        class: "number"
      }, formatDays(entry.days)), h("td", {
        class: "number",
        title: `${g(entry.landed.doneDays)}d of ${g(entry.landed.days)}d estimated \xB7 ${entry.landed.done} of ${entry.landed.steps} steps done`
      }, share === null ? "\u2014" : percent(share))));
    }
    table.append(body2);
    const none = view.entries.every((entry) => !entry.badge);
    return h("div", {}, h("div", {
      class: "caption bold"
    }, "Milestones"), table, none ? h("div", {
      class: "note"
    }, "No milestones yet \xB7 Step \u25B8 Type \u25B8 Milestone") : null);
  }
  function banner(view) {
    const count2 = view.report.unestimated;
    if (!count2) return null;
    const opted = view.unestimated.filter((step2) => step2.estimateOff).length;
    return h("div", {
      class: "banner"
    }, h("span", {
      class: "dot"
    }, "\u25CF"), ` ${count2} step${count2 === 1 ? "" : "s"} unestimated \xB7 counted as 0d`, h("span", {
      class: "names",
      title: view.unestimated.map((step2) => `${stepKey(step2)} ${step2.title}${step2.estimateOff ? " (opted out: milestone, feature or check)" : ""}`).join("\n")
    }, opted ? ` \u2014 ${opted} of them opted out of estimating` : " \u2014 which?"));
  }
  function pager(on) {
    return h("div", {
      class: "pager"
    }, h("button", {
      title: "A month earlier",
      onclick: () => on.page(on.offset - 1)
    }, "\u25C2"), h("button", {
      title: "A month later",
      onclick: () => on.page(on.offset + 1)
    }, "\u25B8"), on.offset ? h("button", {
      class: "link",
      onclick: () => on.page(0)
    }, "back to the start") : null);
  }
  var charts = 0;
  function plots(view, state, on) {
    const holder = h("div", {
      class: "chart-holder"
    });
    const tip = h("div", {
      class: "tooltip",
      hidden: true
    });
    const draw = () => {
      const width = Math.max(420, holder.clientWidth || 640);
      const id = `chart${charts += 1}`;
      const { svg, geometry: geometry2 } = chartSvg(view.chart, state.page, width, id);
      holder.innerHTML = svg;
      holder.append(tip);
      const element = holder.querySelector("svg");
      const line = element.querySelector(".hover");
      element.addEventListener("mousemove", (event) => {
        const box = element.getBoundingClientRect();
        const [x, y] = [
          event.clientX - box.left,
          event.clientY - box.top
        ];
        const panel = geometry2.panels.find((one) => y >= one.top - 18 && y <= one.top + one.height + 10);
        if (!panel || x < geometry2.left || x > geometry2.right) {
          tip.hidden = true;
          line.setAttribute("visibility", "hidden");
          return;
        }
        const day = geometry2.day(x);
        line.setAttribute("x1", String(geometry2.x(day)));
        line.setAttribute("x2", String(geometry2.x(day)));
        line.setAttribute("visibility", "visible");
        const lines = readout(view.chart, panel.kind, day);
        tip.replaceChildren(h("b", {}, formatDate(day, view.today)), ...lines.map((text2) => h("div", {}, text2)));
        tip.hidden = false;
        tip.style.left = `${Math.min(x + 14, box.width - 260)}px`;
        tip.style.top = `${y + 14}px`;
      });
      element.addEventListener("mouseleave", () => {
        tip.hidden = true;
        line.setAttribute("visibility", "hidden");
      });
    };
    queueMicrotask(draw);
    const pages = h("div", {
      class: "segmented pages"
    }, ...PAGES.map(({ page, label: label2 }) => h("button", {
      class: state.page === page ? "on" : "",
      onclick: () => on.view({
        page
      })
    }, label2)));
    return h("div", {
      class: "plots"
    }, pages, holder);
  }

  // src/ui/compare.ts
  function resolvePick(pick, today) {
    return pick.kind === "week" ? {
      kind: "day",
      day: today - 7
    } : pick;
  }
  function basisName(pick, view) {
    if (pick.kind === "start") return "the plan at start";
    if (pick.kind === "week") return "the plan a week ago";
    if (pick.kind === "saved") return pick.title;
    if (pick.kind === "now") return "the plan now";
    return `the plan at ${shortDate(pick.day, view.now.day)}`;
  }
  function comparePicker(view, pick, picked) {
    const select = h("select", {
      title: pickWords(resolvePick(pick, view.now.day), view.then, view.now.day) || "Nothing recorded to compare with yet",
      onchange: (event) => {
        const value = event.target.value;
        if (value === "start") picked({
          kind: "start"
        });
        else if (value === "week") picked({
          kind: "week"
        });
        else if (value === "day") picked({
          kind: "day",
          day: view.now.day - 14
        });
        else picked({
          kind: "saved",
          title: value.slice(6)
        });
      }
    });
    select.append(h("option", {
      value: "start",
      selected: pick.kind === "start"
    }, "the plan at start"));
    select.append(h("option", {
      value: "week",
      selected: pick.kind === "week"
    }, "the plan a week ago"));
    for (const row of view.recording.saved) {
      select.append(h("option", {
        value: `saved:${row.title}`,
        selected: pick.kind === "saved" && pick.title.toLowerCase() === row.title.toLowerCase(),
        title: row.note
      }, `${row.title} \xB7 ${shortDate(row.day, view.now.day)}`));
    }
    select.append(h("option", {
      value: "day",
      selected: pick.kind === "day"
    }, "a day\u2026"));
    const day = pick.kind === "day" ? h("input", {
      type: "date",
      value: isoDay(pick.day),
      onchange: (event) => {
        const when = parseDay(event.target.value);
        if (when !== null) picked({
          kind: "day",
          day: when
        });
      }
    }) : null;
    const found = view.then && view.then.day !== view.now.day ? h("span", {
      class: "recorded"
    }, `recorded ${shortDate(view.then.day, view.now.day)}`) : h("span", {
      class: "recorded missing"
    }, "nothing recorded before today");
    return h("label", {
      class: "compare"
    }, "Compared with ", select, day, found);
  }

  // src/ui/v2/state.ts
  var V2_START = {
    then: {
      kind: "start"
    },
    scope: null,
    whatIf: {},
    offset: 0,
    folds: {
      whatif: false,
      calendar: false
    }
  };

  // src/brief.ts
  var EPSILON2 = 1e-9;
  var NOTICEABLE = 2;
  function promisedCurve(stretches) {
    const byDay = /* @__PURE__ */ new Map();
    for (const stretch of stretches) {
      for (const knot of stretch.landings) {
        byDay.set(knot.day, (byDay.get(knot.day) ?? 0) + knot.days);
      }
    }
    let running = 0;
    return [
      ...byDay.keys()
    ].sort((a, b) => a - b).map((day) => [
      day,
      running += byDay.get(day)
    ]);
  }
  function paceOf(live, key, today) {
    const knots = promisedCurve(through(live, key));
    const done = toward(live, key).doneDays;
    let earned = null;
    let due = null;
    let promised = 0;
    for (const [day, cumulative] of knots) {
      if (day <= today) promised = cumulative;
      if (due === null && cumulative <= done + EPSILON2) earned = day;
      else if (due === null) due = day;
    }
    return {
      done,
      promised,
      short: Math.max(0, promised - done),
      earned,
      due,
      // Work still undone can be done today at the soonest, or on Monday if today is a weekend.
      lag: due !== null && due < today ? landingShift(due, nextWorkingDay(today)) : 0
    };
  }
  function ownTally(snapshot, key) {
    if (key === null) return toward(snapshot, null);
    return snapshot.stretches.find((stretch) => stretch.key === key)?.tally ?? null;
  }
  function ownSpan(snapshot, key) {
    if (!snapshot.stretches.length) return null;
    if (key === null) return [
      snapshot.stretches[0].start,
      landingIn(snapshot, null)
    ];
    const stretch = snapshot.stretches.find((one) => one.key === key);
    return stretch ? [
      stretch.start,
      stretch.finish
    ] : null;
  }
  function landedBy(rows, live, key) {
    const landed = (row) => {
      const reached = toward(row, key);
      return has(row, key) && reached.steps > 0 && reached.done === reached.steps;
    };
    if (!landed(live)) return null;
    return until(rows, live).find(landed)?.day ?? live.day;
  }
  function verdictOf(scope, compared2, then, today) {
    if (scope.landedBy !== null) return "landed";
    if (scope.move.planned !== null && scope.move.planned < today) return "overdue";
    if (!compared2) return "no-baseline";
    if (then && !has(then, scope.key)) return "new";
    const total = scope.move.total;
    if (total !== null && total >= NOTICEABLE) return "later";
    if (total !== null && total <= -NOTICEABLE) return "earlier";
    return "on-track";
  }
  function scopeOf(view, key, labels, compared2) {
    const { now, then } = view;
    const today = now.day;
    const pace = paceOf(now, key, today);
    const planned = landingIn(now, key);
    const landed = landedBy(view.recording.rows, now, key);
    const projected = landed !== null || planned === null ? null : addWorkingDays(planned, pace.lag);
    const was = compared2 && then ? landingIn(then, key) : null;
    const move = {
      then: was,
      planned,
      projected,
      plan: was !== null && planned !== null ? landingShift(was, planned) : null,
      pace: pace.lag,
      total: was !== null && projected !== null ? landingShift(was, projected) : null
    };
    const partial = {
      key,
      ...labels,
      own: ownTally(now, key) ?? EMPTY_TALLY,
      thenOwn: compared2 && then ? ownTally(then, key) : null,
      span: ownSpan(now, key),
      thenSpan: compared2 && then ? ownSpan(then, key) : null,
      pace,
      move,
      landedBy: landed
    };
    return {
      ...partial,
      verdict: verdictOf(partial, compared2, then, today)
    };
  }
  function attentionOf(milestones2) {
    const overdue = milestones2.filter((scope) => scope.verdict === "overdue").sort((a, b) => a.move.planned - b.move.planned);
    if (overdue.length) return {
      scope: overdue[0],
      kind: "overdue",
      days: 0,
      plan: 0,
      pace: 0
    };
    let best = null;
    let before = {
      then: null,
      planned: null,
      projected: null,
      plan: 0,
      pace: 0,
      total: 0
    };
    for (const scope of milestones2) {
      const move = scope.move;
      if (move.total === null) continue;
      const days = move.total - (before.total ?? 0);
      if (days >= NOTICEABLE && (!best || days > best.days)) {
        best = {
          scope,
          kind: "origin",
          days,
          plan: (move.plan ?? 0) - (before.plan ?? 0),
          pace: move.pace - before.pace
        };
      }
      before = move;
    }
    return best;
  }
  function brief(view) {
    const compared2 = view.then !== null && view.then.day !== view.now.day;
    const whole = scopeOf(view, null, {
      label: "All work",
      title: "",
      badge: "",
      color: WHOLE_COLOR
    }, compared2);
    const milestones2 = view.stretches.map(({ phase, key, label: label2, color }) => scopeOf(view, key, {
      label: label2,
      title: phase.milestone && phase.milestone.title !== label2 ? phase.milestone.title : "",
      badge: phase.milestone ? `S${phase.milestone.number}` : "",
      color
    }, compared2));
    return {
      today: view.now.day,
      compared: compared2,
      whole,
      milestones: milestones2,
      attention: attentionOf(milestones2)
    };
  }
  function burnup(view, key, compared2) {
    const scope = [];
    const done = [];
    const jumps = [];
    const active = /* @__PURE__ */ new Set();
    let before = null;
    for (const row of until(view.recording.rows, view.now)) {
      const own = ownTally(row, key);
      if (!own) continue;
      if (scope.length && scope[scope.length - 1][0] === row.day) {
        scope.pop();
        done.pop();
      }
      if (before && (own.steps !== before.steps || Math.abs(own.days - before.days) > EPSILON2)) {
        jumps.push({
          day: row.day,
          steps: own.steps - before.steps,
          days: own.days - before.days
        });
      }
      if (own.changed > 0 || before && own.done !== before.done) active.add(row.day);
      scope.push([
        row.day,
        own.days
      ]);
      done.push([
        row.day,
        own.doneDays
      ]);
      before = own;
    }
    const stretches = key === null ? view.now.stretches : view.now.stretches.filter((one) => one.key === key);
    const promised = promisedCurve(stretches);
    const start2 = stretches[0]?.start;
    const baseline2 = compared2 && view.then ? ownTally(view.then, key)?.days ?? null : null;
    return {
      scope,
      done,
      baseline: baseline2,
      promised: start2 !== void 0 ? [
        [
          start2,
          0
        ],
        ...promised
      ] : promised,
      jumps,
      active: [
        ...active
      ].sort((a, b) => a - b)
    };
  }
  function stepsOf(view, plan, key) {
    if (key === null) return plan.steps;
    return view.stretches.find((one) => one.key === key)?.phase.steps ?? [];
  }
  function changes(view, scope) {
    const then = view.then;
    if (!then || !scope.thenOwn) return null;
    const now = scope.own;
    const listed = changesSince(stepsOf(view, view.plan, scope.key), then.day);
    const unnamed = now.steps - scope.thenOwn.steps - listed.added.length;
    const whole = toward(view.now, null).steps - toward(then, null).steps - changesSince(view.plan.steps, then.day).added.length;
    const throughNow = toward(view.now, scope.key);
    const throughThen = toward(then, scope.key);
    return {
      since: then.day,
      steps: now.steps - scope.thenOwn.steps,
      days: now.days - scope.thenOwn.days,
      added: listed.added,
      estimates: listed.estimates,
      unnamed,
      moved: scope.key !== null && unnamed !== 0 && whole === 0,
      doneSteps: now.done - scope.thenOwn.done,
      doneDays: now.doneDays - scope.thenOwn.doneDays,
      unexplained: (scope.move.plan ?? 0) !== 0 && throughNow.steps === throughThen.steps && Math.abs(throughNow.days - throughThen.days) < EPSILON2
    };
  }

  // src/ui/glyphs.ts
  var CELL_W = 14;
  var CELL_H = 12;
  var GLYPH = 6;
  var MARGIN = 2;
  var EDGE_GLYPH = 8;
  var SMALL_W = 16;
  var SMALL_H = 10;
  function placeGlyphs(rects) {
    const found = [];
    const half = GLYPH / 2;
    for (const rect of rects) {
      if (rect.width < SMALL_W || rect.height < SMALL_H) {
        if (rect.width >= 4 && rect.height >= 4) {
          found.push({
            x: rect.x + Math.min(EDGE_GLYPH, rect.width) / 2 + 1,
            y: rect.y + rect.height / 2,
            size: EDGE_GLYPH
          });
        }
        continue;
      }
      const firstRow = Math.floor(rect.y / CELL_H);
      const lastRow = Math.ceil((rect.y + rect.height) / CELL_H);
      for (let row = firstRow; row <= lastRow; row += 1) {
        const y = row * CELL_H + CELL_H / 2;
        if (y - half < rect.y + MARGIN || y + half > rect.y + rect.height - MARGIN) continue;
        const shift = row % 2 ? CELL_W / 2 : 0;
        const firstColumn = Math.floor((rect.x - shift) / CELL_W);
        const lastColumn = Math.ceil((rect.x + rect.width - shift) / CELL_W);
        for (let column = firstColumn; column <= lastColumn; column += 1) {
          const x = column * CELL_W + CELL_W / 2 + shift;
          if (x - half < rect.x + MARGIN || x + half > rect.x + rect.width - MARGIN) continue;
          found.push({
            x,
            y,
            size: GLYPH
          });
        }
      }
    }
    return found;
  }
  function alongSegment(from, to, y, spacing = 10) {
    const [left, right] = [
      Math.min(from, to),
      Math.max(from, to)
    ];
    const count2 = Math.floor((right - left - 4) / spacing);
    if (count2 < 2) {
      return right - left >= 4 ? [
        {
          x: to - Math.sign(to - from) * 4,
          y,
          size: GLYPH
        }
      ] : [];
    }
    const start2 = left + (right - left - (count2 - 1) * spacing) / 2;
    return Array.from({
      length: count2
    }, (_, index) => ({
      x: start2 + index * spacing,
      y,
      size: GLYPH
    }));
  }
  function glyphPath(glyph, direction) {
    const w = glyph.size / 2;
    const h2 = glyph.size * 5 / 12;
    const [x, y] = [
      glyph.x,
      glyph.y
    ];
    const round = (value) => Math.round(value * 10) / 10;
    const points = direction === "up" ? [
      [
        x,
        y - h2
      ],
      [
        x + w,
        y + h2
      ],
      [
        x - w,
        y + h2
      ]
    ] : direction === "down" ? [
      [
        x,
        y + h2
      ],
      [
        x + w,
        y - h2
      ],
      [
        x - w,
        y - h2
      ]
    ] : direction === "right" ? [
      [
        x + h2,
        y
      ],
      [
        x - h2,
        y - w
      ],
      [
        x - h2,
        y + w
      ]
    ] : [
      [
        x - h2,
        y
      ],
      [
        x + h2,
        y - w
      ],
      [
        x + h2,
        y + w
      ]
    ];
    return `M${points.map(([px, py]) => `${round(px)},${round(py)}`).join(" L")} Z`;
  }

  // src/ui/v2/burnup.ts
  var HEIGHT = 250;
  var LEFT = 48;
  var RIGHT = 96;
  var TOP = 30;
  var BOTTOM = 24;
  function stepPath(points, x, y, end) {
    if (!points.length) return "";
    let path = `M${n(x(points[0][0]))},${n(y(points[0][1]))}`;
    points.forEach((_, index) => {
      const next = index + 1 < points.length ? points[index + 1] : null;
      path += ` H${n(x(next ? next[0] : end))}`;
      if (next) path += ` V${n(y(next[1]))}`;
    });
    return path;
  }
  function burnupSvg(data, scope, view, width, basis) {
    const today = view.today;
    const days = [
      today,
      ...data.scope.map(([day]) => day),
      ...data.promised.map(([day]) => day)
    ];
    for (const day of [
      scope.move.projected,
      scope.move.planned,
      scope.move.then,
      scope.span?.[0] ?? null
    ]) {
      if (day !== null) days.push(day);
    }
    const [first, last] = [
      Math.min(...days) - 1,
      Math.max(...days) + 2
    ];
    const values = [
      ...data.scope.map(([, v]) => v),
      ...data.promised.map(([, v]) => v),
      data.baseline ?? 0,
      1
    ];
    const top = niceCeiling(Math.max(...values));
    const plotW = width - LEFT - RIGHT;
    const x = (day) => LEFT + (day - first) / (last - first) * plotW;
    const y = (value) => TOP + (1 - value / top) * (HEIGHT - TOP - BOTTOM);
    const out = [
      `<svg class="chart" viewBox="0 0 ${n(width)} ${HEIGHT}" width="${n(width)}" height="${HEIGHT}" font-size="11">`
    ];
    for (const share of [
      0,
      0.5,
      1
    ]) {
      out.push(`<line x1="${LEFT}" x2="${n(LEFT + plotW)}" y1="${n(y(top * share))}" y2="${n(y(top * share))}" style="stroke:${INK}" stroke-opacity="0.12"/>`);
      out.push(`<text x="${LEFT - 8}" y="${n(y(top * share))}" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${formatDays(top * share) || "0d"}</text>`);
    }
    for (const [when, label2] of axisTicks(first, last, Math.max(1, Math.floor(plotW / 70)))) {
      out.push(`<line x1="${n(x(when))}" x2="${n(x(when))}" y1="${TOP}" y2="${HEIGHT - BOTTOM}" style="stroke:${INK}" stroke-opacity="0.08"/>`);
      out.push(`<text x="${n(x(when))}" y="${HEIGHT - 8}" text-anchor="middle" style="fill:${SECONDARY}">${esc(label2)}</text>`);
    }
    const since = view.then?.day ?? null;
    if (data.baseline !== null && since !== null) {
      const areas = {
        up: [],
        down: [],
        left: [],
        right: []
      };
      data.scope.forEach(([day, value], index) => {
        const next = index + 1 < data.scope.length ? data.scope[index + 1][0] : today;
        const from = Math.max(day, since);
        if (next <= from || Math.abs(value - data.baseline) < 1e-9) return;
        const [left, right] = [
          x(from),
          x(next)
        ];
        const [upper, lower] = [
          y(Math.max(value, data.baseline)),
          y(Math.min(value, data.baseline))
        ];
        areas[value > data.baseline ? "up" : "down"].push({
          x: left,
          y: upper,
          width: right - left,
          height: lower - upper
        });
      });
      for (const direction of [
        "up",
        "down"
      ]) {
        for (const rect of areas[direction]) {
          out.push(`<rect x="${n(rect.x)}" y="${n(rect.y)}" width="${n(rect.width)}" height="${n(rect.height)}" class="scope-${direction}-fill"/>`);
        }
        for (const glyph of placeGlyphs(areas[direction])) {
          out.push(`<path d="${glyphPath(glyph, direction)}" class="scope-${direction}-glyph"/>`);
        }
      }
      const at = y(data.baseline);
      out.push(`<line x1="${n(x(since))}" x2="${n(LEFT + plotW)}" y1="${n(at)}" y2="${n(at)}" style="stroke:${SECONDARY}" stroke-dasharray="5 4"/>`);
      out.push(`<text x="${n(LEFT + plotW + 6)}" y="${n(at)}" dominant-baseline="central" style="fill:${SECONDARY}">${esc(`${formatDays(data.baseline) || "0d"} then`)}</text>`);
    }
    const end = today;
    if (data.done.length) {
      const line = stepPath(data.done, x, y, end);
      out.push(`<path d="${line} V${n(y(0))} H${n(x(data.done[0][0]))} Z" style="fill:${INK}" fill-opacity="0.1"/>`);
      out.push(`<path d="${line}" fill="none" style="stroke:${INK}" stroke-width="2"/>`);
    }
    if (data.promised.length > 1) {
      out.push(`<path d="${stepPath(data.promised, x, y, data.promised[data.promised.length - 1][0])}" fill="none" style="stroke:${SECONDARY}" stroke-width="1.5" stroke-dasharray="1 3" stroke-linecap="round"/>`);
    }
    if (data.scope.length) {
      out.push(`<path d="${stepPath(data.scope, x, y, end)}" fill="none" stroke="${PLAN}" stroke-width="2.5"/>`);
      const [, now] = data.scope[data.scope.length - 1];
      out.push(`<text x="${n(LEFT + plotW + 6)}" y="${n(y(now) - (data.baseline !== null && Math.abs(y(now) - y(data.baseline)) < 12 ? 10 : 0))}" dominant-baseline="central" fill="${PLAN}" font-weight="600">${esc(`${formatDays(now) || "0d"} now`)}</text>`);
    }
    const scopeNow = data.scope.length ? data.scope[data.scope.length - 1][1] : 0;
    const doneNow = data.done.length ? data.done[data.done.length - 1][1] : 0;
    const lands = scope.move.projected;
    if (lands !== null && scope.landedBy === null) {
      out.push(`<line x1="${n(x(today))}" y1="${n(y(doneNow))}" x2="${n(x(lands))}" y2="${n(y(scopeNow))}" class="projection"/>`);
      out.push(`<circle cx="${n(x(lands))}" cy="${n(y(scopeNow))}" r="5" class="projected"><title>${esc(`lands ~${shortDate(lands, today)} at today's pace`)}</title></circle>`);
      const label2 = `~${shortDate(lands, today)}`;
      out.push(`<text x="${n(Math.min(x(lands) + 8, LEFT + plotW + RIGHT - textWidth(label2) - 4))}" y="${n(y(scopeNow) + 16)}" font-weight="600" style="fill:${INK}">${esc(label2)}</text>`);
    }
    if (scope.move.planned !== null && scope.move.planned !== lands && scope.landedBy === null) {
      const at = x(scope.move.planned);
      out.push(`<line x1="${n(at)}" x2="${n(at)}" y1="${n(y(scopeNow) - 6)}" y2="${n(y(scopeNow) + 6)}" style="stroke:${INK}" stroke-width="2"><title>${esc(`the plan itself says ${shortDate(scope.move.planned, today)}`)}</title></line>`);
    }
    if (scope.move.then !== null && data.baseline !== null) {
      out.push(`<circle cx="${n(x(scope.move.then))}" cy="${n(y(data.baseline))}" r="4.5" style="fill:var(--surface);stroke:${SECONDARY}" stroke-width="1.5"><title>${esc(`${basis} landed it ${shortDate(scope.move.then, today)}`)}</title></circle>`);
    }
    for (const row of view.recording.saved) {
      if (row.day < first || row.day > last) continue;
      out.push(`<line x1="${n(x(row.day))}" x2="${n(x(row.day))}" y1="${TOP}" y2="${HEIGHT - BOTTOM}" style="stroke:${INK}" stroke-opacity="0.4" stroke-dasharray="4 3"><title>${esc(`saved: ${row.title}`)}</title></line>`);
    }
    out.push(`<line x1="${n(x(today))}" x2="${n(x(today))}" y1="${TOP - 6}" y2="${HEIGHT - BOTTOM}" class="today-line"/>`);
    out.push(`<text x="${n(x(today))}" y="${TOP - 10}" text-anchor="middle" font-weight="600" style="fill:${INK}">today</text>`);
    for (const jump of data.jumps) {
      const words2 = `${jump.steps >= 0 ? "+" : "\u2212"}${Math.abs(jump.steps)} step${Math.abs(jump.steps) === 1 ? "" : "s"}, ${jump.days >= 0 ? "+" : "\u2212"}${formatDays(Math.abs(jump.days)) || "0d"} on ${shortDate(jump.day, today)}`;
      out.push(`<rect x="${n(x(jump.day) - 5)}" y="${TOP}" width="10" height="${HEIGHT - TOP - BOTTOM}" fill="transparent"><title>${esc(words2)}</title></rect>`);
    }
    out.push("</svg>");
    return out.join("");
  }
  function burnupKey(basis, compared2) {
    const up = glyphPath({
      x: 9,
      y: 8,
      size: 7
    }, "up");
    const down = glyphPath({
      x: 9,
      y: 8,
      size: 7
    }, "down");
    const items = [
      `<span><svg width="18" height="14"><line x1="1" x2="17" y1="7" y2="7" stroke="${PLAN}" stroke-width="2.5"/></svg>scope</span>`,
      `<span><svg width="18" height="14"><rect x="1" y="3" width="16" height="9" style="fill:${INK}" fill-opacity="0.18"/><line x1="1" x2="17" y1="3" y2="3" style="stroke:${INK}" stroke-width="2"/></svg>done</span>`,
      `<span><svg width="18" height="14"><line x1="1" x2="17" y1="7" y2="7" style="stroke:${SECONDARY}" stroke-width="1.5" stroke-dasharray="1 3" stroke-linecap="round"/></svg>the plan's schedule</span>`,
      `<span><svg width="18" height="14"><line x1="1" x2="17" y1="7" y2="7" class="projection"/></svg>at today's pace</span>`
    ];
    if (compared2) {
      items.push(`<span><svg width="18" height="14"><line x1="1" x2="17" y1="7" y2="7" style="stroke:${SECONDARY}" stroke-dasharray="5 4"/></svg>scope in ${esc(basis)}</span>`, `<span><svg width="18" height="16"><rect x="0" y="0" width="18" height="16" class="scope-up-fill"/><path d="${up}" class="scope-up-glyph"/></svg>work added</span>`, `<span><svg width="18" height="16"><rect x="0" y="0" width="18" height="16" class="scope-down-fill"/><path d="${down}" class="scope-down-glyph"/></svg>work taken away</span>`);
    }
    return items.join("");
  }

  // src/ui/v2/words.ts
  var VERDICTS = {
    landed: {
      glyph: "\u2713",
      word: "Landed",
      tone: "landed"
    },
    overdue: {
      glyph: "\u26A0",
      word: "Overdue",
      tone: "overdue"
    },
    later: {
      glyph: "\u25B6",
      word: "Later",
      tone: "later"
    },
    earlier: {
      glyph: "\u25C0",
      word: "Earlier",
      tone: "earlier"
    },
    "on-track": {
      glyph: "\u25CF",
      word: "On track",
      tone: "ok"
    },
    "no-baseline": {
      glyph: "\u25CB",
      word: "Nothing to compare",
      tone: "none"
    },
    new: {
      glyph: "\u271A",
      word: "New",
      tone: "none"
    }
  };
  function workingDays(count2) {
    const size = Math.abs(count2);
    return `${size} working day${size === 1 ? "" : "s"}`;
  }
  function longDate(day, today) {
    return `${weekdayName(day).slice(0, 3)} ${formatDate(day, today)}`;
  }
  function moveChip(total) {
    if (total === null) return {
      text: "",
      tone: "none"
    };
    if (total === 0) return {
      text: "= same day",
      tone: "ok"
    };
    return total > 0 ? {
      text: `\u25B6 +${total}d`,
      tone: "later"
    } : {
      text: `\u25C0 \u2212${-total}d`,
      tone: "earlier"
    };
  }
  function moveParts(move) {
    const parts = [];
    if (move.plan) {
      parts.push(`${move.plan > 0 ? "+" : "\u2212"}${Math.abs(move.plan)} from changes to the plan`);
    }
    if (move.pace) parts.push(`+${move.pace} from today's pace`);
    return parts.join(", ");
  }
  function moveSentence(scope, basis, today) {
    const { move } = scope;
    if (move.total === null || move.then === null) return "";
    const was = `${basis} (${shortDate(move.then, today)})`;
    if (Math.abs(move.total) <= 1) return `Within a day of ${was}.`;
    const direction = move.total > 0 ? "later" : "earlier";
    const why = moveParts(move);
    return `${workingDays(move.total)} ${direction} than ${was}${why ? ` \u2014 ${why}` : ""}.`;
  }
  function paceSentence(pace, today) {
    if (pace.lag === 0) return "The work is on the plan's own schedule.";
    return `Work due ${shortDate(pace.due, today)} is not done yet: ${workingDays(pace.lag)} behind the plan's own schedule` + (pace.short > 0 ? ` (${g(Math.round(pace.short * 4) / 4)} days of work).` : ".");
  }

  // src/ui/v2/changes.ts
  var LISTED = 6;
  function arrow2(direction) {
    const holder = h("span", {
      class: "inline-glyph"
    });
    holder.innerHTML = `<svg width="12" height="12"><path d="${glyphPath({
      x: 6,
      y: 6,
      size: 8
    }, direction)}" class="scope-${direction}-glyph"/></svg>`;
    return holder.firstElementChild;
  }
  function signed(value, unit = "") {
    return `${value > 0 ? "+" : value < 0 ? "\u2212" : "\xB1"}${g(Math.abs(value))}${unit}`;
  }
  function changesPanel(listed, scope, basis, today) {
    if (!listed) {
      return h("div", {
        class: "changes empty-note"
      }, h("h3", {}, "What changed"), h("p", {}, "Nothing recorded before today to compare with. Pick a saved snapshot or a day under \u201CCompared with\u201D."));
    }
    const items = [];
    const scopeLine = listed.steps === 0 && Math.abs(listed.days) < 1e-9 ? h("li", {}, "Scope unchanged.") : h("li", {
      class: "scope-line"
    }, listed.days >= 0 ? arrow2("up") : arrow2("down"), ` Scope ${signed(listed.steps, listed.steps === 1 || listed.steps === -1 ? " step" : " steps")}, ${signed(listed.days, "d")} of work.`);
    items.push(scopeLine);
    if (scope.move.total !== null) {
      const why = moveParts(scope.move);
      items.push(h("li", {}, scope.move.total === 0 ? "Lands the same day." : `Lands ${workingDays(scope.move.total)} ${scope.move.total > 0 ? "later" : "earlier"}${why ? ` \u2014 ${why}` : ""}.`));
    }
    if (listed.unexplained) {
      items.push(h("li", {
        class: "note-box"
      }, "The dates moved with no change in scope: a different team, focus or start date. Records do not keep which."));
    }
    if (listed.added.length) {
      items.push(h("li", {}, `Added (${listed.added.length}):`, h("ul", {}, ...listed.added.slice(0, LISTED).map(([step2, days]) => h("li", {}, h("span", {
        class: "key"
      }, stepKey(step2)), ` ${step2.title}`, h("span", {
        class: "planned"
      }, ` ${days !== null ? formatDays(days) : "unsized"}${step2.created !== null ? ` \xB7 ${shortDate(step2.created, today)}` : ""}`))), listed.added.length > LISTED ? h("li", {
        class: "planned"
      }, `and ${listed.added.length - LISTED} more`) : null)));
    }
    if (listed.estimates.length) {
      items.push(h("li", {}, `Re-estimated (${listed.estimates.length}):`, h("ul", {}, ...listed.estimates.slice(0, LISTED).map(([step2, day, was, now]) => h("li", {}, h("span", {
        class: "key"
      }, stepKey(step2)), ` ${step2.title}`, h("span", {
        class: "planned"
      }, ` ${formatDays(was)} \u2192 ${now !== null ? formatDays(now) : "unsized"} \xB7 ${shortDate(day, today)}`))), listed.estimates.length > LISTED ? h("li", {
        class: "planned"
      }, `and ${listed.estimates.length - LISTED} more`) : null)));
    }
    if (listed.unnamed) {
      items.push(h("li", {}, listed.unnamed > 0 ? `${listed.unnamed} step${listed.unnamed === 1 ? "" : "s"} moved in from another milestone (not named).` : `${-listed.unnamed} step${listed.unnamed === -1 ? "" : "s"} ${listed.moved ? "moved to another milestone" : "removed or moved out"} (not named \u2014 records keep counts, not steps).`));
    }
    items.push(h("li", {}, listed.doneSteps > 0 ? `Done since: ${listed.doneSteps} step${listed.doneSteps === 1 ? "" : "s"}, ${formatDays(listed.doneDays) || "0d"} of work.` : listed.doneSteps < 0 ? `${-listed.doneSteps} step${listed.doneSteps === -1 ? "" : "s"} reopened since: ${formatDays(-listed.doneDays) || "0d"} of work no longer counts as done.` : "Nothing done since."));
    return h("div", {
      class: "changes"
    }, h("h3", {}, `What changed since ${basis} (${shortDate(listed.since, today)})`), h("ul", {}, ...items));
  }

  // src/ui/v2/headline.ts
  function verdictChip(scope) {
    const verdict = VERDICTS[scope.verdict];
    return h("span", {
      class: `verdict tone-${verdict.tone}`
    }, h("span", {
      class: "glyph"
    }, verdict.glyph), verdict.word);
  }
  function headline(view, found, state, on) {
    const whole = found.whole;
    const basis = basisName(state.then, view);
    const share = shareOf(whole.own);
    const done = `${share === null ? "\u2014" : percent(share)} of the work done (${g(whole.own.doneDays)} of ${g(whole.own.days)} days)`;
    let answer;
    if (whole.landedBy !== null) {
      answer = h("div", {
        class: "answer"
      }, h("span", {
        class: "lead"
      }, "Landed"), h("strong", {}, `recorded done by ${longDate(whole.landedBy, view.today)}`));
    } else if (whole.move.projected !== null) {
      const moved = whole.move.projected !== whole.move.planned;
      answer = h("div", {
        class: "answer"
      }, h("span", {
        class: "lead"
      }, "Lands"), h("strong", {}, `${moved ? "~" : ""}${longDate(whole.move.projected, view.today)}`), h("span", {
        class: "qualifier"
      }, moved ? "at today's pace" : "on schedule"));
    } else {
      answer = h("div", {
        class: "answer"
      }, h("span", {
        class: "lead"
      }, "Nothing estimated to land"));
    }
    const planned = whole.move.planned !== null && whole.move.projected !== whole.move.planned ? `The plan itself says ${longDate(whole.move.planned, view.today)} \xB7 ` : "";
    const verdictLine = h("div", {
      class: "verdict-line"
    }, verdictChip(whole), h("span", {}, whole.verdict === "no-baseline" ? "Nothing recorded before today to compare with \u2014 pick a saved snapshot or a day." : moveSentence(whole, basis, view.today)), " ", h("span", {
      class: "pace"
    }, whole.landedBy === null ? paceSentence(whole.pace, view.today) : ""));
    return h("header", {
      class: "v2-head"
    }, h("div", {
      class: "v2-controls"
    }, comparePicker(view, state.then, (then) => on.state({
      then
    })), whatIfChip(state, on)), answer, h("div", {
      class: "sub"
    }, planned + done), verdictLine, attentionLine(found, view, on));
  }
  function attentionLine(found, view, on) {
    const attention = found.attention;
    if (!attention) return null;
    const { scope } = attention;
    const name = `${scope.badge ? scope.badge + " " : ""}${scope.label}`;
    const words2 = attention.kind === "overdue" ? `${name} is overdue \u2014 planned ${shortDate(scope.move.planned, view.today)}, not done; ~${shortDate(scope.move.projected ?? view.today, view.today)} at today's pace.` : `Most of the move is added in ${name}'s own work: +${workingDays(attention.days)} (${[
      attention.plan ? `${attention.plan > 0 ? "+" : "\u2212"}${Math.abs(attention.plan)} from changes to the plan` : "",
      attention.pace ? `+${attention.pace} from today's pace` : ""
    ].filter(Boolean).join(", ")}).`;
    const tone = attention.kind === "overdue" ? "overdue" : "later";
    return h("div", {
      class: `attention tone-border-${tone}`,
      role: "button",
      tabindex: "0",
      title: `Show ${name}`,
      onclick: () => on.state({
        scope: scope.key
      }),
      onkeydown: (event) => {
        if (event.key === "Enter") on.state({
          scope: scope.key
        });
      }
    }, h("span", {
      class: `glyph tone-${tone}`
    }, attention.kind === "overdue" ? "\u26A0" : "\u25B6"), ` ${words2}`);
  }
  function whatIfChip(state, on) {
    if (!Object.keys(state.whatIf).length) return null;
    return h("span", {
      class: "what-if"
    }, "what-if active", h("button", {
      class: "link",
      onclick: () => on.state({
        whatIf: {}
      })
    }, "reset"));
  }

  // src/ui/v2/milestones.ts
  var ROW_H = 26;
  var refocus = false;
  function extent2(scopes, today) {
    const days = [
      today
    ];
    for (const scope of scopes) {
      for (const span of [
        scope.span,
        scope.thenSpan
      ]) {
        if (span) days.push(span[0], ...span[1] !== null ? [
          span[1]
        ] : []);
      }
      for (const day of [
        scope.move.projected,
        scope.move.planned,
        scope.move.then
      ]) {
        if (day !== null) days.push(day);
      }
    }
    return [
      Math.min(...days) - 1,
      Math.max(...days) + 3
    ];
  }
  function ganttRow(scope, today, first, last, width) {
    const x = (day) => (day - first) / (last - first) * width;
    const mid = ROW_H / 2;
    const out = [
      `<svg viewBox="0 0 ${n(width)} ${ROW_H}" width="${n(width)}" height="${ROW_H}">`
    ];
    const thenSpan = scope.thenSpan;
    if (thenSpan && thenSpan[1] !== null) {
      out.push(`<rect x="${n(x(thenSpan[0]))}" y="${mid - 7}" width="${n(Math.max(2, x(thenSpan[1] + 1) - x(thenSpan[0])))}" height="14" rx="3" fill="none" style="stroke:${SECONDARY}" stroke-dasharray="3 2"><title>${esc(`then: ${shortDate(thenSpan[0], today)} \u2192 ${shortDate(thenSpan[1], today)}`)}</title></rect>`);
    }
    const span = scope.span;
    const planned = scope.move.planned;
    if (span && planned !== null) {
      const [from, to] = [
        x(span[0]),
        x(planned + 1)
      ];
      out.push(`<rect x="${n(from)}" y="${mid - 5}" width="${n(Math.max(2, to - from))}" height="10" rx="2" style="fill:${INK}" fill-opacity="0.16"><title>${esc(`planned ${shortDate(span[0], today)} \u2192 ${shortDate(planned, today)}`)}</title></rect>`);
      const earned = scope.landedBy ?? scope.pace.earned;
      if (earned !== null && earned >= span[0]) {
        const end = x(Math.min(earned, planned) + 1);
        out.push(`<rect x="${n(from)}" y="${mid - 5}" width="${n(Math.max(1, end - from))}" height="10" rx="2" style="fill:${INK}" fill-opacity="0.5"><title>${esc(`the work done was due by ${shortDate(earned, today)}`)}</title></rect>`);
      }
      const projected = scope.move.projected;
      if (projected !== null && projected > planned) {
        const [start2, end] = [
          x(planned + 1),
          x(projected + 1)
        ];
        out.push(`<rect x="${n(start2)}" y="${mid - 5}" width="${n(end - start2)}" height="10" rx="2" class="lag-fill"><title>${esc(`${scope.pace.lag} working days at today's pace`)}</title></rect>`);
        for (const glyph of alongSegment(start2, end, mid, 9)) {
          out.push(`<path d="${glyphPath({
            ...glyph,
            size: 6
          }, "right")}" class="lag-glyph"/>`);
        }
      }
    }
    if (scope.move.then !== null) {
      out.push(`<circle cx="${n(x(scope.move.then + 0.5))}" cy="${mid}" r="4" style="fill:var(--surface);stroke:${SECONDARY}" stroke-width="1.5"><title>${esc(`then it landed ${shortDate(scope.move.then, today)}`)}</title></circle>`);
    }
    const lands = scope.landedBy ?? scope.move.projected;
    if (lands !== null) {
      out.push(`<circle cx="${n(x(lands + 0.5))}" cy="${mid}" r="3.5" style="fill:${INK}"/>`);
    }
    out.push(`<line x1="${n(x(today + 0.5))}" x2="${n(x(today + 0.5))}" y1="0" y2="${ROW_H}" class="today-line"/>`);
    out.push("</svg>");
    return out.join("");
  }
  function axis(first, last, today, width) {
    const x = (day) => (day - first) / (last - first) * width;
    const out = [
      `<svg viewBox="0 0 ${n(width)} 18" width="${n(width)}" height="18">`
    ];
    for (const [when, label2] of axisTicks(first, last, Math.max(1, Math.floor(width / 64)))) {
      if (Math.abs(x(when) - x(today)) < 34) continue;
      out.push(`<text x="${n(x(when + 0.5))}" y="12" text-anchor="middle" style="fill:${SECONDARY}" font-size="11">${esc(label2)}</text>`);
    }
    out.push(`<text x="${n(x(today + 0.5))}" y="12" text-anchor="middle" font-size="11" font-weight="600" style="fill:${INK}">today</text>`);
    out.push("</svg>");
    return out.join("");
  }
  function timeline(view, found, state, on, basis) {
    const scopes = [
      found.whole,
      ...found.milestones
    ];
    const [first, last] = extent2(scopes, view.today);
    const choose2 = (scope) => on.state({
      scope: scope.key
    });
    const selected = scopes.find((scope) => scope.key === state.scope) ?? found.whole;
    const holders = [];
    const axisHolder = h("div", {
      class: "gantt axis"
    });
    const rows = scopes.map((scope) => {
      const holder = h("div", {
        class: "gantt"
      });
      holders.push([
        scope,
        holder
      ]);
      const chip = moveChip(scope.move.total);
      const lands = scope.landedBy !== null ? h("span", {}, `done by ${shortDate(scope.landedBy, view.today)}`) : scope.move.projected !== null ? h("span", {}, h("b", {}, `${scope.move.projected !== scope.move.planned ? "~" : ""}${shortDate(scope.move.projected, view.today)}`), scope.move.projected !== scope.move.planned ? h("span", {
        class: "planned"
      }, ` plan ${shortDate(scope.move.planned, view.today)}`) : null) : h("span", {
        class: "planned"
      }, "nothing estimated");
      return h("div", {
        class: `row${scope === selected ? " selected" : ""}${scope.key === null ? " whole" : ""}`,
        role: "option",
        "aria-selected": String(scope === selected),
        onclick: () => choose2(scope)
      }, h("span", {
        class: "name"
      }, scope.badge ? h("span", {
        class: "badge",
        style: `background:${scope.color}`
      }, scope.badge) : null, h("span", {}, scope.label), scope.title ? h("span", {
        class: "subtitle"
      }, scope.title) : null), verdictChip(scope), h("span", {
        class: "lands"
      }, lands), h("span", {
        class: `move tone-${chip.tone}`,
        title: scope.move.total !== null ? moveParts(scope.move) || "no change" : "nothing to compare with"
      }, chip.text), holder);
    });
    const list = h("div", {
      class: "timeline",
      role: "listbox",
      tabindex: "0",
      "aria-label": "Milestones \u2014 \u2191 and \u2193 move between them",
      onkeydown: (event) => {
        if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
        event.preventDefault();
        const index = scopes.indexOf(selected) + (event.key === "ArrowDown" ? 1 : -1);
        if (index < 0 || index >= scopes.length) return;
        refocus = true;
        choose2(scopes[index]);
      }
    }, h("div", {
      class: "row head"
    }, h("span", {}, "Milestone"), h("span", {}, "Status"), h("span", {}, "Lands"), h("span", {
      title: `against ${basis}`
    }, "Moved"), axisHolder), ...rows);
    queueMicrotask(() => {
      const width = Math.max(160, axisHolder.clientWidth);
      axisHolder.innerHTML = axis(first, last, view.today, width);
      for (const [scope, holder] of holders) {
        holder.innerHTML = ganttRow(scope, view.today, first, last, width);
      }
      if (refocus) {
        refocus = false;
        list.focus();
      }
    });
    return h("section", {
      class: "v2-section"
    }, h("h2", {}, "Milestones"), list);
  }

  // src/ui/v2/view.ts
  function v2View(view, state, on) {
    if (view.report.cycle.length) {
      const names = view.report.cycle.map((step2) => step2.title || "an untitled step").join(", ");
      return h("div", {
        class: "v2"
      }, h("div", {
        class: "banner error"
      }, `These steps wait on each other, so nothing can be dated: ${names}. Unlink one to time the plan.`));
    }
    const found = brief(view);
    const basis = basisName(state.then, view);
    const scopes = [
      found.whole,
      ...found.milestones
    ];
    const selected = scopes.find((scope) => scope.key === state.scope) ?? found.whole;
    const head = headline(view, found, state, on);
    head.querySelector(".v2-controls")?.append(saveButton(view, on.save));
    return h("div", {
      class: "v2"
    }, head, unsized(view), timeline(view, found, state, on, basis), detail(view, selected, found.compared, basis), whatIf(view, state, on), calendar(view, state, on));
  }
  function unsized(view) {
    const steps = view.unestimated.filter((step2) => !step2.estimateOff);
    if (!steps.length) return null;
    return h("div", {
      class: "unsized",
      title: steps.map((step2) => `${stepKey(step2)} ${step2.title}`).join("\n")
    }, `${steps.length} step${steps.length === 1 ? " has" : "s have"} no estimate and count as 0 days \u2014 every date here is that much early.`);
  }
  function detail(view, scope, compared2, basis) {
    const data = burnup(view, scope.key, compared2);
    const holder = h("div", {
      class: "burnup"
    });
    queueMicrotask(() => {
      holder.innerHTML = burnupSvg(data, scope, view, Math.max(420, holder.clientWidth), basis);
    });
    const own = scope.own;
    const title3 = scope.key === null ? "All work" : `${scope.badge ? scope.badge + " " : ""}${scope.label}${scope.title ? " \u2014 " + scope.title : ""}`;
    const lands = scope.landedBy !== null ? `recorded done by ${longDate(scope.landedBy, view.today)}` : scope.move.projected !== null ? `lands ${scope.move.projected !== scope.move.planned ? "~" : ""}${longDate(scope.move.projected, view.today)}` : "nothing estimated to land";
    return h("section", {
      class: "v2-section detail"
    }, h("h2", {}, title3), h("div", {
      class: "detail-sub"
    }, verdictChip(scope), ` ${lands} \xB7 own work: ${own.done} of ${own.steps} steps, ${Math.round(own.doneDays * 4) / 4} of ${Math.round(own.days * 4) / 4} days done`, scope.key !== null ? h("span", {
      class: "planned"
    }, " \xB7 dates count everything before it; the chart shows its own work") : null), h("div", {
      class: "detail-grid"
    }, h("div", {}, holder, h("div", {
      class: "chart-key",
      html: burnupKey(basis, compared2)
    })), changesPanel(compared2 ? changes(view, scope) : null, scope, basis, view.today)));
  }
  function fold(title3, open, toggled, ...inner) {
    const details = h("details", {
      class: "v2-fold",
      open
    }, h("summary", {}, title3), ...inner);
    details.addEventListener("toggle", () => {
      if (details.open !== open) toggled(details.open);
    });
    return details;
  }
  function whatIf(view, state, on) {
    const efficiency = Math.round((view.plan.assumptions.efficiency ?? DEFAULT_EFFICIENCY) * 100);
    const focus2 = h("select", {
      onchange: (event) => on.state({
        whatIf: {
          ...state.whatIf,
          efficiency: Number(event.target.value) / 100
        }
      })
    });
    for (let value = 10; value <= 100; value += 5) {
      focus2.append(h("option", {
        value: String(value),
        selected: value === efficiency
      }, `${value}%`));
    }
    const start2 = h("input", {
      type: "date",
      value: isoDay(view.start),
      onchange: (event) => {
        const when = parseDay(event.target.value);
        if (when !== null) on.state({
          whatIf: {
            ...state.whatIf,
            start: when
          }
        });
      }
    });
    return fold("What if\u2026 the team, the focus or the start were different", state.folds.whatif, (open) => on.state({
      folds: {
        ...state.folds,
        whatif: open
      }
    }), h("p", {
      class: "planned"
    }, "Every tile is how long the plan takes with that team; picking one re-dates everything above for this day only. Nothing is saved."), h("div", {
      class: "row"
    }, h("label", {}, "Focus ", focus2), h("label", {}, "Start ", start2), Object.keys(state.whatIf).length ? h("button", {
      class: "link",
      onclick: () => on.state({
        whatIf: {}
      })
    }, "reset") : null), staffing(view, "calendar", (team2) => on.state({
      whatIf: {
        ...state.whatIf,
        team: team2
      }
    })));
  }
  function calendar(view, state, on) {
    return fold("Calendar", state.folds.calendar, (open) => on.state({
      folds: {
        ...state.folds,
        calendar: open
      }
    }), state.folds.calendar ? h("div", {}, h("div", {
      class: "pager"
    }, h("button", {
      title: "A month earlier",
      onclick: () => on.state({
        offset: state.offset - 1
      })
    }, "\u25C2"), h("button", {
      title: "A month later",
      onclick: () => on.state({
        offset: state.offset + 1
      })
    }, "\u25B8")), monthsView(view, state.scope, state.offset, {
      onDay: (day) => on.state({
        whatIf: {
          ...state.whatIf,
          start: day
        }
      })
    })) : null);
  }

  // src/ui/v3/state.ts
  var V3_START = {
    page: "milestones",
    then: {
      kind: "start"
    },
    scope: null,
    whatIf: {},
    offset: 0,
    asOf: null,
    adjust: false
  };

  // src/ui/v3/marks.ts
  var CHECK_R = 8;
  function landedCheck(x, y, color) {
    return `<circle cx="${n(x)}" cy="${n(y)}" r="${CHECK_R}" fill="${color}" class="landed-check"/><path d="M${n(x - 3.8)},${n(y + 0.2)} L${n(x - 1)},${n(y + 3)} L${n(x + 4)},${n(y - 3)}" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
  }

  // src/ui/v3/shifts.ts
  var ROW_H2 = 34;
  var LEFT2 = 230;
  var RIGHT2 = 80;
  var TOP2 = 28;
  var BOTTOM2 = 26;
  var DOT = 4.5;
  function arrow3(from, to, y, color) {
    const way = to >= from ? 1 : -1;
    const tip = to - way * (DOT + 2);
    if (Math.abs(tip - from) < 6) return "";
    return `<line x1="${n(from + way * (DOT + 1))}" x2="${n(tip)}" y1="${n(y)}" y2="${n(y)}" stroke="${color}" stroke-width="1.5" stroke-opacity="0.85"/><path d="M${n(tip)},${n(y)} L${n(tip - way * 6)},${n(y - 3.5)} L${n(tip - way * 6)},${n(y + 3.5)} Z" fill="${color}" fill-opacity="0.85"/>`;
  }
  function words(scope, view) {
    const today = view.now.day;
    const parts = [
      `${scope.badge} ${scope.label}${scope.title ? ` \u2014 ${scope.title}` : ""}`
    ];
    if (scope.move.then !== null) parts.push(`then: ${shortDate(scope.move.then, today)}`);
    if (scope.landedBy !== null) parts.push(`done by ${shortDate(scope.landedBy, today)}`);
    else if (scope.move.planned !== null) {
      parts.push(`plan now: ${shortDate(scope.move.planned, today)}`);
    }
    const stretch = lookingBack(view) ? void 0 : view.stretches.find((one) => one.key === scope.key);
    for (const step2 of stretch?.phase.steps.filter(isDelay) ?? []) parts.push(`waits: ${step2.title}`);
    return parts.join("\n");
  }
  function shiftsSvg(found, view, selected, width) {
    const today = view.now.day;
    const scopes = found.milestones.filter((scope) => scope.key);
    const days = [
      today
    ];
    for (const scope of scopes) {
      for (const day of [
        scope.move.then,
        scope.move.planned,
        scope.landedBy
      ]) {
        if (day !== null) days.push(day);
      }
    }
    for (const row of view.recording.saved) days.push(row.day);
    const [first, last] = [
      Math.min(...days) - 2,
      Math.max(...days) + 3
    ];
    const plotW = width - LEFT2 - RIGHT2;
    const x = (day) => LEFT2 + (day - first) / (last - first) * plotW;
    const height = TOP2 + Math.max(1, scopes.length) * ROW_H2 + BOTTOM2;
    const bottom2 = height - BOTTOM2;
    const out = [
      `<svg class="chart shifts" viewBox="0 0 ${n(width)} ${n(height)}" width="${n(width)}" height="${n(height)}" font-size="12">`
    ];
    const rows = [];
    const ticks2 = axisTicks(first, last, Math.max(1, Math.floor(plotW / 70)));
    for (const [when, label2] of ticks2) {
      out.push(`<line x1="${n(x(when))}" x2="${n(x(when))}" y1="${TOP2}" y2="${n(bottom2)}" style="stroke:${INK}" stroke-opacity="0.08"/>`);
      if (Math.abs(x(when) - x(today)) < 34) continue;
      out.push(`<text x="${n(x(when))}" y="${n(height - 8)}" text-anchor="middle" style="fill:${SECONDARY}" font-size="11">${esc(label2)}</text>`);
    }
    if (!scopes.length) {
      out.push(`<text x="${LEFT2}" y="${TOP2 + ROW_H2 / 2}" dominant-baseline="central" style="fill:${SECONDARY}">No milestones yet</text>`);
    }
    scopes.forEach((scope, index) => {
      const y = TOP2 + (index + 0.5) * ROW_H2;
      rows.push({
        key: scope.key,
        top: y - ROW_H2 / 2,
        bottom: y + ROW_H2 / 2
      });
      const faded = selected !== null && selected !== scope.key ? ` opacity="0.35"` : "";
      out.push(`<g class="shift-row"${faded}><title>${esc(words(scope, view))}</title>`);
      if (selected === scope.key) {
        out.push(`<rect x="0" y="${n(y - ROW_H2 / 2)}" width="${n(width)}" height="${ROW_H2}" class="row-picked"/>`);
      }
      out.push(`<line x1="${LEFT2}" x2="${n(LEFT2 + plotW)}" y1="${n(y)}" y2="${n(y)}" style="stroke:${INK}" stroke-opacity="0.08"/>`);
      const badgeW = textWidth(scope.badge, 10) + 10;
      out.push(`<rect x="8" y="${n(y - 8)}" width="${n(badgeW)}" height="16" rx="4" fill="${scope.color}"/>`);
      out.push(`<text x="${n(8 + badgeW / 2)}" y="${n(y)}" text-anchor="middle" dominant-baseline="central" fill="#fff" font-size="10" font-weight="600">${esc(scope.badge)}</text>`);
      out.push(`<text x="${n(16 + badgeW)}" y="${n(y)}" dominant-baseline="central" style="fill:${INK}" font-weight="600">${esc(scope.label)}</text>`);
      if (scope.title) {
        const room = Math.floor((LEFT2 - 24 - badgeW - textWidth(scope.label, 12) - 8) / (12 * 0.56));
        if (room > 4) {
          out.push(`<text x="${n(24 + badgeW + textWidth(scope.label, 12))}" y="${n(y)}" dominant-baseline="central" style="fill:${SECONDARY}">${esc(clip(scope.title, room))}</text>`);
        }
      }
      const then = scope.move.then;
      const done = scope.landedBy;
      const end = done ?? scope.move.planned;
      if (end !== null) {
        out.push(`<line x1="${n(x(end))}" x2="${n(x(end))}" y1="${n(y)}" y2="${n(bottom2)}" stroke="${scope.color}" stroke-opacity="0.3"/>`);
      }
      if (then !== null && end !== null && then !== end) {
        out.push(arrow3(x(then), x(end), y, scope.color));
      }
      if (then !== null) {
        out.push(`<circle cx="${n(x(then))}" cy="${n(y)}" r="${DOT + (then === end ? 2 : 0)}" style="fill:var(--surface)" stroke="${scope.color}" stroke-width="1.6"/>`);
      }
      if (done !== null) out.push(landedCheck(x(done), y, scope.color));
      else if (end !== null) {
        out.push(`<circle cx="${n(x(end))}" cy="${n(y)}" r="${DOT}" fill="${scope.color}"/>`);
      }
      const labels = [];
      if (end !== null) {
        const rightward = then === null || then <= end;
        const offset = (done !== null ? CHECK_R : DOT) + 6;
        labels.push([
          shortDate(end, today),
          rightward ? x(end) + offset : x(end) - offset,
          rightward ? "start" : "end",
          INK
        ]);
      }
      if (then !== null && then !== end) {
        const leftward = end === null || then <= end;
        labels.push([
          shortDate(then, today),
          leftward ? x(then) - DOT - 6 : x(then) + DOT + 6,
          leftward ? "end" : "start",
          SECONDARY
        ]);
      }
      const spans = labels.map(([text2, at, anchor]) => anchor === "start" ? [
        at,
        at + textWidth(text2, 11)
      ] : [
        at - textWidth(text2, 11),
        at
      ]);
      labels.forEach(([text2, at, anchor, ink], position) => {
        const [left, right] = spans[position];
        const clash = position === 1 && spans[0] && left < spans[0][1] && spans[0][0] < right;
        if (clash || left < LEFT2 - 4 || right > width - 2) return;
        out.push(`<text x="${n(at)}" y="${n(y)}" text-anchor="${anchor}" dominant-baseline="central" font-size="11" style="fill:${ink}">${esc(text2)}</text>`);
      });
      out.push(`</g>`);
    });
    for (const row of view.recording.saved) {
      const at = x(row.day);
      out.push(`<line x1="${n(at)}" x2="${n(at)}" y1="${TOP2 - 4}" y2="${n(bottom2)}" style="stroke:${INK}" stroke-opacity="0.4" stroke-dasharray="4 3"><title>${esc(`saved: ${row.title}`)}</title></line>`);
      out.push(`<text x="${n(at + 4)}" y="${TOP2 - 8}" style="fill:${SECONDARY}" font-size="11">${esc(clip(row.title, 20))}</text>`);
    }
    out.push(`<line x1="${n(x(today))}" x2="${n(x(today))}" y1="${TOP2 - 4}" y2="${n(bottom2)}" class="today-line"/>`);
    out.push(`<text x="${n(x(today))}" y="${n(height - 8)}" text-anchor="middle" font-size="11" font-weight="600" style="fill:${INK}" class="today-label">${esc(dayWord(view))}</text>`);
    out.push("</svg>");
    return {
      svg: out.join(""),
      rows
    };
  }

  // src/ui/v3/toolbar.ts
  var TABS = [
    [
      "milestones",
      "Milestones"
    ],
    [
      "work",
      "Work"
    ]
  ];
  function tabs(state, on, pages = TABS) {
    return h("span", {
      class: "v3-tabs",
      role: "tablist"
    }, ...pages.map(([page, name]) => h("button", {
      role: "tab",
      "aria-selected": String(state.page === page),
      class: state.page === page ? "on" : "",
      onclick: () => on.state({
        page
      })
    }, name)));
  }
  function showing(found, state, on) {
    const select = h("select", {
      title: "Which work the plots show: everything, or one milestone's own",
      onchange: (event) => {
        const value = event.target.value;
        on.state({
          scope: value === "*" ? null : value
        });
      }
    });
    select.append(h("option", {
      value: "*",
      selected: state.scope === null
    }, "All work"));
    for (const scope of found.milestones) {
      select.append(h("option", {
        value: scope.key ?? "",
        selected: state.scope === scope.key
      }, scope.badge ? `${scope.badge} ${scope.label}` : scope.label));
    }
    return h("label", {
      class: "showing"
    }, "Showing ", select);
  }
  function team(view, state, on) {
    const agents = view.report.hasAgentSteps ? AGENTS : [
      1
    ];
    const select = h("select", {
      title: "What if the team were different \u2014 how long the plan takes with each",
      onchange: (event) => {
        const [people, bots] = event.target.value.split("+").map(Number);
        on.state({
          whatIf: {
            ...state.whatIf,
            team: [
              people,
              bots
            ]
          }
        });
      }
    });
    for (const people of HUMANS) {
      for (const bots of agents) {
        const cell = cellAt(view.report.calendar, people, bots);
        const chosen = view.team[0] === people && (view.team[1] === bots || !view.report.hasAgentSteps);
        select.append(h("option", {
          value: `${people}+${bots}`,
          selected: chosen
        }, `${people} ${people === 1 ? "person" : "people"}${view.report.hasAgentSteps ? ` + ${bots} agent${bots === 1 ? "" : "s"}` : ""} \xB7 ${formatDays(cell.days)}`));
      }
    }
    return select;
  }
  function focus(view, state, on) {
    const current = Math.round((view.plan.assumptions.efficiency ?? DEFAULT_EFFICIENCY) * 100);
    const select = h("select", {
      title: "What if people gave this project a different share of their day",
      onchange: (event) => on.state({
        whatIf: {
          ...state.whatIf,
          efficiency: Number(event.target.value) / 100
        }
      })
    });
    for (let value = 10; value <= 100; value += 5) {
      select.append(h("option", {
        value: String(value),
        selected: value === current
      }, `${value}% focus`));
    }
    return select;
  }
  var opened = /* @__PURE__ */ new Set();
  document.addEventListener("pointerdown", (event) => {
    for (const menu of document.querySelectorAll("details.popover-menu[open]")) {
      if (!menu.contains(event.target)) menu.open = false;
    }
  });
  function popover(name, summary, panel, tone = "") {
    const details = h("details", {
      class: `popover-menu ${name}${tone}`,
      open: opened.has(name)
    }, summary, panel);
    details.addEventListener("toggle", () => {
      if (details.open) opened.add(name);
      else opened.delete(name);
    });
    return details;
  }
  function whatIfActive(state) {
    const { team: team2, efficiency, start: start2, begins } = state.whatIf;
    return team2 !== void 0 || efficiency !== void 0 || start2 !== void 0 || begins !== void 0;
  }
  function whatIf2(view, state, on) {
    const active = whatIfActive(state);
    const clear = () => {
      const { palette } = state.whatIf;
      on.state({
        whatIf: palette === void 0 ? {} : {
          palette
        }
      });
    };
    const menu = popover("what-if", h("summary", {
      title: active ? "A what-if is active: the dates are this team's and focus, and nothing is saved" : "What if the team, or its focus, were different"
    }, "What if\u2026"), h("div", {
      class: "menu-panel"
    }, h("label", {}, "Team ", team(view, state, on)), h("label", {}, "Focus ", focus(view, state, on))), active ? " active" : "");
    return active ? [
      menu,
      h("button", {
        class: "clear-what-if",
        title: "Back to the plan as it is",
        onclick: clear
      }, "\u2715")
    ] : [
      menu
    ];
  }
  function more(view, state, on, off) {
    if (off) return h("button", {
      class: "budget-off",
      disabled: true,
      title: off
    }, "\u22EF");
    const palette = h("select", {
      onchange: (event) => on.state({
        whatIf: {
          ...state.whatIf,
          palette: event.target.value
        }
      })
    });
    for (const found of PALETTES) {
      palette.append(h("option", {
        value: found.id,
        selected: found.id === paletteById(view.plan.assumptions.palette).id
      }, found.name));
    }
    return popover("more", h("summary", {
      title: "More"
    }, "\u22EF"), h("div", {
      class: "menu-panel"
    }, h("label", {}, "Milestone colours ", palette)));
  }
  function toolbar2(view, found, state, on) {
    return h("div", {
      class: "v3-toolbar"
    }, tabs(state, on), h("span", {
      class: "divider"
    }), comparePicker(view, state.then, (then) => on.state({
      then
    })), state.page === "work" ? showing(found, state, on) : null, h("span", {
      class: "spacer"
    }), ...whatIf2(view, state, on), saveButton(view, on.save), more(view, state, on));
  }

  // src/ui/v3/work.ts
  var LEFT3 = 52;
  var RIGHT3 = 90;
  var TOP3 = 30;
  var PLOT_H2 = 150;
  var GAP = 46;
  var BOTTOM3 = 26;
  var MARK = 8;
  var AXIS_STEPS = [
    1,
    1.5,
    2,
    3,
    4,
    5,
    7.5,
    10
  ];
  var HEADROOM = 1.05;
  function scopeMarks(jumps) {
    const byDay = /* @__PURE__ */ new Map();
    for (const jump of jumps) {
      const sum = byDay.get(jump.day);
      byDay.set(jump.day, sum ? {
        day: jump.day,
        steps: sum.steps + jump.steps,
        days: sum.days + jump.days
      } : jump);
    }
    return [
      ...byDay.values()
    ].flatMap((jump) => {
      const sign = Math.abs(jump.days) > 1e-9 ? Math.sign(jump.days) : Math.sign(jump.steps);
      return sign ? [
        {
          ...jump,
          direction: sign > 0 ? "up" : "down"
        }
      ] : [];
    });
  }
  function stepAt(points, day) {
    let found = null;
    for (const [when, value] of points) {
      if (when > day) break;
      found = value;
    }
    return found;
  }
  function stepsFrom(points, day) {
    const at = stepAt(points, day);
    return [
      ...at === null ? [] : [
        [
          day,
          at
        ]
      ],
      ...points.filter(([when]) => when > day)
    ];
  }
  function reachOf(view, key) {
    const series = burnup(view, key, false);
    const points = [
      ...series.scope,
      ...series.promised
    ];
    return {
      day: Math.max(view.now.day, ...points.map(([day]) => day)),
      days: Math.max(0, ...points.map(([, value]) => value))
    };
  }
  function delaySpans(view) {
    return view.stretches.flatMap(({ phase }) => phase.steps.filter(isDelay).flatMap((step2) => {
      const [begins, ends] = [
        phase.starts.get(step2.id),
        phase.landings.get(step2.id)
      ];
      if (begins === void 0 || ends === void 0 || ends - begins < 1e-9) return [];
      return [
        {
          title: step2.title,
          from: startDayOf(phase, step2.id),
          to: landingOf(phase, step2.id)
        }
      ];
    }));
  }
  function stepPath2(points, x, y, end) {
    if (!points.length) return "";
    let path = `M${n(x(points[0][0]))},${n(y(points[0][1]))}`;
    points.forEach((_, index) => {
      const next = index + 1 < points.length ? points[index + 1] : null;
      path += ` H${n(x(next ? next[0] : end))}`;
      if (next) path += ` V${n(y(next[1]))}`;
    });
    return path;
  }
  function scopeFills(points, baseline2, from, to, x, y) {
    return points.flatMap(([day, value], index) => {
      const [start2, end] = [
        Math.max(day, from),
        index + 1 < points.length ? points[index + 1][0] : to
      ];
      if (end <= start2 || Math.abs(value - baseline2) < 1e-9) return [];
      const [top, bottom2] = [
        y(Math.max(value, baseline2)),
        y(Math.min(value, baseline2))
      ];
      return [
        `<rect x="${n(x(start2))}" y="${n(top)}" width="${n(x(end) - x(start2))}" height="${n(bottom2 - top)}" class="scope-${value > baseline2 ? "up" : "down"}-fill"/>`
      ];
    });
  }
  function title2(name, keys, y, right) {
    const out = [
      `<text x="${LEFT3}" y="${n(y)}" dominant-baseline="central" font-size="12" font-weight="600" style="fill:${INK}">${esc(name)}</text>`
    ];
    let cursor = right;
    for (const [mark, words2] of [
      ...keys
    ].reverse()) {
      cursor -= words2.length * 6.2 + 4;
      out.push(`<text x="${n(cursor)}" y="${n(y)}" dominant-baseline="central" font-size="11" style="fill:${SECONDARY}">${esc(words2)}</text>`);
      cursor -= 22;
      out.push(`<g transform="translate(${n(cursor)},${n(y - 7)})">${mark}</g>`);
      cursor -= 12;
    }
    return out.join("");
  }
  function workSvg(data, marked, view, width, compared2, marks = {}) {
    const today = view.now.day;
    const days = [
      today,
      ...data.scope.map(([day]) => day),
      ...data.promised.map(([day]) => day)
    ];
    if (marks.reach) days.push(marks.reach.day);
    for (const one of marked) {
      for (const day of [
        one.move.planned,
        one.landedBy
      ]) if (day !== null) days.push(day);
    }
    const [first, last] = [
      Math.min(...days) - 1,
      Math.max(...days) + 2
    ];
    const top = niceCeiling(HEADROOM * Math.max(1, ...data.scope.map(([, v]) => v), ...data.promised.map(([, v]) => v), data.baseline ?? 0, marks.reach?.days ?? 0), AXIS_STEPS);
    const right = width - RIGHT3;
    const x = (day) => LEFT3 + (day - first) / (last - first) * (right - LEFT3);
    const scopeTop = TOP3;
    const workTop = TOP3 + PLOT_H2 + GAP;
    const scopeY = (value) => scopeTop + (1 - value / top) * PLOT_H2;
    const workY = (value) => workTop + (1 - value / top) * PLOT_H2;
    const height = workTop + PLOT_H2 + BOTTOM3;
    const out = [
      `<svg class="chart work" viewBox="0 0 ${n(width)} ${n(height)}" width="${n(width)}" height="${n(height)}" font-size="11">`
    ];
    for (const y of [
      scopeY,
      workY
    ]) {
      for (const share of [
        0,
        0.5,
        1
      ]) {
        out.push(`<line x1="${LEFT3}" x2="${n(right)}" y1="${n(y(top * share))}" y2="${n(y(top * share))}" style="stroke:${INK}" stroke-opacity="${share ? 0.1 : 0.25}"/>`);
        out.push(`<text x="${LEFT3 - 8}" y="${n(y(top * share))}" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${formatDays(top * share) || "0d"}</text>`);
      }
    }
    for (const [when, label2] of axisTicks(first, last, Math.max(1, Math.floor((right - LEFT3) / 70)))) {
      out.push(`<line x1="${n(x(when))}" x2="${n(x(when))}" y1="${scopeTop}" y2="${n(workTop + PLOT_H2)}" style="stroke:${INK}" stroke-opacity="0.07"/>`);
      if (Math.abs(x(when) - x(today)) < 34) continue;
      out.push(`<text x="${n(x(when))}" y="${n(height - 8)}" text-anchor="middle" style="fill:${SECONDARY}">${esc(label2)}</text>`);
    }
    const band = (from, to, fill, top2, label2) => {
      const [a, b] = [
        Math.max(LEFT3, from),
        Math.min(right, to)
      ];
      if (b - a < 0.5) return;
      out.push(`<rect x="${n(a)}" y="${n(top2)}" width="${n(b - a)}" height="${PLOT_H2}" ${fill}>${label2 ? `<title>${esc(label2)}</title>` : ""}</rect>`);
    };
    if (marks.weekends) {
      for (let day = first + 1; day <= last; day += 1) {
        if (isWorkingDay(day)) continue;
        for (const top2 of [
          scopeTop,
          workTop
        ]) band(x(day - 1), x(day), `class="weekend"`, top2);
      }
    }
    if (marks.delays) {
      const spans = delaySpans(view);
      if (spans.length) {
        out.push(`<defs><pattern id="delay-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" class="delay-fill"/><line x1="0" y1="0" x2="0" y2="6" class="delay-line"/></pattern></defs>`);
      }
      for (const span of spans) {
        for (const top2 of [
          scopeTop,
          workTop
        ]) {
          band(x(span.from), x(span.to), `fill="url(#delay-hatch)" class="delay"`, top2, span.title);
        }
        const at = Math.max(LEFT3, x(span.from)) + 4;
        if (at < right - 20) {
          out.push(`<text x="${n(at)}" y="${n(workTop + 12)}" font-size="10" class="delay-label">${esc(span.title)}</text>`);
        }
      }
    }
    const up = glyphPath({
      x: 9,
      y: 7,
      size: 8
    }, "up");
    const down = glyphPath({
      x: 9,
      y: 7,
      size: 8
    }, "down");
    const scopeKeys = [
      [
        `<line x1="0" x2="18" y1="7" y2="7" stroke="${PLAN}" stroke-width="2.5"/>`,
        "scope"
      ]
    ];
    if (compared2 && data.baseline !== null) {
      scopeKeys.push([
        `<line x1="0" x2="18" y1="7" y2="7" style="stroke:${SECONDARY}" stroke-dasharray="5 4"/>`,
        "then"
      ]);
    }
    scopeKeys.push([
      `<rect x="0" y="1" width="18" height="12" class="scope-up-fill"/><path d="${up}" class="scope-up-glyph"/>`,
      "added"
    ], [
      `<rect x="0" y="1" width="18" height="12" class="scope-down-fill"/><path d="${down}" class="scope-down-glyph"/>`,
      "removed"
    ]);
    out.push(title2("Scope", scopeKeys, scopeTop - 16, right));
    const scopeNow = data.scope.length ? data.scope[data.scope.length - 1][1] : 0;
    if (compared2 && data.baseline !== null && view.then) {
      out.push(...scopeFills(data.scope, data.baseline, view.then.day, today, x, scopeY));
      const at = scopeY(data.baseline);
      out.push(`<line x1="${n(x(view.then.day))}" x2="${n(right)}" y1="${n(at)}" y2="${n(at)}" style="stroke:${SECONDARY}" stroke-dasharray="5 4"/>`);
      const clash = Math.abs(at - scopeY(scopeNow)) < 13;
      out.push(`<text x="${n(right + 6)}" y="${n(at + (clash ? 7 : 0))}" dominant-baseline="central" style="fill:${SECONDARY}">${esc(`${formatDays(data.baseline) || "0d"} then`)}</text>`);
    }
    if (data.scope.length) {
      out.push(`<path d="${stepPath2(data.scope, x, scopeY, today)}" fill="none" stroke="${PLAN}" stroke-width="2.5"/>`);
      const clash = data.baseline !== null && Math.abs(scopeY(data.baseline) - scopeY(scopeNow)) < 13;
      out.push(`<text x="${n(right + 6)}" y="${n(scopeY(scopeNow) - (clash ? 7 : 0))}" dominant-baseline="central" fill="${PLAN}" font-weight="600">${esc(`${formatDays(scopeNow) || "0d"} now`)}</text>`);
    }
    for (const mark of scopeMarks(data.jumps)) {
      const level = stepAt(data.scope, mark.day) ?? 0;
      const glyph = {
        x: x(mark.day) + 6,
        y: scopeY(level) + MARK,
        size: MARK
      };
      const said = `${mark.steps >= 0 ? "+" : "\u2212"}${Math.abs(mark.steps)} step${Math.abs(mark.steps) === 1 ? "" : "s"}, ${mark.days >= 0 ? "+" : "\u2212"}${formatDays(Math.abs(mark.days)) || "0d"} on ${shortDate(mark.day, today)}`;
      out.push(`<path d="${glyphPath(glyph, mark.direction)}" class="scope-${mark.direction}-glyph scope-mark"><title>${esc(said)}</title></path>`);
    }
    const schedule = marks.idle ? `stroke-dasharray="5 3"` : `stroke-dasharray="1 3" stroke-linecap="round"`;
    const idle2 = `stroke-dasharray="0.5 4" stroke-linecap="round"`;
    out.push(title2("Work done", [
      [
        `<rect x="0" y="2" width="18" height="10" style="fill:${INK}" fill-opacity="0.15"/><line x1="0" x2="18" y1="2" y2="2" style="stroke:${INK}" stroke-width="2"/>`,
        "done"
      ],
      ...marks.idle ? [
        [
          `<line x1="0" x2="18" y1="7" y2="7" style="stroke:${INK}" stroke-width="2" ${idle2}/>`,
          "no status change"
        ]
      ] : [],
      [
        `<line x1="0" x2="18" y1="7" y2="7" style="stroke:${SECONDARY}" stroke-width="1.5" ${schedule}/>`,
        "the plan's schedule"
      ]
    ], workTop - 16, right));
    out.push(`<line x1="${LEFT3}" x2="${n(right)}" y1="${n(workY(scopeNow))}" y2="${n(workY(scopeNow))}" style="stroke:${PLAN}" stroke-opacity="0.35" stroke-dasharray="2 3"><title>${esc(`all of the work: ${formatDays(scopeNow) || "0d"}`)}</title></line>`);
    if (data.promised.length > 1) {
      out.push(`<path d="${stepPath2(data.promised, x, workY, data.promised[data.promised.length - 1][0])}" fill="none" style="stroke:${SECONDARY}" stroke-width="1.5" ${schedule}/>`);
    }
    if (data.done.length) {
      const line = stepPath2(data.done, x, workY, today);
      out.push(`<path d="${line} V${n(workY(0))} H${n(x(data.done[0][0]))} Z" style="fill:${INK}" fill-opacity="0.1"/>`);
      if (!marks.idle) {
        out.push(`<path d="${line}" fill="none" style="stroke:${INK}" stroke-width="2"/>`);
      } else {
        const active = new Set(data.active);
        const [solid, dotted] = [
          [],
          []
        ];
        let level = data.done[0][1];
        for (let day = data.done[0][0] + 1; day <= today; day += 1) {
          const y = workY(level);
          (active.has(day) ? solid : dotted).push(`M${n(x(day - 1))},${n(y)} H${n(x(day))}`);
          const next = stepAt(data.done, day) ?? level;
          if (next !== level) solid.push(`M${n(x(day))},${n(y)} V${n(workY(next))}`);
          level = next;
        }
        out.push(`<path d="${solid.join(" ")}" fill="none" style="stroke:${INK}" stroke-width="2"/>`);
        out.push(`<path d="${dotted.join(" ")}" fill="none" style="stroke:${INK}" stroke-width="2" ${idle2} class="idle"/>`);
      }
    }
    const labelled = [];
    for (const one of marked) {
      const done = one.landedBy;
      const day = done ?? one.move.planned;
      if (day === null) continue;
      const [cx, cy] = [
        x(day),
        workY((done !== null ? stepAt(data.done, day) : stepAt(data.promised, day)) ?? 0)
      ];
      const said = `${one.badge} ${one.label}${one.title ? ` \u2014 ${one.title}` : ""}
${done !== null ? "done by" : "the plan lands it"} ${shortDate(day, today)}`;
      out.push(`<g class="milestone-mark"><title>${esc(said)}</title>`);
      out.push(done !== null ? landedCheck(cx, cy, one.color) : `<circle cx="${n(cx)}" cy="${n(cy)}" r="5" fill="${one.color}" style="stroke:var(--surface)" stroke-width="1.5"/>`);
      const [lx, ly] = [
        cx,
        cy - (done !== null ? CHECK_R : 5) - 6
      ];
      if (!labelled.some(([ax, ay]) => Math.abs(ax - lx) < 28 && Math.abs(ay - ly) < 14)) {
        labelled.push([
          lx,
          ly
        ]);
        out.push(`<text x="${n(lx)}" y="${n(ly)}" text-anchor="middle" font-weight="600" style="fill:${INK}">${esc(one.label)}</text>`);
      }
      out.push("</g>");
    }
    for (const row of view.recording.saved) {
      if (row.day < first || row.day > last) continue;
      out.push(`<line x1="${n(x(row.day))}" x2="${n(x(row.day))}" y1="${scopeTop}" y2="${n(workTop + PLOT_H2)}" style="stroke:${INK}" stroke-opacity="0.35" stroke-dasharray="4 3"><title>${esc(`saved: ${row.title}`)}</title></line>`);
    }
    out.push(`<line x1="${n(x(today))}" x2="${n(x(today))}" y1="${scopeTop}" y2="${n(workTop + PLOT_H2)}" class="today-line"/>`);
    out.push(`<text x="${n(x(today))}" y="${n(height - 8)}" text-anchor="middle" font-weight="600" style="fill:${INK}">${esc(dayWord(view))}</text>`);
    out.push(`<line class="hover" x1="0" x2="0" y1="${scopeTop}" y2="${n(workTop + PLOT_H2)}" style="stroke:${INK}" stroke-opacity="0.5" visibility="hidden"/>`);
    out.push("</svg>");
    return {
      svg: out.join(""),
      geometry: {
        first,
        last,
        left: LEFT3,
        right,
        top: scopeTop,
        bottom: workTop + PLOT_H2,
        x,
        day: (px) => Math.round(first + (px - LEFT3) / (right - LEFT3) * (last - first)),
        scopeY,
        workY
      }
    };
  }

  // src/ui/v3/view.ts
  function v3View(view, state, on) {
    return tabbedView(view, state, (found) => toolbar2(view, found, state, on), (found) => state.page === "milestones" ? milestonesPage(found, view, state, on) : workPage(found, view, state));
  }
  function tabbedView(view, state, bar, page) {
    if (view.report.cycle.length) {
      const names = view.report.cycle.map((step2) => step2.title || "an untitled step").join(", ");
      return h("div", {
        class: "v3"
      }, h("div", {
        class: "banner error"
      }, `These steps wait on each other, so nothing can be dated: ${names}.`));
    }
    const found = brief(view);
    const basis = basisName(state.then, view);
    return h("div", {
      class: "v3"
    }, keyFigures(found, view, basis), bar(found), page(found));
  }
  function keyFigures(found, view, basis) {
    const whole = found.whole;
    const today = view.now.day;
    const figures = [];
    if (whole.landedBy !== null) {
      figures.push(h("span", {
        class: "figure lead",
        title: "All the work is done"
      }, `\u2713 ${formatDate(whole.landedBy, today)}`));
    } else if (whole.move.planned !== null) {
      figures.push(h("span", {
        class: "figure lead",
        title: "Where the plan lands, re-planned from today"
      }, formatDate(whole.move.planned, today)));
    }
    const moved = whole.move.plan;
    if (moved !== null) {
      figures.push(h("span", {
        class: `figure move tone-${moved > 0 ? "later" : moved < 0 ? "earlier" : "ok"}`,
        title: `Working days the landing moved against ${basis}`
      }, moved === 0 ? "\xB1 0d" : `${moved > 0 ? "\u25B6 +" : "\u25C0 \u2212"}${Math.abs(moved)}d`));
    }
    const share = shareOf(whole.own);
    if (share !== null) {
      figures.push(h("span", {
        class: "figure",
        title: `${g(whole.own.doneDays)} of ${g(whole.own.days)} days of work done`
      }, `${percent(share)} done`));
    }
    const unsized2 = lookingBack(view) ? [] : view.unestimated.filter((step2) => !step2.estimateOff);
    if (unsized2.length) {
      figures.push(h("span", {
        class: "figure tone-later",
        title: `No estimate, so counted as 0 days:
${unsized2.map((step2) => `${stepKey(step2)} ${step2.title}`).join("\n")}`
      }, `\u26A0 ${unsized2.length} unsized`));
    }
    if (lookingBack(view)) {
      figures.push(h("span", {
        class: "figure as-of",
        title: "The tab as it was recorded on that day \u2014 History \u25B8 back to today"
      }, `as recorded ${formatDate(today, view.today)}`));
    }
    return h("div", {
      class: "v3-figures"
    }, ...figures);
  }
  function milestonesPage(found, view, state, on, drill = true) {
    const holder = h("div", {
      class: "shifts-holder"
    });
    queueMicrotask(() => {
      const { svg, rows } = shiftsSvg(found, view, state.scope, Math.max(560, holder.clientWidth));
      holder.innerHTML = svg;
      const element = holder.querySelector("svg");
      const rowAt = (event) => {
        const box = element.getBoundingClientRect();
        const y = (event.clientY - box.top) * (element.viewBox.baseVal.height / box.height);
        return rows.find((row) => row.top <= y && y < row.bottom) ?? null;
      };
      element.addEventListener("click", (event) => {
        const row = rowAt(event);
        if (event.detail >= 2) {
          if (row && drill) on.state({
            scope: row.key,
            page: "work"
          });
        } else {
          on.state({
            scope: row && row.key !== state.scope ? row.key : null
          });
        }
      });
    });
    const key = h("div", {
      class: "v3-key"
    }, h("span", {}, h("span", {
      class: "k-then"
    }), "then"), h("span", {}, h("span", {
      class: "k-now"
    }), "plan now"), h("span", {}, h("span", {
      class: "k-done"
    }, "\u2713"), "done"), h("span", {
      class: "hint"
    }, drill ? "click a milestone to pick it \xB7 double-click to see its work" : "click a milestone to pick it"));
    return h("section", {
      class: "v3-page"
    }, holder, key);
  }
  function workPage(found, view, state, marks = {}) {
    const scopes = [
      found.whole,
      ...found.milestones
    ];
    const scope = scopes.find((one) => one.key === state.scope) ?? found.whole;
    const series = burnup(view, scope.key, found.compared);
    const data = {
      ...series,
      promised: stepsFrom(series.promised, view.now.day)
    };
    const named = found.milestones.filter((one) => one.key);
    const marked = scope.key !== null ? [
      scope
    ] : named.length ? named : [
      scope
    ];
    const holder = h("div", {
      class: "work-holder"
    });
    const tip = h("div", {
      class: "tooltip",
      hidden: true
    });
    queueMicrotask(() => {
      const { svg, geometry: geometry2 } = workSvg(data, marked, view, Math.max(560, holder.clientWidth), found.compared, marks);
      holder.innerHTML = svg;
      holder.append(tip);
      const element = holder.querySelector("svg");
      const line = element.querySelector(".hover");
      element.addEventListener("mousemove", (event) => {
        const box = element.getBoundingClientRect();
        const scale = element.viewBox.baseVal.width / box.width;
        const px = (event.clientX - box.left) * scale;
        if (px < geometry2.left || px > geometry2.right) {
          tip.hidden = true;
          line.setAttribute("visibility", "hidden");
          return;
        }
        const day = geometry2.day(px);
        line.setAttribute("x1", String(geometry2.x(day)));
        line.setAttribute("x2", String(geometry2.x(day)));
        line.setAttribute("visibility", "visible");
        const read = (label2, value) => value === null ? null : h("div", {}, `${label2}: ${g(Math.round(value * 4) / 4)}d`);
        const lines = [
          day <= view.now.day ? read("scope", stepAt(data.scope, day)) : null,
          day <= view.now.day ? read("done", stepAt(data.done, day)) : null,
          read("the plan's schedule", stepAt(data.promised, day))
        ].filter((one) => one !== null);
        tip.replaceChildren(h("b", {}, formatDate(day, view.now.day)), ...lines);
        tip.hidden = false;
        tip.style.left = `${Math.min(event.clientX - box.left + 14, box.width - 200)}px`;
        tip.style.top = `${event.clientY - box.top + 14}px`;
      });
      element.addEventListener("mouseleave", () => {
        tip.hidden = true;
        line.setAttribute("visibility", "hidden");
      });
    });
    return h("section", {
      class: "v3-page"
    }, holder);
  }

  // src/ui/v4/budget.ts
  function counts(label2, values, current, pick) {
    return h("div", {
      class: "budget-row"
    }, h("span", {
      class: "budget-label"
    }, label2), h("span", {
      class: "segmented",
      role: "group",
      "aria-label": label2
    }, ...values.map((value) => h("button", {
      class: value === current ? "on" : "",
      onclick: () => pick(value)
    }, String(value)))));
  }
  function budgetMenu(view, apply, off) {
    const now = budgetOf(view.plan);
    const percent2 = Math.round(now.efficiency * 100);
    const agents = view.report.hasAgentSteps;
    const focus2 = h("select", {
      onchange: (event) => apply({
        ...now,
        efficiency: Number(event.target.value) / 100
      })
    });
    for (let value = 10; value <= 100; value += 5) {
      focus2.append(h("option", {
        value: String(value),
        selected: value === percent2
      }, `${value}%`));
    }
    const people = `${now.humans} ${now.humans === 1 ? "person" : "people"}`;
    const summary = h("summary", {
      title: `${people}${agents ? ` and ${now.agents} agent${now.agents === 1 ? "" : "s"}` : ""}, at ${percent2}% focus \u2014 a change applies from this day on`
    }, "Budget ", h("span", {
      class: "budget-now"
    }, agents ? `${now.humans}p/${now.agents}a \xB7 ${percent2}%` : `${now.humans}p \xB7 ${percent2}%`));
    const panel = h("div", {
      class: "menu-panel budget-panel"
    }, counts("People", HUMANS, now.humans, (humans) => apply({
      ...now,
      humans
    })), agents ? counts("Agents", AGENTS, now.agents, (count2) => apply({
      ...now,
      agents: count2
    })) : null, h("div", {
      class: "budget-row"
    }, h("span", {
      class: "budget-label"
    }, "Focus"), focus2), h("div", {
      class: "budget-note"
    }, `From ${formatDate(view.today, view.today)} on; the days before keep theirs.`));
    if (off) {
      return h("button", {
        class: "budget-off",
        disabled: true,
        title: off
      }, ...summary.childNodes);
    }
    return popover("budget", summary, panel);
  }

  // src/ui/v4/view.ts
  function toolbar3(view, found, state, on) {
    return h("div", {
      class: "v3-toolbar"
    }, tabs(state, on), h("span", {
      class: "divider"
    }), comparePicker(view, state.then, (then) => on.state({
      then
    })), state.page === "work" ? showing(found, state, on) : null, h("span", {
      class: "spacer"
    }), budgetMenu(view, on.budget), saveButton(view, on.save), more(view, state, on));
  }
  var V4_MARKS = {
    weekends: true,
    idle: true,
    delays: true
  };
  function v4View(view, state, on) {
    return tabbedView(view, state, (found) => toolbar3(view, found, state, on), (found) => state.page === "milestones" ? milestonesPage(found, view, state, on) : workPage(found, view, state, V4_MARKS));
  }

  // src/ui/v5/efficiency.ts
  var pct = (share) => `${Math.round(share * 100)}%`;
  function efficiencyToggle(view, on, toggle2, off) {
    const { pace } = view;
    const planned = efficiencyOf(view.plan);
    const measured = pace === null ? null : planned * pace;
    const title3 = off ?? (pace === null || measured === null ? `Adjusting for efficiency needs ${PACE_AFTER} working days of work and ${PACE_STEPS} finished steps` : asPlanned(pace) ? `Finished steps ran at about the planned focus (${pct(measured)} against ${pct(planned)}): adjusting leaves the dates as they are` : `Finished steps ran at ${pct(measured)} focus against the ${pct(planned)} planned, taking ${(1 / pace).toFixed(1)}\xD7 their estimates: adjust what is left to it`);
    const applied = on && !off && pace !== null;
    return h("button", {
      class: `efficiency-toggle${applied ? " on" : ""}`,
      disabled: Boolean(off) || pace === null,
      title: title3,
      "aria-pressed": String(applied),
      onclick: () => toggle2(!on)
    }, measured === null || off ? "Adjust for efficiency" : `Adjust for efficiency \xB7 ${pct(measured)}`);
  }

  // src/ui/v5/history.ts
  var stepping = false;
  function historyMenu(view, on, recorded2, scrub) {
    const today = view.today;
    const days = [
      ...new Set(recorded2.filter((day) => day < today)),
      today
    ].sort((a, b) => a - b);
    const shown = view.now.day;
    const at = Math.max(0, days.findLastIndex((day) => day <= shown));
    const show = (index) => {
      const day = days[Math.max(0, Math.min(days.length - 1, index))];
      on.state({
        asOf: day === today ? null : day
      });
    };
    const said = (day) => day === today ? "today" : `as recorded ${formatDate(day, today)}`;
    const named = (day) => day === today ? "History" : `History \xB7 ${shortDate(day, today)}`;
    const label2 = h("span", {
      class: "history-day"
    }, said(days[at]));
    const back = lookingBack(view);
    const summary = h("summary", {
      title: back ? `Showing the tab as recorded ${formatDate(shown, today)}; nothing can be changed` : "Look back at the tab as it was recorded on an earlier day"
    }, named(shown));
    const slider2 = h("input", {
      type: "range",
      min: "0",
      max: String(days.length - 1),
      step: "1",
      value: String(at),
      "aria-label": "The day shown",
      oninput: () => {
        const day = days[Number(slider2.value)];
        label2.textContent = said(day);
        summary.textContent = named(day);
        scrub(day === today ? null : day);
      },
      onchange: () => {
        stepping = true;
        show(Number(slider2.value));
      }
    });
    if (stepping) {
      stepping = false;
      queueMicrotask(() => slider2.focus());
    }
    const step2 = (by, words2, glyph) => h("button", {
      title: words2,
      disabled: at + by < 0 || at + by >= days.length,
      onclick: () => show(at + by)
    }, glyph);
    const panel = h("div", {
      class: "menu-panel history-panel"
    }, h("div", {
      class: "history-row"
    }, step2(-1, "The record before", "\u25C2"), slider2, step2(1, "The record after", "\u25B8")), h("div", {
      class: "history-row"
    }, label2, back ? h("button", {
      class: "link",
      onclick: () => show(days.length - 1)
    }, "back to today") : null), h("div", {
      class: "budget-note"
    }, days.length > 1 ? `${days.length - 1} recorded day${days.length === 2 ? "" : "s"}, from ${shortDate(days[0], today)}. Looking back, the page reads each day's record; nothing is written.` : "Nothing recorded before today yet."));
    const menu = popover("history", summary, panel, back ? " active" : "");
    return back ? [
      menu,
      h("button", {
        class: "clear-active",
        title: "Back to today",
        onclick: () => show(days.length - 1)
      }, "\u2715")
    ] : [
      menu
    ];
  }

  // src/ui/v5/view.ts
  var PAGES2 = [
    ...TABS,
    [
      "calendar",
      "Calendar"
    ]
  ];
  var PAST = "History shows a recorded day: back to today to change the plan";
  var ASKED = "History shows the dates as they were recorded";
  function toolbar4(view, state, on, recorded2) {
    const off = lookingBack(view) ? PAST : void 0;
    return h("div", {
      class: "v3-toolbar"
    }, tabs(state, on, PAGES2), h("span", {
      class: "divider"
    }), comparePicker(view, state.then, (then) => on.state({
      then
    })), h("span", {
      class: "spacer"
    }), ...historyMenu(view, on, recorded2, on.scrub), budgetMenu(view, on.budget, off), efficiencyToggle(view, state.adjust, (adjust) => on.state({
      adjust
    }), off && ASKED), saveButton(view, on.save, off), more(view, state, on, off));
  }
  function calendarPage(view, state, on) {
    const waits = lookingBack(view) ? [] : delaySpans(view);
    const pager2 = h("div", {
      class: "pager"
    }, h("button", {
      title: "A month earlier",
      onclick: () => on.state({
        offset: state.offset - 1
      })
    }, "\u25C2"), h("button", {
      title: "A month later",
      onclick: () => on.state({
        offset: state.offset + 1
      })
    }, "\u25B8"), state.offset ? h("button", {
      class: "link",
      onclick: () => on.state({
        offset: 0
      })
    }, "from the start") : null);
    const key = h("div", {
      class: "v3-key"
    }, h("span", {}, h("span", {
      class: "k-lands"
    }), "lands"), h("span", {}, h("span", {
      class: "k-today"
    }), lookingBack(view) ? "the day shown" : "today"), waits.length ? h("span", {}, h("span", {
      class: "k-wait"
    }), "a wait") : null, h("span", {
      class: "hint"
    }, "weekends are pale: they are not counted"));
    return h("section", {
      class: "v3-page calendar-page"
    }, pager2, monthsView(view, state.scope, state.offset, {
      waits,
      months: 6,
      named: true
    }), key);
  }
  function v5View(view, state, on, recorded2, reach) {
    const marks = {
      ...V4_MARKS,
      delays: !lookingBack(view),
      reach
    };
    return tabbedView(view, state, () => toolbar4(view, state, on, recorded2), (found) => state.page === "milestones" ? milestonesPage(found, view, state, on, false) : state.page === "calendar" ? calendarPage(view, state, on) : workPage(found, view, {
      ...state,
      scope: null
    }, marks));
  }

  // src/ui/debugger/track.ts
  function seriesOf(plan, timeline3, today) {
    const colors = milestoneColors(plan, plan.assumptions.palette);
    const found = placed(plan).map((place) => place.step).filter(isMilestone).map((step2) => {
      const truth = timeline3.finished.get(step2.id) ?? null;
      return {
        key: step2.id,
        label: milestoneLabel(step2),
        color: colors.get(step2.id),
        truth: truth !== null && truth <= today ? truth : null
      };
    });
    const everything = plan.steps.map((step2) => timeline3.finished.get(step2.id) ?? null);
    const last = everything.every((day) => day !== null) ? Math.max(...everything) : null;
    found.push({
      key: null,
      label: "All work",
      color: WHOLE_COLOR,
      truth: last !== null && last <= today ? last : null
    });
    return found;
  }
  function forecasts(rows, key) {
    return rows.flatMap((row) => {
      const landing = landingIn(row, key);
      return landing === null || key !== null && !row.stretches.some((s) => s.key === key) ? [] : [
        [
          row.day,
          landing
        ]
      ];
    });
  }
  function trackRecord(timeline3, recording2, compared2, options, index) {
    const today = timeline3.frames[index].day;
    const plan = timeline3.frames[timeline3.frames.length - 1].plan;
    const rows = recording2.rows.filter((row) => row.day <= today);
    const others = compared2?.rows.filter((row) => row.day <= today) ?? [];
    const series = seriesOf(plan, timeline3, today);
    if (!rows.length) {
      return h("div", {
        class: "track"
      }, h("p", {
        class: "note"
      }, "Nothing recorded yet \u2014 scrub forward, or pick a recorder that runs on more days."));
    }
    return h("div", {
      class: "track"
    }, h("p", {
      class: "lede"
    }, "Each line is one milestone's landing date, as the plan said it on each recorded day. A forecast that holds is flat; ", "where a line meets the diagonal, that day is the landing it promised. \u25C6 marks where the milestone really landed.", compared2 ? " Dashed lines are DPlanner as it is today; solid ones are the model the page runs, re-planned from today with any variants switched on." : ""), h("div", {
      html: trendSvg(series, rows, others, today, timeline3)
    }), errorTable(series, rows, others, today, Boolean(compared2)), h("h3", {}, "What the Progress plot said each day"), h("p", {
      class: "lede"
    }, "The ahead/behind the Time tab printed beside today's dot, day by day \u2014 the only warning a reader gets that the plan is slipping."), h("div", {
      html: standingSvg(timeline3, recording2, options, index)
    }));
  }
  function trendSvg(series, rows, others, today, timeline3) {
    const [width, height, left, right, top, bottom2] = [
      1e3,
      380,
      70,
      60,
      16,
      30
    ];
    const lines = series.map((one) => forecasts(rows, one.key));
    const shadows = series.map((one) => forecasts(others, one.key));
    const days = [
      timeline3.frames[0].day,
      today
    ];
    for (const line of [
      ...lines,
      ...shadows
    ]) {
      for (const [made, lands] of line) days.push(made, lands);
    }
    for (const one of series) if (one.truth !== null) days.push(one.truth);
    const [xFirst, xLast] = [
      Math.min(...days.slice(0, 2), ...rows.map((row) => row.day)),
      today + 1
    ];
    const [yFirst, yLast] = [
      Math.min(...days) - 1,
      Math.max(...days) + 2
    ];
    const x = (day) => left + (day - xFirst) / Math.max(1, xLast - xFirst) * (width - left - right);
    const y = (day) => top + (1 - (day - yFirst) / Math.max(1, yLast - yFirst)) * (height - top - bottom2);
    const out = [
      `<svg class="chart" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" font-size="11">`
    ];
    for (const [when, label2] of axisTicks(xFirst, xLast, 10)) {
      out.push(`<line x1="${n(x(when))}" x2="${n(x(when))}" y1="${top}" y2="${height - bottom2}" style="stroke:${INK}" stroke-opacity="0.1"/>`);
      out.push(`<text x="${n(x(when))}" y="${height - bottom2 + 15}" text-anchor="middle" style="fill:${SECONDARY}">${esc(label2)}</text>`);
    }
    for (const [when, label2] of axisTicks(yFirst, yLast, 8)) {
      out.push(`<line x1="${left}" x2="${width - right}" y1="${n(y(when))}" y2="${n(y(when))}" style="stroke:${INK}" stroke-opacity="0.1"/>`);
      out.push(`<text x="${left - 8}" y="${n(y(when))}" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${esc(label2)}</text>`);
    }
    const low = Math.max(xFirst, yFirst);
    const high = Math.min(xLast, yLast);
    out.push(`<line x1="${n(x(low))}" y1="${n(y(low))}" x2="${n(x(high))}" y2="${n(y(high))}" style="stroke:${INK}" stroke-opacity="0.35" stroke-dasharray="2 3"><title>today: a forecast on this line is due that very day</title></line>`);
    const step2 = (line, end) => line.flatMap(([made, lands], index) => {
      const until2 = index + 1 < line.length ? line[index + 1][0] : end;
      return [
        `${n(x(made))},${n(y(lands))}`,
        `${n(x(until2))},${n(y(lands))}`
      ];
    }).join(" ");
    const labelled = [];
    series.forEach((one, index) => {
      const end = one.truth !== null ? Math.min(one.truth, today) : today;
      const before = ([made]) => one.truth !== null ? made < end : made <= end;
      if (one.truth !== null) {
        out.push(`<line x1="${left}" x2="${n(x(one.truth))}" y1="${n(y(one.truth))}" y2="${n(y(one.truth))}" stroke="${one.color}" stroke-opacity="0.35" stroke-dasharray="1 3"/>`);
      }
      if (shadows[index].length) {
        out.push(`<polyline points="${step2(shadows[index].filter(before), end)}" fill="none" stroke="${one.color}" stroke-width="1.5" stroke-dasharray="5 4" stroke-opacity="0.8"/>`);
      }
      const line = lines[index].filter(before);
      if (line.length) {
        out.push(`<polyline points="${step2(line, end)}" fill="none" stroke="${one.color}" stroke-width="${one.key === null ? 1.5 : 2}"><title>${esc(one.label)}</title></polyline>`);
        let at = y(line[line.length - 1][1]);
        while (labelled.some((taken) => Math.abs(taken - at) < 12)) at += 12;
        labelled.push(at);
        out.push(`<text x="${n(Math.min(x(end), width - right) + 4)}" y="${n(at)}" dominant-baseline="central" style="fill:${SECONDARY}">${esc(one.label)}</text>`);
      }
      if (one.truth !== null) {
        const [cx, cy] = [
          x(one.truth),
          y(one.truth)
        ];
        out.push(`<path d="M${n(cx)},${n(cy - 6)} L${n(cx + 6)},${n(cy)} L${n(cx)},${n(cy + 6)} L${n(cx - 6)},${n(cy)} Z" fill="${one.color}"><title>${esc(one.label)} really landed ${esc(formatDate(one.truth, today))}</title></path>`);
      }
    });
    out.push(`<text x="${left}" y="${height - 4}" style="fill:${SECONDARY}">day the forecast was recorded \u2192</text>`);
    out.push(`<text x="10" y="${top + 4}" style="fill:${SECONDARY}">lands \u2191</text>`);
    out.push("</svg>");
    return out.join("");
  }
  function errorTable(series, rows, others, today, compared2) {
    const table = h("table", {
      class: "errors"
    });
    table.append(h("thead", {}, h("tr", {}, ...[
      "Milestone",
      "Really landed",
      "Said at the start",
      "at \xBC of the way",
      "at \xBD",
      "at \xBE",
      "last before landing"
    ].map((name) => h("th", {}, name)))));
    const body2 = h("tbody");
    for (const one of series) {
      const cells = (source) => {
        const line = forecasts(source, one.key);
        if (!line.length) return Array(5).fill("\u2014");
        const said = (row) => row ? landingIn(row, one.key) : null;
        const first = line[0][0];
        const truth = one.truth;
        const at = (share) => {
          if (truth === null) return null;
          return said(baseline(source, first + Math.round((truth - first) * share)));
        };
        const lastBefore = truth === null ? null : said(baseline(source, truth - 1));
        const picks = [
          line[0][1],
          at(0.25),
          at(0.5),
          at(0.75),
          lastBefore
        ];
        return picks.map((forecast) => {
          if (forecast === null) return "\u2014";
          if (truth === null) return shortDate(forecast, today);
          const shift = landingShift(forecast, truth);
          return `${shortDate(forecast, today)} (${shift === 0 ? "exact" : `${shift > 0 ? "+" : ""}${shift}d`})`;
        });
      };
      const mine = cells(rows);
      const theirs = compared2 ? cells(others) : null;
      body2.append(h("tr", {}, h("td", {}, h("span", {
        class: "badge",
        style: `background:${one.color}`
      }), one.label), h("td", {}, one.truth !== null ? shortDate(one.truth, today) : "not yet"), ...mine.map((text2, index) => h("td", {
        class: "number"
      }, text2, theirs ? h("div", {
        class: "subtitle"
      }, `today's model: ${theirs[index]}`) : null))));
    }
    table.append(body2);
    return h("div", {}, table, h("p", {
      class: "note"
    }, "(+3d) means it really landed three working days after that forecast; (\u22122d), two before it. \xBC, \xBD and \xBE are points between the first record and the real landing."));
  }
  function standingSvg(timeline3, recording2, options, index) {
    const [width, height, left, right, top, bottom2] = [
      1e3,
      150,
      70,
      60,
      12,
      26
    ];
    const points = [];
    for (const frame of timeline3.frames.slice(0, index + 1)) {
      const live = snapshotOf(frame.plan, frame.day, options);
      if (!live) continue;
      const rows = recording2.rows.filter((row) => row.day <= frame.day);
      const found = standing(expected(live, null), actual(rows, live, null), frame.day);
      if (found !== null) points.push([
        frame.day,
        found
      ]);
    }
    if (!points.length) return `<p class="note">No reading yet.</p>`;
    const reach = Math.max(0.1, ...points.map(([, value]) => Math.abs(value)));
    const [first, last] = [
      points[0][0],
      Math.max(points[points.length - 1][0], points[0][0] + 1)
    ];
    const x = (day) => left + (day - first) / (last - first) * (width - left - right);
    const y = (value) => top + (1 - (value + reach) / (2 * reach)) * (height - top - bottom2);
    const out = [
      `<svg class="chart" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" font-size="11">`
    ];
    for (const [value, label2] of [
      [
        reach,
        "ahead"
      ],
      [
        0,
        "on plan"
      ],
      [
        -reach,
        "behind"
      ]
    ]) {
      out.push(`<line x1="${left}" x2="${width - right}" y1="${n(y(value))}" y2="${n(y(value))}" style="stroke:${INK}" stroke-opacity="${value ? 0.1 : 0.35}"/>`);
      out.push(`<text x="${left - 8}" y="${n(y(value))}" text-anchor="end" dominant-baseline="central" style="fill:${SECONDARY}">${label2}</text>`);
    }
    for (const [when, label2] of axisTicks(first, last, 10)) {
      out.push(`<text x="${n(x(when))}" y="${height - 8}" text-anchor="middle" style="fill:${SECONDARY}">${esc(label2)}</text>`);
    }
    out.push(`<polyline points="${points.map(([d, v]) => `${n(x(d))},${n(y(v))}`).join(" ")}" fill="none" style="stroke:${INK}" stroke-width="1.5"/>`);
    for (const [day, value] of points) {
      out.push(`<circle cx="${n(x(day))}" cy="${n(y(value))}" r="2.5" style="fill:${INK}"><title>${esc(formatDate(day, day))}: ${esc(standingWords(value))}</title></circle>`);
    }
    out.push("</svg>");
    return out.join("");
  }

  // src/main.ts
  var VERSIONS = [
    [
      "v1",
      "v1 \xB7 today"
    ],
    [
      "v2",
      "v2"
    ],
    [
      "v3",
      "v3"
    ],
    [
      "v4",
      "v4"
    ],
    [
      "v5",
      "v5 \xB7 latest"
    ]
  ];
  var VERSION_KEY = "te2.version";
  function readVersion() {
    try {
      const stored = localStorage.getItem(VERSION_KEY);
      return VERSIONS.find(([version]) => version === stored)?.[0] ?? "v5";
    } catch {
      return "v5";
    }
  }
  var FOLDS_KEY = "te2.debugger";
  var exports = /* @__PURE__ */ new Map();
  var app = {
    source: "sample",
    seed: 1,
    scenario: SCENARIOS[0].id,
    world: {
      ...DEFAULT_WORLD,
      ...SCENARIOS[0].world
    },
    cadence: "weekdays",
    options: {
      ...ADOPTED
    },
    frame: -1,
    version: readVersion(),
    view: {
      picked: null,
      then: AT_START,
      now: LIVE,
      lens: "calendar",
      page: "progress",
      whatIf: {}
    },
    v2: V2_START,
    v3: V3_START,
    v4: V3_START,
    v5: V3_START,
    saved: [],
    edits: NO_EDITS,
    offset: 0,
    locked: false
  };
  var folds = readFolds();
  function readFolds() {
    const fallback = {
      open: true,
      setup: true,
      track: false,
      records: false
    };
    try {
      return {
        ...fallback,
        ...JSON.parse(localStorage.getItem(FOLDS_KEY) ?? "{}")
      };
    } catch {
      return fallback;
    }
  }
  function fold2(patch) {
    folds = {
      ...folds,
      ...patch
    };
    try {
      localStorage.setItem(FOLDS_KEY, JSON.stringify(folds));
    } catch {
    }
    body.hidden = !folds.open;
    toggle.textContent = folds.open ? "\u25BE Debugger" : "\u25B8 Debugger";
    renderContent();
  }
  var timelineKey = "";
  var timelineBase = "";
  var timeline2;
  var replayed = null;
  var recordingKey = "";
  var recording;
  var compared = null;
  function currentTimeline() {
    const base = JSON.stringify([
      app.source,
      app.seed,
      app.world
    ]);
    const key = JSON.stringify([
      base,
      app.edits
    ]);
    if (key !== timelineKey) {
      const kept = base === timelineBase ? timeline2.frames[app.frame]?.day : void 0;
      [timelineKey, timelineBase] = [
        key,
        base
      ];
      const file = exports.get(app.source);
      const played = file ? replay(file) : run(samplePlan(app.seed), {
        ...app.world,
        seed: app.seed,
        budgets: [
          ...app.world.budgets,
          ...worldBudgets(app.edits, SAMPLE_START)
        ],
        delays: [
          ...app.world.delays,
          ...worldDelays(app.edits, SAMPLE_START)
        ]
      }, SAMPLE_START);
      timeline2 = file ? edited(played, app.edits) : played;
      replayed = file ? parity(played) : null;
      const at = kept === void 0 ? -1 : timeline2.frames.findIndex((f) => f.day === kept);
      if (at >= 0) {
        app.frame = at;
      } else {
        app.frame = file ? timeline2.frames.length - 1 : Math.min(timeline2.frames.length - 1, timeline2.frames.findIndex((f) => f.day === timeline2.begin) + 14);
        app.offset = 0;
      }
    }
    return timeline2;
  }
  function savedSpecs() {
    if (timeline2.kind === "replay") return app.saved;
    return [
      ...SAVED_BY_DEFAULT.map((one) => ({
        day: timeline2.begin + one.after,
        title: one.title,
        note: one.note
      })),
      ...app.saved
    ];
  }
  function currentRecording() {
    const key = JSON.stringify([
      timelineKey,
      app.options,
      app.cadence,
      app.saved
    ]);
    if (key !== recordingKey) {
      recordingKey = key;
      const spec = {
        options: app.options,
        cadence: app.cadence,
        saved: savedSpecs(),
        seed: app.seed
      };
      recording = record(timeline2, spec);
      compared = app.cadence !== "stored" ? record(timeline2, {
        ...spec,
        options: FAITHFUL
      }) : null;
    }
    return recording;
  }
  var root = document.getElementById("app");
  var content;
  var body;
  var toggle;
  var happened;
  var trackHost;
  var recordsHost;
  var viewTitle;
  function render() {
    currentTimeline();
    currentRecording();
    root.replaceChildren(debuggerBar(), debuggerBody(), viewFrame());
    renderContent();
    writeHash();
  }
  function renderContent() {
    const frame = timeline2.frames[app.frame];
    const upToDay = recordedBy(recording, frame.day);
    content.replaceChildren(app.version === "v3" || app.version === "v4" || app.version === "v5" ? tabbedContent(app.version, frame.plan, frame.day, upToDay) : app.version === "v2" ? v2Content(frame.plan, frame.day, upToDay) : v1Content(frame.plan, frame.day, upToDay));
    viewTitle.textContent = `${frame.plan.title} \u2014 Time Estimates`;
    viewTitle.dataset.version = app.version;
    happened.replaceChildren(events(frame.events));
    trackHost.replaceChildren(folds.open && folds.track ? trackRecord(timeline2, recording, compared, app.options, app.frame) : "");
    recordsHost.replaceChildren(folds.open && folds.records ? recordsView(timeline2, recording, app.frame, replayed) : "");
    updateBar();
  }
  function viewFrame() {
    viewTitle = h("span", {
      class: "view-tab"
    });
    content = h("main");
    return h("section", {
      class: "view"
    }, h("div", {
      class: "view-tabs"
    }, viewTitle), content);
  }
  var NO_STEPS = "No steps yet \u2014 the staffing grid and the calendar date a plan once it has some.";
  function saver(day, upToDay) {
    return (title3, note) => {
      const named = title3.trim();
      if (!named) return "A snapshot needs a title.";
      if (upToDay.saved.some((row) => row.title.toLowerCase() === named.toLowerCase()) || app.saved.some((one) => one.title.toLowerCase() === named.toLowerCase())) {
        return `A snapshot called \u201C${named}\u201D is already saved.`;
      }
      app.saved = [
        ...app.saved,
        {
          day,
          title: named,
          note: note.trim()
        }
      ];
      currentRecording();
      renderContent();
      return null;
    };
  }
  function v1Content(plan, day, upToDay) {
    const view = present(plan, day, upToDay, app.view, app.options);
    if (!view) return h("div", {
      class: "empty"
    }, NO_STEPS);
    return timeTab(view, app.view, {
      view: (patch) => {
        app.view = {
          ...app.view,
          ...patch
        };
        renderContent();
      },
      whatIf: (patch) => {
        app.view = {
          ...app.view,
          whatIf: patch === null ? {} : {
            ...app.view.whatIf,
            ...patch
          }
        };
        renderContent();
      },
      save: saver(day, upToDay),
      offset: app.offset,
      page: (offset) => {
        app.offset = offset;
        renderContent();
      }
    });
  }
  function v2Content(plan, day, upToDay) {
    const state = app.v2;
    const view = present(plan, day, upToDay, {
      picked: state.scope,
      then: resolvePick(state.then, day),
      now: LIVE,
      lens: "calendar",
      page: "progress",
      whatIf: state.whatIf
    }, app.options);
    if (!view) return h("div", {
      class: "empty"
    }, NO_STEPS);
    return v2View(view, state, {
      state: (patch) => {
        app.v2 = {
          ...app.v2,
          ...patch
        };
        renderContent();
        writeHash();
      },
      save: saver(day, upToDay)
    });
  }
  function tabbedContent(version, plan, day, upToDay) {
    const state = app[version];
    const asOf = state.asOf !== null && state.asOf < day ? state.asOf : null;
    const view = present(plan, day, asOf === null ? upToDay : recordedBy(upToDay, asOf), {
      picked: state.scope,
      then: resolvePick(state.then, asOf ?? day),
      now: asOf === null ? LIVE : {
        kind: "day",
        day: asOf
      },
      lens: "calendar",
      page: "progress",
      whatIf: state.whatIf
    }, {
      ...app.options,
      pace: version === "v5" && state.adjust
    });
    if (!view) return h("div", {
      class: "empty"
    }, NO_STEPS);
    const handlers = {
      state: (patch) => {
        app[version] = {
          ...app[version],
          ...patch
        };
        renderContent();
        writeHash();
      },
      save: saver(day, upToDay)
    };
    if (version === "v3") return v3View(view, state, handlers);
    const budgeted = {
      ...handlers,
      budget: (budget) => {
        const before = timeline2.frames[app.frame - 1]?.plan ?? plan;
        app.edits = rebudget(app.edits, day, budget, budgetOf(before));
        render();
      }
    };
    if (version === "v4") return v4View(view, state, budgeted);
    const scrubbed = {
      ...budgeted,
      // While History's slider moves: the view redrawn around the toolbar that holds it.
      scrub: (asOf2) => {
        app.v5 = {
          ...app.v5,
          asOf: asOf2
        };
        const live = content.firstElementChild;
        const fresh = tabbedContent(version, plan, day, upToDay);
        if (live) redrawAround(live, fresh, [
          ".v3-toolbar",
          ".popover-menu.history"
        ]);
        else content.replaceChildren(fresh);
        writeHash();
      }
    };
    const reach = app.locked ? runReach(state) : void 0;
    return v5View(view, state, scrubbed, upToDay.rows.map((row) => row.day), reach);
  }
  function redrawAround(live, fresh, path) {
    const [selector, ...deeper] = path;
    const kept = live.querySelector(`:scope > ${selector}`);
    const children = [
      ...fresh.children
    ];
    const at = children.findIndex((child) => child.matches(selector));
    if (!kept || at < 0) {
      live.replaceWith(fresh);
      return;
    }
    for (const child of [
      ...live.children
    ]) if (child !== kept) child.remove();
    kept.before(...children.slice(0, at));
    kept.after(...children.slice(at + 1));
    if (deeper.length) redrawAround(kept, children[at], deeper);
  }
  function runReach(state) {
    const last = timeline2.frames[timeline2.frames.length - 1];
    const landed = last.plan.steps.every((step2) => isDelay(step2) || step2.status === "done");
    const end = landed && timeline2.finished.size ? Math.max(...timeline2.finished.values()) : last.day;
    const frame = timeline2.frames.find((one) => one.day === end) ?? last;
    const view = present(frame.plan, frame.day, recordedBy(recording, frame.day), {
      picked: state.scope,
      then: resolvePick(state.then, frame.day),
      now: LIVE,
      lens: "calendar",
      page: "progress",
      whatIf: {}
    }, app.options);
    return view ? reachOf(view, null) : void 0;
  }
  function section(key, name, ...inner) {
    const details = h("details", {
      class: "debug-section",
      open: folds[key]
    }, h("summary", {}, name), ...inner);
    details.addEventListener("toggle", () => {
      if (details.open !== folds[key]) fold2({
        [key]: details.open
      });
    });
    return details;
  }
  function debuggerBody() {
    happened = h("div", {
      class: "happened"
    });
    trackHost = h("div");
    recordsHost = h("div");
    body = h("section", {
      class: "debug debug-body",
      hidden: !folds.open
    }, section("setup", "Plan, scenario and model", ...setupRows()), happened, section("track", "Track record \u2014 how good the forecasts were", trackHost), section("records", "Records \u2014 what progress_history.json holds", recordsHost));
    return body;
  }
  function setupRows() {
    const file = exports.get(app.source);
    const source = h("select", {
      onchange: (event) => {
        app.source = event.target.value;
        app.cadence = exports.has(app.source) ? "stored" : scenarioById(app.scenario).cadence ?? "weekdays";
        app.saved = [];
        app.edits = NO_EDITS;
        app.view = {
          ...app.view,
          whatIf: {},
          picked: null,
          then: AT_START,
          now: LIVE
        };
        app.v2 = {
          ...app.v2,
          whatIf: {},
          scope: null
        };
        app.v3 = {
          ...app.v3,
          whatIf: {},
          scope: null
        };
        app.v4 = {
          ...app.v4,
          whatIf: {},
          scope: null
        };
        app.v5 = {
          ...app.v5,
          whatIf: {},
          scope: null,
          asOf: null
        };
        render();
      }
    }, h("option", {
      value: "sample",
      selected: !file
    }, "Synthetic sample plan"), ...[
      ...exports.values()
    ].map((one) => h("option", {
      value: one.slug,
      selected: one.slug === app.source
    }, `Replay: ${one.title} (${one.slug}, ${one.frames.length} commits)`)));
    const open = h("input", {
      type: "file",
      accept: ".json",
      onchange: async (event) => {
        const chosen = event.target.files?.[0];
        if (chosen) adopt(JSON.parse(await chosen.text()));
      }
    });
    const rows = [
      h("div", {
        class: "row"
      }, h("label", {}, "Plan ", source), file ? null : h("label", {}, "seed ", h("input", {
        type: "number",
        value: String(app.seed),
        class: "short",
        onchange: (event) => {
          app.seed = Number(event.target.value) || 1;
          app.saved = [];
          app.edits = NO_EDITS;
          render();
        }
      })), h("label", {
        class: "open",
        title: "An export written by tools/export_plan.ts \u2014 or drop one anywhere on the page"
      }, "open an export\u2026 ", open))
    ];
    if (!file) rows.push(scenarioRow());
    rows.push(editsRow());
    rows.push(modelRow(Boolean(file)));
    rows.push(h("div", {
      class: "row"
    }, h("label", {
      title: "Scrubbing then moves only the lines \u2014 for reading the days in turn, or a recording"
    }, h("input", {
      type: "checkbox",
      checked: app.locked,
      onchange: (event) => {
        app.locked = event.target.checked;
        render();
      }
    }), " Lock the Work plot's axes to the whole run (v5)")));
    return rows;
  }
  function editsRow() {
    const frame = timeline2.frames[app.frame];
    const byId2 = new Map(frame.plan.steps.map((step2) => [
      step2.id,
      step2
    ]));
    const waiting = frame.plan.steps.filter((step2) => step2.status === "pending" && !isDelay(step2));
    const before = h("select", {
      title: "The step that waits: it starts no earlier than the delay allows"
    }, ...waiting.map((step2) => h("option", {
      value: step2.id
    }, `${stepKey(step2)} ${step2.title}`)));
    const until2 = h("input", {
      type: "date",
      value: isoDay(frame.day + 7)
    });
    const days = h("input", {
      type: "number",
      class: "short",
      value: "3",
      min: "1",
      step: "1",
      hidden: true
    });
    const kind = h("select", {
      onchange: () => {
        until2.hidden = kind.value === "days";
        days.hidden = !until2.hidden;
      }
    }, h("option", {
      value: "until"
    }, "until"), h("option", {
      value: "days"
    }, "for working days"));
    const add = () => {
      const wait = kind.value === "days" ? Number(days.value) > 0 ? {
        days: Number(days.value)
      } : null : (() => {
        const day = parseDay(until2.value);
        return day === null ? null : {
          until: day
        };
      })();
      if (!wait || !before.value) return;
      const edit = {
        day: frame.day,
        before: before.value,
        delay: wait
      };
      app.edits = {
        ...app.edits,
        delays: [
          ...app.edits.delays,
          edit
        ]
      };
      render();
    };
    const made = app.edits.delays.map((edit, index) => {
      const held = byId2.get(edit.before);
      return h("span", {
        class: "edit"
      }, `${waitTitle(edit.delay)} before ${held ? stepKey(held) : edit.before} \xB7 made ${shortDate(edit.day, frame.day)} `, h("button", {
        class: "link",
        title: "Remove this delay",
        onclick: () => {
          app.edits = {
            ...app.edits,
            delays: app.edits.delays.filter((_, at) => at !== index)
          };
          render();
        }
      }, "\u2715"));
    });
    return h("div", {
      class: "row edits"
    }, h("span", {
      class: "label"
    }, "Plan edits:"), waiting.length ? h("span", {
      class: "add-delay"
    }, "add a delay before ", before, " ", kind, " ", until2, days, " ", h("button", {
      onclick: add
    }, "Add")) : h("span", {
      class: "note"
    }, "nothing left that has not started"), ...made);
  }
  function scenarioRow() {
    const scenario = scenarioById(app.scenario);
    const select = h("select", {
      onchange: (event) => {
        const chosen = scenarioById(event.target.value);
        app.scenario = chosen.id;
        app.world = {
          ...DEFAULT_WORLD,
          ...chosen.world
        };
        app.cadence = chosen.cadence ?? "weekdays";
        app.saved = [];
        app.edits = NO_EDITS;
        render();
      }
    }, ...SCENARIOS.map((one) => h("option", {
      value: one.id,
      selected: one.id === app.scenario
    }, one.name)));
    const number = (key, label2, step2, hint) => h("label", {
      title: hint
    }, `${label2} `, h("input", {
      type: "number",
      class: "short",
      step: String(step2),
      value: String(app.world[key] ?? ""),
      placeholder: "as stored",
      onchange: (event) => {
        const raw = event.target.value;
        app.world[key] = raw === "" ? null : Number(raw);
        render();
      }
    }));
    const flag = (key, label2) => h("label", {}, h("input", {
      type: "checkbox",
      checked: app.world[key],
      onchange: (event) => {
        app.world = {
          ...app.world,
          [key]: event.target.checked
        };
        render();
      }
    }), ` ${label2}`);
    const world = h("details", {
      class: "world"
    }, h("summary", {}, "Adjust the world"), h("div", {
      class: "params"
    }, number("humanBias", "human effort \xD7", 0.05, "True effort \xF7 estimate for human steps"), number("agentBias", "agent effort \xD7", 0.05, "True effort \xF7 estimate for agent steps"), number("noise", "noise \u03C3", 0.05, "Each step's own luck: lognormal spread around the bias"), number("unestimatedEffort", "unsized step days", 0.25, "What a step nobody estimated really takes"), number("focus", "real focus", 0.05, "The share of a day people really give; empty = what the plan assumes"), number("agentLoad", "supervision", 0.05, "Share of a person's day each running agent step takes"), number("scopePerWeek", "steps added / week", 0.5, "Scope creep into the milestone being worked"), number("reestimateEvery", "re-estimate every (days)", 1, "0 = never"), number("reestimateFactor", "re-estimate \xD7", 0.05, "How much a re-estimate multiplies by"), flag("workAhead", "team works ahead"), flag("dated", "plan has a start date")));
    return h("div", {
      class: "row scenario"
    }, h("label", {}, "Scenario ", select), h("span", {
      class: "breaks"
    }, h("b", {}, "Breaks: "), scenario.breaks), world, h("div", {
      class: "look"
    }, h("b", {}, "Look at: "), scenario.look));
  }
  function modelRow(replaying) {
    const cadence = h("select", {
      onchange: (event) => {
        app.cadence = event.target.value;
        render();
      }
    }, ...CADENCES.filter(({ key }) => replaying || key !== "stored").map(({ key, label: label2 }) => h("option", {
      value: key,
      selected: key === app.cadence
    }, label2)));
    return h("div", {
      class: "row model"
    }, h("label", {
      title: "Which days the recorder ran \u2014 the window was open \u2014 and so wrote a row"
    }, "Recorder runs ", cadence), h("span", {
      class: "label",
      title: "The plan's own dates stand while what is done matches them; otherwise the rest resumes from tomorrow, with work in flight credited (ISSUES.md F1, F5). Rounding is fixed (I1, Q3)."
    }, `Model: the plan holds, else resumes from tomorrow${VARIANTS.length ? " \xB7 variants:" : ""}`), ...VARIANTS.map(({ key, label: label2, hint }) => h("label", {
      title: hint
    }, h("input", {
      type: "checkbox",
      checked: app.options[key],
      disabled: app.cadence === "stored",
      onchange: (event) => {
        app.options = {
          ...app.options,
          [key]: event.target.checked
        };
        render();
      }
    }), ` ${label2}`)), app.cadence === "stored" ? h("span", {
      class: "note"
    }, "(the variants apply to what the prototype records, not to what DPlanner stored)") : null);
  }
  function events(lines) {
    return h("div", {
      class: "events"
    }, h("b", {}, "What happened today: "), lines.length ? lines.join(" \xB7 ") : "nothing");
  }
  var slider;
  var label;
  var playing = null;
  function debuggerBar() {
    const last = timeline2.frames.length - 1;
    slider = h("input", {
      type: "range",
      min: "0",
      max: String(last),
      value: String(app.frame),
      oninput: (event) => go(Number(event.target.value))
    });
    label = h("span", {
      class: "today-label"
    });
    toggle = h("button", {
      class: "fold",
      title: "Fold the debugger away to read the view on its own (d)",
      onclick: () => fold2({
        open: !folds.open
      })
    }, folds.open ? "\u25BE Debugger" : "\u25B8 Debugger");
    const play = h("button", {
      title: "Play the days",
      onclick: () => {
        if (playing !== null) {
          clearInterval(playing);
          playing = null;
          play.textContent = "\u25B6";
          return;
        }
        if (app.frame >= last) go(0);
        play.textContent = "\u275A\u275A";
        playing = setInterval(() => {
          if (app.frame >= last) {
            clearInterval(playing);
            playing = null;
            play.textContent = "\u25B6";
            return;
          }
          go(app.frame + 1);
        }, 220);
      }
    }, "\u25B6");
    const scenario = exports.has(app.source) ? `replay of ${exports.get(app.source).title}` : `${scenarioById(app.scenario).name} \xB7 seed ${app.seed}`;
    return h("div", {
      class: "debug debug-bar"
    }, h("div", {
      class: "controls"
    }, toggle, h("button", {
      title: "First day",
      onclick: () => go(0)
    }, "\u23EE"), h("button", {
      title: "A day earlier (\u2190)",
      onclick: () => go(app.frame - 1)
    }, "\u25C2"), play, h("button", {
      title: "A day later (\u2192)",
      onclick: () => go(app.frame + 1)
    }, "\u25B8"), h("button", {
      title: "Last day",
      onclick: () => go(last)
    }, "\u23ED"), h("span", {
      class: "segmented versions",
      title: "Which design of the view: today's tab, or the redesign"
    }, ...VERSIONS.map(([version, name]) => h("button", {
      class: app.version === version ? "on" : "",
      onclick: () => switchVersion(version)
    }, name))), label, h("span", {
      class: "scenario-name"
    }, scenario), h("nav", {}, h("a", {
      href: "explainer.html"
    }, "Explainer"), h("a", {
      href: "ISSUES.md"
    }, "Issues"), h("a", {
      href: "README.md"
    }, "README"))), h("div", {
      class: "track-strip"
    }, slider, h("div", {
      class: "ticks",
      html: ticks()
    })));
  }
  function ticks() {
    const frames = timeline2.frames;
    const at = (day) => (day - frames[0].day) / Math.max(1, frames.length - 1) * 100;
    const out = [
      `<svg viewBox="0 0 100 14" preserveAspectRatio="none" width="100%" height="14">`
    ];
    for (const row of recording.rows) {
      out.push(`<rect x="${at(row.day) - 0.1}" y="0" width="0.2" height="5" fill="var(--secondary)"><title>recorded ${isoDay(row.day)}</title></rect>`);
    }
    for (const row of recording.saved) {
      out.push(`<rect x="${at(row.day) - 0.15}" y="0" width="0.3" height="14" fill="var(--ink)"><title>saved: ${row.title}</title></rect>`);
    }
    const plan = frames[frames.length - 1].plan;
    const colors = milestoneColors(plan, plan.assumptions.palette);
    for (const step2 of placed(plan).map((place) => place.step).filter(isMilestone)) {
      const day = timeline2.finished.get(step2.id);
      if (day !== void 0) {
        out.push(`<rect x="${at(day) - 0.35}" y="7" width="0.7" height="7" fill="${colors.get(step2.id)}"><title>${step2.milestone} really landed ${isoDay(day)}</title></rect>`);
      }
    }
    out.push("</svg>");
    return out.join("");
  }
  function updateBar() {
    const day = timeline2.frames[app.frame].day;
    slider.value = String(app.frame);
    const worked = day - timeline2.begin;
    label.textContent = `${weekdayName(day)} ${formatDate(day, day)} \u2014 ` + (worked >= 0 ? `day ${worked + 1} since work began` : `${-worked} day${worked === -1 ? "" : "s"} before work begins`) + ` \xB7 ${app.frame + 1} of ${timeline2.frames.length}`;
    label.title = label.textContent;
  }
  function switchVersion(version) {
    app.version = version;
    try {
      localStorage.setItem(VERSION_KEY, version);
    } catch {
    }
    render();
  }
  function go(index) {
    app.frame = Math.max(0, Math.min(timeline2.frames.length - 1, index));
    renderContent();
    writeHash();
  }
  function adopt(value) {
    if (!isExport(value)) {
      alertInPage("That file is not an export \u2014 tools/export_plan.ts writes one.");
      return;
    }
    exports.set(value.slug, value);
    app.source = value.slug;
    app.cadence = "stored";
    app.saved = [];
    app.edits = NO_EDITS;
    render();
  }
  function alertInPage(message) {
    root.prepend(h("div", {
      class: "banner error"
    }, message));
  }
  function writeHash() {
    try {
      const day = timeline2.frames[app.frame].day;
      const state = new URLSearchParams({
        source: app.source,
        seed: String(app.seed),
        scenario: app.scenario,
        day: isoDay(day),
        cadence: app.cadence,
        ui: app.version
      });
      const variants = VARIANTS.filter(({ key }) => app.options[key]).map(({ key }) => key);
      if (variants.length) state.set("variants", variants.join(","));
      const budgets = budgetsToHash(app.edits.budgets);
      if (budgets) state.set("budget", budgets);
      const delays = delaysToHash(app.edits.delays);
      if (delays) state.set("delay", delays);
      const tabbed = app.version === "v3" || app.version === "v4" || app.version === "v5" ? app[app.version] : null;
      const picked = tabbed ? tabbed.scope : app.version === "v2" ? app.v2.scope : null;
      if (picked !== null) state.set("scope", picked || "rest");
      if (tabbed) state.set("page", tabbed.page);
      if (tabbed?.asOf != null) state.set("asof", isoDay(tabbed.asOf));
      if (app.locked) state.set("axes", "run");
      if (app.version === "v5" && app.v5.adjust) state.set("adjust", "on");
      history.replaceState(null, "", `#${state}`);
    } catch {
    }
  }
  function readHash() {
    const state = new URLSearchParams(location.hash.slice(1));
    const source = state.get("source");
    if (source && (source === "sample" || exports.has(source))) app.source = source;
    const seed = Number(state.get("seed"));
    if (seed) app.seed = seed;
    const scenario = state.get("scenario");
    if (scenario) {
      app.scenario = scenarioById(scenario).id;
      app.world = {
        ...DEFAULT_WORLD,
        ...scenarioById(scenario).world
      };
      app.cadence = scenarioById(scenario).cadence ?? "weekdays";
    }
    if (exports.has(app.source)) app.cadence = "stored";
    const cadence = state.get("cadence");
    if (cadence && CADENCES.some(({ key }) => key === cadence)) app.cadence = cadence;
    const variants = (state.get("variants") ?? "").split(",");
    app.options = {
      ...ADOPTED
    };
    for (const { key } of VARIANTS) app.options[key] = variants.includes(key);
    app.edits = {
      budgets: budgetsFromHash(state.get("budget")),
      delays: delaysFromHash(state.get("delay"))
    };
    const tab = state.get("tab");
    if (tab === "track" || tab === "records") folds = {
      ...folds,
      open: true,
      [tab]: true
    };
    const ui = state.get("ui");
    const named = VERSIONS.find(([version]) => version === ui);
    if (named) app.version = named[0];
    const scoped = state.get("scope");
    const scope = scoped === null ? null : scoped === "rest" ? "" : scoped;
    app.v2 = {
      ...app.v2,
      scope
    };
    const page = state.get("page");
    for (const version of [
      "v3",
      "v4",
      "v5"
    ]) {
      app[version] = {
        ...app[version],
        scope,
        ...page === "milestones" || page === "work" || page === "calendar" && version === "v5" ? {
          page
        } : {}
      };
    }
    app.v5 = {
      ...app.v5,
      asOf: parseDay(state.get("asof") ?? ""),
      adjust: state.get("adjust") === "on"
    };
    app.locked = state.get("axes") === "run";
    currentTimeline();
    const asked = state.get("day");
    const day = parseDay(asked ?? "");
    const index = asked === "end" ? timeline2.frames.length - 1 : day !== null ? timeline2.frames.findIndex((frame) => frame.day === day) : -1;
    if (index >= 0) app.frame = index;
  }
  function start() {
    const local = globalThis.TE2_LOCAL ?? [];
    for (const file of local) if (isExport(file)) exports.set(file.slug, file);
    readHash();
    render();
    addEventListener("hashchange", () => {
      readHash();
      render();
    });
    document.addEventListener("keydown", (event) => {
      const target = event.target;
      if ([
        "INPUT",
        "SELECT",
        "TEXTAREA"
      ].includes(target.tagName)) return;
      if (event.key === "ArrowLeft") go(app.frame - 1);
      if (event.key === "ArrowRight") go(app.frame + 1);
      if (event.key === "d" && !event.ctrlKey && !event.metaKey) fold2({
        open: !folds.open
      });
    });
    document.addEventListener("dragover", (event) => event.preventDefault());
    document.addEventListener("drop", async (event) => {
      event.preventDefault();
      const file = event.dataTransfer?.files[0];
      if (file) adopt(JSON.parse(await file.text()));
    });
    let resize;
    addEventListener("resize", () => {
      clearTimeout(resize);
      resize = setTimeout(renderContent, 150);
    });
  }
  if (document.body.dataset.page === "explainer") renderFigures();
  else start();
})();
