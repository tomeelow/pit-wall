import type { PlannedStop, SimRace } from "../contract/sim";
import { minDryCompounds } from "./rules.ts";

/** Neutralisation kinds, by index in every per-kind array of the engine. */
export const KINDS = ["SC", "VSC", "RED"] as const;
export const GREEN = -1;
export const SC = 0;
export const VSC = 1;
export const RED = 2;

/** One plan per car, in SimRace.cars order: the stops it makes after the start lap. */
export type Strategy = readonly PlannedStop[];

/** Everything about a race and a start lap that does not change between simulations. */
export interface Prepared {
  race: SimRace;
  cars: number;
  laps: number; // total race laps
  fromLap: number; // simulations start after this lap
  compounds: number; // count; per-compound arrays follow race.compounds
  warmupLaps: number; // stint laps with a warm-up term, from the out-lap
  compoundIndex: Map<number, number>; // C-number → index
  // Start state, per car. A retired car has alive 0.
  time: Float64Array;
  compound: Int32Array; // index into race.compounds
  age: Int32Array;
  stintLaps: Int32Array;
  stops: Int32Array;
  used: Int32Array; // bit C set when C-number C has been used
  minCompounds: Int32Array; // dry C-numbers the car must use: 0 once it ran wet tyres
  alive: Uint8Array;
  retiredAfter: Int32Array; // realised: last lap completed by a car that did not finish, else -1
  // Realised neutralisation per lap (GREEN where none) and the lap it ends.
  realisedKind: Int8Array;
  realisedEnd: Int32Array;
  // A neutralisation running at the start lap, known then; its end is not.
  ongoing: { kind: number; startLap: number } | null;
  durations: Int32Array[]; // per kind, empirical
  stationary: Float64Array; // sorted
  lapFactor: Float64Array; // per kind
  pitFactor: Float64Array; // per kind
}

export function prepare(race: SimRace, fromLap: number): Prepared {
  const snapshot = race.snapshots.find((s) => s.lap === fromLap);
  if (!snapshot || fromLap < race.first_start_lap) {
    throw new Error(`no race state to simulate from after lap ${fromLap} (${race.first_start_lap} .. ${race.total_laps - 1})`);
  }
  const n = race.cars.length;
  const compoundIndex = new Map(race.compounds.map((c, i) => [c, i]));
  const time = new Float64Array(n);
  const compound = new Int32Array(n);
  const age = new Int32Array(n);
  const stintLaps = new Int32Array(n);
  const stops = new Int32Array(n);
  const used = new Int32Array(n);
  const alive = new Uint8Array(n);
  const retiredAfter = new Int32Array(n).fill(-1);
  race.cars.forEach((car, i) => {
    const t = snapshot.race_time_s[i];
    const c = snapshot.compound_c[i];
    stops[i] = snapshot.stops[i] ?? 0;
    for (const used_c of snapshot.dry_compounds[i] ?? []) used[i]! |= 1 << used_c;
    if (car.retired_after_lap !== null) retiredAfter[i] = car.retired_after_lap;
    if (t === null || t === undefined || c === null || c === undefined) return;
    const index = compoundIndex.get(c);
    if (index === undefined) throw new Error(`${car.driver}: C${c} has no parameters`);
    time[i] = t;
    compound[i] = index;
    age[i] = snapshot.tyre_age[i] ?? 0;
    stintLaps[i] = snapshot.stint_laps[i] ?? 0;
    alive[i] = 1;
  });

  const realisedKind = new Int8Array(race.total_laps + 2).fill(GREEN);
  const realisedEnd = new Int32Array(race.total_laps + 2);
  let ongoing: Prepared["ongoing"] = null;
  for (const period of race.realised) {
    const kind = KINDS.indexOf(period.kind);
    for (let lap = period.start_lap; lap <= Math.min(period.end_lap, race.total_laps); lap++) {
      realisedKind[lap] = kind;
      realisedEnd[lap] = period.end_lap;
    }
    if (period.start_lap <= fromLap && fromLap < period.end_lap) {
      ongoing = { kind, startLap: period.start_lap };
    }
  }

  const params = KINDS.map((kind) => {
    const found = race.neutralisations.find((p) => p.kind === kind);
    if (!found) throw new Error(`no ${kind} parameters`);
    return found;
  });
  const factor = (kind: number) => {
    if (kind === RED) return race.rules.red_flag_free_tyre_change ? 0 : race.pit_loss.sc_factor;
    return kind === VSC ? race.pit_loss.vsc_factor : race.pit_loss.sc_factor;
  };
  return {
    race,
    cars: n,
    laps: race.total_laps,
    fromLap,
    compounds: race.compounds.length,
    warmupLaps: race.degradation.warmup_s[0]?.length ?? 0,
    compoundIndex,
    time,
    compound,
    age,
    stintLaps,
    stops,
    used,
    minCompounds: Int32Array.from(race.cars, (_, i) => minDryCompounds(race, i)),
    alive,
    retiredAfter,
    realisedKind,
    realisedEnd,
    ongoing,
    durations: params.map((p) => Int32Array.from(p.duration_laps).sort()),
    stationary: Float64Array.from(race.pit_loss.stationary_s).sort(),
    lapFactor: Float64Array.from(params, (p) => p.lap_factor),
    pitFactor: Float64Array.from(KINDS, (_, kind) => factor(kind)),
  };
}

/** The strategies the cars actually ran, from the start lap on. */
export function actualStrategies(race: SimRace, fromLap: number): Strategy[] {
  return race.cars.map((car) => car.stops.filter((stop) => stop.lap > fromLap));
}

/** Per-car stops as flat arrays, checked against the race. */
export interface Plan {
  offset: Int32Array; // car i's stops are entries offset[i] .. offset[i + 1] - 1
  lap: Int32Array;
  compound: Int32Array; // index into race.compounds
  cNumber: Int32Array;
  tyreAge: Int32Array;
}

export function compilePlan(prepared: Prepared, strategies: readonly Strategy[]): Plan {
  if (strategies.length !== prepared.cars) {
    throw new Error(`expected ${prepared.cars} strategies, got ${strategies.length}`);
  }
  const total = strategies.reduce((sum, s) => sum + s.length, 0);
  const plan: Plan = {
    offset: new Int32Array(prepared.cars + 1),
    lap: new Int32Array(total),
    compound: new Int32Array(total),
    cNumber: new Int32Array(total),
    tyreAge: new Int32Array(total),
  };
  let k = 0;
  strategies.forEach((strategy, i) => {
    plan.offset[i] = k;
    let previous = prepared.fromLap;
    for (const stop of strategy) {
      const driver = prepared.race.cars[i]?.driver;
      if (stop.lap <= previous || stop.lap >= prepared.laps) {
        throw new Error(
          `${driver}: stop laps must increase, after lap ${prepared.fromLap} and before ` +
            `lap ${prepared.laps}`,
        );
      }
      const index = prepared.compoundIndex.get(stop.compound_c);
      if (index === undefined) throw new Error(`${driver}: C${stop.compound_c} has no parameters`);
      if (stop.tyre_age < 0) throw new Error(`${driver}: tyre age must be at least 0`);
      plan.lap[k] = stop.lap;
      plan.compound[k] = index;
      plan.cNumber[k] = stop.compound_c;
      plan.tyreAge[k] = stop.tyre_age;
      previous = stop.lap;
      k++;
    }
  });
  plan.offset[prepared.cars] = k;
  return plan;
}
