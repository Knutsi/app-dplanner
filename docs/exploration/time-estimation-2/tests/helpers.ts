/** Hand-rolled asserts and a small plan builder — the tests import nothing from outside. */

import { type Day, fromYMD } from "../src/model/calendar.ts";
import type { Delay, Plan, Status, Step } from "../src/model/graph.ts";

export function assert(condition: unknown, message = "assertion failed"): asserts condition {
  if (!condition) throw new Error(message);
}

function show(value: unknown): string {
  return JSON.stringify(value, (_key, inner) => (inner instanceof Map ? [...inner] : inner));
}

export function assertEquals(actual: unknown, expected: unknown, message = ""): void {
  const [a, b] = [show(actual), show(expected)];
  if (a !== b) throw new Error(`${message ? message + ": " : ""}expected ${b}\n     got ${a}`);
}

export function assertClose(actual: number, expected: number, within = 1e-9): void {
  if (Math.abs(actual - expected) > within) throw new Error(`expected ≈${expected}, got ${actual}`);
}

export function assertThrows(run: () => unknown, pattern?: RegExp): void {
  try {
    run();
  } catch (error) {
    if (pattern && !pattern.test(String(error))) throw new Error(`threw the wrong thing: ${error}`);
    return;
  }
  throw new Error("expected it to throw");
}

// 2026-09-07 is a Monday; 2026-09-12 a Saturday — the Python suite's dates.
export const MONDAY: Day = fromYMD(2026, 9, 7);
export const SATURDAY: Day = fromYMD(2026, 9, 12);
export const sep = (day: number): Day => fromYMD(2026, 9, day);

export interface Shape {
  days?: Record<string, number>;
  requires?: Record<string, string[]>;
  chain?: boolean; // Each step requires the one before it.
  milestones?: string[];
  agents?: string[];
  done?: string[];
  starts?: Record<string, Day>;
  start?: Day | null;
  created?: Record<string, Day>;
  running?: string[]; // In progress.
  since?: Record<string, Day>;
  delays?: Record<string, Delay>; // Delay steps: no estimate, no status of their own.
}

/** A plan whose step ids are their titles, so a test reads like the Python one. */
export function planOf(titles: string[], shape: Shape = {}): Plan {
  const steps: Step[] = titles.map((title, index) => ({
    id: title,
    number: index + 1,
    title,
    requires: shape.requires?.[title] ?? (shape.chain && index ? [titles[index - 1]] : []),
    estimate: shape.days?.[title] ?? null,
    estimateOff: Boolean(shape.delays?.[title]),
    estimateHistory: [],
    status:
      (shape.done?.includes(title)
        ? "done"
        : shape.running?.includes(title)
        ? "in-progress"
        : "pending") as Status,
    milestone: shape.milestones?.includes(title) ? title : null,
    agent: shape.agents?.includes(title) ?? false,
    created: shape.created?.[title] ?? null,
    start: shape.starts?.[title] ?? null,
    color: null,
    since: shape.since?.[title] ?? null,
    delay: shape.delays?.[title] ?? null,
  }));
  return {
    id: "plan",
    title: "Discovery",
    start: shape.start ?? null,
    assumptions: { efficiency: null, palette: null, team: null },
    steps,
  };
}

export const CHAIN = ["A", "B", "C", "D"];
export const DAYS = { A: 1.0, B: 2.0, C: 3.0, D: 4.0 };
