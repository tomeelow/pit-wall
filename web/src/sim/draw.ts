import type { SimRace } from "../contract/sim";
import { KINDS, type Prepared } from "./prepare.ts";
import type { Rng } from "./rng.ts";

/** One posterior draw of every model, flattened for the lap loop. */
export interface Draw {
  fuelSPerKg: number;
  noiseSd: number;
  nu: number;
  pace: Float64Array; // per car
  slope: Float64Array; // per car x compound
  offset: Float64Array; // per compound
  warmup: Float64Array; // per compound x stint lap (0 is the out-lap)
  dnfRate: Float64Array; // per car, per lap
  eventRate: Float64Array; // per kind, per green lap
  intercept: number;
  betaGap: number;
  betaPace: number;
  betaDrs: number;
  reactSc: number; // safety-car reaction, see Reaction in the contract
  reactVsc: number;
  reactAge: number;
  reactLeft: number;
}

export function createDraw(prepared: Prepared): Draw {
  return {
    fuelSPerKg: 0,
    noiseSd: 0,
    nu: 0,
    pace: new Float64Array(prepared.cars),
    slope: new Float64Array(prepared.cars * prepared.compounds),
    offset: new Float64Array(prepared.compounds),
    warmup: new Float64Array(prepared.compounds * prepared.warmupLaps),
    dnfRate: new Float64Array(prepared.cars),
    eventRate: new Float64Array(KINDS.length),
    intercept: 0,
    betaGap: 0,
    betaPace: 0,
    betaDrs: 0,
    reactSc: 0,
    reactVsc: 0,
    reactAge: 0,
    reactLeft: 0,
  };
}

/** Fill `out` with draw `d`, or with the posterior mean of every parameter when `d` is "mean". */
export function fillDraw(race: SimRace, d: number | "mean", out: Draw): void {
  const at = (values: readonly number[]) => (d === "mean" ? mean(values) : values[d]!);
  const deg = race.degradation;
  out.fuelSPerKg = at(deg.fuel_s_per_kg);
  out.noiseSd = at(deg.noise_sd_s);
  out.nu = at(deg.nu);
  const k = race.compounds.length;
  race.compounds.forEach((_, c) => (out.offset[c] = at(deg.offset_s[c]!)));
  const w = out.warmup.length / k;
  for (let c = 0; c < k; c++) {
    for (let j = 0; j < w; j++) out.warmup[c * w + j] = at(deg.warmup_s[c]![j]!);
  }
  race.cars.forEach((car, i) => {
    out.pace[i] = at(car.pace_s);
    out.dnfRate[i] = at(car.dnf_rate_per_lap);
    for (let c = 0; c < k; c++) out.slope[i * k + c] = at(car.slope_s_per_lap[c]!);
  });
  KINDS.forEach((kind, j) => {
    out.eventRate[j] = at(race.neutralisations.find((p) => p.kind === kind)!.rate_per_lap);
  });
  out.intercept = at(race.traffic.intercept);
  out.betaGap = at(race.traffic.beta_gap_s);
  out.betaPace = at(race.traffic.beta_pace_delta_s);
  out.betaDrs = at(race.traffic.beta_within_drs);
  // Without a fitted reaction no car reacts.
  const react = race.reaction;
  const none = react.intercept_sc.length === 0;
  out.reactSc = none ? -Infinity : at(react.intercept_sc);
  out.reactVsc = none ? -Infinity : at(react.intercept_vsc);
  out.reactAge = none ? 0 : at(react.tyre_age_per_10);
  out.reactLeft = none ? 0 : at(react.race_left);
}

function mean(values: readonly number[]): number {
  let sum = 0;
  for (const v of values) sum += v;
  return sum / values.length;
}

/**
 * Every random number one simulation needs, drawn before it runs. Common random numbers: each
 * number is tied to a car and a lap (or a lap), not to the order the simulation asks for them,
 * so simulation i sees the same noise, events and stop times under every strategy.
 */
export interface Randoms {
  lapNoise: Float64Array; // per car x lap: standard Student-t
  pass: Float64Array; // per car x lap: uniform
  dnf: Float64Array; // per car x lap: uniform
  stationary: Float64Array; // per car x lap: uniform, for a stop made on that lap
  event: Float64Array; // per lap: uniform
  duration: Float64Array; // per lap: uniform
  react: Float64Array; // per car x lap: uniform, for a stop brought forward on that lap
}

export function createRandoms(prepared: Prepared): Randoms {
  const perCar = prepared.cars * (prepared.laps + 1);
  return {
    lapNoise: new Float64Array(perCar),
    pass: new Float64Array(perCar),
    dnf: new Float64Array(perCar),
    stationary: new Float64Array(perCar),
    event: new Float64Array(prepared.laps + 1),
    duration: new Float64Array(prepared.laps + 1),
    react: new Float64Array(perCar),
  };
}

export function fillRandoms(rng: Rng, nu: number, out: Randoms): void {
  for (let k = 0; k < out.lapNoise.length; k++) out.lapNoise[k] = rng.studentT(nu);
  // Appended last: adding a stream leaves every earlier number where it was.
  for (const array of [out.pass, out.dnf, out.stationary, out.event, out.duration, out.react]) {
    for (let k = 0; k < array.length; k++) array[k] = rng.uniform();
  }
}
