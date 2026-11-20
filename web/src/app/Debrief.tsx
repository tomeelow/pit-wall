import type { StrategySettings } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import { debrief, type Decision, type Strategy, type Verdict } from "../sim/index.ts";
import { tyreLabel } from "./compounds";
import { useRun } from "./hooks";
import { evaluator, SEED } from "./lab";
import { Empty, Failure, Skeleton } from "./States";

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

function stops(race: SimRace, strategy: Strategy): string {
  if (strategy.length === 0) return "No more stops";
  return strategy.map((s) => `lap ${s.lap} for ${tyreLabel(race.compounds, s.compound_c)}`).join(", then ");
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
  return (
    <table className="grid ranked">
      <thead>
        <tr>
          <th>Stop</th>
          <th className="r">The stop cost, places</th>
          <th className="r">The plan from there cost</th>
          <th>Best plan: pit on</th>
        </tr>
      </thead>
      <tbody>
        {decisions.map((d) => {
          const v: Verdict = d[side];
          return (
            <tr key={d.stop.lap}>
              <td>
                Lap <span className="num">{d.stop.lap}</span>, {tyreLabel(race.compounds, d.stop.compound_c)}
              </td>
              <td className="r num">
                <Cost value={v.regret} se={v.regretSe} />
              </td>
              <td className="r num">
                <Cost value={v.planRegret} se={v.planRegretSe} />
              </td>
              <td className="plan-text">{stops(race, v.best)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Swings({ race, done, side }: { race: SimRace; done: Results["done"]; side: Side }) {
  const rows = Object.entries(done)
    .flatMap(([driver, decisions]) => decisions.map((d) => ({ driver, d, v: d[side] })))
    .sort((x, y) => y.v.regret - x.v.regret)
    .slice(0, SWINGS);
  if (rows.length === 0) return <p className="note sub">No stops judged yet.</p>;
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Driver</th>
          <th>Stop</th>
          <th className="r">Cost, places</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ driver, d, v }) => (
          <tr key={`${driver}${d.stop.lap}`}>
            <td>{driver}</td>
            <td>
              Lap <span className="num">{d.stop.lap}</span>, {tyreLabel(race.compounds, d.stop.compound_c)}
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
        <section className="panel">
          <header>
            <h2>Debrief</h2>
          </header>
          <div className="body">
            <p className="sub">
              Each stop is judged from the end of the lap before it, against the best plan the search finds from there,
              on {settings.holdout_runs.toLocaleString("en")} fresh races. Twice: once with safety cars drawn at random,
              as the pit wall saw it, once with them where they fell.
            </p>
            <button type="button" className="primary" onClick={() => go([car])} disabled={run.status === "running" || !!mine}>
              Debrief {driver}
            </button>
            <button
              type="button"
              className="quiet wide"
              onClick={() => go(race.cars.map((_, k) => k))}
              disabled={run.status === "running" || judged === race.cars.length}
            >
              Debrief the whole field
            </button>
            {run.status === "running" && (
              <p className="sub num">
                {results.current ? `Judging ${results.current}'s stops; ` : ""}
                {judged} of {race.cars.length} drivers done, {run.races.toLocaleString("en")} races simulated
              </p>
            )}
            {run.status === "error" && <Failure message={run.message} />}
          </div>
        </section>

        <section className="panel" aria-live="polite">
          <header>
            <h2>{driver}&rsquo;s stops</h2>
            <span className="sub">expected places lost against the best plan; higher is worse</span>
          </header>
          {!mine ? (
            run.status === "running" ? (
              <Skeleton rows={6} label={`Judging ${driver}'s stops`} />
            ) : (
              <Empty title="Not judged yet">Debrief {driver} to see what each stop cost.</Empty>
            )
          ) : mine.length === 0 ? (
            <Empty title="No stops to judge">{driver} made no stop the search could judge.</Empty>
          ) : (
            <div className="body verdicts">
              <h3>Was it a good call?</h3>
              <p className="sub">Ex ante: safety cars, red flags and retirements drawn at random after the decision lap.</p>
              <div className="scroll">
                <Verdicts race={race} decisions={mine} side="exAnte" />
              </div>
              <h3>Did it work out?</h3>
              <p className="sub">Ex post: they happen when they really did. Hindsight, kept apart from the call.</p>
              <div className="scroll">
                <Verdicts race={race} decisions={mine} side="exPost" />
              </div>
            </div>
          )}
          <ul className="assumptions">
            <li>
              <b>Rivals keep their real strategies.</b> The best plan is best against a field that does not react.
            </li>
            <li>
              <b>The stop cost</b> compares the best plan with the best plan that makes this stop; later stops are
              charged to their own row. <b>The plan cost</b> is everything the real plan lost from that lap on.
            </li>
            <li>
              <b>Pace is fitted on the whole race,</b> a known softening of the ex ante view. Red figures are more than
              twice their standard error.
            </li>
          </ul>
        </section>
      </div>

      <section className="panel swings">
        <header>
          <h2>Biggest strategic swings</h2>
          <span className="sub num">
            {judged} of {race.cars.length} drivers judged
          </span>
        </header>
        <div className="split split-even">
          <div>
            <h3 className="note">Worst calls, ex ante</h3>
            <Swings race={race} done={results.done} side="exAnte" />
          </div>
          <div>
            <h3 className="note">Worst outcomes, ex post</h3>
            <Swings race={race} done={results.done} side="exPost" />
          </div>
        </div>
      </section>
    </>
  );
}
