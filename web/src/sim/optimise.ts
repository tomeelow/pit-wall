import type { StrategySettings } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import type { Mode } from "./engine.ts";
import { actualStrategies, type Strategy } from "./prepare.ts";
import {
  distribution,
  paired,
  score,
  withStrategy,
  type Distribution,
  type Evaluate,
  type Objective,
  type Paired,
} from "./strategy.ts";

export interface Search {
  car: number;
  fromLap: number;
  candidates: readonly Strategy[];
  objective: Objective;
  mode: Mode;
  seed: number;
  settings: StrategySettings;
}

export interface Ranked {
  strategy: Strategy;
  value: number; // mean objective score over max_runs runs: higher is better
  distribution: Distribution;
  versusActual: Paired; // places gained over the actual strategy, run by run
}

export interface SearchResult {
  ranked: Ranked[]; // best first, at most settings.keep
  actual: Ranked; // the strategy the car really ran, on the same runs
  simulations: number; // races simulated, every strategy set counted
}

/**
 * Successive halving under common random numbers. Every candidate is simulated first_runs times;
 * each round keeps the best 1/eta (never fewer than keep) and runs them on eta times as many
 * simulations, reusing the runs already done, until max_runs. Ties on the objective (often 0 for
 * podium or points) are broken on expected position, then on candidate order. The survivors and
 * the actual strategy are then scored together on the same max_runs runs.
 */
export async function optimise(
  race: SimRace,
  search: Search,
  evaluate: Evaluate,
): Promise<SearchResult> {
  const { car, fromLap, candidates, objective, mode, seed, settings } = search;
  if (candidates.length === 0) throw new Error("no candidate strategies");
  const sets = (indexes: readonly number[]) =>
    indexes.map((k) => withStrategy(race, fromLap, car, candidates[k]!));
  const value = new Float64Array(candidates.length);
  const position = new Float64Array(candidates.length);
  let alive = candidates.map((_, k) => k);
  let done = 0;
  let target = Math.min(settings.first_runs, settings.max_runs);
  let simulations = 0;

  for (;;) {
    const runs = target - done;
    const outcome = await evaluate({ fromLap, sets: sets(alive), runs, seed, mode }, done);
    simulations += alive.length * runs;
    alive.forEach((k, set) => {
      for (let run = 0; run < runs; run++) {
        value[k]! += score(race, objective, outcome, set, run, car);
        position[k]! += score(race, { kind: "position" }, outcome, set, run, car);
      }
    });
    done = target;
    alive.sort((a, b) => value[b]! - value[a]! || position[b]! - position[a]! || a - b);
    if (alive.length <= settings.keep || done >= settings.max_runs) break;
    alive = alive.slice(0, Math.max(settings.keep, Math.ceil(alive.length / settings.eta)));
    target = Math.min(settings.max_runs, done * settings.eta);
  }

  const finalists = alive.slice(0, settings.keep);
  const outcome = await evaluate(
    {
      fromLap,
      sets: [actualStrategies(race, fromLap), ...sets(finalists)],
      runs: settings.max_runs,
      seed,
      mode,
    },
    0,
  );
  simulations += (finalists.length + 1) * settings.max_runs;
  const rank = (set: number, strategy: Strategy): Ranked => {
    let total = 0;
    for (let run = 0; run < outcome.runs; run++) {
      total += score(race, objective, outcome, set, run, car);
    }
    return {
      strategy,
      value: total / outcome.runs,
      distribution: distribution(race, outcome, set, car),
      versusActual: paired(outcome, 0, set, car),
    };
  };
  const ranked = finalists
    .map((k, i) => rank(i + 1, candidates[k]!))
    .sort((a, b) => b.value - a.value || a.distribution.meanPosition - b.distribution.meanPosition);
  return { ranked, actual: rank(0, actualStrategies(race, fromLap)[car]!), simulations };
}
