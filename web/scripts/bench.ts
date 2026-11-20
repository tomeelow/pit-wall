// Times the engine on one thread: node scripts/bench.ts <races> <laps> <cars> <max seconds>.
// `make bench` passes the numbers from config/budgets.yaml and fails when the budget is exceeded.
import { actualStrategies, runSimulations } from "../src/sim/index.ts";
import { syntheticRace } from "../src/sim/synthetic.ts";

const [races, laps, cars, maxSeconds] = process.argv.slice(2).map(Number);
if (![races, laps, cars, maxSeconds].every((v) => v !== undefined && Number.isFinite(v))) {
  throw new Error("usage: node scripts/bench.ts <races> <laps> <cars> <max seconds>");
}
const race = syntheticRace({ cars, laps, draws: 200, eventRate: 0.01, dnfRate: 0.0005 });
const query = {
  fromLap: 1,
  sets: [actualStrategies(race, 1)],
  runs: races!,
  seed: 1,
  mode: { events: "sampled", noise: true } as const,
};
runSimulations(race, { ...query, runs: Math.ceil(races! / 20) }); // warm up the JIT

const start = performance.now();
runSimulations(race, query);
const seconds = (performance.now() - start) / 1000;
console.log(
  `${races} races x ${laps} laps x ${cars} cars on one thread: ${seconds.toFixed(2)} s ` +
    `(${Math.round(races! / seconds)} races/s; budget ${maxSeconds} s)`,
);
if (seconds > maxSeconds!) {
  console.error("over budget");
  process.exitCode = 1;
}
