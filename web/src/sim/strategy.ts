import type { SimRace } from "../contract/sim";
import { DSQ, type Mode } from "./engine.ts";
import { runSimulations, type Outcome, type Query } from "./montecarlo.ts";
import { actualStrategies, type Strategy } from "./prepare.ts";

/** A podium is the first three: a definition, not a tunable. */
const PODIUM = 3;

/** What a strategy is chosen for. "beat": finish ahead of car `rival` (an index into race.cars). */
export type Objective =
  { kind: "position" } | { kind: "podium" } | { kind: "points" } | { kind: "beat"; rival: number };

/** Simulations first .. first + query.runs - 1 of a query: in process, or on the worker pool. */
export type Evaluate = (query: Query, first: number) => Promise<Outcome>;

export function inProcess(race: SimRace): Evaluate {
  return (query, first) => Promise.resolve(runSimulations(race, query, first, query.runs));
}

/** Every car on its actual plan from `fromLap`, except `car` on `strategy` (open-loop opponents). */
export function withStrategy(
  race: SimRace,
  fromLap: number,
  car: number,
  strategy: Strategy,
): Strategy[] {
  const set = actualStrategies(race, fromLap);
  set[car] = strategy;
  return set;
}

/** One run's score for `car` in strategy set `set`: higher is better. */
export function score(
  race: SimRace,
  objective: Objective,
  outcome: Outcome,
  set: number,
  run: number,
  car: number,
): number {
  const at = (set * outcome.runs + run) * outcome.cars;
  const place = outcome.position[at + car]!;
  const classified = outcome.classified[at + car] === 1;
  switch (objective.kind) {
    case "position":
      return -place;
    case "podium":
      return classified && place <= PODIUM ? 1 : 0;
    case "points":
      return classified && place <= race.rules.points_places ? 1 : 0;
    case "beat":
      return place < outcome.position[at + objective.rival]! ? 1 : 0;
  }
}

/** Where one car finished across the runs of one strategy set. */
export interface Distribution {
  runs: number;
  places: number[]; // places[k]: runs classified in place k + 1
  notClassified: number; // retired before the classified distance
  disqualified: number; // broke a rule
  meanPosition: number; // in the engine's order: finishers, then retirements, then disqualified
  podium: number; // share of runs
  points: number; // share of runs
}

export function distribution(
  race: SimRace,
  outcome: Outcome,
  set: number,
  car: number,
): Distribution {
  const places = new Array<number>(outcome.cars).fill(0);
  let notClassified = 0;
  let disqualified = 0;
  let total = 0;
  let podium = 0;
  let points = 0;
  for (let run = 0; run < outcome.runs; run++) {
    const at = (set * outcome.runs + run) * outcome.cars + car;
    const place = outcome.position[at]!;
    total += place;
    if (outcome.status[at] === DSQ) disqualified++;
    else if (outcome.classified[at] === 0) notClassified++;
    else {
      places[place - 1]!++;
      if (place <= PODIUM) podium++;
      if (place <= race.rules.points_places) points++;
    }
  }
  const runs = outcome.runs;
  return {
    runs,
    places,
    notClassified,
    disqualified,
    meanPosition: total / runs,
    podium: podium / runs,
    points: points / runs,
  };
}

/** Strategy set `b` against set `a` for one car, run by run (common random numbers). */
export interface Paired {
  ahead: number; // share of runs in which b finishes ahead of a
  behind: number;
  meanGain: number; // mean places gained by b over a
  meanGainSe: number; // its standard error
}

export function paired(outcome: Outcome, a: number, b: number, car: number): Paired {
  let ahead = 0;
  let behind = 0;
  let sum = 0;
  let squares = 0;
  for (let run = 0; run < outcome.runs; run++) {
    const gain =
      outcome.position[(a * outcome.runs + run) * outcome.cars + car]! -
      outcome.position[(b * outcome.runs + run) * outcome.cars + car]!;
    if (gain > 0) ahead++;
    if (gain < 0) behind++;
    sum += gain;
    squares += gain * gain;
  }
  const n = outcome.runs;
  const mean = sum / n;
  const variance = n > 1 ? (squares - n * mean * mean) / (n - 1) : 0;
  return {
    ahead: ahead / n,
    behind: behind / n,
    meanGain: mean,
    meanGainSe: Math.sqrt(variance / n),
  };
}

export interface CounterfactualQuery {
  car: number;
  fromLap: number;
  strategy: Strategy; // the car's stops after fromLap
  runs: number;
  seed: number;
  mode: Mode;
}

/** The alternative is only meaningful next to the actual strategy: both, and the difference. */
export interface Comparison extends Paired {
  actual: Distribution;
  alternative: Distribution;
}

export async function counterfactual(
  race: SimRace,
  query: CounterfactualQuery,
  evaluate: Evaluate = inProcess(race),
): Promise<Comparison> {
  const { car, fromLap, strategy, runs, seed, mode } = query;
  const outcome = await evaluate(
    {
      fromLap,
      sets: [actualStrategies(race, fromLap), withStrategy(race, fromLap, car, strategy)],
      runs,
      seed,
      mode,
    },
    0,
  );
  return compare(race, outcome, car);
}

/** Set 1 against set 0 for one car: also for a partial outcome, while more runs are coming. */
export function compare(race: SimRace, outcome: Outcome, car: number): Comparison {
  return {
    actual: distribution(race, outcome, 0, car),
    alternative: distribution(race, outcome, 1, car),
    ...paired(outcome, 0, 1, car),
  };
}
