import { describe, expect, it } from "vitest";
import type { StrategySettings } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import {
  candidates,
  compilePlan,
  counterfactual,
  debrief,
  inProcess,
  optimise,
  prepare,
  undercut,
  type Mode,
  type Strategy,
} from "./index.ts";
import { syntheticRace } from "./synthetic.ts";

const REPLAY: Mode = { events: "realised", noise: false };
const SAMPLED: Mode = { events: "sampled", noise: true };
const SETTINGS: StrategySettings = {
  max_stops: 2,
  min_stint_laps: 5,
  max_candidates: 1500,
  min_race_clean_laps: 10,
  first_runs: 4,
  eta: 3,
  keep: 3,
  max_runs: 36,
  holdout_runs: 24,
};

/**
 * Two identical cars that never meet on track, both on C2 after lap 1, with one fixed stop time:
 * a plan's race time is then a sum this test can do by hand, and the best plan is known.
 */
function knownRace(): SimRace {
  const race = syntheticRace({ cars: 2, laps: 30, eventRate: 0, dnfRate: 0, spacingS: 0 });
  race.traffic = { ...race.traffic, max_gap_s: -1 }; // never close enough to interact
  race.pit_loss = { ...race.pit_loss, stationary_s: [2.5] };
  race.snapshots[0]!.compound_c[1] = 2;
  race.snapshots[0]!.dry_compounds[1] = [2];
  return race;
}

/** Car 0's race time from the end of lap 1, without the terms every plan shares. */
function planTime(race: SimRace, plan: Strategy): number {
  const index = (c: number) => race.compounds.indexOf(c);
  const offset = (c: number) => race.degradation.offset_s[index(c)]![0]!;
  const slope = (c: number) => race.cars[0]!.slope_s_per_lap[index(c)]![0]!;
  let compound = 2;
  let age = 1;
  let time = 0;
  let next = 0;
  for (let lap = 2; lap <= race.total_laps; lap++) {
    time += offset(compound) + slope(compound) * (age + 1);
    age++;
    const stop = plan[next];
    if (stop?.lap === lap) {
      time += race.pit_loss.transit_s + 2.5;
      compound = stop.compound_c;
      age = stop.tyre_age;
      next++;
    }
  }
  return time;
}

describe("candidates", () => {
  const race = knownRace();

  it("lists only plans the rules and the stint bounds allow", () => {
    const plans = candidates(race, 0, 1, SETTINGS);
    expect(plans.length).toBeGreaterThan(100);
    const prepared = prepare(race, 1);
    for (const plan of plans) {
      expect(plan.length).toBeGreaterThanOrEqual(1); // C2 alone breaks the two-compound rule
      expect(plan.length).toBeLessThanOrEqual(SETTINGS.max_stops);
      expect(new Set([2, ...plan.map((s) => s.compound_c)]).size).toBeGreaterThanOrEqual(2);
      const ends = [...plan.map((s) => s.lap), race.total_laps];
      const stints = ends.map((end, k) => end - (k === 0 ? 0 : ends[k - 1]!));
      expect(Math.min(...stints)).toBeGreaterThanOrEqual(SETTINGS.min_stint_laps);
      expect(() => compilePlan(prepared, [plan, []])).not.toThrow();
    }
    // One stop: every lap that leaves both stints long enough, onto C1 or C3.
    const oneStop = plans.filter((p) => p.length === 1);
    expect(oneStop).toHaveLength((25 - 5 + 1) * 2);
  });

  it("applies race rules, spreads pit laps to fit the budget, and skips cars not running", () => {
    const monaco = { ...race, rules: { ...race.rules, min_stops: 2 } };
    expect(candidates(monaco, 0, 1, SETTINGS).every((p) => p.length >= 2)).toBe(true);
    const qatar = { ...race, rules: { ...race.rules, max_stint_laps: 12 } };
    for (const plan of candidates(qatar, 0, 1, SETTINGS)) {
      const ends = [...plan.map((s) => s.lap), race.total_laps];
      expect(Math.max(...ends.map((end, k) => end - (k === 0 ? 0 : ends[k - 1]!)))).toBeLessThan(
        13,
      );
    }
    // C3 barely ran in this race: it is not proposed.
    const unproven = {
      ...race,
      degradation: { ...race.degradation, race_clean_laps: [100, 100, 3] },
    };
    const proposed = candidates(unproven, 0, 1, SETTINGS).flatMap((p) =>
      p.map((s) => s.compound_c),
    );
    expect(new Set(proposed)).toEqual(new Set([1, 2]));
    // Wear beyond the stints of other races is extrapolated: C1 never runs more than 10 laps, and
    // a running C2 stint capped below the minimum stint stops as soon as that allows.
    const capped = {
      ...race,
      degradation: { ...race.degradation, max_stint_laps: [10, 3, null] },
    };
    const cappedPlans = candidates(capped, 0, 1, SETTINGS);
    expect(cappedPlans.length).toBeGreaterThan(0);
    for (const plan of cappedPlans) {
      const ends = [...plan.map((s) => s.lap), race.total_laps];
      plan.forEach((stop, k) => {
        if (stop.compound_c === 1) expect(ends[k + 1]! - stop.lap).toBeLessThanOrEqual(10);
      });
    }
    expect(cappedPlans.every((p) => p[0]!.lap === SETTINGS.min_stint_laps)).toBe(true);
    const tight = candidates(race, 0, 1, { ...SETTINGS, max_candidates: 100 });
    expect(tight.length).toBeLessThanOrEqual(100);
    expect(tight.filter((p) => p.length === 1)).toHaveLength(42); // one-stop plans keep every lap
    expect(tight.some((p) => p.length === 2)).toBe(true);

    const retired = knownRace();
    retired.snapshots[9]!.race_time_s[0] = null;
    retired.snapshots[9]!.compound_c[0] = null;
    expect(candidates(retired, 0, 10, SETTINGS)).toEqual([]);
  });
});

describe("counterfactual", () => {
  const race = syntheticRace({ cars: 8, laps: 30, eventRate: 0.03, dnfRate: 0.002 });
  const query = { car: 3, fromLap: 5, runs: 200, seed: 3, mode: SAMPLED };

  it("finds no difference between a strategy and itself", async () => {
    const same = await counterfactual(race, { ...query, strategy: race.cars[3]!.stops });
    expect(same.alternative).toEqual(same.actual);
    expect([same.ahead, same.behind, same.meanGain, same.meanGainSe]).toEqual([0, 0, 0, 0]);
    const { places, notClassified, disqualified, runs } = same.actual;
    expect(places.reduce((a, b) => a + b, 0) + notClassified + disqualified).toBe(runs);
  });

  it("gives a rule-breaking plan its real consequence", async () => {
    // Car 3 started on C1: never changing compound breaks the two-compound rule.
    const illegal = await counterfactual(race, { ...query, strategy: [] });
    // Only a car that retires escapes the stewards.
    expect(illegal.alternative.disqualified).toBeGreaterThan(0.9 * illegal.alternative.runs);
    expect(illegal.behind).toBeGreaterThan(0.9);
  });
});

describe("optimise", () => {
  it("recovers the known best plan, and spends fewer runs than brute force", async () => {
    const race = knownRace();
    const plans = candidates(race, 0, 1, SETTINGS);
    const byTime = [...plans].sort((a, b) => planTime(race, a) - planTime(race, b));
    const [best, second] = [byTime[0]!, byTime[1]!];
    expect(planTime(race, second) - planTime(race, best)).toBeGreaterThan(0.01);
    // The rival runs the second-best plan, a hair faster: only the best plan beats it.
    race.cars[1]!.stops = [...second];
    race.cars[1]!.pace_s = race.cars[0]!.pace_s.map((p) => p - 0.0001);

    for (const objective of [{ kind: "beat", rival: 1 } as const, { kind: "position" } as const]) {
      const result = await optimise(
        race,
        {
          car: 0,
          fromLap: 1,
          candidates: plans,
          objective,
          mode: REPLAY,
          seed: 1,
          settings: SETTINGS,
        },
        inProcess(race),
      );
      expect(result.ranked[0]!.strategy).toEqual(best);
      expect(result.ranked[0]!.distribution.places[0]).toBe(SETTINGS.max_runs);
      expect(result.ranked).toHaveLength(SETTINGS.keep);
      expect(result.simulations).toBeLessThan(plans.length * SETTINGS.max_runs);
    }
  });
});

describe("undercut", () => {
  /** Car 1 starts lap 10 one second behind car 0; both on C2 aged 9 laps. */
  function duel(slope: number): SimRace {
    const race = syntheticRace({
      cars: 2,
      laps: 30,
      eventRate: 0,
      dnfRate: 0,
      spacingS: 1,
      paceStepS: 0,
    });
    race.snapshots[8]!.compound_c[1] = 2;
    for (const car of race.cars) car.slope_s_per_lap[1] = car.slope_s_per_lap[1]!.map(() => slope);
    return race;
  }
  const query = {
    attacker: 1,
    defender: 0,
    lap: 10,
    attackerCompound: 2,
    defenderCompound: 2,
    runs: 200,
    seed: 5,
  };

  it("works when the old tyres are slow and fails the other way round", () => {
    const race = duel(0.3);
    const exact = undercut(race, { ...query, mode: REPLAY });
    expect([exact.undercut, exact.overcut]).toEqual([1, 0]);
    // The attacker nets ~1.7 s; a 5 s stop (1 in 7 of the stop times) undoes it.
    const result = undercut(race, { ...query, mode: SAMPLED });
    expect(result.undercut).toBeGreaterThan(0.7);
    expect(result.undercut).toBeLessThan(0.95);
    expect(result.overcut).toBeLessThan(0.1);
    expect(result.runs).toEqual({ undercut: 200, overcut: 200 });
    const parts = result.components;
    expect(parts.gapS).toBeCloseTo(1, 9);
    expect(parts.paceDeltaS).toBeCloseTo(0, 9);
    expect(parts.tyreDeltaS).toBeCloseTo(0.3 * (9 + 2) - 0.3, 9);
    expect(parts.pitLossS.median).toBeCloseTo(race.pit_loss.transit_s + 2.4, 9);
  });

  it("does not work on tyres that barely wear", () => {
    const result = undercut(duel(0.001), { ...query, mode: REPLAY });
    expect([result.undercut, result.overcut]).toEqual([0, 0]);
  });
});

describe("debrief", () => {
  it("charges a poor stop, and keeps ex ante and ex post apart", async () => {
    const race = knownRace();
    race.cars[0]!.stops = [{ lap: 6, compound_c: 1, tyre_age: 0 }]; // early, onto the slow set
    race.cars[1]!.stops = [{ lap: 15, compound_c: 3, tyre_age: 0 }];
    const [decision, ...rest] = await debrief(race, 0, SETTINGS, 2, inProcess(race));
    expect(rest).toHaveLength(0);
    expect(decision!.fromLap).toBe(5);
    for (const verdict of [decision!.exAnte, decision!.exPost]) {
      expect(verdict.planRegret).toBeGreaterThan(0.5);
      expect(verdict.best).not.toEqual(race.cars[0]!.stops);
      // The stop with the rest played well costs no more than the whole plan.
      expect(verdict.regret).toBeGreaterThan(-0.05);
      expect(verdict.regret).toBeLessThanOrEqual(verdict.planRegret + 0.05);
    }
    expect(decision!.exAnte).not.toBe(decision!.exPost);
  });

  it("finds a stop outside the candidate grid: a free tyre change under a red flag", async () => {
    const race = knownRace();
    race.realised = [{ kind: "RED", start_lap: 3, end_lap: 3 }];
    // A 3-lap first stint is shorter than any planned one, so only the actual plan has this stop.
    race.cars[0]!.stops = [{ lap: 3, compound_c: 3, tyre_age: 0 }];
    const [decision] = await debrief(race, 0, SETTINGS, 2, inProcess(race));
    expect(decision!.exPost.best[0]).toEqual(race.cars[0]!.stops[0]);
    expect(decision!.exPost.regret).toBe(0);
    // Nobody could know the red flag was coming: ex ante the stop costs a full green stop.
    expect(decision!.exAnte.regret).toBeGreaterThan(0.5);
  });
});
