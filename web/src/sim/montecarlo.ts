import type { SimRace } from "../contract/sim";
import { createDraw, createRandoms, fillDraw, fillRandoms } from "./draw.ts";
import { createWorkspace, simulateRace, type Mode } from "./engine.ts";
import { compilePlan, prepare, type Strategy } from "./prepare.ts";
import { Rng } from "./rng.ts";

/**
 * Several strategy sets for the same race, compared under common random numbers: simulation i
 * uses posterior draw i mod draws and the same random numbers for every set.
 */
export interface Query {
  fromLap: number;
  sets: readonly (readonly Strategy[])[]; // per set, one strategy per car
  runs: number;
  seed: number;
  mode: Mode;
  /** Use the posterior mean instead of one draw per simulation (replays only). */
  meanParameters?: boolean;
}

/** Simulations first .. first + runs - 1 of a query. Entry [(set * runs + run) * cars + car]. */
export interface Outcome {
  first: number;
  runs: number;
  sets: number;
  cars: number;
  position: Int8Array;
  status: Uint8Array;
}

export function runSimulations(race: SimRace, query: Query, first = 0, runs = query.runs): Outcome {
  const prepared = prepare(race, query.fromLap);
  const plans = query.sets.map((set) => compilePlan(prepared, set));
  const draw = createDraw(prepared);
  const random = createRandoms(prepared);
  const ws = createWorkspace(prepared);
  const n = prepared.cars;
  const outcome: Outcome = {
    first,
    runs,
    sets: plans.length,
    cars: n,
    position: new Int8Array(plans.length * runs * n),
    status: new Uint8Array(plans.length * runs * n),
  };
  if (query.meanParameters) fillDraw(race, "mean", draw);
  for (let r = 0; r < runs; r++) {
    const index = first + r;
    if (!query.meanParameters) fillDraw(race, index % race.draws, draw);
    fillRandoms(new Rng(query.seed, index), draw.nu, random);
    plans.forEach((plan, s) => {
      simulateRace(prepared, plan, draw, random, query.mode, ws);
      const at = (s * runs + r) * n;
      outcome.position.set(ws.position, at);
      outcome.status.set(ws.status, at);
    });
  }
  return outcome;
}

/** Outcomes of consecutive, non-overlapping chunks of one query, joined in run order. */
export function mergeOutcomes(chunks: readonly Outcome[]): Outcome {
  const sorted = [...chunks].sort((a, b) => a.first - b.first);
  const head = sorted[0];
  if (!head) throw new Error("no outcomes to merge");
  const { sets, cars } = head;
  const runs = sorted.reduce((sum, c) => sum + c.runs, 0);
  const merged: Outcome = {
    first: head.first,
    runs,
    sets,
    cars,
    position: new Int8Array(sets * runs * cars),
    status: new Uint8Array(sets * runs * cars),
  };
  let offset = 0;
  for (const chunk of sorted) {
    if (chunk.first !== head.first + offset) throw new Error("outcome chunks are not contiguous");
    for (let s = 0; s < sets; s++) {
      const from = s * chunk.runs * cars;
      const to = (s * runs + offset) * cars;
      const size = chunk.runs * cars;
      merged.position.set(chunk.position.subarray(from, from + size), to);
      merged.status.set(chunk.status.subarray(from, from + size), to);
    }
    offset += chunk.runs;
  }
  return merged;
}
