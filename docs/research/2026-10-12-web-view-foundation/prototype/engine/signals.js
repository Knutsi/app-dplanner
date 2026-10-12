// Signals: a value that knows who read it.
//
// Push-pull with version numbers, the scheme @preact/signals-core and the TC39 proposal
// share. A write pushes "maybe stale" down the graph and queues the effects it reaches;
// the queued effects then *pull*: each asks its sources whether their version moved, and a
// computed answers by recomputing only if one of its own sources moved. So a computed whose
// result did not change stops the wave, and nothing ever sees a half-updated graph.

let active = null; // the computed or effect currently tracking reads
let batchDepth = 0;
const queue = new Set(); // effects to run when the outermost batch ends

class Source {
  version = 0;
  subs = new Set();

  track() {
    if (active) {
      active.deps.set(this, this.version);
      this.subs.add(active);
    }
  }

  // A source answers whether it moved since `version`, refreshing itself first if it can.
  changedSince(version) {
    return this.version !== version;
  }
}

class Signal extends Source {
  #value;
  constructor(value, equals) {
    super();
    this.#value = value;
    this.equals = equals ?? Object.is;
  }
  get value() {
    this.track();
    return this.#value;
  }
  set value(next) {
    if (this.equals(this.#value, next)) return;
    this.#value = next;
    this.version++;
    batch(() => stale(this));
  }
  peek() {
    return this.#value;
  }
  update(fn) {
    this.value = fn(this.#value);
  }
}

class Computed extends Source {
  #fn;
  #value;
  deps = new Map(); // source -> the version this computed last saw
  #state = "never"; // never | maybe | fresh | running
  constructor(fn, equals) {
    super();
    this.#fn = fn;
    this.equals = equals ?? Object.is;
  }
  get value() {
    // Subscribe first, so a refresh that finds no reader does not let go of its sources;
    // record the version after, so the reader does not see this refresh as a change.
    const reader = active;
    reader && this.subs.add(reader);
    this.#refresh();
    reader?.deps.set(this, this.version);
    return this.#value;
  }
  peek() {
    this.#refresh();
    return this.#value;
  }
  changedSince(version) {
    this.#refresh();
    return this.version !== version;
  }
  markMaybe() {
    if (this.#state !== "fresh") return false;
    this.#state = "maybe";
    return true;
  }
  #refresh() {
    if (this.#state === "fresh") return;
    if (this.#state === "running") throw new Error("A computed read itself");
    if (this.#state === "maybe" && !anyMoved(this.deps)) {
      this.#state = "fresh";
      return;
    }
    this.#state = "running";
    let next;
    try {
      next = run(this, this.#fn);
    } finally {
      this.#state = "fresh";
    }
    if (this.version === 0 || !this.equals(this.#value, next)) {
      this.#value = next;
      this.version++;
    }
    if (!this.subs.size) this.detach(); // nobody watches: keep the value, not the links
  }
  // With no readers left, a computed lets go of its sources, so a row's computed is collected
  // with the row, and a write no longer visits it. It recomputes when next read.
  detach() {
    for (const dep of this.deps.keys()) unsubscribe(dep, this);
    this.deps.clear();
    this.#state = "never";
  }
}

class Effect {
  deps = new Map();
  #fn;
  #cleanup = null;
  #schedule;
  disposed = false;
  constructor(fn, schedule) {
    this.#fn = fn;
    this.#schedule = schedule;
  }
  markMaybe() {
    queue.add(this);
    return false; // effects have no subscribers to pass the wave on to
  }
  // Called when the batch ends: run only if a source really moved.
  flush() {
    if (this.disposed || !anyMoved(this.deps)) return;
    if (this.#schedule) this.#schedule(() => this.run());
    else this.run();
  }
  run() {
    if (this.disposed) return;
    this.#cleanup?.();
    const result = run(this, this.#fn);
    this.#cleanup = typeof result === "function" ? result : null;
  }
  dispose() {
    this.disposed = true;
    this.#cleanup?.();
    for (const dep of this.deps.keys()) unsubscribe(dep, this);
    this.deps.clear();
  }
}

function unsubscribe(dep, node) {
  dep.subs.delete(node);
  if (!dep.subs.size && dep instanceof Computed) dep.detach();
}

function anyMoved(deps) {
  for (const [dep, version] of deps) if (dep.changedSince(version)) return true;
  return false;
}

// Run `fn` with `node` collecting what it reads; drop the subscriptions it no longer makes.
function run(node, fn) {
  const before = node.deps;
  node.deps = new Map();
  const outer = active;
  active = node;
  try {
    return fn();
  } finally {
    active = outer;
    for (const dep of before.keys()) if (!node.deps.has(dep)) unsubscribe(dep, node);
  }
}

function stale(source) {
  for (const sub of source.subs) if (sub.markMaybe()) stale(sub);
}

export function batch(fn) {
  batchDepth++;
  try {
    return fn();
  } finally {
    if (--batchDepth === 0) {
      // An effect may write while we drain; its effects join this same drain.
      batchDepth++;
      try {
        for (const effect of queue) {
          queue.delete(effect);
          try {
            effect.flush();
          } catch (error) {
            reportError(error); // one failing effect must not strand the rest of the queue
          }
        }
      } finally {
        batchDepth--;
      }
    }
  }
}

export function untracked(fn) {
  const outer = active;
  active = null;
  try {
    return fn();
  } finally {
    active = outer;
  }
}

export const signal = (value, options) => new Signal(value, options?.equals);
export const computed = (fn, options) => new Computed(fn, options?.equals);
export const isSignal = (value) => value instanceof Source;

// Runs `fn` now and whenever what it read changes; returns a disposer. A write outside a
// batch runs the effects it reaches before the write returns. With `schedule`,
// a change hands the rerun to the scheduler instead (an element coalesces into a microtask).
export function effect(fn, { schedule } = {}) {
  const e = new Effect(fn, schedule);
  e.run();
  return () => e.dispose();
}
