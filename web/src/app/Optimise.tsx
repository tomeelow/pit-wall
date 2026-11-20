import { useState } from "react";
import type { StrategySettings } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import { candidates, EX_ANTE, optimise, type Objective, type Ranked, type SearchResult } from "../sim/index.ts";
import { LapField, percent, Pick, Segmented, signed } from "./Controls";
import { Spark } from "./Histogram";
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
  const [kind, setKind] = useState<Kind>("position");
  const rivals = race.cars.map((c, i) => ({ value: i, label: c.driver })).filter((o) => o.value !== car);
  const [rival, setRival] = useState(rivals[0]!.value);
  const [run, start] = useRun<Result>();
  const objective: Objective = kind === "beat" ? { kind, rival } : { kind };

  const go = () =>
    start(async ({ ticket, addRaces }) => {
      const options = candidates(race, car, fromLap, settings);
      if (options.length === 0) throw new Error(`${race.cars[car]!.driver} is not running after lap ${fromLap}.`);
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
          <StintLane laps={race.total_laps} name={describePlan(segments)} stints={planLane(race, car, fromLap, r.strategy)} />
          <span className="plan-text">{describePlan(segments)}</span>
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
          <h2>Search</h2>
        </header>
        <div className="body">
          <Segmented
            label="Optimise for"
            value={kind}
            onChange={setKind}
            options={[
              { value: "position", label: "Position" },
              { value: "podium", label: "Podium" },
              { value: "points", label: "Points" },
              { value: "beat", label: "Beat a rival" },
            ]}
          />
          {kind === "beat" && <Pick label="Rival" value={rival} options={rivals} onChange={setRival} />}
          <LapField label="Decide after" laps={laps} value={fromLap} total={race.total_laps} onChange={onLap} />
          <p className="sub">
            0 to {settings.max_stops} stops in all, stints of {settings.min_stint_laps} laps or more, on
            compounds run for {settings.min_race_clean_laps} clean laps or more in this race.
          </p>
          <button type="button" className="primary" onClick={go} disabled={run.status === "running"}>
            {run.status === "running" ? "Searching" : "Search"}
          </button>
          {run.status !== "idle" && run.status !== "error" && (
            <p className="sub num">{run.races.toLocaleString("en")} races simulated</p>
          )}
        </div>
      </section>

      <section className="panel" aria-live="polite">
        <header>
          <h2>Best plans from lap {fromLap}</h2>
          {run.status === "done" && (
            <span className="sub num">
              {run.result.tried.toLocaleString("en")} plans tried; finalists raced {settings.max_runs.toLocaleString("en")} times on the same draws
            </span>
          )}
        </header>
        {run.status === "idle" && (
          <Empty title="No search yet">
            Every legal plan races a few times; the better ones race again on more draws until{" "}
            {settings.keep} are left, then they race the actual plan.
          </Empty>
        )}
        {run.status === "running" && <Skeleton rows={settings.keep + 1} label="Searching" />}
        {run.status === "error" && <Failure message={run.message} />}
        {run.status === "done" && (
          <div className="scroll">
            <table className="grid ranked">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Plan</th>
                  <th className="r">Stops</th>
                  <th className="r">Expected position</th>
                  <th className="r">Win</th>
                  <th className="r">Podium</th>
                  <th className="r">Points</th>
                  {run.result.objective.kind === "beat" && (
                    <th className="r">Beat {race.cars[(run.result.objective as { rival: number }).rival]!.driver}</th>
                  )}
                  <th className="r">Places vs actual</th>
                  <th>P1 to P5, then the rest</th>
                </tr>
              </thead>
              <tbody>
                {run.result.ranked.map((r, k) => row(r, String(k + 1), false))}
                {row(run.result.actual, "Actual", true)}
              </tbody>
            </table>
          </div>
        )}
        <Assumptions fromLap={fromLap} events="sampled" />
      </section>
    </div>
  );
}
