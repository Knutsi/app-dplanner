/**
 * A synthetic plan shaped like the real ones this was built against.
 *
 * What the real plans have in common (DPlanner's own, the dermatology module, Local
 * measurement): one start step; milestones in a chain, each gathering what branches out of
 * the previous one and collects into it; most steps agent work sized in quarter days; a
 * few human steps sized in whole days; milestone steps opted out of estimating; and a
 * couple of steps nobody has sized yet. The seed changes the shape, never the kind.
 */

import { type Day, fromYMD } from "../model/calendar.ts";
import type { Plan, Step } from "../model/graph.ts";
import { choose, type Rng, rng } from "./rng.ts";

export const SAMPLE_START: Day = fromYMD(2026, 10, 5); // A Monday.

const VERBS = [
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
  "Index",
];
const NOUNS = [
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
  "the onboarding",
];
const HUMAN = [
  "Review the design",
  "Decide the data model",
  "Usability walkthrough",
  "Security review",
  "Write the migration guide",
  "Pair on the hard part",
];

export interface SampleShape {
  milestones: number;
  branches: [number, number]; // Parallel chains per stretch, least and most.
  chain: [number, number]; // Steps per chain.
  agentShare: number;
  unestimated: number;
}

export const SAMPLE_SHAPE: SampleShape = {
  milestones: 4,
  branches: [2, 3],
  chain: [2, 4],
  agentShare: 0.75,
  unestimated: 2,
};

function between(random: Rng, [least, most]: [number, number]): number {
  return least + Math.floor(random() * (most - least + 1));
}

export function samplePlan(seed: number, shape: SampleShape = SAMPLE_SHAPE): Plan {
  const random = rng(seed);
  const steps: Step[] = [];
  const add = (title: string, fields: Partial<Step> = {}): Step => {
    const step: Step = {
      id: `s${steps.length + 1}`,
      number: steps.length + 1,
      title,
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
      delay: null,
      ...fields,
    };
    steps.push(step);
    return step;
  };
  const origin = add("Project start", { estimate: 0.0 });
  let previous = origin;
  for (let index = 1; index <= shape.milestones; index += 1) {
    const ends: string[] = [];
    for (let branch = 0; branch < between(random, shape.branches); branch += 1) {
      let at = previous.id;
      for (let link = 0; link < between(random, shape.chain); link += 1) {
        const agent = random() < shape.agentShare;
        const step = agent
          ? add(`${choose(random, VERBS)} ${choose(random, NOUNS)}`, {
            agent: true,
            estimate: choose(random, [0.25, 0.25, 0.5, 0.5, 0.75, 1, 1.5]),
          })
          : add(choose(random, HUMAN), { estimate: choose(random, [1, 1, 2, 2, 3, 5]) });
        step.requires = [at];
        at = step.id;
      }
      ends.push(at);
    }
    previous = add(`Release ${index}`, {
      milestone: `M${index}`,
      estimateOff: true,
      requires: ends,
    });
  }
  const sized = steps.filter((step) => step.estimate && step !== origin);
  for (let left = shape.unestimated; left > 0 && sized.length; left -= 1) {
    sized.splice(Math.floor(random() * sized.length), 1)[0].estimate = null;
  }
  return {
    id: `sample-${seed}`,
    title: `Sample plan (seed ${seed})`,
    start: SAMPLE_START,
    assumptions: { efficiency: 0.5, palette: null, team: [1, 2] },
    steps,
  };
}
