import type { SimRace } from "../contract/sim";
import type { Strategy } from "./prepare.ts";

export interface RuleCheck {
  /** Plans the engine cannot run: nothing to simulate until they are fixed. */
  invalid: string[];
  /** Rules the plan breaks: it runs, and the engine disqualifies it, as the stewards would. */
  breaks: string[];
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
    return { invalid: [`Not running after lap ${fromLap}.`], breaks: [] };
  }
  const total = race.total_laps;
  const invalid: string[] = [];
  let previous = fromLap;
  for (const stop of strategy) {
    if (stop.lap <= previous || stop.lap >= total) {
      invalid.push(`Pit laps must rise, after lap ${fromLap} and before lap ${total}.`);
      break;
    }
    if (!race.compounds.includes(stop.compound_c)) {
      invalid.push(`C${stop.compound_c} was not allocated for this race.`);
    }
    previous = stop.lap;
  }

  const { min_dry_compounds, min_stops, max_stint_laps } = race.rules;
  const breaks: string[] = [];
  const used = new Set([...(snapshot.dry_compounds[car] ?? []), ...strategy.map((s) => s.compound_c)]);
  if (used.size < min_dry_compounds) {
    breaks.push(`Uses ${used.size} dry compound; the rules need ${min_dry_compounds}.`);
  }
  const stops = (snapshot.stops[car] ?? 0) + strategy.length;
  if (stops < min_stops) breaks.push(`Makes ${stops} stops; the rules need ${min_stops}.`);
  if (max_stint_laps !== null) {
    let start = fromLap - (snapshot.stint_laps[car] ?? 0);
    let longest = 0;
    for (const end of [...strategy.map((s) => s.lap), total]) {
      longest = Math.max(longest, end - start);
      start = end;
    }
    if (longest > max_stint_laps) {
      breaks.push(`Runs a ${longest}-lap stint; the limit is ${max_stint_laps}.`);
    }
  }
  return { invalid, breaks };
}
