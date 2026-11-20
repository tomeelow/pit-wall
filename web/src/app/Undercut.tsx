import { useState } from "react";
import type { StrategySettings } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import { EX_ANTE, EX_POST, type UndercutResult } from "../sim/index.ts";
import { tyreLabel } from "./compounds";
import { LapField, percent, Pick, Segmented, signed } from "./Controls";
import { useRun } from "./hooks";
import { askUndercut, SEED } from "./lab";
import { Assumptions, Empty, Failure, Skeleton } from "./States";

type Events = "sampled" | "realised";
type Result = UndercutResult & { events: Events; attacker: number; defender: number; lap: number };

/** The car running just ahead of `car` after `lap`; for the leader, the one just behind. */
function nearest(race: SimRace, car: number, lap: number): number | null {
  const times = race.snapshots.find((s) => s.lap === lap)?.race_time_s ?? [];
  const mine = times[car];
  if (mine === null || mine === undefined) return null;
  let ahead: number | null = null;
  let behind: number | null = null;
  times.forEach((t, i) => {
    if (t === null || t === undefined || i === car) return;
    if (t < mine && (ahead === null || t > times[ahead]!)) ahead = i;
    if (t >= mine && (behind === null || t < times[behind]!)) behind = i;
  });
  return ahead ?? behind;
}

const seconds = (x: number) => `${x.toFixed(2)} s`;

export function Undercut({
  race,
  car,
  settings,
  laps,
  fromLap,
  onLap,
}: {
  race: SimRace;
  car: number;
  settings: StrategySettings;
  laps: readonly number[];
  fromLap: number;
  onLap: (lap: number) => void;
}) {
  // The question is about in-laps fromLap + 1 and fromLap + 2: the engine needs both run after it.
  const inLaps = laps.filter((lap) => lap >= 1 && lap + 1 <= race.total_laps - 2);
  const lap = Math.min(Math.max(fromLap, inLaps[0] ?? 1), inLaps.at(-1) ?? fromLap);
  const running = race.cars
    .map((c, i) => ({ value: i, label: c.driver }))
    .filter((o) => o.value !== car && race.snapshots.find((s) => s.lap === lap)?.compound_c[o.value] != null);
  const [picked, setPicked] = useState<number | null>(null);
  const defender = picked ?? nearest(race, car, lap) ?? running[0]?.value ?? null;
  const hardest = Math.min(...race.compounds);
  const [attackerC, setAttackerC] = useState(hardest);
  const [defenderC, setDefenderC] = useState(hardest);
  const [events, setEvents] = useState<Events>("sampled");
  const [run, start] = useRun<Result>();
  const tyres = race.compounds.map((c) => ({ value: c, label: tyreLabel(race.compounds, c) }));
  const attacker = race.cars[car]!.driver;

  const go = () =>
    defender !== null &&
    start(async ({ addRaces }) => {
      const asked = events;
      const query = {
        attacker: car,
        defender,
        lap: lap + 1,
        attackerCompound: attackerC,
        defenderCompound: defenderC,
        runs: settings.max_runs,
        seed: SEED,
        mode: asked === "sampled" ? EX_ANTE : EX_POST,
      };
      const result = await askUndercut(race, query);
      addRaces(2 * settings.max_runs);
      return { ...result, events: asked, attacker: car, defender, lap: lap + 1 };
    });

  return (
    <div className="split">
      <section className="panel">
        <header>
          <h2>Undercut or overcut</h2>
          <span className="sub">{attacker} attacks</span>
        </header>
        <div className="body">
          {defender === null ? (
            <Empty title="Nobody to attack">{attacker} is not running at this point.</Empty>
          ) : (
            <>
              <Pick label="Defender" value={defender} options={running} onChange={setPicked} />
              <LapField label="Race state after" laps={inLaps} value={lap} total={race.total_laps} onChange={onLap} />
              <Pick label={`${attacker} fits`} value={attackerC} options={tyres} onChange={setAttackerC} />
              <Pick label={`${race.cars[defender]!.driver} fits`} value={defenderC} options={tyres} onChange={setDefenderC} />
              <Segmented
                label="Safety cars and retirements"
                value={events}
                onChange={setEvents}
                options={[
                  { value: "sampled", label: "Drawn at random" },
                  { value: "realised", label: "As they happened" },
                ]}
              />
              <p className="sub">
                Undercut: {attacker} pits at the end of lap {lap + 1}, the defender a lap later. Overcut:
                the other way round. Read once both have done their out-lap.
              </p>
              <button type="button" className="primary" onClick={go}>
                Run {settings.max_runs.toLocaleString("en")} races each way
              </button>
            </>
          )}
        </div>
      </section>

      <section className="panel" aria-live="polite">
        <header>
          <h2>Who comes out ahead</h2>
        </header>
        {run.status === "idle" && (
          <Empty title="No answer yet">
            Pick a defender and a lap: the answer is the chance {attacker} is ahead once both have stopped,
            and the parts it is made of.
          </Empty>
        )}
        {run.status === "running" && <Skeleton rows={5} label="Simulating" />}
        {run.status === "error" && <Failure message={run.message} />}
        {run.status === "done" && <Answer race={race} result={run.result} />}
        <Assumptions fromLap={run.status === "done" ? run.result.lap - 1 : lap} events={run.status === "done" ? run.result.events : events} />
        <p className="sub note">
          How far to trust this:{" "}
          <a href="https://github.com/tomeelow/pit-wall#strategy-tools-known-weaknesses">
            the undercut check against real pit sequences
          </a>
          .
        </p>
      </section>
    </div>
  );
}

function Answer({ race, result }: { race: SimRace; result: Result }) {
  const a = race.cars[result.attacker]!.driver;
  const d = race.cars[result.defender]!.driver;
  const c = result.components;
  return (
    <>
      <div className="stats">
        <div>
          <span className="figure">{percent(result.undercut)}</span>
          <span className="caption">
            {a} ahead after pitting first, of {result.runs.undercut.toLocaleString("en")} races both finished the stops
          </span>
        </div>
        <div>
          <span className="figure">{percent(result.overcut)}</span>
          <span className="caption">
            {a} ahead after staying out a lap longer, of {result.runs.overcut.toLocaleString("en")}
          </span>
        </div>
      </div>
      <div className="body">
        <table className="parts">
          <caption>The parts, from posterior means at the start of lap {result.lap}</caption>
          <tbody>
            <tr>
              <th>Gap</th>
              <td className="num">
                {c.gapS >= 0 ? `${a} ${seconds(c.gapS)} behind ${d}` : `${a} ${seconds(-c.gapS)} ahead of ${d}`}
              </td>
            </tr>
            <tr>
              <th>Pace, tyres aside</th>
              <td className="num">{signed(c.paceDeltaS)} s a lap for {a}</td>
            </tr>
            <tr>
              <th>New set over old, on the out-lap</th>
              <td className="num">{signed(c.tyreDeltaS)} s for {a}</td>
            </tr>
            <tr>
              <th>Green pit stop</th>
              <td className="num">
                {seconds(c.pitLossS.median)}, 80% between {seconds(c.pitLossS.p10)} and {seconds(c.pitLossS.p90)}
              </td>
            </tr>
            <tr>
              <th>Warm-up, by lap on the new set</th>
              <td className="num">
                {a}: {c.warmupS.attacker.map((x) => x.toFixed(2)).join(", ")} s; {d}:{" "}
                {c.warmupS.defender.map((x) => x.toFixed(2)).join(", ")} s
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </>
  );
}
