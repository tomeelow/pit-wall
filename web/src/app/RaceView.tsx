import type { Race } from "../contract/race";
import type { SimRace } from "../contract/sim";
import { stintTyre, type Tyre } from "./compounds";
import { LapAxis, StintLane } from "./StintLane";

const TYRES: Tyre[] = ["soft", "medium", "hard", "intermediate", "wet"];

function neutralisations(sim: SimRace | null): string | null {
  if (!sim || sim.realised.length === 0) return null;
  return sim.realised
    .map((p) =>
      p.start_lap === p.end_lap
        ? `${p.kind} lap ${p.start_lap}`
        : `${p.kind} laps ${p.start_lap} to ${p.end_lap}`,
    )
    .join(", ");
}

/** Every car's real strategy, the race the counterfactuals start from. */
export function RaceView({
  race,
  sim,
  driver,
  onDriver,
}: {
  race: Race;
  sim: SimRace | null;
  driver: string | null;
  onDriver: (code: string) => void;
}) {
  const used = TYRES.filter((t) => race.drivers.some((d) => d.stints.some((s) => stintTyre(s) === t)));
  const periods = neutralisations(sim);
  return (
    <section className="panel">
      <header>
        <div>
          <h2>
            {race.name} {race.season}, {race.total_laps} laps
          </h2>
          {periods && <p className="sub">{periods}</p>}
        </div>
        <ul className="legend">
          {used.map((t) => (
            <li key={t}>
              <i className={`dot tyre-${t}`} />
              {t}
            </li>
          ))}
        </ul>
      </header>
      <div className="scroll">
        <table className="grid">
          <thead>
            <tr>
              <th className="r">Pos</th>
              <th>Driver</th>
              <th>Team</th>
              <th className="r">Stops</th>
              <th className="lane-head">
                <LapAxis laps={race.total_laps} />
              </th>
            </tr>
          </thead>
          <tbody>
            {race.drivers.map((d) => (
              <tr key={d.driver} aria-selected={d.driver === driver}>
                <td className="r num">{d.position ?? d.status}</td>
                <td>
                  <button type="button" className="link" onClick={() => onDriver(d.driver)}>
                    {d.driver}
                  </button>
                </td>
                <td className="muted">{d.team}</td>
                <td className="r num">{Math.max(d.stints.length - 1, 0)}</td>
                <td className="lane-cell">
                  <StintLane
                    laps={race.total_laps}
                    name={`${d.driver}: ${d.stints.map((s) => `${s.compound.toLowerCase()} laps ${s.start_lap} to ${s.end_lap}`).join(", ")}`}
                    stints={d.stints.map((s) => ({
                      from: s.start_lap,
                      to: s.end_lap,
                      tyre: stintTyre(s),
                      label: s.compound.toLowerCase(),
                    }))}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
