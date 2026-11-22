import { useEffect, useState } from "react";
import type { Race } from "../contract/race";
import type { Replay } from "../contract/replay";
import { stintTyre } from "./compounds";
import { Segmented } from "./Controls";
import { useT } from "./i18n";
import {
  lapStart,
  lastLine,
  neutralisationOn,
  pitting,
  pointAt,
  standings,
  stintOn,
} from "./timing";
import { markerSize, TrackMap } from "./TrackMap";

const SPEEDS = [
  { value: "10", label: "10×" },
  { value: "30", label: "30×" },
  { value: "60", label: "60×" },
] as const;
type Speed = (typeof SPEEDS)[number]["value"];

const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Race time advancing while playing: continuous, or a lap a second when motion is reduced. */
function usePlayback(replay: Replay, end: number): [number, (t: number) => void, boolean, () => void, Speed, (s: Speed) => void] {
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>("30");
  const running = playing && t < end;
  useEffect(() => {
    if (!running) return;
    if (reducedMotion()) {
      const timer = setInterval(() => {
        setT((now) => {
          const lap = standings(replay, now)[0]?.progress.lap ?? 1;
          return Math.min(lapStart(replay, lap + 1), end);
        });
      }, 1000);
      return () => clearInterval(timer);
    }
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const step = ((now - last) / 1000) * Number(speed);
      last = now;
      setT((current) => Math.min(current + step, end));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [running, speed, replay, end]);
  const toggle = () => {
    if (!running && t >= end) setT(0);
    setPlaying(!running);
  };
  return [t, setT, running, toggle, speed, setSpeed];
}

export function ReplayView({
  race,
  replay,
  driver,
  onDriver,
}: {
  race: Race;
  replay: Replay;
  driver: string | null;
  onDriver: (code: string) => void;
}) {
  const tr = useT();
  const { replay: tx } = tr;
  const end = lastLine(replay);
  const [t, setT, playing, toggle, speed, setSpeed] = usePlayback(replay, end);
  const order = standings(replay, t);
  const lap = Math.min(order[0]?.progress.lap ?? 1, race.total_laps);
  const period = neutralisationOn(replay, lap);
  const stints = new Map(race.drivers.map((d) => [d.driver, d.stints]));
  const status = new Map(race.drivers.map((d) => [d.driver, d.status]));
  const size = markerSize(replay.track);
  const pits = (stints.get(driver ?? "") ?? []).slice(0, -1).map((s) => s.end_lap);
  const at = (l: number) => `${((l - 1) / race.total_laps) * 100}%`;

  return (
    <div className="split split-wide">
      <section className="panel">
        <header>
          <h2>
            {tr.lap} <span className="num">{lap}</span> {tr.of} <span className="num">{race.total_laps}</span>
          </h2>
          <span className={`sub${period ? " flagged" : ""}`}>
            {period ? (period.kind === "RED" ? tx.red : period.kind === "SC" ? tx.sc : tx.vsc) : tx.green}
          </span>
        </header>
        <TrackMap track={replay.track} label={tx.map(lap)}>
          {[...order].reverse().map(({ driver: code, progress }) => {
            if (progress.finished && status.get(code) !== "Finished") return null;
            const p = pointAt(replay.track, progress.finished ? 0 : progress.fraction);
            const tyre = stintOn(stints.get(code) ?? [], progress.lap);
            const mine = code === driver;
            return (
              <g key={code} className={mine ? "car car-mine" : "car"} transform={`translate(${p.x} ${-p.y})`}>
                <circle r={mine ? size * 1.4 : size} className={`fill-${tyre ? stintTyre(tyre) : "unknown"}`} />
                {mine && (
                  <text x={size * 2.2} y={size * 0.8} style={{ fontSize: size * 2.6 }}>
                    {code}
                  </text>
                )}
                <title>{code}</title>
              </g>
            );
          })}
        </TrackMap>
        <div className="body timeline">
          <div className="laps-strip" aria-hidden="true">
            {replay.neutralisations.map((n) => (
              <span
                key={`${n.kind}${n.start_lap}`}
                className={`band band-${n.kind.toLowerCase()}`}
                style={{ left: at(n.start_lap), width: `${((n.end_lap - n.start_lap + 1) / race.total_laps) * 100}%` }}
              >
                {n.kind === "RED" ? tx.redBand : n.kind}
              </span>
            ))}
            {pits.map((p) => (
              <span key={p} className="pit-tick" style={{ left: at(p + 1) }} />
            ))}
            <span className="now" style={{ left: `${(t / end) * 100}%` }} />
          </div>
          <label className="visually-hidden" htmlFor="race-time">
            {tx.time}
          </label>
          <input
            id="race-time"
            className="scrubber"
            type="range"
            min={0}
            max={end}
            step={0.5}
            value={t}
            aria-valuetext={tr.lapOf(lap, race.total_laps)}
            onChange={(e) => setT(Number(e.target.value))}
          />
          <div className="row">
            <button type="button" className="quiet" onClick={toggle}>
              {playing ? tx.pause : t >= end ? tx.again : tx.play}
            </button>
            <Segmented label={tx.speed} value={speed} onChange={setSpeed} options={SPEEDS} />
          </div>
          <p className="sub">
            {pits.length > 0 && driver && tx.ticks(driver)}
            {tx.line(replay.track.driver, replay.track.lap)}
          </p>
        </div>
      </section>

      <section className="panel">
        <header>
          <h2>{tx.order}</h2>
          <span className="sub">{tx.gapNote}</span>
        </header>
        <table className="grid order">
          <thead>
            <tr>
              <th className="r">{tr.race.pos}</th>
              <th>{tr.race.driver}</th>
              <th className="r">{tx.gap}</th>
              <th>{tx.tyre}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {order.map(({ driver: code, progress, gap }, k) => {
              const own = stints.get(code) ?? [];
              const tyre = stintOn(own, progress.lap);
              const out = progress.finished && status.get(code) !== "Finished";
              return (
                <tr key={code} aria-selected={code === driver}>
                  <td className="r num">{k + 1}</td>
                  <td>
                    <button type="button" className="link" onClick={() => onDriver(code)}>
                      {code}
                    </button>
                  </td>
                  <td className="r num">{out ? tx.out : progress.finished && k > 0 ? "" : tr.gap(gap)}</td>
                  <td>
                    {tyre && (
                      <>
                        <i className={`dot tyre-${stintTyre(tyre)}`} /> {tr.tyre[stintTyre(tyre)]}
                      </>
                    )}
                  </td>
                  <td className="muted">{!out && !progress.finished && pitting(own, progress.lap) ? tx.pit : ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
