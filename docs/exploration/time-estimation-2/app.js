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
    replan: false
  };
  var GUARD = 1e-9;
  function guardOf(options) {
    return options.epsilon ? GUARD : 0;
  }
  var VARIANTS = [
    {
      key: "epsilon",
      label: "Round with a guard",
      hint: "ceil(days \u2212 1e-9): 25.000000000000004 working days is 25, not 26"
    },
    {
      key: "carry",
      label: "Carry part-days between milestones",
      hint: "the next stretch starts at the fraction of a day the previous one ended, not the next morning"
    },
    {
      key: "replan",
      label: "Re-plan from today",
      hint: "done steps cost nothing, and the first unfinished stretch starts no earlier than today"
    }
  ];

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
  function parallelFinish(steps, daysFor2, humans, agents) {
    if (humans < 1 || agents < 1) throw new Error("a pool with work in it needs at least one worker");
    if (!steps.length) return null;
    const order = new Map(steps.map((step2, index) => [
      step2.id,
      index
    ]));
    const days = new Map(steps.map((step2) => [
      step2.id,
      daysFor2(step2)
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
    for (const step2 of steps) {
      if (!waiting.get(step2.id).size) ready.get(pool.get(step2.id)).push(step2.id);
    }
    let running = [];
    const landings2 = /* @__PURE__ */ new Map();
    let now = 0;
    let remaining2 = steps.length;
    const priority = (a, b) => tails.get(b) - tails.get(a) || order.get(a) - order.get(b);
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
          running.push([
            now + (days.get(id) ?? 0),
            id
          ]);
        }
      }
      if (!running.length) break;
      now = Math.min(...running.map(([finish]) => finish));
      const landed = running.filter(([finish]) => finish <= now);
      running = running.filter(([finish]) => finish > now);
      for (const [finish, id] of landed) {
        landings2.set(id, finish);
        free.set(pool.get(id), free.get(pool.get(id)) + 1);
        remaining2 -= 1;
        for (const after of dependents.get(id)) {
          const left = waiting.get(after);
          left.delete(id);
          if (!left.size) ready.get(pool.get(after)).push(after);
        }
      }
    }
    return {
      days: now,
      unestimated: [
        ...days.values()
      ].filter((value) => value === null).length,
      landings: landings2,
      tails
    };
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
      daysFor2(step2)
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
    const offset = phase.landings.get(id) ?? 0;
    return offset > 0 ? workingDaysAfter(phase.start, phase.lead + offset, phase.guard) : phase.start;
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
    const guard = guardOf(options);
    const result = [];
    let when = args.start;
    let lead = 0;
    let replanned = false;
    for (const [index, [milestone, steps]] of groups(plan).entries()) {
      let costs = daysFor2;
      if (options.replan && !replanned && steps.some((step2) => step2.status !== DONE)) {
        replanned = true;
        if (args.today > when) [when, lead] = [
          args.today,
          0
        ];
      }
      if (options.replan && replanned) {
        costs = (step2) => {
          const days = daysFor2(step2);
          return days !== null && step2.status === DONE ? 0 : days;
        };
      }
      const asked = milestone ? startFor(milestone) : null;
      let begins = asked !== null && (index === 0 || asked >= when) ? asked : when;
      let used = begins === when ? lead : 0;
      if (nextWorkingDay(begins) !== begins) used = 0;
      begins = nextWorkingDay(begins);
      const run2 = parallelFinish(steps, costs, args.humans, args.agents);
      const finish = run2.days > 0 ? workingDaysAfter(begins, used + run2.days, guard) : null;
      result.push({
        milestone,
        steps,
        days: run2.days,
        start: begins,
        finish,
        asked,
        unestimated: run2.unestimated,
        landings: run2.landings,
        lead: used,
        guard
      });
      if (finish === null) {
        [when, lead] = [
          begins,
          used
        ];
      } else if (options.carry) {
        const total = used + run2.days;
        const part = total - Math.floor(total + GUARD);
        [when, lead] = part > GUARD ? [
          finish,
          part
        ] : [
          nextWorkingDay(finish + 1),
          0
        ];
      } else {
        [when, lead] = [
          nextWorkingDay(finish + 1),
          0
        ];
      }
    }
    return result;
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
    const raw = phases(plan, daysFor2, common);
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
    const calendar = [];
    for (const humans of HUMANS) {
      for (const agents of AGENTS) {
        const [raw, slow] = cellFor(plan, daysFor2, humans, agents, args);
        parallel.push(raw);
        calendar.push(slow);
      }
    }
    return {
      ...base,
      start: calendar[0].phases[0].start,
      unestimated: calendar[0].phases.reduce((sum, phase) => sum + phase.unestimated, 0),
      floor: path ? path.days : 0,
      calendarFloor: calendarPath ? Math.ceil(calendarPath.days - 1e-9) : 0,
      parallel,
      calendar,
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
    doneDays: 0
  };
  function addTally(a, b) {
    return {
      steps: a.steps + b.steps,
      done: a.done + b.done,
      days: a.days + b.days,
      doneDays: a.doneDays + b.doneDays
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
    return a.key === b.key && a.start === b.start && a.finish === b.finish && a.tally.steps === b.tally.steps && a.tally.done === b.tally.done && a.tally.days === b.tally.days && a.tally.doneDays === b.tally.doneDays && a.landings.length === b.landings.length && a.landings.every((knot, index) => {
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
  function snapshotFrom(dated, today) {
    return {
      day: today,
      stretches: dated.map((phase) => ({
        key: phase.milestone ? phase.milestone.id : "",
        tally: tally(phase.steps),
        start: phase.start,
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
  function tally(steps, days = daysFor) {
    let total = EMPTY_TALLY;
    for (const step2 of steps) {
      const cost = days(step2) ?? 0;
      const landed = step2.status === DONE;
      total = addTally(total, {
        steps: 1,
        done: landed ? 1 : 0,
        days: cost,
        doneDays: landed ? cost : 0
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
  function findSaved(saved, title2) {
    const wanted = title2.trim().toLowerCase();
    return saved.find((row) => row.title.toLowerCase() === wanted) ?? null;
  }
  function savedWith(saved, now, title2, note = "") {
    const named = title2.trim();
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
  function niceCeiling(value) {
    if (value <= 1) return 1;
    const magnitude = 10 ** Math.floor(Math.log10(value));
    for (const step2 of [
      1,
      2,
      5,
      10
    ]) {
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
        doneDays: amount(row.done_days)
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
        start: dayOrNull(step2.start)
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
  function applyWhatIf(plan, whatIf) {
    const begins = whatIf.begins ?? {};
    return {
      ...plan,
      start: whatIf.start ?? plan.start,
      assumptions: {
        efficiency: whatIf.efficiency ?? plan.assumptions.efficiency,
        palette: whatIf.palette ?? plan.assumptions.palette,
        team: whatIf.team ?? plan.assumptions.team
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
    const plan = applyWhatIf(stored, state.whatIf);
    const start2 = startOf(plan, today);
    const report = timeReport(plan, daysFor, {
      start: start2,
      today,
      efficiency: efficiencyOf(plan),
      options
    });
    if (!report) return null;
    const team = teamOf(plan);
    const cell = cellAt(report.calendar, ...team) ?? report.calendar[0];
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
      team,
      cell,
      stretches,
      entries: entries(stretches, live, cell, start2),
      unestimated,
      live,
      now,
      then,
      chart: chart2,
      recording: recording2,
      start: start2
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
  function record(timeline2, spec) {
    if (spec.cadence === "stored") {
      const last = timeline2.frames[timeline2.frames.length - 1]?.stored;
      return {
        rows: last?.rows ?? [],
        saved: last?.saved ?? []
      };
    }
    let rows = [];
    let saved = [];
    for (const frame of timeline2.frames) {
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
    const finished = /* @__PURE__ */ new Map();
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
      const plan = planFromJson(found.plan);
      const events2 = describe(before, plan.steps, found.commit);
      for (const step2 of plan.steps) {
        const was = before?.plan.steps.find((other) => other.id === step2.id);
        if (step2.status === DONE && was?.status !== DONE) finished.set(step2.id, day);
        if (step2.status !== DONE) finished.delete(step2.id);
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
      finished,
      kind: "replay"
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
  function parity(timeline2) {
    const found = [];
    for (const frame of timeline2.frames) {
      const stored = frame.stored?.rows.find((row) => row.day === frame.day);
      if (!stored || !frame.events.length) continue;
      const mine = snapshotOf(frame.plan, frame.day);
      if (!mine) continue;
      found.push({
        day: frame.day,
        same: samePlan(stored, mine),
        differences: differences(stored, mine)
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
    const add = (title2, fields = {}) => {
      const step2 = {
        id: `s${steps.length + 1}`,
        number: steps.length + 1,
        title: title2,
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
        teamChange: {
          after: 14,
          humans: 2,
          agents: 3
        }
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
    teamChange: null,
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
    humans;
    agents;
    random;
    events;
    constructor(start2, params, begin) {
      this.params = params;
      this.begin = begin;
      this.effort = /* @__PURE__ */ new Map();
      this.progress = /* @__PURE__ */ new Map();
      this.blockedUntil = /* @__PURE__ */ new Map();
      this.finished = /* @__PURE__ */ new Map();
      this.events = [];
      this.steps = start2.steps.map((step2) => ({
        ...step2,
        status: "pending"
      }));
      this.plan = {
        ...start2,
        start: params.dated ? begin : null
      };
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
        if (doneOn === null && this.steps.every((step2) => step2.status === DONE)) doneOn = day;
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
    update(id, patch) {
      const index = this.steps.findIndex((step2) => step2.id === id);
      this.steps[index] = {
        ...this.steps[index],
        ...patch
      };
      return this.steps[index];
    }
    scheduled(offset, day) {
      const change = this.params.teamChange;
      if (change && offset === change.after) {
        this.plan = {
          ...this.plan,
          assumptions: {
            ...this.plan.assumptions,
            team: [
              change.humans,
              change.agents
            ]
          }
        };
        this.humans = resized(this.humans, change.humans);
        this.agents = resized(this.agents, change.agents);
        this.events.push(`the team becomes ${change.humans} ${change.humans === 1 ? "person" : "people"} + ${change.agents} agent${change.agents === 1 ? "" : "s"}`);
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
          color: null
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
      const calendar = stretched(daysFor, efficiencyOf(plan));
      const found = /* @__PURE__ */ new Map();
      for (const [, members] of groups(plan)) {
        for (const [id, tail] of chainTails(members, calendar)) found.set(id, tail);
      }
      return found;
    }
    currentStretch() {
      return groups({
        ...this.plan,
        steps: this.steps
      }).find(([, members]) => members.some((step2) => step2.status !== DONE));
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
      const done = (id) => this.find(id).status === DONE;
      const known = new Set(this.steps.map((step2) => step2.id));
      const current = () => stretches.findIndex(([, members]) => members.some((step2) => !done(step2.id)));
      const running = () => new Set([
        ...this.humans,
        ...this.agents
      ].filter((id) => id !== null));
      const focus = this.params.focus ?? efficiencyOf(plan);
      const eligible = (agent) => {
        const busy = running();
        const now = current();
        if (now < 0) return void 0;
        return this.steps.filter((step2) => {
          const stretch = stretchOf.get(step2.id);
          return step2.agent === agent && step2.status !== DONE && step2.status !== "blocked" && !busy.has(step2.id) && (this.params.workAhead || stretch === now) && (opens[stretch] === null || opens[stretch] <= day) && step2.requires.every((id) => !known.has(id) || done(id));
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
      const assign = () => {
        for (; ; ) {
          let moved = false;
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
      let time = 0;
      for (let guard = 0; guard < 1e4; guard += 1) {
        assign();
        const busyAgents = this.agents.filter((id) => id !== null).length;
        const human = Math.max(0.05, focus - this.params.agentLoad * busyAgents / Math.max(1, this.humans.length));
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
        if (!busy.length || time >= 1 - EPSILON) return;
        const step2 = Math.min(1 - time, ...busy.map(([id, rate]) => (this.effortOf(this.find(id)) - (this.progress.get(id) ?? 0)) / rate));
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

  // src/ui/charts.ts
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
      const body = panel.kind === "status" ? statusPlot(data, panel, g2) : panel.kind === "scope" ? scopePlot(data, panel, g2) : panel.kind === "shift" ? shiftPlot(data, panel, g2, emphasised) : amountPlot(data, panel, g2);
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
        out.push(`<g opacity="${FADE}">${body}</g><g clip-path="url(#${clipId})">${body}</g>`);
      } else {
        out.push(body);
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
      const words = standingWords(data.standing);
      if (words) {
        const flipped = g2.x(when) + 8 + textWidth(words) > g2.right;
        out.push(`<text class="standing" x="${n(g2.x(when) + (flipped ? -8 : 8))}" y="${n(g2.y(panel, share))}" dominant-baseline="central" text-anchor="${flipped ? "end" : "start"}" style="fill:${INK}" font-weight="600">${esc(words)}</text>`);
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
  function step(id, number, title2, estimate, requires, milestone = null) {
    return {
      id,
      number,
      title: title2,
      requires,
      estimate: milestone ? null : estimate,
      estimateOff: milestone !== null,
      estimateHistory: [],
      status: "pending",
      milestone,
      agent: false,
      created: MONDAY - 3,
      start: null,
      color: null
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
    const timeline2 = {
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
      ...timeline2,
      frames: timeline2.frames.filter((frame) => frame.day !== MONDAY + 1)
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
      timeline: timeline2,
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
      const words = pickWords(pick, found, TODAY) || "nothing to compare with";
      out.push(`<text x="0" y="${y}" dominant-baseline="central" style="fill:${INK}">${esc(label2)}</text>`);
      out.push(`<circle cx="${n(x(asked))}" cy="${y}" r="3" style="fill:none;stroke:${INK}"/>`);
      if (found) {
        out.push(`<line x1="${n(x(asked))}" x2="${n(x(found.day))}" y1="${y}" y2="${y}" style="stroke:${INK}" stroke-width="1.5"/>`);
        out.push(`<circle cx="${n(x(found.day))}" cy="${y}" r="5" style="fill:${INK}"/>`);
      }
      out.push(`<text x="${right + 24}" y="${y}" dominant-baseline="central" style="fill:${SECONDARY}">${esc(`\u2192 ${words}`)}</text>`);
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
    const { timeline: timeline2, view } = example();
    const atStart = view(AT_START);
    const rows = atStart.recording.rows;
    const fill = (name, make) => {
      for (const holder of document.querySelectorAll(`[data-figure="${name}"]`)) {
        make(holder);
      }
    };
    fill("record", (holder) => {
      const thursday = rows.find((one) => one.day === MONDAY + 3);
      holder.replaceChildren(recordTable(thursday, timeline2.frames[3].plan));
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

  // src/ui/records.ts
  function stretchText(row, key, today) {
    const stretch = row.stretches.find((one) => one.key === key);
    if (!stretch) return "";
    const { steps, done, days, doneDays } = stretch.tally;
    const finish = stretch.finish !== null ? shortDate(stretch.finish, today) : "undated";
    return `${done}/${steps} steps \xB7 ${formatDays(doneDays) || "0d"} of ${formatDays(days) || "0d"} \xB7 ${shortDate(stretch.start, today)} \u2192 ${finish}`;
  }
  function recordsTab(timeline2, recording2, index, parity2) {
    const today = timeline2.frames[index].day;
    const plan = timeline2.frames[timeline2.frames.length - 1].plan;
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
    const body = h("tbody");
    for (const frame of timeline2.frames.slice(0, index + 1).reverse()) {
      const row = byDay.get(frame.day);
      const found = parity2?.find((one) => one.day === frame.day);
      body.append(h("tr", {
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
    table.append(body);
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

  // src/ui/calendar.ts
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
  function tooltip(day, band, today) {
    let said = `${weekdayName(day)} ${formatDate(day, today)}`;
    if (!band) said += " \u2014 click to start the work here";
    else if (day === band.finish && band.lands) said += ` \u2014 ${band.label} lands`;
    else if (!isWorkingDay(day)) said += " \u2014 weekend, not counted";
    else {
      const worked = workingDaysBetween(band.start, day);
      const total = workingDaysBetween(band.start, band.finish);
      said += ` \u2014 ${band.label}${day === band.start ? " starts," : ","} working day ${worked} of ${total}`;
    }
    return day === today ? `${said} \xB7 today` : said;
  }
  function monthsView(view, emphasis, offset, onDay) {
    const bands = view.stretches.filter(({ phase }) => phase.finish !== null).map(({ phase, key, label: label2, color }) => ({
      key,
      label: label2,
      start: phase.start,
      finish: phase.finish,
      color,
      lands: phase.milestone !== null
    }));
    const [first, count2] = monthSpan(view.report.start, view.cell.finish);
    const grid2 = h("div", {
      class: "months"
    });
    for (let index = 0; index < count2; index += 1) {
      const month = addMonths(first, index + offset);
      const [year, number] = ymd(month);
      const name = year === ymd(view.today)[0] ? MONTHS[number - 1] : `${MONTHS[number - 1].slice(0, 3)} '${String(year % 100).padStart(2, "0")}`;
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
        const cell = h("button", {
          class: `day${isWorkingDay(day) ? "" : " weekend"}${day === view.today ? " today" : ""}`,
          title: tooltip(day, band, view.today),
          onclick: () => onDay(day)
        }, String(ymd(day)[2]));
        if (band) {
          const strength = day === band.finish && band.lands ? 220 : day === view.report.start ? 130 : isWorkingDay(day) ? 64 : 24;
          cell.style.background = alpha(band.color, strength / 255 * faded);
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

  // src/ui/timetab.ts
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
    }, staffing(view, state, on), milestoneTable(view, state, on));
    const right = h("div", {
      class: "right"
    }, banner(view), pager(on), monthsView(view, state.picked, on.offset, (day) => on.whatIf({
      start: day
    })), plots(view, state, on));
    return h("div", {
      class: "time"
    }, toolbar(view, state, on), h("div", {
      class: "split"
    }, left, right));
  }
  function toolbar(view, state, on) {
    const efficiency = Math.round((view.plan.assumptions.efficiency ?? DEFAULT_EFFICIENCY) * 100);
    const focus = h("select", {
      title: "Human focus: how much of a person's working day this project gets",
      onchange: (event) => on.whatIf({
        efficiency: Number(event.target.value) / 100
      })
    });
    for (let value = 10; value <= 100; value += 5) {
      focus.append(h("option", {
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
    }, saveButton(view, on), h("span", {
      class: "divider"
    }), focus, lens, swatch, palette, h("span", {
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
  function describeWhatIf(whatIf, view) {
    const parts = [];
    if (whatIf.efficiency !== void 0) parts.push(`focus ${percent(whatIf.efficiency)}`);
    if (whatIf.team) parts.push(`team ${whatIf.team[0]}+${whatIf.team[1]}`);
    if (whatIf.palette) parts.push(`colours ${paletteById(whatIf.palette).name}`);
    if (whatIf.start !== void 0) parts.push(`start ${shortDate(whatIf.start, view.today)}`);
    const begins = Object.keys(whatIf.begins ?? {}).length;
    if (begins) parts.push(`${begins} milestone date${begins === 1 ? "" : "s"}`);
    return parts.join(", ");
  }
  function saveButton(view, on) {
    const title2 = h("input", {
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
    }, "Title"), title2, refusal, h("div", {
      class: "caption"
    }, "Note"), note, h("div", {
      class: "footer"
    }, h("button", {
      onclick: () => panel.hidden = true
    }, "Cancel"), h("button", {
      class: "primary",
      onclick: () => {
        const refused = on.save(title2.value, note.value);
        refusal.textContent = refused ?? "";
      }
    }, "Save")));
    return h("span", {
      class: "anchor"
    }, h("button", {
      title: "Save Snapshot\u2026 \u2014 keep the plan as it stands today under a title",
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
  function staffing(view, state, on) {
    const cells = state.lens === "calendar" ? view.report.calendar : view.report.parallel;
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
        const calendar = cellAt(view.report.calendar, humans, a);
        const parallel = cellAt(view.report.parallel, humans, a);
        const tint = most > least ? 18 + (cell.days - least) / (most - least) * 70 : 18;
        const chosen = view.team[0] === humans && (view.team[1] === a || !view.report.hasAgentSteps);
        grid2.append(h("button", {
          class: `tile${chosen ? " chosen" : ""}`,
          style: `background: rgba(95, 135, 215, ${(tint / 255).toFixed(3)})`,
          title: [
            `${humans} ${humans === 1 ? "person" : "people"} + ${a} agent${a === 1 ? "" : "s"}`,
            `${formatDays(parallel.days)} of project time`,
            `${formatDays(calendar.days)} of calendar time at ${percent(view.report.efficiency)} focus`,
            calendar.finish !== null ? `lands ${formatDate(calendar.finish, view.today)}` : "nothing estimated to land"
          ].join("\n"),
          onclick: () => on.whatIf({
            team: [
              humans,
              view.report.hasAgentSteps ? a : view.team[1]
            ]
          })
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
    const body = h("tbody");
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
      body.append(h("tr", {
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
    table.append(body);
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
    requestAnimationFrame(draw);
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

  // src/ui/track.ts
  function seriesOf(plan, timeline2, today) {
    const colors = milestoneColors(plan, plan.assumptions.palette);
    const found = placed(plan).map((place) => place.step).filter(isMilestone).map((step2) => {
      const truth = timeline2.finished.get(step2.id) ?? null;
      return {
        key: step2.id,
        label: milestoneLabel(step2),
        color: colors.get(step2.id),
        truth: truth !== null && truth <= today ? truth : null
      };
    });
    const everything = plan.steps.map((step2) => timeline2.finished.get(step2.id) ?? null);
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
  function trackTab(timeline2, recording2, compared2, options, index) {
    const today = timeline2.frames[index].day;
    const plan = timeline2.frames[timeline2.frames.length - 1].plan;
    const rows = recording2.rows.filter((row) => row.day <= today);
    const others = compared2?.rows.filter((row) => row.day <= today) ?? [];
    const series = seriesOf(plan, timeline2, today);
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
    }, "Each line is one milestone's landing date, as the plan said it on each recorded day. A forecast that holds is flat; ", "where a line meets the diagonal, that day is the landing it promised. \u25C6 marks where the milestone really landed.", compared2 ? " Dashed lines are DPlanner as it is today; solid ones are the model with the variants switched on." : ""), h("div", {
      html: trendSvg(series, rows, others, today, timeline2)
    }), errorTable(series, rows, others, today, Boolean(compared2)), h("h3", {}, "What the Progress plot said each day"), h("p", {
      class: "lede"
    }, "The ahead/behind the Time tab printed beside today's dot, day by day \u2014 the only warning a reader gets that the plan is slipping."), h("div", {
      html: standingSvg(timeline2, recording2, options, index)
    }));
  }
  function trendSvg(series, rows, others, today, timeline2) {
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
      timeline2.frames[0].day,
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
    const body = h("tbody");
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
      body.append(h("tr", {}, h("td", {}, h("span", {
        class: "badge",
        style: `background:${one.color}`
      }), one.label), h("td", {}, one.truth !== null ? shortDate(one.truth, today) : "not yet"), ...mine.map((text2, index) => h("td", {
        class: "number"
      }, text2, theirs ? h("div", {
        class: "subtitle"
      }, `today's model: ${theirs[index]}`) : null))));
    }
    table.append(body);
    return h("div", {}, table, h("p", {
      class: "note"
    }, "(+3d) means it really landed three working days after that forecast; (\u22122d), two before it. \xBC, \xBD and \xBE are points between the first record and the real landing."));
  }
  function standingSvg(timeline2, recording2, options, index) {
    const [width, height, left, right, top, bottom2] = [
      1e3,
      150,
      70,
      60,
      12,
      26
    ];
    const points = [];
    for (const frame of timeline2.frames.slice(0, index + 1)) {
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
      ...FAITHFUL
    },
    frame: -1,
    tab: "time",
    view: {
      picked: null,
      then: AT_START,
      now: LIVE,
      lens: "calendar",
      page: "progress",
      whatIf: {}
    },
    saved: [],
    offset: 0
  };
  var timelineKey = "";
  var timeline;
  var replayed = null;
  var recordingKey = "";
  var recording;
  var compared = null;
  function currentTimeline() {
    const key = JSON.stringify([
      app.source,
      app.seed,
      app.world
    ]);
    if (key !== timelineKey) {
      timelineKey = key;
      const file = exports.get(app.source);
      timeline = file ? replay(file) : run(samplePlan(app.seed), {
        ...app.world,
        seed: app.seed
      }, SAMPLE_START);
      replayed = file ? parity(timeline) : null;
      app.frame = file ? timeline.frames.length - 1 : Math.min(timeline.frames.length - 1, timeline.frames.findIndex((f) => f.day === timeline.begin) + 14);
      app.offset = 0;
    }
    return timeline;
  }
  function savedSpecs() {
    if (timeline.kind === "replay") return app.saved;
    return [
      ...SAVED_BY_DEFAULT.map((one) => ({
        day: timeline.begin + one.after,
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
      recording = record(timeline, spec);
      const variant = VARIANTS.some(({ key: key2 }) => app.options[key2]);
      compared = variant && app.cadence !== "stored" ? record(timeline, {
        ...spec,
        options: FAITHFUL
      }) : null;
    }
    return recording;
  }
  var root = document.getElementById("app");
  var content;
  var strip;
  function render() {
    currentTimeline();
    currentRecording();
    root.replaceChildren(header(), strip = timelineStrip(), tabs(), content = h("main"));
    renderContent();
    writeHash();
  }
  function renderContent() {
    const frame = timeline.frames[app.frame];
    const upToDay = recordedBy(recording, frame.day);
    content.replaceChildren(events(frame.events), app.tab === "time" ? timeContent(frame.plan, frame.day, upToDay) : app.tab === "track" ? trackTab(timeline, recording, compared, app.options, app.frame) : recordsTab(timeline, recording, app.frame, replayed));
    updateStrip();
  }
  function timeContent(plan, day, upToDay) {
    const view = present(plan, day, upToDay, app.view, app.options);
    if (!view) {
      return h("div", {
        class: "empty"
      }, "No steps yet \u2014 the staffing grid and the calendar date a plan once it has some.");
    }
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
      save: (title2, note) => {
        const named = title2.trim();
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
      },
      offset: app.offset,
      page: (offset) => {
        app.offset = offset;
        renderContent();
      }
    });
  }
  function header() {
    const file = exports.get(app.source);
    const source = h("select", {
      onchange: (event) => {
        app.source = event.target.value;
        app.cadence = exports.has(app.source) ? "stored" : scenarioById(app.scenario).cadence ?? "weekdays";
        app.saved = [];
        app.view = {
          ...app.view,
          whatIf: {},
          picked: null,
          then: AT_START,
          now: LIVE
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
          render();
        }
      })), h("label", {
        class: "open",
        title: "An export written by tools/export_plan.ts \u2014 or drop one anywhere on the page"
      }, "open an export\u2026 ", open))
    ];
    if (!file) rows.push(scenarioRow());
    rows.push(modelRow(Boolean(file)));
    return h("header", {}, h("div", {
      class: "title"
    }, h("h1", {}, "Time estimation \u2014 exploration 2"), h("nav", {}, h("a", {
      href: "explainer.html"
    }, "How comparisons over time work"), " \xB7 ", h("a", {
      href: "ISSUES.md"
    }, "Issues found"), " \xB7 ", h("a", {
      href: "README.md"
    }, "README"))), ...rows);
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
      class: "label"
    }, "Model variants:"), ...VARIANTS.map(({ key, label: label2, hint }) => h("label", {
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
  var slider;
  var label;
  var playing = null;
  function timelineStrip() {
    const last = timeline.frames.length - 1;
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
    return h("div", {
      class: "timeline"
    }, h("div", {
      class: "controls"
    }, h("button", {
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
    }, "\u23ED"), label), h("div", {
      class: "track-strip"
    }, slider, h("div", {
      class: "ticks",
      html: ticks()
    })));
  }
  function ticks() {
    const frames = timeline.frames;
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
      const day = timeline.finished.get(step2.id);
      if (day !== void 0) {
        out.push(`<rect x="${at(day) - 0.35}" y="7" width="0.7" height="7" fill="${colors.get(step2.id)}"><title>${step2.milestone} really landed ${isoDay(day)}</title></rect>`);
      }
    }
    out.push("</svg>");
    return out.join("");
  }
  function updateStrip() {
    if (!strip) return;
    const day = timeline.frames[app.frame].day;
    slider.value = String(app.frame);
    const worked = day - timeline.begin;
    label.textContent = `Today: ${weekdayName(day)} ${formatDate(day, day)} \u2014 ` + (worked >= 0 ? `day ${worked + 1} since work began (${shortDate(timeline.begin, day)})` : `${-worked} day${worked === -1 ? "" : "s"} before work begins`) + ` \xB7 ${app.frame + 1} of ${timeline.frames.length}`;
  }
  function go(index) {
    app.frame = Math.max(0, Math.min(timeline.frames.length - 1, index));
    renderContent();
    writeHash();
  }
  function events(happened) {
    return h("div", {
      class: "events"
    }, h("b", {}, "What happened today: "), happened.length ? happened.join(" \xB7 ") : "nothing");
  }
  function tabs() {
    const tab = (key, name) => h("button", {
      class: app.tab === key ? "on" : "",
      onclick: () => {
        app.tab = key;
        render();
      }
    }, name);
    return h("nav", {
      class: "tabs"
    }, tab("time", "Time tab"), tab("track", "Track record"), tab("records", "Records"));
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
    render();
  }
  function alertInPage(message) {
    root.prepend(h("div", {
      class: "banner error"
    }, message));
  }
  function writeHash() {
    try {
      const day = timeline.frames[app.frame].day;
      const state = new URLSearchParams({
        source: app.source,
        seed: String(app.seed),
        scenario: app.scenario,
        day: isoDay(day),
        tab: app.tab,
        cadence: app.cadence,
        variants: VARIANTS.filter(({ key }) => app.options[key]).map(({ key }) => key).join(",")
      });
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
      ...FAITHFUL
    };
    for (const { key } of VARIANTS) app.options[key] = variants.includes(key);
    const tab = state.get("tab");
    if (tab === "time" || tab === "track" || tab === "records") app.tab = tab;
    currentTimeline();
    const asked = state.get("day");
    const day = parseDay(asked ?? "");
    const index = asked === "end" ? timeline.frames.length - 1 : day !== null ? timeline.frames.findIndex((frame) => frame.day === day) : -1;
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
