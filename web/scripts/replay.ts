// Zero-noise replay of every simulable race in a bundle: actual strategies, realised safety cars
// and retirements, posterior-mean pace, no noise. The finishing order should come out close to
// the real one. A mechanics check, not evidence of predictive skill.
// Usage: node scripts/replay.ts [bundle dir, default public/data]
import type { Manifest } from "../src/contract/manifest";
import type { SimRace } from "../src/contract/sim";
import { actualStrategies, DSQ, runSimulations } from "../src/sim/index.ts";

const base = new URL(`${process.argv[2] ?? "public/data"}/`, `file://${process.cwd()}/`);
const load = async <T>(path: string): Promise<T> =>
  (await import(new URL(path, base).href, { with: { type: "json" } })).default as T;

const manifest = await load<Manifest>("manifest.json");
const rows: string[] = [];
let totalError = 0;
let totalBaseline = 0;
let totalCars = 0;
let totalExact = 0;
let illegal = 0;
for (const entry of manifest.races) {
  if (!entry.sim_path) continue;
  const race = await load<SimRace>(entry.sim_path);
  const from = race.first_start_lap;
  const outcome = runSimulations(race, {
    fromLap: from,
    sets: [actualStrategies(race, from)],
    runs: 1,
    seed: 0,
    mode: { events: "realised", noise: false },
    meanParameters: true,
  });
  // Compare the order of the official finishers among themselves.
  const finishers = race.cars
    .map((car, i) => ({ car, simulated: outcome.position[i]!, status: outcome.status[i]! }))
    .filter((f) => f.car.finish_position !== null);
  const simulatedRank = new Map(
    [...finishers].sort((a, b) => a.simulated - b.simulated).map((f, k) => [f.car.driver, k + 1]),
  );
  const actualRank = new Map(
    [...finishers]
      .sort((a, b) => a.car.finish_position! - b.car.finish_position!)
      .map((f, k) => [f.car.driver, k + 1]),
  );
  // Baseline: the order where the replay starts, after lap 1 unless the race began wet.
  const atStart = race.snapshots[from - 1]!.race_time_s;
  const index = new Map(race.cars.map((car, i) => [car.driver, i]));
  const baselineRank = new Map(
    [...finishers]
      .sort((a, b) => atStart[index.get(a.car.driver)!]! - atStart[index.get(b.car.driver)!]!)
      .map((f, k) => [f.car.driver, k + 1]),
  );
  let error = 0;
  let baseline = 0;
  let exact = 0;
  for (const [driver, rank] of actualRank) {
    const d = Math.abs(rank - simulatedRank.get(driver)!);
    error += d;
    baseline += Math.abs(rank - baselineRank.get(driver)!);
    exact += d === 0 ? 1 : 0;
  }
  const dsq = finishers.filter((f) => f.status === DSQ).map((f) => f.car.driver);
  illegal += dsq.length;
  totalError += error;
  totalBaseline += baseline;
  totalCars += finishers.length;
  totalExact += exact;
  const n = finishers.length;
  rows.push(
    `${race.season}-${String(race.round).padStart(2, "0")} ${race.name.padEnd(28)} ` +
      `${n} finishers  mean |error| ${(error / n).toFixed(2)} (start order ${(baseline / n).toFixed(2)})  exact ${exact}/${n}` +
      (dsq.length ? `  DSQ by the rules: ${dsq.join(", ")}` : ""),
  );
}
console.log(rows.join("\n"));
console.log(
  `\n${rows.length} races, ${totalCars} finishers: mean |position error| ` +
    `${(totalError / totalCars).toFixed(2)} (start order ${(totalBaseline / totalCars).toFixed(2)}), exact ${((100 * totalExact) / totalCars).toFixed(1)} %, ` +
    `actual strategies disqualified by the rules: ${illegal}`,
);
