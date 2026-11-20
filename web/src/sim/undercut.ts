import type { SimRace } from "../contract/sim";
import { createDraw, createRandoms, fillDraw, fillRandoms } from "./draw.ts";
import { createTrace, createWorkspace, simulateRace, type Mode } from "./engine.ts";
import { actualStrategies, compilePlan, prepare, type Strategy } from "./prepare.ts";
import { Rng } from "./rng.ts";

export interface UndercutQuery {
  attacker: number; // car indexes
  defender: number;
  lap: number; // the first of the two in-laps
  attackerCompound: number; // C-numbers of the new sets
  defenderCompound: number;
  runs: number;
  seed: number;
  mode: Mode;
}

/** Why the answer is what it is, from posterior means at the start of `lap`. */
export interface UndercutComponents {
  gapS: number; // attacker's time behind the defender (negative: ahead)
  paceDeltaS: number; // attacker's free-air pace advantage per lap, tyres aside
  tyreDeltaS: number; // attacker's new set over the defender's old one, on the attacker's out-lap
  pitLossS: { p10: number; median: number; p90: number }; // a green stop
  warmupS: { attacker: number[]; defender: number[] }; // per stint lap of the new sets
}

export interface UndercutResult {
  undercut: number; // P(attacker ahead) once both have stopped: attacker first, defender next lap
  overcut: number; // the same with the defender stopping first
  runs: { undercut: number; overcut: number }; // runs in which both cars were still running
  components: UndercutComponents;
}

/**
 * Attacker and defender stop on consecutive laps; everyone else keeps the actual plan. The answer
 * is read at the end of `lap + 2`, when the second car has finished its out-lap: the engine charges
 * the pit loss on the in-lap, and the out-lap adds the new set's pace and warm-up. The two cars'
 * other stops are dropped; none could matter by then. Common random numbers across the two orders.
 */
export function undercut(race: SimRace, query: UndercutQuery): UndercutResult {
  const { attacker, defender, lap, attackerCompound, defenderCompound, runs, seed, mode } = query;
  if (lap < 2 || lap > race.total_laps - 2) {
    throw new Error(`the first in-lap must be 2 .. ${race.total_laps - 2}`);
  }
  const prepared = prepare(race, lap - 1);
  if (!prepared.alive[attacker] || !prepared.alive[defender]) {
    throw new Error("both cars must be running at the start of the lap");
  }
  const stop = (at: number, compound_c: number): Strategy => [{ lap: at, compound_c, tyre_age: 0 }];
  const plan = (first: number, second: number) => {
    const set = actualStrategies(race, lap - 1);
    set[first] = stop(lap, first === attacker ? attackerCompound : defenderCompound);
    set[second] = stop(lap + 1, second === attacker ? attackerCompound : defenderCompound);
    return compilePlan(prepared, set);
  };
  const plans = [plan(attacker, defender), plan(defender, attacker)];
  const draw = createDraw(prepared);
  const random = createRandoms(prepared);
  const ws = createWorkspace(prepared);
  const trace = createTrace(prepared);
  const read = (lap + 2) * prepared.cars;
  const ahead = [0, 0];
  const counted = [0, 0];
  for (let r = 0; r < runs; r++) {
    fillDraw(race, r % race.draws, draw);
    fillRandoms(new Rng(seed, r), draw.nu, random);
    plans.forEach((p, k) => {
      simulateRace(prepared, p, draw, random, mode, ws, trace);
      const a = trace.position[read + attacker]!;
      const d = trace.position[read + defender]!;
      if (a === 0 || d === 0) return; // a retirement: no order to read
      counted[k]!++;
      if (a < d) ahead[k]!++;
    });
  }
  return {
    undercut: ahead[0]! / Math.max(counted[0]!, 1),
    overcut: ahead[1]! / Math.max(counted[1]!, 1),
    runs: { undercut: counted[0]!, overcut: counted[1]! },
    components: components(race, query),
  };
}

function components(race: SimRace, query: UndercutQuery): UndercutComponents {
  const { attacker, defender, lap, attackerCompound, defenderCompound } = query;
  const prepared = prepare(race, lap - 1);
  const draw = createDraw(prepared);
  fillDraw(race, "mean", draw);
  const k = prepared.compounds;
  const index = (c: number) => {
    const found = prepared.compoundIndex.get(c);
    if (found === undefined) throw new Error(`C${c} has no parameters`);
    return found;
  };
  const a = index(attackerCompound);
  const old = prepared.compound[defender]!;
  // On lap + 1 the defender's set has run two more laps; the attacker's new one is on its first.
  const defenderOld =
    draw.offset[old]! + draw.slope[defender * k + old]! * (prepared.age[defender]! + 2);
  const attackerNew = draw.offset[a]! + draw.slope[attacker * k + a]!;
  const stationary = prepared.stationary;
  const quantile = (q: number) =>
    race.pit_loss.transit_s + stationary[Math.floor(q * (stationary.length - 1))]!;
  const warmup = (c: number) => {
    const w = prepared.warmupLaps;
    return Array.from({ length: w }, (_, j) => draw.warmup[index(c) * w + j]!);
  };
  return {
    gapS: prepared.time[attacker]! - prepared.time[defender]!,
    paceDeltaS: draw.pace[defender]! - draw.pace[attacker]!,
    tyreDeltaS: defenderOld - attackerNew,
    pitLossS: { p10: quantile(0.1), median: quantile(0.5), p90: quantile(0.9) },
    warmupS: { attacker: warmup(attackerCompound), defender: warmup(defenderCompound) },
  };
}
