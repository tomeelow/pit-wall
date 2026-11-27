import { useState } from "react";
import type { StrategySettings } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import { EX_ANTE, EX_POST, type UndercutResult } from "../sim/index.ts";
import { tyreLabel } from "./compounds";
import { LapField, percent, Pick, Segmented, signed } from "./Controls";
import { useRun } from "./hooks";
import { useT, type Strings } from "./i18n";
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

const seconds = (t: Strings, x: number) => `${x.toFixed(2)} ${t.s}`;

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
  const t = useT();
  const { undercut: tx } = t;
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
  const tyres = race.compounds.map((c) => ({ value: c, label: tyreLabel(t, race.compounds, c) }));
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
      <section className="panel" data-tour="undercut">
        <header>
          <h2>{tx.title}</h2>
          <span className="sub">{tx.attacks(attacker)}</span>
        </header>
        <div className="body">
          {defender === null ? (
            <Empty title={tx.nobody}>{tx.notRunning(attacker)}</Empty>
          ) : (
            <>
              <Pick label={tx.defender} value={defender} options={running} onChange={setPicked} />
              <LapField label={tx.stateAfter} laps={inLaps} value={lap} total={race.total_laps} onChange={onLap} />
              <Pick label={tx.fits(attacker)} value={attackerC} options={tyres} onChange={setAttackerC} />
              <Pick label={tx.fits(race.cars[defender]!.driver)} value={defenderC} options={tyres} onChange={setDefenderC} />
              <Segmented
                label={t.whatif.events}
                value={events}
                onChange={setEvents}
                options={[
                  { value: "sampled", label: t.whatif.sampled },
                  { value: "realised", label: t.whatif.realised },
                ]}
              />
              <p className="sub">{tx.explain(attacker, lap + 1)}</p>
              <button type="button" className="primary" onClick={go}>
                {tx.run(settings.max_runs)}
              </button>
            </>
          )}
        </div>
      </section>

      <section className="panel" aria-live="polite">
        <header>
          <h2>{tx.ahead}</h2>
        </header>
        {run.status === "idle" && (
          <Empty title={tx.noAnswer}>{tx.noAnswerBody(attacker)}</Empty>
        )}
        {run.status === "running" && <Skeleton rows={5} label={tx.simulating} />}
        {run.status === "error" && <Failure message={run.message} />}
        {run.status === "done" && <Answer race={race} result={run.result} />}
        <Assumptions fromLap={run.status === "done" ? run.result.lap - 1 : lap} events={run.status === "done" ? run.result.events : events} />
        <p className="sub note">
          {tx.trust[0]}
          <a href="https://github.com/tomeelow/pit-wall#known-weaknesses-of-the-strategy-tools">{tx.trust[1]}</a>
          {tx.trust[2]}
        </p>
      </section>
    </div>
  );
}

function Answer({ race, result }: { race: SimRace; result: Result }) {
  const t = useT();
  const { undercut: tx } = t;
  const s = (x: number) => seconds(t, x);
  const a = race.cars[result.attacker]!.driver;
  const d = race.cars[result.defender]!.driver;
  const c = result.components;
  return (
    <>
      <div className="stats">
        <div>
          <span className="figure">{percent(result.undercut)}</span>
          <span className="caption">{tx.undercutCaption(a, result.runs.undercut)}</span>
        </div>
        <div>
          <span className="figure">{percent(result.overcut)}</span>
          <span className="caption">{tx.overcutCaption(a, result.runs.overcut)}</span>
        </div>
      </div>
      <div className="body">
        <table className="parts">
          <caption>{tx.parts(result.lap)}</caption>
          <tbody>
            <tr>
              <th>{tx.gap}</th>
              <td className="num">{c.gapS >= 0 ? tx.behindOf(a, s(c.gapS), d) : tx.aheadOf(a, s(-c.gapS), d)}</td>
            </tr>
            <tr>
              <th>{tx.pace}</th>
              <td className="num">{tx.paceValue(signed(c.paceDeltaS), a)}</td>
            </tr>
            <tr>
              <th>{tx.newSet}</th>
              <td className="num">{tx.forDriver(signed(c.tyreDeltaS), a)}</td>
            </tr>
            <tr>
              <th>{tx.greenStop}</th>
              <td className="num">{tx.stopValue(s(c.pitLossS.median), s(c.pitLossS.p10), s(c.pitLossS.p90))}</td>
            </tr>
            <tr>
              <th>{tx.warmup}</th>
              <td className="num">
                {a}: {c.warmupS.attacker.map((x) => x.toFixed(2)).join(", ")} {t.s}; {d}:{" "}
                {c.warmupS.defender.map((x) => x.toFixed(2)).join(", ")} {t.s}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </>
  );
}
