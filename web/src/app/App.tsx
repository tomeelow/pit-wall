import { useEffect, useState } from "react";
import type { Manifest } from "../contract/manifest";
import type { Race } from "../contract/race";
import { loadManifest, loadRace } from "./bundle";
import { StintChart } from "./StintChart";

const COMPOUND_LEGEND = ["soft", "medium", "hard", "intermediate", "wet"] as const;

export function App() {
  const [manifest, setManifest] = useState<Manifest>();
  const [racePath, setRacePath] = useState<string>();
  const [race, setRace] = useState<Race>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    loadManifest()
      .then((loaded) => {
        setManifest(loaded);
        setRacePath(loaded.races.at(-1)?.path);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!racePath) return;
    let current = true;
    loadRace(racePath)
      .then((loaded) => current && setRace(loaded))
      .catch((e: unknown) => current && setError(String(e)));
    return () => {
      current = false;
    };
  }, [racePath]);

  return (
    <main>
      <header>
        <h1>Pit Wall</h1>
        <p className="tagline">Race strategy lab</p>
      </header>

      {error && <p className="error">{error}</p>}
      {!manifest && !error && <p className="muted">Loading races…</p>}
      {manifest?.races.length === 0 && <p className="muted">No races exported yet.</p>}

      {manifest && manifest.races.length > 0 && (
        <label className="race-picker">
          Race{" "}
          <select value={racePath} onChange={(e) => setRacePath(e.target.value)}>
            {manifest.races.map((entry) => (
              <option key={entry.path} value={entry.path}>
                {entry.season} · R{entry.round} · {entry.name}
              </option>
            ))}
          </select>
        </label>
      )}

      {race && (
        <section>
          <h2>
            Tyre strategies — {race.name} {race.season}
          </h2>
          <ul className="legend">
            {COMPOUND_LEGEND.map((compound) => (
              <li key={compound}>
                <span className={`swatch compound-${compound}`} />
                {compound}
              </li>
            ))}
          </ul>
          <div className="chart-scroll">
            <StintChart race={race} />
          </div>
        </section>
      )}

      <footer className="muted">
        {manifest && (
          <p>
            Bundle {manifest.git_sha} · schema {manifest.schema_version}
            {race && <> · dataset {race.dataset_version}</>}
          </p>
        )}
        <p>Unofficial project, not affiliated with Formula 1. Data: OpenF1.</p>
      </footer>
    </main>
  );
}
