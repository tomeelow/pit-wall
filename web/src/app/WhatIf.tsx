import { useState } from "react";
import type { StrategySettings } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import {
  actualStrategies,
  checkRules,
  compare,
  EX_ANTE,
  EX_POST,
  mergeOutcomes,
  withStrategy,
  type Comparison,
  type Outcome,
  type Strategy,
} from "../sim/index.ts";
import { tyreLabel } from "./compounds";
import { LapField, percent, Pick, Segmented, signed } from "./Controls";
import { Histogram, realFinish } from "./Histogram";
import { useT } from "./i18n";
import { useRun } from "./hooks";
import { evaluator, SEED } from "./lab";
import { planLane } from "./plan";
import { Assumptions, Empty, Failure } from "./States";
import { LapAxis, StintLane } from "./StintLane";

/** Results arrive in this many batches, so the histogram fills in while the pool works. */
const BATCHES = 8;

type Events = "sampled" | "realised";
type Result = Comparison & { events: Events };

export function WhatIf({
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
  const { whatif: tx } = t;
  const actual = actualStrategies(race, fromLap)[car]!;
  const [edit, setEdit] = useState<{ fromLap: number; plan: Strategy }>({ fromLap, plan: actual });
  const plan = edit.fromLap === fromLap ? edit.plan : actual;
  const setPlan = (next: Strategy) => setEdit({ fromLap, plan: next });
  const [events, setEvents] = useState<Events>("sampled");
  const [run, start] = useRun<Result>();
  const rules = checkRules(race, car, fromLap, plan);
  const total = race.total_laps;
  const real = realFinish(race.cars[car]!);
  const runs = settings.max_runs;

  const move = (k: number, lap: number) =>
    setPlan(plan.map((s, i) => (i === k ? { ...s, lap } : s)));
  const tyre = (k: number, compound_c: number) =>
    setPlan(plan.map((s, i) => (i === k ? { ...s, compound_c } : s)));
  const add = () => {
    const after = plan.at(-1)?.lap ?? fromLap;
    const current = plan.at(-1)?.compound_c ?? race.snapshots.find((s) => s.lap === fromLap)!.compound_c[car]!;
    const lap = Math.round((after + total) / 2);
    const other = race.compounds.find((c) => c !== current) ?? current;
    setPlan([...plan, { lap, compound_c: other, tyre_age: 0 }]);
  };

  const go = () =>
    start(async ({ ticket, addRaces, partial }) => {
      const evaluate = evaluator(race, ticket, addRaces);
      const sets = [actualStrategies(race, fromLap), withStrategy(race, fromLap, car, plan)];
      const asked = events;
      const mode = asked === "sampled" ? EX_ANTE : EX_POST;
      const size = Math.ceil(runs / BATCHES);
      const parts: Outcome[] = [];
      for (let first = 0; first < runs; first += size) {
        const n = Math.min(size, runs - first);
        parts.push(await evaluate({ fromLap, sets, runs: n, seed: SEED, mode }, first));
        partial({ ...compare(race, mergeOutcomes(parts), car), events: asked });
      }
      return { ...compare(race, mergeOutcomes(parts), car), events: asked };
    });

  const result = run.status === "done" ? run.result : run.status === "running" ? run.partial : null;
  const stops = plan.map((s, k) => ({
    lap: s.lap,
    min: (plan[k - 1]?.lap ?? fromLap) + 1,
    max: (plan[k + 1]?.lap ?? total) - 1,
  }));

  return (
    <div className="split">
      <section className="panel">
        <header>
          <h2>{tx.from(fromLap)}</h2>
          <span className="sub">{race.cars[car]!.driver}</span>
        </header>
        <div className="body">
          <LapField label={tx.decideAfter} laps={laps} value={fromLap} total={total} onChange={onLap} />
          <div className="lanes">
            <p className="lane-name">{tx.actual}</p>
            <StintLane laps={total} name={tx.actualLane} stints={planLane(t, race, car, fromLap, actual)} tall />
            <p className="lane-name">{tx.alternative}</p>
            <StintLane
              laps={total}
              name={tx.alternativeLane}
              stints={planLane(t, race, car, fromLap, plan)}
              stops={stops}
              onMoveStop={move}
              tall
            />
            <LapAxis laps={total} />
          </div>
          <table className="stops">
            <thead>
              <tr>
                <th>{tx.stop}</th>
                <th>{tx.endOfLap}</th>
                <th>{tx.newSet}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {plan.map((s, k) => (
                <tr key={k}>
                  <td className="num">{k + 1}</td>
                  <td>
                    <input
                      className="input num"
                      type="number"
                      aria-label={tx.stopLap(k + 1)}
                      min={stops[k]!.min}
                      max={stops[k]!.max}
                      value={s.lap}
                      onChange={(e) => move(k, Number(e.target.value))}
                    />
                  </td>
                  <td>
                    <Pick
                      label={tx.stopCompound(k + 1)}
                      value={s.compound_c}
                      options={race.compounds.map((c) => ({ value: c, label: tyreLabel(t, race.compounds, c) }))}
                      onChange={(c) => tyre(k, c)}
                    />
                  </td>
                  <td>
                    <button type="button" className="quiet" onClick={() => setPlan(plan.filter((_, i) => i !== k))}>
                      {tx.remove}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row">
            <button type="button" className="quiet" onClick={add}>
              {tx.addStop}
            </button>
            <button type="button" className="quiet" onClick={() => setPlan(actual)}>
              {tx.backToActual}
            </button>
          </div>
          {rules.invalid.length > 0 ? (
            <ul className="rules rules-invalid">
              {rules.invalid.map((issue) => (
                <li key={issue.kind}>{t.rule(issue)}</li>
              ))}
            </ul>
          ) : rules.breaks.length > 0 ? (
            <ul className="rules rules-break">
              <li>{tx.disqualified}</li>
              {rules.breaks.map((issue) => (
                <li key={issue.kind}>{t.rule(issue)}</li>
              ))}
            </ul>
          ) : (
            <p className="rules rules-ok">{tx.legal}</p>
          )}
          <Segmented
            label={tx.events}
            value={events}
            onChange={setEvents}
            options={[
              { value: "sampled", label: tx.sampled },
              { value: "realised", label: tx.realised },
            ]}
          />
          <button type="button" className="primary" disabled={rules.invalid.length > 0} onClick={go}>
            {tx.run(runs)}
          </button>
        </div>
      </section>

      <section className="panel" aria-live="polite">
        <header>
          <h2>{tx.finishing}</h2>
          {result && <span className="sub num">{tx.sameDraws(result.actual.runs)}</span>}
        </header>
        {run.status === "error" && <Failure message={run.message} />}
        {!result && run.status !== "error" && (
          <Empty title={tx.noResult}>{tx.noResultBody(runs)}</Empty>
        )}
        {result && (
          <>
            <div className="stats">
              <div>
                <span className="figure good">{percent(result.ahead)}</span>
                <span className="caption">{tx.ahead}</span>
              </div>
              <div>
                <span className="figure bad">{percent(result.behind)}</span>
                <span className="caption">{tx.behind}</span>
              </div>
              <div>
                <span className="figure">{signed(result.meanGain)}</span>
                <span className="caption">{tx.mean(result.meanGainSe.toFixed(2))}</span>
              </div>
            </div>
            <div className="body">
              <ul className="legend">
                <li>
                  <i className="dot series-a" />
                  {tx.expected(tx.actualLane, result.actual.meanPosition.toFixed(2))}
                </li>
                <li>
                  <i className="dot series-b" />
                  {tx.expected(tx.alternative, result.alternative.meanPosition.toFixed(2))}
                </li>
                {real !== null && (
                  <li>
                    <i className="dash" />
                    {tx.realFinish(real === "retired" ? t.histogram.retired : `P${real}`)}
                  </li>
                )}
              </ul>
              <Histogram
                series={[
                  { name: tx.actualLane, tone: "a", value: result.actual },
                  { name: tx.alternative, tone: "b", value: result.alternative },
                ]}
                real={real}
              />
              {run.status === "running" && <p className="sub">{tx.simulating(run.races)}</p>}
            </div>
          </>
        )}
        <Assumptions fromLap={fromLap} events={result?.events ?? events} />
      </section>
    </div>
  );
}
