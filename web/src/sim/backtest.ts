import type { SimRace } from "../contract/sim";
import { createDraw, createRandoms, fillDraw, fillRandoms } from "./draw.ts";
import { createWorkspace, isClassified, simulateRace } from "./engine.ts";
import { actualStrategies, compilePlan, prepare } from "./prepare.ts";
import { Rng } from "./rng.ts";

/**
 * Where each car finished across `runs` ex-ante simulations from `fromLap`, with the strategies
 * actually run. counts[car][k] for k < cars is finishing k + 1; counts[car][cars] is not
 * classified. A car not running at the start lap is not classified in every run.
 */
export function finishCounts(
  race: SimRace,
  fromLap: number,
  runs: number,
  seed: number,
): number[][] {
  const prepared = prepare(race, fromLap);
  const plan = compilePlan(prepared, actualStrategies(race, fromLap));
  const draw = createDraw(prepared);
  const random = createRandoms(prepared);
  const ws = createWorkspace(prepared);
  const n = prepared.cars;
  const counts = Array.from({ length: n }, () => new Array<number>(n + 1).fill(0));
  for (let r = 0; r < runs; r++) {
    fillDraw(race, r % race.draws, draw);
    fillRandoms(new Rng(seed, r), draw.nu, random);
    simulateRace(prepared, plan, draw, random, { events: "sampled", noise: true }, ws);
    for (let i = 0; i < n; i++) {
      counts[i]![isClassified(ws, i, prepared) ? ws.position[i]! - 1 : n]!++;
    }
  }
  return counts;
}

/** The start lap for each share of race distance: lap 1 for 0, never the last lap, no repeats. */
export function startLaps(
  totalLaps: number,
  fractions: readonly number[],
): { fraction: number; lap: number }[] {
  const seen = new Set<number>();
  const starts = [];
  for (const fraction of fractions) {
    const lap = Math.min(totalLaps - 1, Math.max(1, Math.round(fraction * totalLaps)));
    if (seen.has(lap)) continue;
    seen.add(lap);
    starts.push({ fraction, lap });
  }
  return starts;
}
