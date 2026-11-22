import type { StrategySettings } from "../contract/manifest";
import type { PlannedStop, SimRace } from "../contract/sim";
import type { Strategy } from "./prepare.ts";
import { minDryCompounds } from "./rules.ts";

/**
 * Plans for one car from the race state after `fromLap` that the rules allow: 0 to max_stops
 * stops in all, every planned stint at least min_stint_laps long (the stint running at fromLap
 * counted from its start) and no longer than its C-number's cap (wear beyond the stints of other
 * races is extrapolated), on a new set of any C-number with min_race_clean_laps in the race (with
 * fewer, its pace and wear are extrapolated from other races, and the search would exploit that).
 * Which sets a driver really had left is not in the data, so every such C-number counts as
 * available new.
 *
 * Pit laps are one lap apart while the candidates fit in max_candidates. Plans with fewer stops
 * come first; when the next stop count does not fit, its pit laps are spread further apart.
 */
export function candidates(
  race: SimRace,
  car: number,
  fromLap: number,
  settings: StrategySettings,
): Strategy[] {
  const snapshot = race.snapshots.find((s) => s.lap === fromLap);
  const compound = snapshot?.compound_c[car];
  if (!snapshot || fromLap < race.first_start_lap || compound === null || compound === undefined) return [];
  const total = race.total_laps;
  const { min_stops, max_stint_laps } = race.rules;
  const min_dry_compounds = minDryCompounds(race, car);
  const done = snapshot.stops[car] ?? 0;
  const stintSoFar = (snapshot.stint_laps[car] ?? 0) - fromLap; // + lap gives the stint's length
  const usedBefore = new Set(snapshot.dry_compounds[car] ?? []);
  const minStint = settings.min_stint_laps;
  const offered = race.compounds.filter(
    (_, c) => race.degradation.race_clean_laps[c]! >= settings.min_race_clean_laps,
  );

  const legal = (stops: readonly PlannedStop[]): boolean => {
    const used = new Set(usedBefore);
    for (const stop of stops) used.add(stop.compound_c);
    return used.size >= min_dry_compounds && done + stops.length >= min_stops;
  };
  const fitsMax = (length: number) => max_stint_laps === null || length <= max_stint_laps;
  // A running stint at or past its cap may still stop at the first lap the other bounds allow.
  const cap = (c: number, running: boolean): number => {
    const learnt = race.degradation.max_stint_laps[race.compounds.indexOf(c)] ?? Infinity;
    return running ? Math.max(learnt, minStint, stintSoFar + fromLap + 1) : learnt;
  };
  const stintOk = (length: number, c: number, running: boolean) =>
    length >= minStint && fitsMax(length) && length <= cap(c, running);

  /** All m-stop plans with pit laps `step` apart, or null once there are more than `limit`. */
  const plans = (m: number, step: number, limit: number): Strategy[] | null => {
    const out: Strategy[] = [];
    const stops: PlannedStop[] = [];
    const extend = (previous: number): boolean => {
      if (stops.length === m) {
        const last = stops.length === 0 ? null : stops[stops.length - 1]!;
        const final = last === null ? stintSoFar + total : total - last.lap;
        const ok =
          last === null
            ? fitsMax(final) && final <= cap(compound, true)
            : stintOk(final, last.compound_c, false);
        if (!ok || !legal(stops)) return true;
        out.push([...stops]);
        return out.length <= limit;
      }
      const start = stops.length === 0 ? fromLap + 1 : previous + minStint;
      for (let lap = start; lap < total; lap += step) {
        const running = stops.length === 0;
        const length = running ? stintSoFar + lap : lap - previous;
        const on = running ? compound : stops[stops.length - 1]!.compound_c;
        if (!stintOk(length, on, running)) continue;
        for (const c of offered) {
          stops.push({ lap, compound_c: c, tyre_age: 0 });
          const more = extend(lap);
          stops.pop();
          if (!more) return false;
        }
      }
      return true;
    };
    return extend(fromLap) ? out : null;
  };

  const all: Strategy[] = [];
  for (let m = 0; m <= settings.max_stops - done; m++) {
    const room = settings.max_candidates - all.length;
    if (room <= 0) break;
    for (let step = 1; step < total; step++) {
      const found = plans(m, step, room);
      if (found) {
        all.push(...found);
        break;
      }
    }
  }
  return all;
}
