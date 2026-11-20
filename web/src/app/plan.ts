import type { SimRace } from "../contract/sim";
import type { Strategy } from "../sim/index.ts";
import { dryTyre, tyreLabel } from "./compounds";
import type { LaneStint } from "./StintLane";

/** Laps from..to inclusive on one set. */
export interface Segment {
  from: number;
  to: number;
  compound: number;
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
  let compound = beforeFirst?.compound_c[car] ?? first?.compound_c ?? race.compounds[0]!;
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
export function describePlan(segments: readonly Segment[]): string {
  return segments
    .map((s, k) => (k === segments.length - 1 ? `C${s.compound}` : `C${s.compound} to lap ${s.to}`))
    .join(", ");
}

/** Laps after which the car is running, for a decision: the engine needs a race state there. */
export function decisionLaps(race: SimRace, car: number): number[] {
  return race.snapshots
    .filter((s) => s.lap < race.total_laps - 1 && s.compound_c[car] !== null)
    .map((s) => s.lap);
}

/** A plan as a lane: the laps before the decision are history, drawn as such. */
export function planLane(race: SimRace, car: number, fromLap: number, plan: Strategy): LaneStint[] {
  return planSegments(race, car, fromLap, plan).map((s) => ({
    from: s.from,
    to: s.to,
    tyre: dryTyre(race.compounds, s.compound),
    label: tyreLabel(race.compounds, s.compound),
    past: s.to <= fromLap,
  }));
}
