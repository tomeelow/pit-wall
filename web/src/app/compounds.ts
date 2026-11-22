import type { Stint } from "../contract/race";
import type { Strings } from "./i18n";

export type Tyre = "soft" | "medium" | "hard" | "intermediate" | "wet" | "unknown";

/**
 * Pirelli names an event's dry C-numbers soft, medium and hard, the highest C-number softest.
 * The names are relative to the event; the C-number is what the models key on.
 */
export function dryTyre(compounds: readonly number[], c: number): Tyre {
  const ranked = [...compounds].sort((a, b) => b - a);
  const k = ranked.indexOf(c);
  if (k < 0) return "unknown";
  if (k === 0) return "soft";
  return k === ranked.length - 1 ? "hard" : "medium";
}

export const tyreLabel = (t: Strings, compounds: readonly number[], c: number) =>
  `C${c} ${t.tyre[dryTyre(compounds, c)]}`;

export const stintTyre = (stint: Stint) => stint.compound.toLowerCase() as Tyre;
