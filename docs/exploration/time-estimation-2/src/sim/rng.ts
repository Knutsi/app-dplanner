/** A seeded PRNG, so a scenario plays the same way every time it is opened. */

export type Rng = () => number; // Uniform in [0, 1).

/** mulberry32: small, fast, and good enough for a simulation nobody bets on. */
export function rng(seed: number): Rng {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A seed from a seed and a name, so one step's luck does not move when another is added. */
export function seedOf(seed: number, name: string): number {
  let hash = (seed ^ 0x811c9dc5) >>> 0;
  for (let index = 0; index < name.length; index += 1) {
    hash = Math.imul(hash ^ name.charCodeAt(index), 16777619) >>> 0;
  }
  return hash;
}

/** A standard normal draw (Box–Muller). */
export function normal(random: Rng): number {
  const u = Math.max(random(), 1e-12);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * random());
}

/** A lognormal factor with mean 1: how far one step's real effort lands from its estimate. */
export function lognormal(random: Rng, sigma: number): number {
  return sigma ? Math.exp(sigma * normal(random) - (sigma * sigma) / 2) : 1;
}

export function choose<T>(random: Rng, items: readonly T[]): T {
  return items[Math.floor(random() * items.length)];
}
