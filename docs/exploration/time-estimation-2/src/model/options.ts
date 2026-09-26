/**
 * The model's options: each one a proposed change to DPlanner's time model. With all of them
 * off the port computes exactly what DPlanner computes today, quirks included — that is what
 * the parity tools hold it to (`FAITHFUL`). A change decided on for the backport moves into
 * `ADOPTED`, which the page always runs, and leaves `VARIANTS`, the experiments still open.
 * ISSUES.md says which issue each answers; add the next experiment here and thread it where
 * it bites.
 */
export interface ModelOptions {
  /** Round a fractional day up with a 1e-9 guard, so float noise cannot add a day. */
  epsilon: boolean;
  /** A stretch begins where the previous one ended, not on the next whole working day. */
  carry: boolean;
  /**
   * How what is done and under way moves the dates.
   * - `off`: it does not; every date is simulated from the project's start (DPlanner today).
   * - `restart`: done work drops out, and everything unfinished starts again, at its full
   *   estimate, from today — v3's model, kept to show the saw-tooth it draws (ISSUES F5).
   * - `resume`: the plan's own dates stand while what is done matches them; otherwise the
   *   rest resumes from tomorrow, with work in flight credited for the days already spent.
   */
  replan: "off" | "restart" | "resume";
  /**
   * Under `resume`, once the plan no longer holds: the rest re-estimated at the pace so far —
   * the days finished steps were given against the working days they took (`paceSoFar`).
   * A choice the reader makes (v5's toolbar), never the default: ISSUES.md F6 has why.
   */
  pace: boolean;
}

export const FAITHFUL: ModelOptions = {
  epsilon: false,
  carry: false,
  replan: "off",
  pace: false,
};

/** What the page runs (ISSUES F1, F5, I1, Q3). */
export const ADOPTED: ModelOptions = {
  epsilon: true,
  carry: true,
  replan: "resume",
  pace: false,
};

export const GUARD = 1e-9;

export function guardOf(options: ModelOptions): number {
  return options.epsilon ? GUARD : 0;
}

/** The experiments still open: none, while every proposal so far has been adopted. */
export const VARIANTS: { key: "epsilon" | "carry"; label: string; hint: string }[] = [];
