import { useState } from "react";
import type { Replay } from "../contract/replay";
import type { TelemetryLap } from "../contract/telemetry";
import { loadTelemetry } from "./bundle";
import { Pick, signed } from "./Controls";
import { useLoad } from "./hooks";
import { useT } from "./i18n";
import { interpolate } from "./timing";
import { Empty, Failure, Skeleton } from "./States";
import { delta, distanceGrid, lapTime, minisectors, outlinePieces, pointAlong } from "./traces";
import { markerSize, TrackMap } from "./TrackMap";

/** Chart width in viewBox units; the SVG stretches to the panel, strokes stay one pixel. */
const W = 1000;
/** Keeps a line at the top or bottom of a chart from being cut in half. */
const INSET = 2;
const GRID = 600;

type Channel = "speed_kmh" | "throttle" | "gear" | "brake";

function Trace({
  laps,
  channel,
  height,
  min,
  max,
  step = false,
  area = false,
  length,
}: {
  laps: readonly TelemetryLap[];
  channel: Channel;
  height: number;
  min: number;
  max: number;
  step?: boolean;
  area?: boolean;
  length: number;
}) {
  const t = useT();
  const label = t.telemetry.trace(channel, laps.map((l) => l.driver));
  const inset = area ? 0 : INSET;
  const y = (v: number) => height - inset - ((v - min) / (max - min)) * (height - 2 * inset);
  return (
    <svg className="trace" viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" style={{ height }} role="img" aria-label={label}>
      {laps.map((lap, k) => {
        const points = lap.distance_m.flatMap((d, i) => {
          const x = (d / length) * W;
          const here = `${x},${y(lap[channel][i]!)}`;
          return step && i > 0 ? [`${x},${y(lap[channel][i - 1]!)}`, here] : [here];
        });
        const series = k === 0 ? "a" : "b";
        return area ? (
          <polygon key={lap.driver} className={`area area-${series}`} points={[...points, `${W},${height}`, `0,${height}`].join(" ")} />
        ) : (
          <polyline key={lap.driver} className={`line line-${series}`} points={points.join(" ")} />
        );
      })}
    </svg>
  );
}

function DeltaTrace({ values, height, label }: { values: readonly number[]; height: number; label: string }) {
  const reach = Math.max(0.05, ...values.map(Math.abs));
  const y = (v: number) => height / 2 - (v / reach) * (height / 2 - INSET);
  const points = values.map((v, i) => `${(i / (values.length - 1)) * W},${y(v)}`).join(" ");
  return (
    <svg className="trace" viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" style={{ height }} role="img" aria-label={label}>
      <line className="zero" x1={0} x2={W} y1={height / 2} y2={height / 2} />
      <polyline className="line line-delta" points={points} />
    </svg>
  );
}

export function TelemetryView({
  replay,
  driver,
  vs,
  onVs,
  onDriver,
}: {
  replay: Replay;
  driver: string | null;
  vs: string | null;
  onVs: (code: string) => void;
  onDriver: (code: string) => void;
}) {
  const { telemetry: tx } = useT();
  const laps = replay.fastest_laps;
  if (laps.length === 0) return <Empty title={tx.noData}>{tx.noDataBody}</Empty>;
  return <Laps replay={replay} driver={driver} vs={vs} onVs={onVs} onDriver={onDriver} />;
}

function Laps({
  replay,
  driver,
  vs,
  onVs,
  onDriver,
}: {
  replay: Replay;
  driver: string | null;
  vs: string | null;
  onVs: (code: string) => void;
  onDriver: (code: string) => void;
}) {
  const { telemetry: tx } = useT();
  const laps = replay.fastest_laps;
  const a = laps.find((l) => l.driver === driver) ?? laps[0]!;
  const b = laps.find((l) => l.driver === vs && l.driver !== a.driver) ?? laps.find((l) => l.driver !== a.driver);
  const options = laps.map((l) => ({ value: l.driver, label: tx.option(l.driver, l.lap, lapTime(l.lap_time_s)) }));
  const first = useLoad(a.telemetry_path, loadTelemetry);
  const second = useLoad(b?.telemetry_path ?? null, loadTelemetry);

  return (
    <div className="split split-wide">
      <section className="panel">
        <header>
          <h2>{tx.fastest}</h2>
          <span className="sub">{tx.byDistance}</span>
        </header>
        <div className="body pickers">
          <Pick label={tx.driver} value={a.driver} options={options} onChange={onDriver} />
          {b && <Pick label={tx.against} value={b.driver} options={options.filter((o) => o.value !== a.driver)} onChange={onVs} />}
        </div>
        {first.status === "error" || second.status === "error" ? (
          <Failure message={first.status === "error" ? first.message : second.status === "error" ? second.message : ""} />
        ) : first.status === "ready" && second.status === "ready" ? (
          <Compare a={first.value} b={second.value} />
        ) : first.status === "ready" && !b ? (
          <p className="note sub">{tx.onlyOne}</p>
        ) : (
          <Skeleton rows={12} label={tx.loading} />
        )}
      </section>
      {first.status === "ready" && second.status === "ready" && <Sectors a={first.value} b={second.value} replay={replay} />}
    </div>
  );
}

function Compare({ a, b }: { a: TelemetryLap; b: TelemetryLap }) {
  const t = useT();
  const { telemetry: tx } = t;
  const [at, setAt] = useState<number | null>(null);
  const grid = distanceGrid(a, b, GRID);
  const length = grid.at(-1)!;
  const gap = delta(a, b, grid);
  const read = (lap: TelemetryLap, channel: Channel) =>
    Math.round(interpolate(lap.distance_m, lap[channel], at ?? 0));
  const gapAt = at === null ? null : interpolate(grid, gap, at);

  return (
    <>
      <div className="stats">
        <div>
          <span className="figure num">{lapTime(a.lap_time_s)}</span>
          <span className="caption">
            <b className="ink-a">{a.driver}</b>, {tx.lapN(a.lap)}
          </span>
        </div>
        <div>
          <span className="figure num">{lapTime(b.lap_time_s)}</span>
          <span className="caption">
            <b className="ink-b">{b.driver}</b>, {tx.lapN(b.lap)}
          </span>
        </div>
        <div>
          <span className="figure num">{signed(b.lap_time_s - a.lap_time_s, 3)}</span>
          <span className="caption">{tx.versus(b.driver, a.driver)}</span>
        </div>
      </div>
      <div className="readout num" aria-live="off">
        {at === null ? (
          <span className="muted">{tx.point}</span>
        ) : (
          <>
            <span>
              {(at / 1000).toFixed(2)} {t.km}
            </span>
            {[a, b].map((lap, k) => (
              <span key={lap.driver} className={k === 0 ? "ink-a" : "ink-b"}>
                {tx.reading(lap.driver, read(lap, "speed_kmh"), read(lap, "throttle"), read(lap, "gear"), read(lap, "brake") > 0)}
              </span>
            ))}
            <span>{tx.gapReading(b.driver, gapAt! >= 0, Math.abs(gapAt!).toFixed(3))}</span>
          </>
        )}
      </div>
      <div
        className="charts"
        onPointerMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          setAt(Math.min(Math.max((e.clientX - box.left) / box.width, 0), 1) * length);
        }}
        onPointerLeave={() => setAt(null)}
      >
        <h3>{tx.speed}</h3>
        <Trace laps={[a, b]} channel="speed_kmh" height={160} min={50} max={360} length={length} />
        <h3>{tx.throttle}</h3>
        <Trace laps={[a, b]} channel="throttle" height={56} min={0} max={100} length={length} />
        <h3>{tx.brake(a.driver, b.driver)}</h3>
        <Trace laps={[a]} channel="brake" height={14} min={0} max={1} step area length={length} />
        <Trace laps={[b]} channel="brake" height={14} min={0} max={1} step area length={length} />
        <h3>{tx.gear}</h3>
        <Trace laps={[a, b]} channel="gear" height={64} min={1} max={8} step length={length} />
        <h3>{tx.gapTitle(b.driver)}</h3>
        <DeltaTrace values={gap} height={96} label={tx.gapLabel(b.driver, a.driver)} />
        {at !== null && <span className="cursor" style={{ left: `${(at / length) * 100}%` }} />}
      </div>
      <div className="axis num">
        <span style={{ left: "0%" }}>0 {t.km}</span>
        <span style={{ left: "50%" }}>{(length / 2000).toFixed(1)}</span>
        <span style={{ left: "100%" }}>
          {(length / 1000).toFixed(1)} {t.km}
        </span>
      </div>
      <p className="note sub">{tx.note}</p>
    </>
  );
}

function Sectors({ a, b, replay }: { a: TelemetryLap; b: TelemetryLap; replay: Replay }) {
  const t = useT();
  const { telemetry: tx } = t;
  const sectors = minisectors(a, b);
  const pieces = outlinePieces(replay.track, sectors.length);
  const length = sectors.at(-1)!.to_m;
  const won = (k: 0 | 1) => sectors.filter((s) => (k === 0 ? s.gain_s > 0 : s.gain_s < 0));
  const biggest = [...sectors].map((s, k) => ({ ...s, k })).sort((x, y) => Math.abs(y.gain_s) - Math.abs(x.gain_s)).slice(0, 3);
  const size = markerSize(replay.track);
  const start = pointAlong(replay.track, 0);
  return (
    <section className="panel">
      <header>
        <h2>{tx.where}</h2>
        <span className="sub">{tx.minisectors(sectors.length)}</span>
      </header>
      <TrackMap track={replay.track} label={tx.mapLabel(a.driver, b.driver)} outline={false}>
        {pieces.map((points, k) => (
          <polyline key={k} className={`sector sector-${sectors[k]!.gain_s > 0 ? "a" : "b"}`} points={points} />
        ))}
        <circle className="start" cx={start.x} cy={-start.y} r={size} />
      </TrackMap>
      <ul className="legend note">
        {[a, b].map((lap, k) => {
          const mine = won(k as 0 | 1);
          return (
            <li key={lap.driver}>
              <b className={`ink-${k === 0 ? "a" : "b"}`}>{lap.driver}</b>{" "}
              {tx.fasterIn(mine.length, mine.reduce((s, x) => s + Math.abs(x.gain_s), 0).toFixed(3))}
            </li>
          );
        })}
      </ul>
      <table className="grid">
        <caption className="caption">{tx.largest}</caption>
        <thead>
          <tr>
            <th>{tx.minisector}</th>
            <th className="r">{tx.fromKm}</th>
            <th>{tx.faster}</th>
            <th className="r">{tx.by}</th>
          </tr>
        </thead>
        <tbody>
          {biggest.map((s) => (
            <tr key={s.k}>
              <td className="num">{s.k + 1}</td>
              <td className="r num">{(s.from_m / 1000).toFixed(2)}</td>
              <td>{s.gain_s > 0 ? a.driver : b.driver}</td>
              <td className="r num">{Math.abs(s.gain_s).toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note sub">{tx.sectorsNote((length / 1000).toFixed(2))}</p>
    </section>
  );
}
