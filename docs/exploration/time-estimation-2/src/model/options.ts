/**
 * Model variants: each flag is one proposed change to DPlanner's time model, off by default.
 * With every flag off the port computes exactly what DPlanner computes today, quirks
 * included — that is what the parity tests hold it to. ISSUES.md says which issue each flag
 * answers; add the next experiment here and thread it where it bites.
 */
export interface ModelOptions {
  /** Round a fractional day up with a 1e-9 guard, so float noise cannot add a day. */
  epsilon: boolean;
  /** A stretch begins where the previous one ended, not on the next whole working day. */
  carry: boolean;
  /** Done work drops out, and what remains is simulated from today. */
  replan: boolean;
}

export const FAITHFUL: ModelOptions = { epsilon: false, carry: false, replan: false };

export const GUARD = 1e-9;

export function guardOf(options: ModelOptions): number {
  return options.epsilon ? GUARD : 0;
}

export const VARIANTS: { key: keyof ModelOptions; label: string; hint: string }[] = [
  {
    key: "epsilon",
    label: "Round with a guard",
    hint: "ceil(days − 1e-9): 25.000000000000004 working days is 25, not 26",
  },
  {
    key: "carry",
    label: "Carry part-days between milestones",
    hint:
      "the next stretch starts at the fraction of a day the previous one ended, not the next morning",
  },
  {
    key: "replan",
    label: "Re-plan from today",
    hint: "done steps cost nothing, and the first unfinished stretch starts no earlier than today",
  },
];
