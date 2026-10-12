// The plan store: the only place plan data lives in the page. It is filled in bulk — load()
// takes a whole snapshot, the shape a backend-for-frontend would send in one response — and
// no component ever fetches. A view reads signals here; a command writes through update(),
// which returns its own undo. Every write bumps the step's revision and says who made it, so
// a view can flash what *someone else* changed and stay still for what you did.

import { signal, computed, batch } from "../engine/signals.js";

export const STATUSES = ["pending", "in-progress", "ready-for-review", "ready-to-merge", "done", "blocked"];
export const STATUS_LABEL = {
  pending: "Pending",
  "in-progress": "In Progress",
  "ready-for-review": "Ready for Review",
  "ready-to-merge": "Ready to Merge",
  done: "Done",
  blocked: "Blocked",
};

export const projects = signal([]); // [{ id, name, repo }]
export const steps = signal(new Map()); // id -> step
export const milestones = signal([]); // [{ id, projectId, name, order }]
export const lastWrite = signal(null); // { ids, writer } — what changed last, and by whom

export function load(snapshot) {
  batch(() => {
    projects.value = snapshot.projects;
    milestones.value = snapshot.milestones;
    steps.value = new Map(snapshot.steps.map((s) => [s.id, { rev: 0, ...s }]));
  });
}

// Writes `patch` to each step; returns the undo. `writer` is "you" or who else did it.
export function update(ids, patch, writer = "you") {
  const before = new Map();
  const next = new Map(steps.peek());
  for (const id of ids) {
    const step = next.get(id);
    if (!step) continue;
    before.set(id, Object.fromEntries(Object.keys(patch).map((k) => [k, step[k]])));
    next.set(id, { ...step, ...patch, rev: step.rev + 1, updated: Date.now() });
  }
  batch(() => {
    steps.value = next;
    lastWrite.value = { ids: [...before.keys()], writer };
  });
  return () => {
    const back = new Map(steps.peek());
    for (const [id, old] of before) back.set(id, { ...back.get(id), ...old, rev: back.get(id).rev + 1 });
    batch(() => {
      steps.value = back;
      lastWrite.value = { ids: [...before.keys()], writer };
    });
  };
}

export const stepsOf = (projectId) => computed(() => [...steps.value.values()].filter((s) => s.projectId === projectId));
