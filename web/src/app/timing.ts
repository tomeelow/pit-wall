import type { Stint } from "../contract/race";
import type { Neutralisation, Replay, ReplayCar, TrackOutline } from "../contract/replay";

/** Largest index i with xs[i] <= x, for ascending xs; -1 when x is before the first. */
export function bisect(xs: readonly number[], x: number): number {
  let lo = 0;
  let hi = xs.length - 1;
  if (xs.length === 0 || x < xs[0]!) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (xs[mid]! <= x) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** Linear interpolation of ys over ascending xs, held at the ends. */
export function interpolate(xs: readonly number[], ys: readonly number[], x: number): number {
  const i = bisect(xs, x);
  if (i < 0) return ys[0]!;
  if (i >= xs.length - 1) return ys.at(-1)!;
  const span = xs[i + 1]! - xs[i]!;
  const w = span > 0 ? (x - xs[i]!) / span : 0;
  return ys[i]! + w * (ys[i + 1]! - ys[i]!);
}

export interface Point {
  x: number;
  y: number;
}

/**
 * Where a car is when it has run `fraction` of its lap time, on the reference lap's path: every
 * car is assumed to share the reference lap's pace profile, scaled to its own lap time. Between
 * the last sample and the line the car closes the loop to the first sample.
 */
export function pointAt(track: TrackOutline, fraction: number): Point {
  const total = track.lap_time_s * 1000;
  const t = fraction * total;
  const last = track.t_ms.length - 1;
  if (t >= track.t_ms[last]!) {
    const span = total - track.t_ms[last]! + track.t_ms[0]!;
    const w = span > 0 ? (t - track.t_ms[last]!) / span : 0;
    return {
      x: track.x[last]! + w * (track.x[0]! - track.x[last]!),
      y: track.y[last]! + w * (track.y[0]! - track.y[last]!),
    };
  }
  return { x: interpolate(track.t_ms, track.x, t), y: interpolate(track.t_ms, track.y, t) };
}

/** A car at race time t: the lap it is on and how far through it, by time. */
export interface Progress {
  lap: number; // 1-based lap being run
  fraction: number; // 0 at the line, 1 at the next
  finished: boolean; // past its last completed lap: finished, or retired
}

export function progressAt(car: ReplayCar, t: number): Progress {
  const ends = car.lap_end_s;
  const done = bisect(ends, t) + 1; // laps completed by t
  if (done >= ends.length) return { lap: ends.length, fraction: 1, finished: true };
  const start = done === 0 ? 0 : ends[done - 1]!;
  return { lap: done + 1, fraction: (t - start) / (ends[done]! - start), finished: false };
}

/** Distance run in laps: the running order sorts on it. */
export const laps = (p: Progress) => p.lap - 1 + p.fraction;

export interface Standing {
  driver: string;
  progress: Progress;
  gap: string; // to the leader at the last line both crossed
}

/** The running order at race time t. Cars that stopped short keep the place they stopped in. */
export function standings(replay: Replay, t: number): Standing[] {
  const rows = replay.cars.map((car) => ({ car, progress: progressAt(car, t) }));
  rows.sort((a, b) => laps(b.progress) - laps(a.progress));
  const leader = rows[0]?.car;
  return rows.map(({ car, progress }) => ({
    driver: car.driver,
    progress,
    gap: leader && car !== leader ? gapAt(leader, car, t) : "",
  }));
}

/** Behind the leader at the last line the car crossed, as timing screens show it. */
function gapAt(leader: ReplayCar, car: ReplayCar, t: number): string {
  const crossed = bisect(car.lap_end_s, t) + 1;
  if (crossed === 0) return "";
  const at = car.lap_end_s[crossed - 1]!;
  const down = bisect(leader.lap_end_s, at) + 1 - crossed;
  if (down >= 1) return `+${down} lap${down > 1 ? "s" : ""}`;
  return `+${(at - leader.lap_end_s[crossed - 1]!).toFixed(1)}`;
}

export const lastLine = (replay: Replay) => Math.max(...replay.cars.map((c) => c.lap_end_s.at(-1) ?? 0));

/** The race time at which the leader started `lap`. */
export function lapStart(replay: Replay, lap: number): number {
  const leader = replay.cars.reduce((a, b) => (b.lap_end_s.length > a.lap_end_s.length ? b : a));
  return lap <= 1 ? 0 : (leader.lap_end_s[lap - 2] ?? lastLine(replay));
}

export const neutralisationOn = (replay: Replay, lap: number): Neutralisation | undefined =>
  replay.neutralisations.find((n) => n.start_lap <= lap && lap <= n.end_lap);

export const stintOn = (stints: readonly Stint[], lap: number): Stint | undefined =>
  stints.find((s) => s.start_lap <= lap && lap <= s.end_lap);

/** On the in-lap or the out-lap of a stop: drawn on track, though the car is in the pit lane for part of it. */
export const pitting = (stints: readonly Stint[], lap: number) =>
  stints.some((s, k) => (k < stints.length - 1 && s.end_lap === lap) || (k > 0 && s.start_lap === lap));
