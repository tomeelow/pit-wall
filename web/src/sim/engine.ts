import type { Draw, Randoms } from "./draw.ts";
import { GREEN, KINDS, RED, SC, VSC, type Plan, type Prepared } from "./prepare.ts";

/**
 * events "sampled": safety cars, VSCs, red flags and DNFs are drawn from their rates (ex ante).
 * events "realised": they happen exactly when they did (ex post, replays).
 * noise false: no lap-time noise, median stationary times, a pass happens when P(pass) > 0.5.
 */
export interface Mode {
  events: "sampled" | "realised";
  noise: boolean;
}

export const FINISHED = 0;
export const DNF = 1;
export const DSQ = 2;

/** Buffers one simulation reuses; the outcome is read from `position` and `status`. */
export interface Workspace {
  time: Float64Array;
  end: Float64Array;
  predicted: Float64Array;
  compound: Int32Array;
  age: Int32Array;
  stintLaps: Int32Array;
  longestStint: Int32Array;
  stops: Int32Array;
  used: Int32Array;
  alive: Uint8Array;
  dnfRisk: Float64Array; // per car: P(retiring on this lap)
  lapsDone: Int32Array;
  nextStop: Int32Array;
  pitting: Uint8Array;
  outLap: Uint8Array;
  order: Int32Array;
  gap: Float64Array;
  position: Int32Array; // per car, 1-based
  status: Uint8Array; // per car: FINISHED, DNF or DSQ
}

/** Per-lap record for tests and the replay view: entries are lap x car. */
export interface Trace {
  position: Int32Array; // 0 for a retired car
  age: Int32Array;
  stops: Int32Array;
  compound: Int32Array;
  neutralisation: Int8Array; // per lap
}

export function createWorkspace(prepared: Prepared): Workspace {
  const n = prepared.cars;
  return {
    time: new Float64Array(n),
    end: new Float64Array(n),
    predicted: new Float64Array(n),
    compound: new Int32Array(n),
    age: new Int32Array(n),
    stintLaps: new Int32Array(n),
    longestStint: new Int32Array(n),
    stops: new Int32Array(n),
    used: new Int32Array(n),
    alive: new Uint8Array(n),
    dnfRisk: new Float64Array(n),
    lapsDone: new Int32Array(n),
    nextStop: new Int32Array(n),
    pitting: new Uint8Array(n),
    outLap: new Uint8Array(n),
    order: new Int32Array(n),
    gap: new Float64Array(n),
    position: new Int32Array(n),
    status: new Uint8Array(n),
  };
}

export function createTrace(prepared: Prepared): Trace {
  const size = (prepared.laps + 1) * prepared.cars;
  return {
    position: new Int32Array(size),
    age: new Int32Array(size),
    stops: new Int32Array(size),
    compound: new Int32Array(size),
    neutralisation: new Int8Array(prepared.laps + 1).fill(GREEN),
  };
}

/**
 * One race from `prepared.fromLap` to the flag. Deterministic: the same inputs give the same
 * outcome. Every car follows its plan, with one reaction (ADR-004): on the first lap of a sampled
 * safety car or VSC, a car with a planned stop still to make may take it at once. Ex post the
 * plans already hold the real reactions, so none is added.
 */
export function simulateRace(
  prepared: Prepared,
  plan: Plan,
  draw: Draw,
  random: Randoms,
  mode: Mode,
  ws: Workspace,
  trace?: Trace,
): void {
  const { race, cars: n, laps: total, compounds: k, warmupLaps } = prepared;
  const { traffic, mechanics, degradation: deg, rules } = race;
  const sampled = mode.events === "sampled";
  const stride = total + 1;

  ws.time.set(prepared.time);
  ws.compound.set(prepared.compound);
  ws.age.set(prepared.age);
  ws.stintLaps.set(prepared.stintLaps);
  ws.longestStint.set(prepared.stintLaps);
  ws.stops.set(prepared.stops);
  ws.used.set(prepared.used);
  ws.alive.set(prepared.alive);
  ws.outLap.fill(0);
  for (let i = 0; i < n; i++) {
    ws.lapsDone[i] = prepared.alive[i] ? prepared.fromLap : Math.max(prepared.retiredAfter[i]!, 0);
    ws.nextStop[i] = plan.offset[i]!;
    ws.order[i] = i;
  }
  sortByTime(ws);

  let kind = GREEN;
  let kindEnd = 0;
  if (sampled && prepared.ongoing) {
    // Known at the start: what is running and since when, not when it ends.
    kind = prepared.ongoing.kind;
    const elapsed = prepared.fromLap - prepared.ongoing.startLap + 1;
    kindEnd = prepared.fromLap + 1;
    const durations = prepared.durations[kind]!;
    const longer = durations.filter((d) => d > elapsed);
    if (longer.length > 0) {
      const pick = Math.floor(random.duration[prepared.fromLap]! * longer.length);
      kindEnd = prepared.ongoing.startLap + longer[pick]! - 1;
    }
  }

  const stationaryMedian = prepared.stationary[prepared.stationary.length >> 1]!;
  const rateToP = (rate: number) => 1 - Math.exp(-rate);

  for (let lap = prepared.fromLap + 1; lap <= total; lap++) {
    let started = false;
    if (sampled) {
      if (kind !== GREEN && lap > kindEnd) kind = GREEN;
      if (kind === GREEN) {
        const u = random.event[lap]!;
        let cumulative = 0;
        for (let j = 0; j < KINDS.length; j++) {
          cumulative += rateToP(draw.eventRate[j]!);
          if (u < cumulative) {
            const durations = prepared.durations[j]!;
            const pick = Math.floor(random.duration[lap]! * durations.length);
            kind = j;
            kindEnd = lap + (durations[pick] ?? 1) - 1;
            started = kind === SC || kind === VSC;
            break;
          }
        }
      }
    } else {
      kind = prepared.realisedKind[lap]!;
      kindEnd = prepared.realisedEnd[lap]!;
    }

    if (sampled) {
      // A car's risk depends on where it runs as the lap begins, front (-0.5) to back (+0.5).
      let running = 0;
      for (let i = 0; i < n; i++) running += ws.alive[i]!;
      let place = 0;
      for (let r = 0; r < n; r++) {
        const i = ws.order[r]!;
        if (!ws.alive[i]) continue;
        const share = running > 1 ? place / (running - 1) - 0.5 : 0;
        ws.dnfRisk[i] = rateToP(draw.dnfRate[i]! * Math.exp(draw.dnfPosition * share));
        place++;
      }
    }

    const fuel = draw.fuelSPerKg * deg.race_fuel_kg * (1 - (lap - 0.5) / total);
    for (let i = 0; i < n; i++) {
      ws.pitting[i] = 0;
      if (!ws.alive[i]) continue;
      const cell = i * stride + lap;
      const retires = sampled
        ? random.dnf[cell]! < ws.dnfRisk[i]!
        : prepared.retiredAfter[i] === lap - 1;
      if (retires) {
        ws.alive[i] = 0;
        continue;
      }
      const c = ws.compound[i]!;
      const base =
        deg.race_median_s +
        draw.pace[i]! +
        draw.offset[c]! +
        draw.slope[i * k + c]! * (ws.age[i]! + 1) +
        fuel;
      ws.predicted[i] = base;
      // Warm-up is measured on green laps only; under a neutralisation every lap is slow anyway.
      const stintLap = ws.stintLaps[i]!;
      const warmup = stintLap < warmupLaps ? draw.warmup[c * warmupLaps + stintLap]! : 0;
      let lapTime =
        kind === GREEN
          ? base + warmup + (mode.noise ? draw.noiseSd * random.lapNoise[cell]! : 0)
          : base * prepared.lapFactor[kind]!;
      const s = ws.nextStop[i]!;
      const planned = s < plan.offset[i + 1]!;
      let stops = planned && plan.lap[s] === lap;
      if (!stops && planned && started) {
        const logit =
          (kind === SC ? draw.reactSc : draw.reactVsc) +
          (draw.reactAge * (ws.age[i]! + 1)) / 10 +
          (draw.reactLeft * (total - lap)) / total;
        const p = 1 / (1 + Math.exp(-logit));
        stops = mode.noise ? random.react[cell]! < p : p > 0.5;
      }
      if (stops) {
        ws.pitting[i] = 1;
        const quantile = Math.floor(random.stationary[cell]! * prepared.stationary.length);
        const stationary = mode.noise ? prepared.stationary[quantile]! : stationaryMedian;
        const factor = kind === GREEN ? 1 : prepared.pitFactor[kind]!;
        lapTime += (race.pit_loss.transit_s + stationary) * factor;
      }
      ws.end[i] = ws.time[i]! + lapTime;
    }

    // Cars meet in the order they started the lap. A car only ever reacts to the one directly
    // ahead of it, after that one has been resolved.
    let ahead = -1;
    for (let r = 0; r < n; r++) {
      const i = ws.order[r]!;
      if (!ws.alive[i]) continue;
      if (ahead >= 0 && !ws.pitting[i] && !ws.pitting[ahead]) {
        if (kind !== GREEN) {
          ws.end[i] = Math.max(ws.end[i]!, ws.end[ahead]! + mechanics.follow_gap_s);
        } else if (!ws.outLap[i] && !ws.outLap[ahead]) {
          const gap = ws.time[i]! - ws.time[ahead]!;
          if (gap <= traffic.max_gap_s) {
            ws.end[i] = ws.end[i]! + dirtyAir(traffic.dirty_air, gap);
            const logit =
              draw.intercept +
              draw.betaGap * gap +
              draw.betaPace * (ws.predicted[ahead]! - ws.predicted[i]!) +
              (gap <= traffic.drs_gap_s ? draw.betaDrs : 0);
            const p = 1 / (1 + Math.exp(-logit));
            const passes = mode.noise ? random.pass[i * stride + lap]! < p : p > 0.5;
            if (passes) {
              if (ws.end[i]! > ws.end[ahead]!) {
                const swap = ws.end[i]!;
                ws.end[i] = ws.end[ahead]!;
                ws.end[ahead] = swap;
              }
              ws.end[ahead] = Math.max(ws.end[ahead]!, ws.end[i]! + mechanics.follow_gap_s);
            } else {
              ws.end[i] = Math.max(ws.end[i]!, ws.end[ahead]! + mechanics.follow_gap_s);
            }
          }
        }
      }
      ahead = i;
    }

    for (let i = 0; i < n; i++) {
      if (!ws.alive[i]) continue;
      ws.time[i] = ws.end[i]!;
      ws.lapsDone[i] = lap;
      ws.age[i]!++;
      ws.stintLaps[i]!++;
      ws.longestStint[i] = Math.max(ws.longestStint[i]!, ws.stintLaps[i]!);
      ws.outLap[i] = ws.pitting[i]!;
      if (ws.pitting[i]) {
        const s = ws.nextStop[i]!;
        ws.compound[i] = plan.compound[s]!;
        ws.age[i] = plan.tyreAge[s]!;
        ws.stintLaps[i] = 0;
        ws.stops[i]!++;
        ws.used[i]! |= 1 << plan.cNumber[s]!;
        ws.nextStop[i] = s + 1;
      }
    }
    sortByTime(ws);
    if ((kind === SC || kind === RED) && lap === kindEnd) restart(ws, mechanics.restart_gap_s);
    if (trace) record(trace, ws, lap, kind, n);
  }

  classify(ws, n, prepared.minCompounds, rules.min_stops, rules.max_stint_laps);
}

/**
 * In the official classification: took the flag, or retired after covering the classified share
 * of the laps. A classified car's place is ws.position[i].
 */
export function isClassified(ws: Workspace, i: number, prepared: Prepared): boolean {
  if (ws.status[i] === FINISHED) return true;
  const needed = Math.floor(prepared.race.rules.classified_fraction * prepared.laps);
  return ws.status[i] === DNF && ws.lapsDone[i]! >= needed;
}

function dirtyAir(bins: readonly { gap_upto_s: number; loss_s: number }[], gap: number): number {
  for (const bin of bins) if (gap <= bin.gap_upto_s) return bin.loss_s;
  return 0;
}

/** The field queues up behind the safety car: no gap to the car ahead stays above `gap`. */
function restart(ws: Workspace, gap: number): void {
  let previousOld = 0;
  let previousNew = 0;
  let first = true;
  for (let r = 0; r < ws.order.length; r++) {
    const i = ws.order[r]!;
    if (!ws.alive[i]) continue;
    const old = ws.time[i]!;
    if (!first) ws.time[i] = previousNew + Math.min(old - previousOld, gap);
    first = false;
    previousOld = old;
    previousNew = ws.time[i]!;
  }
}

/** Running cars by race time, then retired cars. Insertion sort: the order barely changes. */
function sortByTime(ws: Workspace): void {
  const { order, time, alive } = ws;
  const key = (i: number) => (alive[i] ? time[i]! : Infinity);
  for (let r = 1; r < order.length; r++) {
    const i = order[r]!;
    const t = key(i);
    let q = r - 1;
    while (q >= 0 && key(order[q]!) > t) {
      order[q + 1] = order[q]!;
      q--;
    }
    order[q + 1] = i;
  }
}

function popcount(x: number): number {
  let count = 0;
  for (let v = x; v !== 0; v &= v - 1) count++;
  return count;
}

/** Finishers by time, then retirements by laps completed, then disqualifications. */
function classify(
  ws: Workspace,
  n: number,
  minCompounds: Int32Array,
  minStops: number,
  maxStint: number | null,
): void {
  for (let i = 0; i < n; i++) {
    if (!ws.alive[i]) ws.status[i] = DNF;
    else {
      const legal =
        popcount(ws.used[i]!) >= minCompounds[i]! &&
        ws.stops[i]! >= minStops &&
        (maxStint === null || ws.longestStint[i]! <= maxStint);
      ws.status[i] = legal ? FINISHED : DSQ;
    }
  }
  let position = 1;
  for (let r = 0; r < n; r++) {
    const i = ws.order[r]!;
    if (ws.status[i] === FINISHED) ws.position[i] = position++;
  }
  // Retired cars, latest retirement first. ws.order ends with them in car order, so sort here.
  for (let laps = ws.lapsDone.reduce((a, b) => Math.max(a, b), 0); laps >= 0; laps--) {
    for (let i = 0; i < n; i++) {
      if (ws.status[i] === DNF && ws.lapsDone[i] === laps) ws.position[i] = position++;
    }
  }
  for (let r = 0; r < n; r++) {
    const i = ws.order[r]!;
    if (ws.status[i] === DSQ) ws.position[i] = position++;
  }
}

function record(trace: Trace, ws: Workspace, lap: number, kind: number, n: number): void {
  trace.neutralisation[lap] = kind;
  let position = 1;
  for (let r = 0; r < n; r++) {
    const i = ws.order[r]!;
    const cell = lap * n + i;
    trace.position[cell] = ws.alive[i] ? position++ : 0;
    trace.age[cell] = ws.age[i]!;
    trace.stops[cell] = ws.stops[i]!;
    trace.compound[cell] = ws.compound[i]!;
  }
}
