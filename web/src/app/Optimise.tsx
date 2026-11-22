import { useState } from "react";
import type { StrategySettings } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import { candidates, EX_ANTE, optimise, type Objective, type Ranked, type SearchResult } from "../sim/index.ts";
import { LapField, percent, Pick, Segmented, signed } from "./Controls";
import { Spark } from "./Histogram";
import { useT } from "./i18n";
import { useRun } from "./hooks";
import { evaluator, SEED } from "./lab";
import { describePlan, planLane, planSegments } from "./plan";
import { Assumptions, Empty, Failure, Skeleton } from "./States";
import { StintLane } from "./StintLane";

type Kind = Objective["kind"];
type Result = SearchResult & { tried: number; objective: Objective };

export function Optimise({
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
  const { optimise: tx } = t;
  const [kind, setKind] = useState<Kind>("position");
  const rivals = race.cars.map((c, i) => ({ value: i, label: c.driver })).filter((o) => o.value !== car);
  const [rival, setRival] = useState(rivals[0]!.value);
  const [run, start] = useRun<Result>();
  const objective: Objective = kind === "beat" ? { kind, rival } : { kind };

  const go = () =>
    start(async ({ ticket, addRaces }) => {
      const options = candidates(race, car, fromLap, settings);
      if (options.length === 0) throw new Error(tx.notRunning(race.cars[car]!.driver, fromLap));
      const search = { car, fromLap, candidates: options, objective, mode: EX_ANTE, seed: SEED, settings };
      const found = await optimise(race, search, evaluator(race, ticket, addRaces));
      return { ...found, tried: options.length, objective };
    });

  const row = (r: Ranked, rank: string, actual: boolean) => {
    const segments = planSegments(race, car, fromLap, r.strategy);
    const d = r.distribution;
    return (
      <tr key={rank} className={actual ? "pinned" : undefined}>
        <td>{rank}</td>
        <td className="plan-cell">
          <StintLane laps={race.total_laps} name={describePlan(t, segments)} stints={planLane(t, race, car, fromLap, r.strategy)} />
          <span className="plan-text">{describePlan(t, segments)}</span>
        </td>
        <td className="r num">{segments.length - 1}</td>
        <td className="r num big">{d.meanPosition.toFixed(2)}</td>
        <td className="r num">{percent(d.places[0]! / d.runs)}</td>
        <td className="r num">{percent(d.podium)}</td>
        <td className="r num">{percent(d.points)}</td>
        {run.status === "done" && run.result.objective.kind === "beat" && <td className="r num">{percent(r.value)}</td>}
        <td className={`r num${r.versusActual.meanGain > 0 ? " good" : ""}`}>
          {actual ? "0" : signed(r.versusActual.meanGain)}
          {!actual && <small> &plusmn;{r.versusActual.meanGainSe.toFixed(2)}</small>}
        </td>
        <td>
          <Spark value={d} tone={actual ? "a" : "b"} />
        </td>
      </tr>
    );
  };

  return (
    <div className="split split-narrow">
      <section className="panel">
        <header>
          <h2>{tx.search}</h2>
        </header>
        <div className="body">
          <Segmented
            label={tx.target}
            value={kind}
            onChange={setKind}
            options={[
              { value: "position", label: tx.position },
              { value: "podium", label: tx.podium },
              { value: "points", label: tx.points },
              { value: "beat", label: tx.beat },
            ]}
          />
          {kind === "beat" && <Pick label={tx.rival} value={rival} options={rivals} onChange={setRival} />}
          <LapField label={t.whatif.decideAfter} laps={laps} value={fromLap} total={race.total_laps} onChange={onLap} />
          <p className="sub">{tx.space(settings.max_stops, settings.min_stint_laps, settings.min_race_clean_laps)}</p>
          <button type="button" className="primary" onClick={go} disabled={run.status === "running"}>
            {run.status === "running" ? tx.searching : tx.search}
          </button>
          {run.status !== "idle" && run.status !== "error" && (
            <p className="sub num">{tx.simulated(run.races)}</p>
          )}
        </div>
      </section>

      <section className="panel" aria-live="polite">
        <header>
          <h2>{tx.best(fromLap)}</h2>
          {run.status === "done" && <span className="sub num">{tx.tried(run.result.tried, settings.max_runs)}</span>}
        </header>
        {run.status === "idle" && (
          <Empty title={tx.noSearch}>{tx.noSearchBody(settings.keep)}</Empty>
        )}
        {run.status === "running" && <Skeleton rows={settings.keep + 1} label={tx.searching} />}
        {run.status === "error" && <Failure message={run.message} />}
        {run.status === "done" && (
          <div className="scroll">
            <table className="grid ranked">
              <thead>
                <tr>
                  <th>{tx.rank}</th>
                  <th>{tx.plan}</th>
                  <th className="r">{tx.stops}</th>
                  <th className="r">{tx.expected}</th>
                  <th className="r">{tx.win}</th>
                  <th className="r">{tx.podium}</th>
                  <th className="r">{tx.points}</th>
                  {run.result.objective.kind === "beat" && (
                    <th className="r">{tx.beatRival(race.cars[(run.result.objective as { rival: number }).rival]!.driver)}</th>
                  )}
                  <th className="r">{tx.versusActual}</th>
                  <th>{tx.spread}</th>
                </tr>
              </thead>
              <tbody>
                {run.result.ranked.map((r, k) => row(r, String(k + 1), false))}
                {row(run.result.actual, tx.actual, true)}
              </tbody>
            </table>
          </div>
        )}
        <Assumptions fromLap={fromLap} events="sampled" />
      </section>
    </div>
  );
}
