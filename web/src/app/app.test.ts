import { describe, expect, it } from "vitest";
import { syntheticRace } from "../sim/synthetic.ts";
import { dryTyre } from "./compounds";
import { decisionLaps, describePlan, planSegments } from "./plan";
import { readView, writeView } from "./url";

describe("view in the URL", () => {
  it("round-trips, and falls back on anything it does not know", () => {
    const view = { race: "2025-14", driver: "NOR", tab: "telemetry" as const, lap: 22, vs: "PIA" };
    expect(readView(writeView(view))).toEqual(view);
    expect(readView("?tab=nope&lap=-3")).toEqual({
      race: null,
      driver: null,
      tab: "race",
      lap: null,
      vs: null,
    });
  });
});

describe("compound names", () => {
  it("names an event's C-numbers soft to hard, highest C-number softest", () => {
    expect([4, 3, 2].map((c) => dryTyre([2, 3, 4], c))).toEqual(["soft", "medium", "hard"]);
    expect(dryTyre([2, 3, 4], 5)).toBe("unknown");
  });
});

describe("planSegments", () => {
  const race = syntheticRace({ cars: 3, laps: 30, eventRate: 0, dnfRate: 0 });
  const [low, , high] = race.compounds as [number, number, number];
  race.cars[0]!.stops = [{ lap: 8, compound_c: high, tyre_age: 0 }];

  it("keeps what was run before the decision and draws the plan after it", () => {
    const start = race.snapshots.find((s) => s.lap === 7)!.compound_c[0]!;
    const plan = [{ lap: 20, compound_c: low, tyre_age: 0 }];
    const segments = planSegments(race, 0, 10, plan);
    expect(segments).toEqual([
      { from: 1, to: 8, compound: start },
      { from: 9, to: 20, compound: high },
      { from: 21, to: 30, compound: low },
    ]);
    expect(describePlan(segments)).toBe(`C${start} to lap 8, C${high} to lap 20, C${low}`);
  });

  it("offers only laps with a race state, leaving room for the last stop", () => {
    const laps = decisionLaps(race, 0);
    expect(laps[0]).toBe(1);
    expect(laps.at(-1)).toBe(race.total_laps - 2);
  });
});
