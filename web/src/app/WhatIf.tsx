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
import { Histogram } from "./Histogram";
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
  const actual = actualStrategies(race, fromLap)[car]!;
  const [edit, setEdit] = useState<{ fromLap: number; plan: Strategy }>({ fromLap, plan: actual });
  const plan = edit.fromLap === fromLap ? edit.plan : actual;
  const setPlan = (next: Strategy) => setEdit({ fromLap, plan: next });
  const [events, setEvents] = useState<Events>("sampled");
  const [run, start] = useRun<Result>();
  const rules = checkRules(race, car, fromLap, plan);
  const total = race.total_laps;
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
          <h2>Strategy from lap {fromLap}</h2>
          <span className="sub">{race.cars[car]!.driver}</span>
        </header>
        <div className="body">
          <LapField label="Decide after" laps={laps} value={fromLap} total={total} onChange={onLap} />
          <div className="lanes">
            <p className="lane-name">Actual</p>
            <StintLane laps={total} name="Actual strategy" stints={planLane(race, car, fromLap, actual)} tall />
            <p className="lane-name">Alternative</p>
            <StintLane
              laps={total}
              name="Alternative strategy; drag the stops"
              stints={planLane(race, car, fromLap, plan)}
              stops={stops}
              onMoveStop={move}
              tall
            />
            <LapAxis laps={total} />
          </div>
          <table className="stops">
            <thead>
              <tr>
                <th>Stop</th>
                <th>End of lap</th>
                <th>New set</th>
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
                      aria-label={`Stop ${k + 1} lap`}
                      min={stops[k]!.min}
                      max={stops[k]!.max}
                      value={s.lap}
                      onChange={(e) => move(k, Number(e.target.value))}
                    />
                  </td>
                  <td>
                    <Pick
                      label={`Stop ${k + 1} compound`}
                      value={s.compound_c}
                      options={race.compounds.map((c) => ({ value: c, label: tyreLabel(race.compounds, c) }))}
                      onChange={(c) => tyre(k, c)}
                    />
                  </td>
                  <td>
                    <button type="button" className="quiet" onClick={() => setPlan(plan.filter((_, i) => i !== k))}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row">
            <button type="button" className="quiet" onClick={add}>
              Add a stop
            </button>
            <button type="button" className="quiet" onClick={() => setPlan(actual)}>
              Back to the actual plan
            </button>
          </div>
          {rules.invalid.length > 0 ? (
            <ul className="rules rules-invalid">
              {rules.invalid.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          ) : rules.breaks.length > 0 ? (
            <ul className="rules rules-break">
              <li>The stewards would disqualify this plan, and so does the simulation:</li>
              {rules.breaks.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          ) : (
            <p className="rules rules-ok">Legal under this race’s rules.</p>
          )}
          <Segmented
            label="Safety cars and retirements"
            value={events}
            onChange={setEvents}
            options={[
              { value: "sampled", label: "Drawn at random" },
              { value: "realised", label: "As they happened" },
            ]}
          />
          <button type="button" className="primary" disabled={rules.invalid.length > 0} onClick={go}>
            Run {runs.toLocaleString("en")} races
          </button>
        </div>
      </section>

      <section className="panel" aria-live="polite">
        <header>
          <h2>Finishing position</h2>
          {result && (
            <span className="sub num">
              {result.actual.runs.toLocaleString("en")} races, the same draws for both plans
            </span>
          )}
        </header>
        {run.status === "error" && <Failure message={run.message} />}
        {!result && run.status !== "error" && (
          <Empty title="No result yet">
            Edit the alternative, then run it: both plans race the same {runs.toLocaleString("en")} simulated
            races, and the difference is the answer.
          </Empty>
        )}
        {result && (
          <>
            <div className="stats">
              <div>
                <span className="figure good">{percent(result.ahead)}</span>
                <span className="caption">of races the alternative finishes ahead</span>
              </div>
              <div>
                <span className="figure bad">{percent(result.behind)}</span>
                <span className="caption">finishes behind</span>
              </div>
              <div>
                <span className="figure">{signed(result.meanGain)}</span>
                <span className="caption">places on average, &plusmn;{result.meanGainSe.toFixed(2)} (one standard error)</span>
              </div>
            </div>
            <div className="body">
              <ul className="legend">
                <li>
                  <i className="dot series-a" />
                  Actual, expected P{result.actual.meanPosition.toFixed(2)}
                </li>
                <li>
                  <i className="dot series-b" />
                  Alternative, expected P{result.alternative.meanPosition.toFixed(2)}
                </li>
              </ul>
              <Histogram
                series={[
                  { name: "Actual", tone: "a", value: result.actual },
                  { name: "Alternative", tone: "b", value: result.alternative },
                ]}
              />
              {run.status === "running" && <p className="sub">Simulating, {run.races.toLocaleString("en")} races so far</p>}
            </div>
          </>
        )}
        <Assumptions fromLap={fromLap} events={result?.events ?? events} />
      </section>
    </div>
  );
}
