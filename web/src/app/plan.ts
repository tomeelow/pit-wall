import type { SimRace } from "../contract/sim";
import type { Strategy } from "../sim/index.ts";
import { dryTyre, tyreLabel } from "./compounds";
import type { Strings } from "./i18n";
import type { LaneStint } from "./StintLane";

/** Laps from..to inclusive on one set; compound null for wet or unknown tyres. */
export interface Segment {
  from: number;
  to: number;
  compound: number | null;
}

/** The car's stints over the whole race: what it really ran up to fromLap, `strategy` after. */
export function planSegments(
  race: SimRace,
  car: number,
  fromLap: number,
  strategy: Strategy,
): Segment[] {
  const past = race.cars[car]!.stops.filter((s) => s.lap <= fromLap);
  const first = past[0];
  const beforeFirst = race.snapshots.find((s) => s.lap === (first ? first.lap - 1 : fromLap));
  // A timed car with no compound was on wet or unknown tyres (before first_start_lap).
  let compound: number | null =
    beforeFirst && beforeFirst.race_time_s[car] != null
      ? (beforeFirst.compound_c[car] ?? null)
      : (first?.compound_c ?? race.compounds[0]!);
  let from = 1;
  const out: Segment[] = [];
  for (const stop of [...past, ...strategy]) {
    out.push({ from, to: stop.lap, compound });
    from = stop.lap + 1;
    compound = stop.compound_c;
  }
  out.push({ from, to: race.total_laps, compound });
  return out;
}

/** "C4 to lap 15, C3 to 36, C4" */
export function describePlan(t: Strings, segments: readonly Segment[]): string {
  return segments
    .map((s, k) => {
      const set = s.compound === null ? t.tyre.unknown : `C${s.compound}`;
      return k === segments.length - 1 ? set : t.toLap(set, s.to);
    })
    .join(", ");
}

/** Laps after which the car is running, for a decision: the engine needs a race state there. */
export function decisionLaps(race: SimRace, car: number): number[] {
  return race.snapshots
    .filter((s) => s.lap >= race.first_start_lap && s.lap < race.total_laps - 1 && s.compound_c[car] !== null)
    .map((s) => s.lap);
}

/** A plan as a lane: the laps before the decision are history, drawn as such. */
export function planLane(t: Strings, race: SimRace, car: number, fromLap: number, plan: Strategy): LaneStint[] {
  return planSegments(race, car, fromLap, plan).map((s) => ({
    from: s.from,
    to: s.to,
    tyre: s.compound === null ? "unknown" : dryTyre(race.compounds, s.compound),
    label: s.compound === null ? t.tyre.unknown : tyreLabel(t, race.compounds, s.compound),
    past: s.to <= fromLap,
  }));
}
