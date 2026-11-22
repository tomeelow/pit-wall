// Ex-ante simulations of every simulable race in a bundle, from several start laps, with the
// strategies actually run: the raw material of `pitwall validate-sim`, printed as JSON.
// Usage: node scripts/backtest.ts <bundle dir> <runs> <seed> <fraction,fraction,...>
import type { Manifest } from "../src/contract/manifest";
import type { SimRace } from "../src/contract/sim";
import { finishCounts, startLaps } from "../src/sim/index.ts";

const [dir, runsArg, seedArg, fractionsArg] = process.argv.slice(2);
const runs = Number(runsArg);
const seed = Number(seedArg);
const fractions = (fractionsArg ?? "").split(",").map(Number);
if (!dir || !Number.isInteger(runs) || !Number.isInteger(seed) || fractions.some(Number.isNaN)) {
  throw new Error("usage: node scripts/backtest.ts <bundle dir> <runs> <seed> <fractions>");
}
const base = new URL(`${dir}/`, `file://${process.cwd()}/`);
const load = async <T>(path: string): Promise<T> =>
  (await import(new URL(path, base).href, { with: { type: "json" } })).default as T;

const manifest = await load<Manifest>("manifest.json");
const races = [];
for (const entry of manifest.races) {
  if (!entry.sim_path) continue;
  const race = await load<SimRace>(entry.sim_path);
  races.push({
    season: race.season,
    round: race.round,
    starts: startLaps(race.total_laps, fractions, race.first_start_lap).map(({ fraction, lap }) => ({
      fraction,
      lap,
      counts: finishCounts(race, lap, runs, seed),
    })),
  });
}
console.log(JSON.stringify({ runs, seed, races }));
