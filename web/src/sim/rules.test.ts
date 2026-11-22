import { describe, expect, it } from "vitest";
import {
  checkRules,
  DSQ,
  prepare,
  runSimulations,
  withStrategy,
  type Mode,
  type Strategy,
} from "./index.ts";
import { syntheticRace } from "./synthetic.ts";

const REPLAY: Mode = { events: "realised", noise: false };

describe("checkRules", () => {
  const race = syntheticRace({ cars: 3, laps: 30, eventRate: 0, dnfRate: 0 });
  race.rules = { ...race.rules, min_dry_compounds: 2, min_stops: 1, max_stint_laps: 20 };
  const fromLap = 5;
  const [low, mid, high] = race.compounds as [number, number, number];
  const running = race.snapshots.find((s) => s.lap === fromLap)!.compound_c[0]!;
  const other = running === low ? mid : low;
  const plans: Strategy[] = [
    [],
    [{ lap: 15, compound_c: running, tyre_age: 0 }],
    [{ lap: 15, compound_c: other, tyre_age: 0 }],
    [{ lap: 24, compound_c: other, tyre_age: 0 }],
    [
      { lap: 10, compound_c: running, tyre_age: 0 },
      { lap: 20, compound_c: high, tyre_age: 0 },
    ],
  ];

  it("agrees with the engine's disqualifications", () => {
    for (const plan of plans) {
      const { invalid, breaks } = checkRules(race, 0, fromLap, plan);
      expect(invalid).toEqual([]);
      const outcome = runSimulations(race, {
        fromLap,
        sets: [withStrategy(race, fromLap, 0, plan)],
        runs: 1,
        seed: 1,
        mode: REPLAY,
      });
      expect(breaks.length > 0).toBe(outcome.status[0] === DSQ);
    }
  });

  it("waives the two-compound rule for a car that ran wet tyres, as the engine does", () => {
    const plan = [{ lap: 15, compound_c: running, tyre_age: 0 }];
    expect(checkRules(race, 0, fromLap, plan).breaks).toEqual([{ kind: "compounds", used: 1, need: 2 }]);
    const wet = structuredClone(race);
    wet.cars[0]!.wet_tyres_used = true;
    expect(checkRules(wet, 0, fromLap, plan).breaks).toEqual([]);
    const outcome = runSimulations(wet, {
      fromLap,
      sets: [withStrategy(wet, fromLap, 0, plan)],
      runs: 1,
      seed: 1,
      mode: REPLAY,
    });
    expect(outcome.status[0]).not.toBe(DSQ);
  });

  it("never starts before the race's first start lap", () => {
    const late = { ...race, first_start_lap: fromLap + 1 };
    expect(() => prepare(late, fromLap)).toThrow(/no race state to simulate from/);
    expect(() => prepare(late, fromLap + 1)).not.toThrow();
  });

  it("names each broken rule, and refuses plans the engine cannot run", () => {
    expect(checkRules(race, 0, fromLap, [])).toEqual({
      invalid: [],
      breaks: [
        { kind: "compounds", used: 1, need: 2 },
        { kind: "stops", made: 0, need: 1 },
        { kind: "stint", laps: 30, limit: 20 },
      ],
    });
    const backwards = [
      { lap: 20, compound_c: other, tyre_age: 0 },
      { lap: 12, compound_c: high, tyre_age: 0 },
    ];
    expect(checkRules(race, 0, fromLap, backwards).invalid).toHaveLength(1);
    expect(checkRules(race, 0, fromLap, [{ lap: 12, compound_c: 9, tyre_age: 0 }]).invalid).toEqual(
      [{ kind: "not-allocated", compound: 9 }],
    );
  });
});
