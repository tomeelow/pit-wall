import type { SimRace } from "../contract/sim";
import type { Strategy } from "./prepare.ts";

/** Why the engine cannot run a plan; the app words it in the viewer's language. */
export type InvalidPlan =
  | { kind: "not-running"; fromLap: number }
  | { kind: "pit-order"; fromLap: number; total: number }
  | { kind: "not-allocated"; compound: number };

export type BrokenRule =
  | { kind: "compounds"; used: number; need: number }
  | { kind: "stops"; made: number; need: number }
  | { kind: "stint"; laps: number; limit: number };

export type RuleIssue = InvalidPlan | BrokenRule;

export interface RuleCheck {
  /** Plans the engine cannot run: nothing to simulate until they are fixed. */
  invalid: InvalidPlan[];
  /** Rules the plan breaks: it runs, and the engine disqualifies it, as the stewards would. */
  breaks: BrokenRule[];
}

/**
 * The engine's own legality test (engine.ts classify) read from the race state after `fromLap`:
 * dry compounds used, stops made, and the longest stint from the one running at fromLap on.
 */
export function checkRules(
  race: SimRace,
  car: number,
  fromLap: number,
  strategy: Strategy,
): RuleCheck {
  const snapshot = race.snapshots.find((s) => s.lap === fromLap);
  const running = snapshot?.compound_c[car];
  if (!snapshot || running === null || running === undefined) {
    return { invalid: [{ kind: "not-running", fromLap }], breaks: [] };
  }
  const total = race.total_laps;
  const invalid: InvalidPlan[] = [];
  let previous = fromLap;
  for (const stop of strategy) {
    if (stop.lap <= previous || stop.lap >= total) {
      invalid.push({ kind: "pit-order", fromLap, total });
      break;
    }
    if (!race.compounds.includes(stop.compound_c)) {
      invalid.push({ kind: "not-allocated", compound: stop.compound_c });
    }
    previous = stop.lap;
  }

  const { min_dry_compounds, min_stops, max_stint_laps } = race.rules;
  const breaks: BrokenRule[] = [];
  const used = new Set([...(snapshot.dry_compounds[car] ?? []), ...strategy.map((s) => s.compound_c)]);
  if (used.size < min_dry_compounds) {
    breaks.push({ kind: "compounds", used: used.size, need: min_dry_compounds });
  }
  const stops = (snapshot.stops[car] ?? 0) + strategy.length;
  if (stops < min_stops) breaks.push({ kind: "stops", made: stops, need: min_stops });
  if (max_stint_laps !== null) {
    let start = fromLap - (snapshot.stint_laps[car] ?? 0);
    let longest = 0;
    for (const end of [...strategy.map((s) => s.lap), total]) {
      longest = Math.max(longest, end - start);
      start = end;
    }
    if (longest > max_stint_laps) {
      breaks.push({ kind: "stint", laps: longest, limit: max_stint_laps });
    }
  }
  return { invalid, breaks };
}
