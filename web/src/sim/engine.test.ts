import { describe, expect, it } from "vitest";
import type { PlannedStop, SimRace } from "../contract/sim";
import {
  actualStrategies,
  compilePlan,
  createDraw,
  createRandoms,
  createTrace,
  createWorkspace,
  DNF,
  DSQ,
  fillDraw,
  fillRandoms,
  FINISHED,
  mergeOutcomes,
  prepare,
  Rng,
  runSimulations,
  simulateRace,
  type Mode,
  type Strategy,
} from "./index.ts";
import { GREEN, SC } from "./prepare.ts";
import { syntheticRace, type SyntheticOptions } from "./synthetic.ts";

const SAMPLED: Mode = { events: "sampled", noise: true };
const REPLAY: Mode = { events: "realised", noise: false };

/** One simulation, with its trace and final state. */
function simulate(
  race: SimRace,
  {
    fromLap = 1,
    mode = SAMPLED,
    index = 0,
    seed = 1,
    strategies = undefined as Strategy[] | undefined,
  } = {},
) {
  const prepared = prepare(race, fromLap);
  const plan = compilePlan(prepared, strategies ?? actualStrategies(race, fromLap));
  const draw = createDraw(prepared);
  fillDraw(race, index % race.draws, draw);
  const random = createRandoms(prepared);
  fillRandoms(new Rng(seed, index), draw.nu, random);
  const ws = createWorkspace(prepared);
  const trace = createTrace(prepared);
  simulateRace(prepared, plan, draw, random, mode, ws, trace);
  return { prepared, plan, ws, trace };
}

const query = (sets: Strategy[][], runs = 200, seed = 1) => ({
  fromLap: 1,
  sets,
  runs,
  seed,
  mode: SAMPLED,
});

describe("determinism and common random numbers", () => {
  const race = syntheticRace({
    cars: 10,
    laps: 30,
    eventRate: 0.03,
    dnfRate: 0.002,
  });
  const actual = actualStrategies(race, 1);

  it("gives identical outcomes for the same seed, and different ones for another", () => {
    const a = runSimulations(race, query([actual]));
    const b = runSimulations(race, query([actual]));
    const c = runSimulations(race, query([actual], 200, 2));
    expect(a.position).toEqual(b.position);
    expect(a.position).not.toEqual(c.position);
  });

  it("shows every strategy set the same random numbers", () => {
    const out = runSimulations(race, query([actual, actual]));
    const size = out.runs * out.cars;
    expect(out.position.subarray(0, size)).toEqual(out.position.subarray(size));
  });

  it("ties random numbers to the simulation index, so chunks merge into the whole", () => {
    const q = query([actual, actual.map(() => [])]);
    const whole = runSimulations(race, q);
    const merged = mergeOutcomes([
      runSimulations(race, q, 120, 80),
      runSimulations(race, q, 0, 120),
    ]);
    expect(merged.position).toEqual(whole.position);
    expect(merged.status).toEqual(whole.status);
  });
});

/** A random legal-looking plan: 0-3 stops on increasing laps, random compounds and set ages. */
function randomStrategy(rng: Rng, race: SimRace, fromLap: number): PlannedStop[] {
  const count = Math.floor(rng.uniform() * 4);
  const laps = new Set<number>();
  for (let k = 0; k < count; k++) {
    laps.add(fromLap + 1 + Math.floor(rng.uniform() * (race.total_laps - fromLap - 1)));
  }
  return [...laps]
    .sort((a, b) => a - b)
    .map((lap) => ({
      lap,
      compound_c: race.compounds[Math.floor(rng.uniform() * race.compounds.length)]!,
      tyre_age: Math.floor(rng.uniform() * 4),
    }));
}

describe("invariants over random races and strategies", () => {
  it("holds positions, tyre ages, stops, retirements and the rules", () => {
    const rng = new Rng(2024);
    for (let scenario = 0; scenario < 40; scenario++) {
      const options: SyntheticOptions = {
        cars: 2 + Math.floor(rng.uniform() * 19),
        laps: 10 + Math.floor(rng.uniform() * 50),
        eventRate: rng.uniform() * 0.1,
        dnfRate: rng.uniform() * 0.02,
        spacingS: rng.uniform() * 3,
        paceStepS: (rng.uniform() - 0.5) * 0.5,
      };
      const race = syntheticRace(options);
      const fromLap = 1 + Math.floor(rng.uniform() * (race.total_laps - 2));
      const strategies = race.cars.map(() => randomStrategy(rng, race, fromLap));
      const { prepared, plan, ws, trace } = simulate(race, {
        fromLap,
        strategies,
        index: scenario,
      });
      const n = prepared.cars;

      let previousAlive = n;
      for (let lap = fromLap + 1; lap <= race.total_laps; lap++) {
        const row = Array.from(trace.position.subarray(lap * n, (lap + 1) * n));
        const alive = row.filter((p) => p > 0).sort((a, b) => a - b);
        expect(alive).toEqual(alive.map((_, k) => k + 1));
        expect(alive.length).toBeLessThanOrEqual(previousAlive);
        previousAlive = alive.length;
        for (let i = 0; i < n; i++) {
          const before = lap * n - n + i;
          if (lap > fromLap + 1 && trace.position[before] === 0) {
            expect(trace.position[lap * n + i]).toBe(0); // retired cars never come back
          }
          if (trace.position[lap * n + i] === 0 || lap === fromLap + 1) continue;
          const stopped = trace.stops[lap * n + i]! - trace.stops[before]!;
          expect(stopped === 0 || stopped === 1).toBe(true);
          const stop = Array.from(plan.lap.subarray(plan.offset[i], plan.offset[i + 1])).indexOf(
            lap,
          );
          if (stop >= 0) {
            expect(stopped).toBe(1);
            expect(trace.age[lap * n + i]).toBe(plan.tyreAge[plan.offset[i]! + stop]);
          } else {
            expect(trace.age[lap * n + i]).toBe(trace.age[before]! + 1);
          }
        }
      }

      const final = Array.from(ws.position).sort((a, b) => a - b);
      expect(final).toEqual(final.map((_, k) => k + 1));
      for (let i = 0; i < n; i++) {
        if (ws.status[i] === DNF) continue;
        const compounds = new Set(
          [...(race.snapshots[fromLap - 1]!.dry_compounds[i] ?? [])].concat(
            strategies[i]!.map((s) => s.compound_c),
          ),
        );
        // The synthetic rules: two dry compounds, no stop minimum, no stint limit.
        expect(ws.status[i]).toBe(compounds.size >= 2 ? FINISHED : DSQ);
      }
    }
  });
});

describe("rules", () => {
  const quiet = { eventRate: 0, dnfRate: 0, cars: 4, laps: 20 };

  it("disqualifies a car that breaks a rule and classifies it last", () => {
    const race = syntheticRace(quiet);
    // From lap 1 every car has used one compound; car 0 never stops, car 1 stops onto another.
    const strategies: Strategy[] = race.cars.map(() => []);
    strategies[1] = [{ lap: 5, compound_c: 3, tyre_age: 0 }];
    const { ws } = simulate(race, { strategies, mode: REPLAY });
    expect(ws.status[0]).toBe(DSQ);
    expect(ws.status[1]).toBe(FINISHED);
    expect(ws.position[1]).toBe(1);

    const twoStops = { ...race, rules: { ...race.rules, min_stops: 2 } };
    expect(simulate(twoStops, { strategies, mode: REPLAY }).ws.status[1]).toBe(DSQ);
    const shortStints = {
      ...race,
      rules: { ...race.rules, max_stint_laps: 10 },
    };
    expect(simulate(shortStints, { strategies, mode: REPLAY }).ws.status[1]).toBe(DSQ);
  });

  it("rejects plans the race cannot run", () => {
    const race = syntheticRace(quiet);
    const prepared = prepare(race, 5);
    const none = race.cars.map(() => [] as PlannedStop[]);
    const withStop = (stop: PlannedStop) => [[stop], ...none.slice(1)];
    expect(() => compilePlan(prepared, none.slice(1))).toThrow(/strategies/);
    expect(() => compilePlan(prepared, withStop({ lap: 5, compound_c: 2, tyre_age: 0 }))).toThrow(
      /after lap 5/,
    );
    expect(() => compilePlan(prepared, withStop({ lap: 8, compound_c: 6, tyre_age: 0 }))).toThrow(
      /C6/,
    );
  });
});

describe("mechanics", () => {
  it("keeps the order of equal cars with no events and no noise", () => {
    const race = syntheticRace({
      paceStepS: 0,
      eventRate: 0,
      dnfRate: 0,
      spacingS: 2,
      cars: 6,
    });
    const { ws } = simulate(race, { mode: REPLAY });
    expect(Array.from(ws.position)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it("lets a much faster car through", () => {
    const race = syntheticRace({
      paceStepS: 0,
      eventRate: 0,
      dnfRate: 0,
      cars: 3,
    });
    race.cars[2]!.pace_s = race.cars[2]!.pace_s.map((p) => p - 1.5);
    expect(simulate(race, { mode: REPLAY }).ws.position[2]).toBe(1);
  });

  it("charges the pit loss, scaled under a safety car", () => {
    const race = syntheticRace({ cars: 1, laps: 12, eventRate: 0, dnfRate: 0 });
    // A stop onto an identical set: the only difference is the time in the pit lane.
    const sameSet = [{ lap: 6, compound_c: 2, tyre_age: 6 }];
    const time = (r: SimRace, strategies: Strategy[]) =>
      simulate(r, { strategies, mode: REPLAY }).ws.time[0]!;
    const green = time(race, [sameSet]) - time(race, [[]]);
    const median = [...race.pit_loss.stationary_s].sort((a, b) => a - b)[3]!;
    expect(green).toBeCloseTo(race.pit_loss.transit_s + median, 6);

    const underSc = {
      ...race,
      realised: [{ kind: "SC" as const, start_lap: 6, end_lap: 6 }],
    };
    const sc = time(underSc, [sameSet]) - time(underSc, [[]]);
    expect(sc).toBeCloseTo(green * race.pit_loss.sc_factor, 6);

    const underRed = { ...race, realised: [{ kind: "RED" as const, start_lap: 6, end_lap: 6 }] };
    expect(time(underRed, [sameSet]) - time(underRed, [[]])).toBeCloseTo(0, 6);
  });

  it("closes the field up behind a safety car", () => {
    const race = syntheticRace({
      laps: 5,
      spacingS: 5,
      eventRate: 0,
      dnfRate: 0,
      cars: 8,
    });
    race.realised = [{ kind: "SC", start_lap: 3, end_lap: 5 }];
    const { ws, trace } = simulate(race, {
      mode: REPLAY,
      strategies: race.cars.map(() => []),
    });
    expect(Array.from(trace.neutralisation.subarray(3, 6))).toEqual([SC, SC, SC]);
    const times = Array.from(ws.time).sort((a, b) => a - b);
    for (let k = 1; k < times.length; k++) {
      expect(times[k]! - times[k - 1]!).toBeLessThanOrEqual(race.mechanics.restart_gap_s + 1e-9);
    }
  });

  it("passes as often as the pass model says", () => {
    const race = syntheticRace({
      cars: 2,
      spacingS: 0.5,
      paceStepS: 0,
      eventRate: 0,
      dnfRate: 0,
      noiseSd: 0,
      passIntercept: 1,
    });
    race.cars[1]!.pace_s = race.cars[1]!.pace_s.map((p) => p - 0.4);
    const fromLap = race.total_laps - 1;
    race.snapshots[fromLap - 1]!.compound_c = [1, 1]; // same tyres: the pace delta is 0.4 s
    const runs = 4000;
    const out = runSimulations(race, {
      ...query([actualStrategies(race, fromLap)], runs),
      fromLap,
    });
    let passes = 0;
    let expected = 0;
    let variance = 0;
    for (let r = 0; r < runs; r++) {
      passes += out.position[r * 2 + 1] === 1 ? 1 : 0;
      const d = r % race.draws;
      const logit =
        race.traffic.intercept[d]! +
        race.traffic.beta_gap_s[d]! * 0.5 +
        race.traffic.beta_pace_delta_s[d]! * 0.4 +
        race.traffic.beta_within_drs[d]!;
      const p = 1 / (1 + Math.exp(-logit));
      expected += p;
      variance += p * (1 - p);
    }
    expect(expected / runs).toBeGreaterThan(0.1); // the test means something
    expect(Math.abs(passes - expected)).toBeLessThan(4 * Math.sqrt(variance));
  });

  it("samples neutralisations and retirements at their rates, and none at rate 0", () => {
    const calm = syntheticRace({ eventRate: 0, dnfRate: 0, cars: 4 });
    const { trace, ws } = simulate(calm);
    expect(trace.neutralisation.every((k) => k === GREEN)).toBe(true);
    expect(Array.from(ws.status).every((s) => s !== DNF)).toBe(true);

    const rate = 0.01;
    const race = syntheticRace({
      eventRate: 0,
      dnfRate: rate,
      cars: 20,
      laps: 60,
    });
    const out = runSimulations(race, query([actualStrategies(race, 1)], 500));
    const dnfs = out.status.reduce((sum, s) => sum + (s === DNF ? 1 : 0), 0);
    const p = 1 - Math.exp(-rate * 59);
    const n = out.status.length;
    expect(Math.abs(dnfs - n * p)).toBeLessThan(4 * Math.sqrt(n * p * (1 - p)));

    // Safety cars only, all 3 laps long: back-to-back ones merge, so runs are multiples of 3.
    const busy = syntheticRace({ eventRate: 0.05, dnfRate: 0, cars: 4 });
    busy.neutralisations = busy.neutralisations.map((p) =>
      p.kind === "SC"
        ? { ...p, duration_laps: [3] }
        : { ...p, rate_per_lap: p.rate_per_lap.map(() => 0) },
    );
    const lengths: number[] = [];
    for (let index = 0; index < 50; index++) {
      const kinds = simulate(busy, { index }).trace.neutralisation;
      let run = 0;
      for (let lap = 2; lap < busy.total_laps; lap++) {
        if (kinds[lap] === SC) run++;
        else if (run > 0) {
          if (kinds[lap] === GREEN) lengths.push(run);
          run = 0;
        }
      }
    }
    expect(lengths.length).toBeGreaterThan(0);
    for (const length of lengths) expect(length % 3).toBe(0);
  });

  it("knows a neutralisation running at the start lap, but not when it ends", () => {
    const race = syntheticRace({ eventRate: 0, dnfRate: 0, cars: 4 });
    race.realised = [{ kind: "SC", start_lap: 5, end_lap: 9 }];
    for (let index = 0; index < 20; index++) {
      const kinds = simulate(race, { fromLap: 6, index }).trace.neutralisation;
      expect(kinds[7]).toBe(SC); // 2 laps run, so it lasts 3 or 4 of [2, 3, 4]
      expect(kinds[9]).toBe(GREEN); // the realised end (lap 9) is not used
    }
  });
});
