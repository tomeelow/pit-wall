import { describe, expect, it } from "vitest";
import type { Replay, TrackOutline } from "../contract/replay";
import type { TelemetryLap } from "../contract/telemetry";
import { STRINGS } from "./i18n";
import { bisect, interpolate, pointAt, progressAt, standings } from "./timing";
import { delta, distanceGrid, lapTime, minisectors, outlinePieces, pointAlong } from "./traces";

/** A square lap of side 1000 run at constant speed: a corner every quarter of the lap. */
const square: TrackOutline = {
  driver: "AAA",
  lap: 2,
  lap_time_s: 40,
  x: [0, 1000, 1000, 0],
  y: [0, 0, 1000, 1000],
  t_ms: [0, 10000, 20000, 30000],
};

const replay = (cars: Record<string, number[]>): Replay => ({
  schema_version: "0.7.0",
  season: 2024,
  round: 1,
  dataset_version: "x",
  track: square,
  cars: Object.entries(cars).map(([driver, lap_end_s]) => ({ driver, lap_end_s })),
  neutralisations: [],
  fastest_laps: [],
});

describe("replay", () => {
  it("interpolates and bisects", () => {
    expect(bisect([1, 2, 3], 0.5)).toBe(-1);
    expect(bisect([1, 2, 3], 2)).toBe(1);
    expect(bisect([1, 2, 3], 9)).toBe(2);
    expect(interpolate([0, 10], [0, 100], 2.5)).toBe(25);
    expect(interpolate([0, 10], [0, 100], 20)).toBe(100);
  });

  it("places a car along the reference lap by the share of its lap time, closing the loop", () => {
    expect(pointAt(square, 0)).toEqual({ x: 0, y: 0 });
    expect(pointAt(square, 0.125)).toEqual({ x: 500, y: 0 });
    expect(pointAt(square, 0.5)).toEqual({ x: 1000, y: 1000 });
    expect(pointAt(square, 0.875)).toEqual({ x: 0, y: 500 });
  });

  it("follows each car's own lap times", () => {
    const car = { driver: "AAA", lap_end_s: [100, 190, 280] };
    expect(progressAt(car, 50)).toEqual({ lap: 1, fraction: 0.5, finished: false });
    expect(progressAt(car, 235)).toEqual({ lap: 3, fraction: 0.5, finished: false });
    expect(progressAt(car, 300)).toEqual({ lap: 3, fraction: 1, finished: true });
  });

  it("orders the field by distance run and gives gaps at the line, in laps once lapped", () => {
    const race = replay({
      LAP: [100, 190, 280, 370],
      CLO: [101.5, 192, 283, 374],
      SLO: [110, 220, 330],
      LAPPED: [150, 300],
      OUT: [105], // stopped on lap 2: the screen says so from the classification
    });
    const order = standings(race, 300);
    expect(order.map((s) => s.driver)).toEqual(["LAP", "CLO", "SLO", "LAPPED", "OUT"]);
    expect(order.map((s) => STRINGS.en.gap(s.gap))).toEqual(["", "+3.0", "+30.0", "+1 lap", "+5.0"]);
    expect(STRINGS.uk.gap(order[3]!.gap)).toBe("+1 коло");
    expect(order[4]!.progress.finished).toBe(true);
  });
});

const lap = (driver: string, distance_m: number[], time_ms: number[]): TelemetryLap => ({
  schema_version: "0.7.0",
  driver,
  lap: 1,
  lap_time_s: time_ms.at(-1)! / 1000,
  distance_m,
  time_ms,
  speed_kmh: distance_m.map(() => 200),
  throttle: distance_m.map(() => 100),
  brake: distance_m.map(() => 0),
  gear: distance_m.map(() => 7),
});

describe("telemetry", () => {
  // b loses 0.5 s over the first half and wins 0.2 s back over the second.
  const a = lap("A", [0, 500, 1000], [0, 10000, 20000]);
  const b = lap("B", [0, 500, 1000], [0, 10500, 20300]);

  it("compares laps by distance", () => {
    const grid = distanceGrid(a, b, 5);
    expect(grid).toEqual([0, 250, 500, 750, 1000]);
    expect(delta(a, b, grid).map((x) => +x.toFixed(3))).toEqual([0, 0.25, 0.5, 0.4, 0.3]);
  });

  it("splits the gap into minisectors that add up to it", () => {
    const sectors = minisectors(a, b, 4);
    expect(sectors.map((s) => +s.gain_s.toFixed(3))).toEqual([0.25, 0.25, -0.1, -0.1]);
    expect(sectors.reduce((sum, s) => sum + s.gain_s, 0)).toBeCloseTo(0.3, 9);
  });

  it("cuts the outline into pieces of equal length", () => {
    const pieces = outlinePieces(square, 4);
    expect(pieces).toEqual(["0,0 1000,0", "1000,0 1000,-1000", "1000,-1000 0,-1000", "0,-1000 0,0"]);
    expect(pointAlong(square, 0.375)).toEqual({ x: 1000, y: 500 });
  });

  it("formats lap times", () => {
    expect(lapTime(81.432)).toBe("1:21.432");
    expect(lapTime(65.05)).toBe("1:05.050");
  });
});
