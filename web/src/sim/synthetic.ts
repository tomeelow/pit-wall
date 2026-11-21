import type { SimRace } from "../contract/sim";

/** A made-up race for tests and the benchmark: every number here is a test input, not a model. */
export interface SyntheticOptions {
  cars?: number;
  laps?: number;
  draws?: number;
  spacingS?: number; // gap between consecutive cars after every lap
  paceStepS?: number; // car i is i x this slower per lap
  eventRate?: number; // starts per lap, every kind
  dnfRate?: number; // per car, per lap
  noiseSd?: number;
  passIntercept?: number;
  warmupS?: number[]; // per stint lap from the out-lap, every compound
  reactSc?: number | null; // safety-car reaction intercept; null: no car reacts
}

export function syntheticRace(options: SyntheticOptions = {}): SimRace {
  const {
    cars = 20,
    laps = 60,
    draws = 50,
    spacingS = 2,
    paceStepS = 0.05,
    eventRate = 0.01,
    dnfRate = 0.0005,
    noiseSd = 0.3,
    passIntercept = 0,
    warmupS = [0, 0],
    reactSc = 1,
  } = options;
  const compounds = [1, 2, 3];
  const repeat = (value: number) => Array.from({ length: draws }, () => value);
  // Draws that differ, so per-draw parameter uncertainty is exercised.
  const spread = (value: number, width: number) =>
    Array.from({ length: draws }, (_, d) => value + width * (d / Math.max(draws - 1, 1) - 0.5));
  const firstStint = (i: number) => (i % 2 === 0 ? 2 : 1);
  const stopLap = Math.floor(laps / 2);
  return {
    schema_version: "0.7.0",
    season: 2024,
    round: 1,
    name: "Synthetic Grand Prix",
    era: "2023-2025",
    total_laps: laps,
    dataset_version: "synthetic",
    draws,
    rules: {
      min_dry_compounds: 2,
      min_stops: 0,
      max_stint_laps: null,
      red_flag_free_tyre_change: true,
      classified_fraction: 0.9,
      points_places: 10,
    },
    mechanics: { follow_gap_s: 0.2, restart_gap_s: 0.5 },
    compounds,
    degradation: {
      race_median_s: 90,
      race_fuel_kg: 110,
      fuel_s_per_kg: spread(0.03, 0.01),
      nu: repeat(4),
      noise_sd_s: repeat(noiseSd),
      offset_s: [repeat(0.6), repeat(0), repeat(-0.6)],
      warmup_s: compounds.map(() => warmupS.map(repeat)),
      race_clean_laps: compounds.map(() => 100),
      max_stint_laps: compounds.map(() => null),
    },
    pit_loss: {
      transit_s: 20,
      stationary_s: [2.1, 2.2, 2.3, 2.4, 2.6, 3.0, 5.0],
      sc_factor: 0.65,
      vsc_factor: 0.8,
    },
    neutralisations: (["SC", "VSC", "RED"] as const).map((kind) => ({
      kind,
      rate_per_lap: repeat(eventRate),
      duration_laps: kind === "RED" ? [1, 2] : [2, 3, 4],
      lap_factor: kind === "VSC" ? 1.25 : 1.45,
    })),
    traffic: {
      max_gap_s: 3,
      drs_gap_s: 1,
      dirty_air: [
        { gap_upto_s: 0.5, loss_s: 0.45 },
        { gap_upto_s: 2, loss_s: 0.05 },
        { gap_upto_s: 3, loss_s: 0 },
      ],
      intercept: spread(passIntercept, 0.5),
      beta_gap_s: repeat(-4),
      beta_pace_delta_s: repeat(1.8),
      beta_within_drs: repeat(-1),
    },
    reaction:
      reactSc === null
        ? { intercept_sc: [], intercept_vsc: [], tyre_age_per_10: [], race_left: [] }
        : {
            intercept_sc: spread(reactSc, 0.5),
            intercept_vsc: repeat(reactSc - 2),
            tyre_age_per_10: repeat(1.2),
            race_left: repeat(-2.9),
          },
    cars: Array.from({ length: cars }, (_, i) => ({
      driver: `D${String(i + 1).padStart(2, "0")}`,
      team_id: `team${Math.floor(i / 2)}`,
      pace_from: "driver" as const,
      pace_s: spread(i * paceStepS, 0.1),
      slope_s_per_lap: [repeat(0.03), repeat(0.06), repeat(0.1)],
      dnf_rate_per_lap: repeat(dnfRate),
      stops: [{ lap: stopLap, compound_c: firstStint(i) === 2 ? 1 : 2, tyre_age: 0 }],
      finish_position: i + 1,
      retired_after_lap: null,
    })),
    snapshots: Array.from({ length: laps - 1 }, (_, k) => {
      const lap = k + 1;
      const stopped = lap >= stopLap;
      const compound = (i: number) => (stopped ? (firstStint(i) === 2 ? 1 : 2) : firstStint(i));
      return {
        lap,
        race_time_s: Array.from({ length: cars }, (_, i) => lap * 92 + i * spacingS),
        compound_c: Array.from({ length: cars }, (_, i) => compound(i)),
        tyre_age: Array.from({ length: cars }, () => (stopped ? lap - stopLap : lap)),
        stint_laps: Array.from({ length: cars }, () => (stopped ? lap - stopLap : lap)),
        stops: Array.from({ length: cars }, () => (stopped ? 1 : 0)),
        dry_compounds: Array.from({ length: cars }, (_, i) => (stopped ? [1, 2] : [firstStint(i)])),
      };
    }),
    realised: [],
  };
}
