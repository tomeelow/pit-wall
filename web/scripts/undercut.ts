// Out-of-sample check of the undercut module. Every pair of cars adjacent at the end of lap L - 1
// and within the traffic window, where one stopped on lap L and the other on lap L + 1, with no
// neutralisation on laps L .. L + 2 and both still running at the end of L + 2. The module predicts
// P(car behind ahead at the end of L + 2) with the events as they happened (green); the outcome is
// the real order then. Pace is fitted on the race itself: the documented softening.
// Usage: node scripts/undercut.ts <bundle dir> <runs> <seed> <bin edges, comma separated>
import type { Manifest } from "../src/contract/manifest";
import type { SimRace } from "../src/contract/sim";
import { undercut, type Mode } from "../src/sim/index.ts";

const [dir, runsArg, seedArg, binsArg] = process.argv.slice(2);
const runs = Number(runsArg);
const seed = Number(seedArg);
const bins = (binsArg ?? "").split(",").map(Number);
if (!dir || !Number.isInteger(runs) || !Number.isInteger(seed) || bins.some(Number.isNaN)) {
  throw new Error("usage: node scripts/undercut.ts <bundle dir> <runs> <seed> <bin edges>");
}
const AS_IT_HAPPENED: Mode = { events: "realised", noise: true };
const base = new URL(`${dir}/`, `file://${process.cwd()}/`);
const load = async <T>(path: string): Promise<T> =>
  (await import(new URL(path, base).href, { with: { type: "json" } })).default as T;

interface Row {
  race: string;
  kind: "undercut" | "overcut"; // undercut: the car behind stopped first
  p: number;
  happened: boolean;
}

function pairs(race: SimRace): Row[] {
  const rows: Row[] = [];
  const name = `${race.season}-${String(race.round).padStart(2, "0")}`;
  // The engine starts from the end of lap - 1.
  for (let lap = Math.max(2, race.first_start_lap + 1); lap <= race.total_laps - 3; lap++) {
    if (race.realised.some((n) => n.start_lap <= lap + 2 && n.end_lap >= lap)) continue;
    const before = race.snapshots[lap - 2]!.race_time_s;
    const after = race.snapshots[lap + 1]!.race_time_s;
    const order = race.cars
      .map((_, i) => i)
      .filter((i) => before[i] != null)
      .sort((a, b) => before[a]! - before[b]!);
    for (let k = 1; k < order.length; k++) {
      const [ahead, behind] = [order[k - 1]!, order[k]!];
      if (before[behind]! - before[ahead]! > race.traffic.max_gap_s) continue;
      if (after[ahead] == null || after[behind] == null) continue;
      const stopAt = (car: number, at: number) => race.cars[car]!.stops.find((s) => s.lap === at);
      const kind =
        stopAt(behind, lap) && stopAt(ahead, lap + 1)
          ? "undercut"
          : stopAt(ahead, lap) && stopAt(behind, lap + 1)
            ? "overcut"
            : null;
      if (!kind) continue;
      const first = kind === "undercut" ? behind : ahead;
      const second = kind === "undercut" ? ahead : behind;
      const result = undercut(race, {
        attacker: behind,
        defender: ahead,
        lap,
        attackerCompound: (behind === first ? stopAt(first, lap) : stopAt(second, lap + 1))!
          .compound_c,
        defenderCompound: (ahead === first ? stopAt(first, lap) : stopAt(second, lap + 1))!
          .compound_c,
        runs,
        seed,
        mode: AS_IT_HAPPENED,
      });
      rows.push({
        race: name,
        kind,
        p: kind === "undercut" ? result.undercut : result.overcut,
        happened: after[behind]! < after[ahead]!,
      });
    }
  }
  return rows;
}

const manifest = await load<Manifest>("manifest.json");
const rows: Row[] = [];
for (const entry of manifest.races) {
  if (entry.sim_path) rows.push(...pairs(await load<SimRace>(entry.sim_path)));
}

const brier = (p: number, y: boolean) => (p - (y ? 1 : 0)) ** 2;
const mean = (values: number[]) => values.reduce((a, b) => a + b, 0) / Math.max(values.length, 1);
console.log("| Pairs | n | Worked | Brier (module) | Brier (base rate, other races) |");
console.log("|---|---|---|---|---|");
for (const kind of ["undercut", "overcut", "all"] as const) {
  const group = rows.filter((r) => kind === "all" || r.kind === kind);
  // The base rate for a pair is learnt from the other races' pairs of the same kind.
  const baseline = group.map((r) => {
    const others = rows.filter((o) => o.kind === r.kind && o.race !== r.race);
    return brier(mean(others.map((o) => (o.happened ? 1 : 0))), r.happened);
  });
  console.log(
    `| ${kind} | ${group.length} | ${mean(group.map((r) => (r.happened ? 1 : 0))).toFixed(3)} | ` +
      `${mean(group.map((r) => brier(r.p, r.happened))).toFixed(3)} | ${mean(baseline).toFixed(3)} |`,
  );
}
console.log("\n| Predicted | n | Mean predicted | Observed |\n|---|---|---|---|");
for (let b = 1; b < bins.length; b++) {
  const [lo, hi] = [bins[b - 1]!, bins[b]!];
  const group = rows.filter((r) => r.p >= lo && (r.p < hi || (b === bins.length - 1 && r.p <= hi)));
  console.log(
    `| ${lo.toFixed(1)}–${hi.toFixed(1)} | ${group.length} | ${mean(group.map((r) => r.p)).toFixed(3)} | ` +
      `${mean(group.map((r) => (r.happened ? 1 : 0))).toFixed(3)} |`,
  );
}
