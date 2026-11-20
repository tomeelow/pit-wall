import { describe, expect, it } from "vitest";
import { finishCounts, startLaps } from "./backtest.ts";
import { syntheticRace } from "./synthetic.ts";

describe("finishCounts", () => {
  it("places every car once per run, the cars already out among the not classified", () => {
    const race = syntheticRace({ cars: 6, laps: 30, dnfRate: 0.01, eventRate: 0.05 });
    const out = 5;
    race.cars[out]!.retired_after_lap = 9;
    for (const snapshot of race.snapshots.slice(9)) snapshot.race_time_s[out] = null;

    const runs = 300;
    const counts = finishCounts(race, 15, runs, 7);
    for (const row of counts) {
      expect(row).toHaveLength(race.cars.length + 1);
      expect(row.reduce((a, b) => a + b, 0)).toBe(runs);
    }
    expect(counts[out]![race.cars.length]).toBe(runs);
    // Each place goes to at most one car per run.
    for (let place = 0; place < race.cars.length; place++) {
      expect(counts.reduce((sum, row) => sum + row[place]!, 0)).toBeLessThanOrEqual(runs);
    }
    expect(finishCounts(race, 15, runs, 7)).toEqual(counts);
  });
});

describe("startLaps", () => {
  it("maps shares of distance to laps, never the last, without repeats", () => {
    expect(startLaps(60, [0, 0.25, 0.5, 0.75])).toEqual([
      { fraction: 0, lap: 1 },
      { fraction: 0.25, lap: 15 },
      { fraction: 0.5, lap: 30 },
      { fraction: 0.75, lap: 45 },
    ]);
    expect(startLaps(3, [0, 0.25, 0.5, 1])).toEqual([
      { fraction: 0, lap: 1 },
      { fraction: 0.5, lap: 2 },
    ]);
  });
});
