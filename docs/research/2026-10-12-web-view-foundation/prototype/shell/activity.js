// Background work: an agent run, a report build, an import. Long work reports where the person
// is looking — on the object it belongs to — and in one status-bar item that opens the
// Activity panel. When it ends: the item's badge always; a toast only if this person started
// it and it took long enough that they will have moved on; never a modal.

import { signal, computed } from "../engine/signals.js";

const TOAST_AFTER_MS = 4000; // the research says 10 s; the prototype's jobs are short

export const tasks = signal([]); // [{ id, label, subject, progress, state, started, ended, by }]
export const running = computed(() => tasks.value.filter((t) => t.state === "running"));
export const unseen = signal(0); // finished since the panel was last opened

let nextId = 1;
const listeners = new Set();
export const onFinish = (fn) => (listeners.add(fn), () => listeners.delete(fn));

function patch(id, change) {
  tasks.value = tasks.peek().map((t) => (t.id === id ? { ...t, ...change } : t));
}

// Runs `steps` (async functions given a progress setter) one after another.
export function startTask(label, { subject = null, by = "you", steps = [] } = {}) {
  const id = nextId++;
  const task = { id, label, subject, progress: 0, state: "running", started: Date.now(), ended: null, by };
  tasks.value = [task, ...tasks.peek()].slice(0, 20);
  (async () => {
    try {
      for (let i = 0; i < steps.length; i++) {
        await steps[i]((fraction) => patch(id, { progress: (i + fraction) / steps.length }));
        patch(id, { progress: (i + 1) / steps.length });
      }
      patch(id, { state: "done", ended: Date.now(), progress: 1 });
    } catch (error) {
      patch(id, { state: "failed", ended: Date.now(), error: String(error.message ?? error) });
    }
    unseen.value++;
    const done = tasks.peek().find((t) => t.id === id);
    for (const listener of listeners) listener(done, { notify: done.by === "you" && done.ended - done.started > TOAST_AFTER_MS });
  })();
  return id;
}

export const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
