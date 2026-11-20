import { useEffect, useState } from "react";
import type { Manifest } from "../contract/manifest";
import { loadCalibration, loadManifest, loadRace, loadReplay, loadSim } from "./bundle";
import { Debrief } from "./Debrief";
import { useLoad } from "./hooks";
import { ModelCard } from "./ModelCard";
import { Optimise } from "./Optimise";
import { decisionLaps } from "./plan";
import { RaceView } from "./RaceView";
import { ReplayView } from "./Replay";
import { Empty, Failure, Skeleton } from "./States";
import { TelemetryView } from "./Telemetry";
import { Undercut } from "./Undercut";
import { raceKey, readView, writeView, type Tab, type View } from "./url";
import { WhatIf } from "./WhatIf";

const TAB_NAMES: Record<Tab, string> = {
  race: "Race",
  replay: "Replay",
  telemetry: "Telemetry",
  whatif: "What if",
  optimise: "Optimise",
  undercut: "Undercut",
  debrief: "Debrief",
  model: "Model card",
};

const STRATEGY_TABS: readonly Tab[] = ["whatif", "optimise", "undercut", "debrief"];

const MANIFEST = "manifest.json";

function useView(): [View, (change: Partial<View>) => void] {
  const [view, setView] = useState(() => readView(location.search));
  useEffect(() => {
    const back = () => setView(readView(location.search));
    addEventListener("popstate", back);
    return () => removeEventListener("popstate", back);
  }, []);
  const change = (next: Partial<View>) => {
    const merged = { ...view, ...next };
    history.pushState(null, "", writeView(merged));
    setView(merged);
  };
  return [view, change];
}

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? "dark");
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      // Storage can be blocked; the choice then lasts until reload.
    }
    setTheme(next);
  };
  return [theme, toggle];
}

export function App() {
  const manifest = useLoad(MANIFEST, loadManifest);
  return (
    <>
      {manifest.status === "ready" ? (
        <Lab manifest={manifest.value} />
      ) : (
        <>
          <Bar />
          <main className="main">
            {manifest.status === "error" ? <Failure message={manifest.message} /> : <Skeleton rows={12} label="Loading races" />}
          </main>
        </>
      )}
      <footer className="footer">
        Unofficial project, not affiliated with Formula 1. Data from OpenF1 and Jolpica.
      </footer>
    </>
  );
}

function Bar({ children }: { children?: React.ReactNode }) {
  const [theme, toggle] = useTheme();
  return (
    <header className="bar">
      <span className="wordmark">Pit Wall</span>
      {children}
      <button type="button" className="quiet theme" onClick={toggle}>
        {theme === "dark" ? "Light" : "Dark"}
      </button>
    </header>
  );
}

function Lab({ manifest }: { manifest: Manifest }) {
  const [view, change] = useView();
  const simulated = manifest.races.filter((r) => r.sim_path);
  const entry =
    manifest.races.find((r) => raceKey(r) === view.race) ?? simulated.at(-1) ?? manifest.races.at(-1);
  const race = useLoad(entry?.path ?? null, loadRace);
  const sim = useLoad(entry?.sim_path ?? null, loadSim);
  const replay = useLoad(entry?.replay_path ?? null, loadReplay);
  const calibration = useLoad(manifest.calibration_path, loadCalibration);
  const drivers = race.status === "ready" ? race.value.drivers.map((d) => d.driver) : [];
  const driver = view.driver && drivers.includes(view.driver) ? view.driver : (drivers[0] ?? null);
  const seasons = [...new Set(manifest.races.map((r) => r.season))];

  if (!entry) {
    return (
      <>
        <Bar />
        <main className="main">
          <Empty title="No races exported yet">Run the weekend pipeline to publish a bundle.</Empty>
        </main>
      </>
    );
  }

  const simReady = sim.status === "ready" ? sim.value : null;
  const car = simReady && driver ? simReady.cars.findIndex((c) => c.driver === driver) : -1;
  const laps = simReady && car >= 0 ? decisionLaps(simReady, car) : [];
  const firstStop = simReady && car >= 0 ? simReady.cars[car]!.stops[0]?.lap : undefined;
  const fallback = firstStop && laps.includes(firstStop - 1) ? firstStop - 1 : (laps[0] ?? 1);
  const fromLap = view.lap !== null && laps.includes(view.lap) ? view.lap : fallback;
  const tool = { settings: manifest.strategy, laps, fromLap, onLap: (lap: number) => change({ lap }) };

  const strategy = () => {
    if (sim.status === "none") {
      return (
        <Empty title="No simulation for this race">
          The race view works for every race; the strategy tools need a simulation bundle, which this race
          does not have yet.
        </Empty>
      );
    }
    if (sim.status === "loading") return <Skeleton rows={10} label="Loading the simulation" />;
    if (sim.status === "error") return <Failure message={sim.message} />;
    if (car < 0 || laps.length === 0) {
      return <Empty title={`No race state for ${driver ?? "this driver"}`}>Pick a driver who started the race.</Empty>;
    }
    const key = `${entry.path}:${driver}`;
    if (view.tab === "debrief") return <Debrief key={entry.path} race={sim.value} car={car} settings={manifest.strategy} />;
    if (view.tab === "whatif") return <WhatIf key={key} race={sim.value} car={car} {...tool} />;
    if (view.tab === "optimise") return <Optimise key={key} race={sim.value} car={car} {...tool} />;
    return <Undercut key={key} race={sim.value} car={car} {...tool} />;
  };

  const analytics = () => {
    if (replay.status === "none") {
      return (
        <Empty title="No replay for this race yet">
          Replay and telemetry need the race&rsquo;s fastest laps, which the pipeline has not fetched for this race.
        </Empty>
      );
    }
    if (replay.status === "loading") return <Skeleton rows={14} label="Loading the replay" />;
    if (replay.status === "error") return <Failure message={replay.message} />;
    if (race.status !== "ready") return <Skeleton rows={14} label="Loading the race" />;
    const onDriver = (d: string) => change({ driver: d, lap: null });
    if (view.tab === "replay") {
      return <ReplayView key={entry.path} race={race.value} replay={replay.value} driver={driver} onDriver={onDriver} />;
    }
    return (
      <TelemetryView
        replay={replay.value}
        driver={driver}
        vs={view.vs}
        onDriver={onDriver}
        onVs={(vs) => change({ vs })}
      />
    );
  };

  return (
    <>
      <Bar>
        <label className="visually-hidden" htmlFor="race">
          Race
        </label>
        <select
          id="race"
          className="input"
          value={raceKey(entry)}
          onChange={(e) => change({ race: e.target.value, lap: null })}
        >
          {seasons.map((season) => (
            <optgroup key={season} label={String(season)}>
              {manifest.races
                .filter((r) => r.season === season)
                .map((r) => (
                  <option key={r.path} value={raceKey(r)}>
                    {r.name} {r.season}
                    {r.sim_path ? "" : " (race view only)"}
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
        <label className="visually-hidden" htmlFor="driver">
          Driver
        </label>
        <select
          id="driver"
          className="input"
          value={driver ?? ""}
          disabled={drivers.length === 0}
          onChange={(e) => change({ driver: e.target.value, lap: null })}
        >
          {drivers.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <nav aria-label="Tools">
          {(Object.keys(TAB_NAMES) as Tab[]).map((tab) => (
            <a
              key={tab}
              href={writeView({ ...view, tab })}
              aria-current={view.tab === tab ? "page" : undefined}
              onClick={(e) => {
                e.preventDefault();
                change({ tab });
              }}
            >
              {TAB_NAMES[tab]}
            </a>
          ))}
        </nav>
      </Bar>
      <main className="main">
        {view.tab === "race" &&
          (race.status === "ready" ? (
            <RaceView race={race.value} sim={simReady} driver={driver} onDriver={(d) => change({ driver: d, lap: null })} />
          ) : race.status === "error" ? (
            <Failure message={race.message} />
          ) : (
            <Skeleton rows={20} label="Loading the race" />
          ))}
        {(view.tab === "replay" || view.tab === "telemetry") && analytics()}
        {STRATEGY_TABS.includes(view.tab) && strategy()}
        {view.tab === "model" && (
          <ModelCard manifest={manifest} entry={entry} sim={simReady} calibration={calibration} />
        )}
      </main>
    </>
  );
}
