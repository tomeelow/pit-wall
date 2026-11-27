import type { StrategySettings } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import { debrief, type Decision, type Strategy, type Verdict } from "../sim/index.ts";
import { tyreLabel } from "./compounds";
import { useT, type Strings } from "./i18n";
import { useRun } from "./hooks";
import { evaluator, SEED } from "./lab";
import { Empty, Failure, Lead, Skeleton } from "./States";

interface Results {
  done: Record<string, Decision[]>;
  current: string | null;
}

type Side = "exAnte" | "exPost";

/** Biggest swings shown per side. */
const SWINGS = 5;

/** A cost is shown as real when it is more than twice its standard error. */
const real = (value: number, se: number) => value > 2 * se;

/** Rounds away the sign of a zero: "-0.00" reads as a gain. */
const places = (value: number) => (Math.abs(value) < 0.005 ? 0 : value).toFixed(2);

function Cost({ value, se }: { value: number; se: number }) {
  return (
    <span className={real(value, se) ? "bad" : undefined}>
      {places(value)}
      <small> &plusmn;{se.toFixed(2)}</small>
    </span>
  );
}

function stops(t: Strings, race: SimRace, strategy: Strategy): string {
  if (strategy.length === 0) return t.debrief.noMoreStops;
  return strategy.map((s) => t.debrief.stopFor(s.lap, tyreLabel(t, race.compounds, s.compound_c))).join(t.debrief.then);
}

function StopName({ race, stop }: { race: SimRace; stop: Decision["stop"] }) {
  const t = useT();
  return (
    <>
      {t.lap} <span className="num">{stop.lap}</span>, {tyreLabel(t, race.compounds, stop.compound_c)}
    </>
  );
}

function Verdicts({
  race,
  decisions,
  side,
}: {
  race: SimRace;
  decisions: readonly Decision[];
  side: Side;
}) {
  const t = useT();
  return (
    <table className="grid ranked">
      <thead>
        <tr>
          <th>{t.debrief.stop}</th>
          <th className="r">{t.debrief.stopCost}</th>
          <th className="r">{t.debrief.planCost}</th>
          <th>{t.debrief.best}</th>
        </tr>
      </thead>
      <tbody>
        {decisions.map((d) => {
          const v: Verdict = d[side];
          return (
            <tr key={d.stop.lap}>
              <td>
                <StopName race={race} stop={d.stop} />
              </td>
              <td className="r num">
                <Cost value={v.regret} se={v.regretSe} />
              </td>
              <td className="r num">
                <Cost value={v.planRegret} se={v.planRegretSe} />
              </td>
              <td className="plan-text">{stops(t, race, v.best)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Swings({ race, done, side }: { race: SimRace; done: Results["done"]; side: Side }) {
  const t = useT();
  const rows = Object.entries(done)
    .flatMap(([driver, decisions]) => decisions.map((d) => ({ driver, d, v: d[side] })))
    .sort((x, y) => y.v.regret - x.v.regret)
    .slice(0, SWINGS);
  if (rows.length === 0) return <p className="note sub">{t.debrief.noneJudged}</p>;
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>{t.debrief.driver}</th>
          <th>{t.debrief.stop}</th>
          <th className="r">{t.debrief.cost}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ driver, d, v }) => (
          <tr key={`${driver}${d.stop.lap}`}>
            <td>{driver}</td>
            <td>
              <StopName race={race} stop={d.stop} />
            </td>
            <td className="r num">
              <Cost value={v.regret} se={v.regretSe} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Debrief({
  race,
  car,
  settings,
}: {
  race: SimRace;
  car: number;
  settings: StrategySettings;
}) {
  const t = useT();
  const { debrief: tx } = t;
  const [run, start] = useRun<Results>();
  const results: Results =
    run.status === "done" ? run.result : run.status === "running" && run.partial ? run.partial : { done: {}, current: null };
  const driver = race.cars[car]!.driver;
  const mine = results.done[driver];
  const judged = Object.keys(results.done).length;

  const go = (cars: number[]) =>
    start(async ({ ticket, addRaces, partial }) => {
      const done = { ...results.done };
      for (const c of cars) {
        const code = race.cars[c]!.driver;
        if (done[code]) continue;
        partial({ done: { ...done }, current: code });
        done[code] = await debrief(race, c, settings, SEED, evaluator(race, ticket, addRaces));
      }
      return { done, current: null };
    });

  return (
    <>
      <div className="split split-narrow">
        <section className="panel" data-tour="debrief">
          <header>
            <h2>{tx.title}</h2>
          </header>
          <div className="body">
            <p className="sub">{tx.intro(settings.holdout_runs)}</p>
            <button type="button" className="primary" onClick={() => go([car])} disabled={run.status === "running" || !!mine}>
              {tx.one(driver)}
            </button>
            <button
              type="button"
              className="quiet wide"
              onClick={() => go(race.cars.map((_, k) => k))}
              disabled={run.status === "running" || judged === race.cars.length}
            >
              {tx.field}
            </button>
            {run.status === "running" && (
              <p className="sub num">
                {results.current ? `${tx.judging(results.current)}; ` : ""}
                {tx.progress(judged, race.cars.length, run.races)}
              </p>
            )}
            {run.status === "error" && <Failure message={run.message} />}
          </div>
        </section>

        <section className="panel" aria-live="polite">
          <header>
            <h2>{tx.stopsOf(driver)}</h2>
            <span className="sub">{tx.stopsSub}</span>
          </header>
          {!mine ? (
            run.status === "running" ? (
              <Skeleton rows={6} label={tx.judging(driver)} />
            ) : (
              <Empty title={tx.notJudged}>{tx.notJudgedBody(driver)}</Empty>
            )
          ) : mine.length === 0 ? (
            <Empty title={tx.noStops}>{tx.noStopsBody(driver)}</Empty>
          ) : (
            <div className="body verdicts">
              <h3>{tx.goodCall}</h3>
              <p className="sub">{tx.exAnte}</p>
              <div className="scroll">
                <Verdicts race={race} decisions={mine} side="exAnte" />
              </div>
              <h3>{tx.workedOut}</h3>
              <p className="sub">{tx.exPost}</p>
              <div className="scroll">
                <Verdicts race={race} decisions={mine} side="exPost" />
              </div>
            </div>
          )}
          <ul className="assumptions">
            <Lead text={tx.rivals} />
            <li>
              <b>{tx.costs[0]}</b> {tx.costs[1]} <b>{tx.costs[2]}</b> {tx.costs[3]}
            </li>
            <Lead text={tx.pace} />
          </ul>
        </section>
      </div>

      <section className="panel swings">
        <header>
          <h2>{tx.swings}</h2>
          <span className="sub num">{tx.judged(judged, race.cars.length)}</span>
        </header>
        <div className="split split-even">
          <div>
            <h3 className="note">{tx.worstCalls}</h3>
            <Swings race={race} done={results.done} side="exAnte" />
          </div>
          <div>
            <h3 className="note">{tx.worstOutcomes}</h3>
            <Swings race={race} done={results.done} side="exPost" />
          </div>
        </div>
      </section>
    </>
  );
}
