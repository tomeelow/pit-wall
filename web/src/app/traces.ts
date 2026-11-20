import type { TelemetryLap } from "../contract/telemetry";
import type { TrackOutline } from "../contract/replay";
import { interpolate, type Point } from "./timing";

/** Equal-distance minisectors on the map: a convention of timing screens, not a tunable. */
export const MINISECTORS = 25;

const length = (lap: TelemetryLap) => lap.distance_m.at(-1)!;

/** Seconds lap `b` is behind lap `a` at each distance of `grid` (negative: b is ahead). */
export function delta(a: TelemetryLap, b: TelemetryLap, grid: readonly number[]): number[] {
  return grid.map(
    (d) => (interpolate(b.distance_m, b.time_ms, d) - interpolate(a.distance_m, a.time_ms, d)) / 1000,
  );
}

export function distanceGrid(a: TelemetryLap, b: TelemetryLap, points: number): number[] {
  const end = Math.min(length(a), length(b));
  return Array.from({ length: points }, (_, k) => (end * k) / (points - 1));
}

export interface Minisector {
  from_m: number;
  to_m: number;
  gain_s: number; // time b lost to a here (negative: b was faster)
}

export function minisectors(a: TelemetryLap, b: TelemetryLap, n = MINISECTORS): Minisector[] {
  const edges = distanceGrid(a, b, n + 1);
  const behind = delta(a, b, edges);
  return Array.from({ length: n }, (_, k) => ({
    from_m: edges[k]!,
    to_m: edges[k + 1]!,
    gain_s: behind[k + 1]! - behind[k]!,
  }));
}

/** The closed outline with the path length run to each point: telemetry distance maps onto it. */
function path(track: TrackOutline) {
  const xs = [...track.x, track.x[0]!];
  const ys = [...track.y, track.y[0]!];
  const along = [0];
  for (let k = 1; k < xs.length; k++) {
    along.push(along[k - 1]! + Math.hypot(xs[k]! - xs[k - 1]!, ys[k]! - ys[k - 1]!));
  }
  return { xs, ys, along, total: along.at(-1)! };
}

/** The point `fraction` of the way round the outline, by path length. */
export function pointAlong(track: TrackOutline, fraction: number): Point {
  const { xs, ys, along, total } = path(track);
  return { x: interpolate(along, xs, fraction * total), y: interpolate(along, ys, fraction * total) };
}

/** The outline cut into n pieces of equal path length, as SVG point lists, with y pointing up. */
export function outlinePieces(track: TrackOutline, n = MINISECTORS): string[] {
  const { xs, ys, along, total } = path(track);
  return Array.from({ length: n }, (_, k) => {
    const from = (total * k) / n;
    const to = (total * (k + 1)) / n;
    const inside = along.flatMap((s, i) => (s > from && s < to ? [i] : []));
    const ends = [from, to].map((s) => `${interpolate(along, xs, s)},${-interpolate(along, ys, s)}`);
    return [ends[0], ...inside.map((i) => `${xs[i]},${-ys[i]!}`), ends[1]].join(" ");
  });
}

/** "1:21.432" */
export function lapTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds - minutes * 60).toFixed(3).padStart(6, "0")}`;
}
