// Strategy debrief of the first finishers of some races: for each pit stop they made, the
// expected places it cost against the best plan found from the lap before, ex ante (future events
// sampled) and ex post (events as they happened), each on runs the search never saw. In process,
// on one thread: the times show what the browser's worker pool has to beat.
// Usage: node scripts/debrief.ts <bundle dir> <seed> <season-round,...> <drivers per race>
import type { Manifest } from "../src/contract/manifest";
import type { PlannedStop, SimRace } from "../src/contract/sim";
import {
  debrief,
  inProcess,
  type Evaluate,
  type Strategy,
  type Verdict,
} from "../src/sim/index.ts";

const [dir, seedArg, racesArg, driversArg] = process.argv.slice(2);
const seed = Number(seedArg);
const drivers = Number(driversArg);
const wanted = (racesArg ?? "").split(",").filter(Boolean);
if (!dir || !Number.isInteger(seed) || !Number.isInteger(drivers) || wanted.length === 0) {
  throw new Error(
    "usage: node scripts/debrief.ts <bundle dir> <seed> <season-round,...> <drivers>",
  );
}
const base = new URL(`${dir}/`, `file://${process.cwd()}/`);
const load = async <T>(path: string): Promise<T> =>
  (await import(new URL(path, base).href, { with: { type: "json" } })).default as T;

const plan = (stops: readonly PlannedStop[]) =>
  stops
    .map((s) => `L${s.lap} C${s.compound_c}${s.tyre_age ? ` (${s.tyre_age} laps old)` : ""}`)
    .join(", ") || "no stop";
const after = (strategy: Strategy, stop: PlannedStop) =>
  plan(strategy.filter((s) => s.lap >= stop.lap));

const manifest = await load<Manifest>("manifest.json");
const settings = manifest.strategy;
console.log(
  "| Race | Driver | Plan from the stop | Ex ante: stop / plan regret | best plan | " +
    "Ex post: stop / plan regret | best plan | s |",
);
console.log("|---|---|---|---|---|---|---|---|");
const regrets = (v: Verdict) =>
  `${v.regret.toFixed(2)} ± ${v.regretSe.toFixed(2)} / ${v.planRegret.toFixed(2)} ± ${v.planRegretSe.toFixed(2)}`;
for (const key of wanted) {
  const entry = manifest.races.find(
    (e) => `${e.season}-${String(e.round).padStart(2, "0")}` === key,
  );
  if (!entry?.sim_path) throw new Error(`${key}: no simulator inputs`);
  const race = await load<SimRace>(entry.sim_path);
  let simulations = 0;
  const local = inProcess(race);
  const counted: Evaluate = (query, first) => {
    simulations += query.sets.length * query.runs;
    return local(query, first);
  };
  const finishers = race.cars
    .map((car, i) => ({ car, i }))
    .filter(({ car }) => car.finish_position !== null && car.finish_position <= drivers)
    .sort((a, b) => a.car.finish_position! - b.car.finish_position!);
  for (const { car, i } of finishers) {
    const started = performance.now();
    simulations = 0;
    const decisions = await debrief(race, i, settings, seed, counted);
    const seconds = (performance.now() - started) / 1000;
    for (const d of decisions) {
      const actual = car.stops.filter((s) => s.lap >= d.stop.lap);
      console.log(
        `| ${key} ${race.name} | ${car.driver} (P${car.finish_position}) | ${plan(actual)} | ` +
          `${regrets(d.exAnte)} | ${after(d.exAnte.best, d.stop)} | ` +
          `${regrets(d.exPost)} | ${after(d.exPost.best, d.stop)} | ` +
          `${(seconds / Math.max(decisions.length, 1)).toFixed(1)} |`,
      );
    }
    console.error(
      `${key} ${car.driver}: ${decisions.length} decisions, ${simulations} races simulated in ${seconds.toFixed(1)} s`,
    );
  }
}
