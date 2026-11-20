import type { StrategySettings } from "../contract/manifest";
import type { PlannedStop, SimRace } from "../contract/sim";
import { candidates } from "./candidates.ts";
import type { Mode } from "./engine.ts";
import { optimise } from "./optimise.ts";
import { actualStrategies, type Strategy } from "./prepare.ts";
import {
  distribution,
  paired,
  withStrategy,
  type Distribution,
  type Evaluate,
} from "./strategy.ts";

/** Future safety cars, VSCs, red flags and retirements drawn from their rates. */
export const EX_ANTE: Mode = { events: "sampled", noise: true };
/** They happen when they did; lap noise and stop times are still drawn. */
export const EX_POST: Mode = { events: "realised", noise: true };

/**
 * Two numbers, both expected places on runs the searches never saw:
 * - regret: what the stop itself cost. The best plan found against the best plan that makes this
 *   stop (same lap, same set) and plays the rest well. Later decisions are not charged here.
 * - planRegret: what the whole actual plan from here cost, later stops included.
 * The searches always include the actual plan and every plan that makes the actual stop, so a
 * stop outside the candidate grid (a free tyre change under a red flag, say) is still found.
 */
export interface Verdict {
  best: Strategy;
  bestWithStop: Strategy;
  regret: number;
  regretSe: number;
  planRegret: number;
  planRegretSe: number;
  actual: Distribution;
  bestDistribution: Distribution;
}

/** One pit decision, judged from the race state at the end of the lap before its in-lap. */
export interface Decision {
  stop: PlannedStop;
  fromLap: number;
  exAnte: Verdict; // was it a good call?
  exPost: Verdict; // did it work out? Never merged with exAnte.
}

export async function debrief(
  race: SimRace,
  car: number,
  settings: StrategySettings,
  seed: number,
  evaluate: Evaluate,
): Promise<Decision[]> {
  const decisions: Decision[] = [];
  for (const stop of race.cars[car]!.stops) {
    const fromLap = stop.lap - 1;
    if (fromLap < 1) continue;
    const options = candidates(race, car, fromLap, settings);
    if (options.length === 0) continue; // not running at that lap
    const actual = actualStrategies(race, fromLap)[car]!;
    // After the stop the car is on the set it really fitted: the race state there is real.
    const withStop = [
      actual,
      ...candidates(race, car, stop.lap, settings).map((rest) => [stop, ...rest]),
    ];
    const verdict = async (mode: Mode): Promise<Verdict> => {
      const best = async (pool: readonly Strategy[]) =>
        (
          await optimise(
            race,
            {
              car,
              fromLap,
              candidates: pool,
              objective: { kind: "position" },
              mode,
              seed,
              settings,
            },
            evaluate,
          )
        ).ranked[0]!.strategy;
      const overall = await best([...withStop, ...options]);
      const given = await best(withStop);
      const holdout = await evaluate(
        {
          fromLap,
          sets: [actual, overall, given].map((s) => withStrategy(race, fromLap, car, s)),
          runs: settings.holdout_runs,
          seed,
          mode,
        },
        settings.max_runs,
      );
      const decision = paired(holdout, 2, 1, car);
      const plan = paired(holdout, 0, 1, car);
      return {
        best: overall,
        bestWithStop: given,
        regret: decision.meanGain,
        regretSe: decision.meanGainSe,
        planRegret: plan.meanGain,
        planRegretSe: plan.meanGainSe,
        actual: distribution(race, holdout, 0, car),
        bestDistribution: distribution(race, holdout, 1, car),
      };
    };
    decisions.push({
      stop,
      fromLap,
      exAnte: await verdict(EX_ANTE),
      exPost: await verdict(EX_POST),
    });
  }
  return decisions;
}
