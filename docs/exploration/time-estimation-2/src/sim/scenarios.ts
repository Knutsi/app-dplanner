/**
 * The scenarios: each breaks one assumption the model makes, so whatever the view does
 * afterwards can be put down to that one thing. "By the book" breaks none, which makes it
 * the control: any gap it shows between forecast and reality is the model's own.
 *
 * Every "look" sentence was checked against the numbers at the default seed (1); the issue
 * ids point into ISSUES.md.
 */

import type { Cadence } from "./timeline.ts";
import type { WorldParams } from "./world.ts";

export interface Scenario {
  id: string;
  name: string;
  breaks: string; // The assumption, in the model's words.
  look: string; // Where the effect shows, in the page's words.
  world: Partial<WorldParams>;
  cadence?: Cadence;
}

export const SAVED_BY_DEFAULT = [
  { after: 0, title: "Kickoff review", note: "The plan as it was presented on the first day." },
  { after: 21, title: "Three-week check-in", note: "Where we thought we were after three weeks." },
];

export const SCENARIOS: Scenario[] = [
  {
    id: "by-the-book",
    name: "By the book",
    breaks: "nothing — every step takes exactly its estimate and nothing happens to the plan",
    look: "Progress reads “behind” while every step is exactly on time — the plan line is " +
      "drawn straight between landings, progress only counts at one (P1). Track record: " +
      "flat forecasts, but M2–M4 land a day or two before them — the model's own rounding " +
      "(Q3); switch on “Carry part-days” and they meet.",
    world: { unestimatedEffort: 0 },
  },
  {
    id: "unsized",
    name: "Unsized steps",
    breaks: "a step nobody estimated costs nothing — each really takes two days",
    look: "The banner counts them as 0d (together with the milestones, I2), and the forecast " +
      "believes it: the milestones holding them land 2–3 days late while Progress reads " +
      "about on plan.",
    world: { unestimatedEffort: 2 },
  },
  {
    id: "optimistic",
    name: "Optimistic estimates",
    breaks: "the estimates are right — human work really takes 1.5× its estimate",
    look: "Progress falls far behind, yet the milestone table keeps its dates — past ones " +
      "included — and Milestone shifts shows nothing, because the forecast never reads what " +
      "has landed (F1). Track record: flat lines, every milestone weeks late. Try “Re-plan " +
      "from today”.",
    world: { humanBias: 1.5, noise: 0.25 },
  },
  {
    id: "scope-creep",
    name: "Scope creep",
    breaks:
      "the plan is complete — about three steps every two weeks are added to the milestone being worked",
    look: "Volume: the total climbs while remaining barely falls. Scope change: red where the " +
      "plan now promises less than it did. Progress reads about on plan throughout — the " +
      "plan now absorbs whatever was added, and each day's share was of that day's own " +
      "total (P2).",
    world: { scopePerWeek: 1.5 },
  },
  {
    id: "learning",
    name: "Learning re-estimates",
    breaks: "the first estimates are final — they are 1.5× too low, and every week the team " +
      "re-estimates the three largest waiting steps",
    look: "Milestone shifts and Scope change move in steps on re-estimate days. Track record: " +
      "the forecasts climb toward the truth and overshoot it — a waiting step can be " +
      "re-estimated twice.",
    world: { humanBias: 1.5, reestimateEvery: 5, reestimateFactor: 1.5 },
  },
  {
    id: "joiner",
    name: "Someone joins",
    breaks: "the team stays as it is — a second person and a third agent join on day 14",
    look: "Every landing jumps earlier on day 14. Scope change against the plan at start " +
      "reads as “pulled in”, though no scope changed: a record freezes its day's team (R2).",
    world: { teamChange: { after: 14, humans: 2, agents: 3 } },
  },
  {
    id: "blocked",
    name: "A blocked step",
    breaks: "nothing waits — the longest-running step is blocked for six working days on day 8",
    look: "The step reads “blocked”, and the forecast does not care: status is only ever read " +
      "as done or not done (F4). Progress falls behind; the landings do not move.",
    world: { block: { after: 8, days: 6 } },
  },
  {
    id: "work-ahead",
    name: "Team works ahead",
    breaks: "milestones run in sequence — idle people start the next milestone's ready work",
    look: "Little changes here, and not always for the better: someone busy on the next " +
      "milestone is not free when this one's next step becomes ready, so a milestone can " +
      "land later (Q1). The model shows neither.",
    world: { workAhead: true },
  },
  {
    id: "undated",
    name: "Undated project",
    breaks: "the plan has a start date — nobody set one, so it starts “today”, every day",
    look: "Every landing slides a working day each day and a row is written daily; Progress " +
      "reads far ahead, and “Plan at start” resolves to today's own record — the plan " +
      "compared with itself (F2).",
    world: { dated: false },
  },
  {
    id: "sparse",
    name: "Window rarely open",
    breaks: "the recorder sees every day — the window is opened on Mondays and Thursdays",
    look: "Records: most days have no row. Progress: the actual line is straight segments " +
      "drawn through days nothing was recorded (R1).",
    world: { humanBias: 1.3, noise: 0.3 },
    cadence: "twice-weekly",
  },
  {
    id: "supervision",
    name: "Agents need supervision",
    breaks:
      "agent work costs no human time — each running agent step takes a quarter of a person's day",
    look: "Human steps slow down whenever agents run; the forecast, which prices the two pools " +
      "apart, never sees it (S1). The later milestones slip three or four days.",
    world: { agentLoad: 0.25 },
  },
  {
    id: "realistic",
    name: "A realistic mix",
    breaks:
      "several at once — optimistic estimates, noise, some scope creep, occasional re-estimates",
    look: "What a real project probably looks like. Compare the model variants in Track record.",
    world: {
      humanBias: 1.3,
      agentBias: 1.1,
      noise: 0.35,
      scopePerWeek: 1,
      reestimateEvery: 10,
      reestimateFactor: 1.25,
    },
  },
];

export function scenarioById(id: string): Scenario {
  return SCENARIOS.find((found) => found.id === id) ?? SCENARIOS[0];
}
