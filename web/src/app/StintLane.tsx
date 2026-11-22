import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import type { Tyre } from "./compounds";
import { useT } from "./i18n";

export interface LaneStint {
  from: number;
  to: number;
  tyre: Tyre;
  label: string;
  past?: boolean; // run before the decision lap: fixed
}

interface Props {
  stints: readonly LaneStint[];
  laps: number;
  name: string; // what the lane shows, for screen readers
  tall?: boolean;
  /** Editable stops: index k sits at the end of stint k + stopOffset. */
  stops?: { lap: number; min: number; max: number }[];
  stopOffset?: number;
  onMoveStop?: (index: number, lap: number) => void;
}

const at = (lap: number, laps: number) => `${(lap / laps) * 100}%`;

/** One car's race as stints across the laps; with onMoveStop, its planned pit laps can be dragged. */
export function StintLane({ stints, laps, name, tall, stops, onMoveStop }: Props) {
  const t = useT();
  const lane = useRef<HTMLDivElement>(null);
  const lapAt = (clientX: number) => {
    const box = lane.current!.getBoundingClientRect();
    return Math.round(((clientX - box.left) / box.width) * laps);
  };
  const clamp = (k: number, lap: number) => {
    const stop = stops![k]!;
    return Math.min(stop.max, Math.max(stop.min, lap));
  };
  const drag = (k: number) => (event: PointerEvent<HTMLButtonElement>) => {
    if (event.buttons !== 1) return;
    const lap = clamp(k, lapAt(event.clientX));
    if (lap !== stops![k]!.lap) onMoveStop!(k, lap);
  };
  const nudge = (k: number) => (event: KeyboardEvent<HTMLButtonElement>) => {
    const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    onMoveStop!(k, clamp(k, stops![k]!.lap + step));
  };

  return (
    <div ref={lane} className={tall ? "lane lane-tall" : "lane"} role="img" aria-label={name}>
      {stints.map((s) => (
        <div
          key={s.from}
          className={`stint tyre-${s.tyre}${s.past ? " stint-past" : ""}`}
          style={{ left: at(s.from - 1, laps), width: at(s.to - s.from + 1, laps) }}
          title={t.stintLaps(s.label, s.from, s.to)}
        >
          {s.to - s.from >= 5 && <span>{s.label.split(" ")[0]}</span>}
        </div>
      ))}
      {onMoveStop &&
        stops?.map((stop, k) => (
          <button
            key={k}
            type="button"
            className="handle"
            style={{ left: at(stop.lap, laps) }}
            aria-label={t.handle(k + 1, stop.lap)}
            onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)}
            onPointerMove={drag(k)}
            onKeyDown={nudge(k)}
          />
        ))}
    </div>
  );
}

export function LapAxis({ laps }: { laps: number }) {
  const ticks = [1, ...Array.from({ length: Math.floor(laps / 10) }, (_, i) => (i + 1) * 10)];
  if (laps - ticks.at(-1)! >= 4) ticks.push(laps);
  return (
    <div className="axis" aria-hidden="true">
      {ticks.map((lap) => (
        <span key={lap} style={{ left: at(lap - 0.5, laps) }}>
          {lap}
        </span>
      ))}
    </div>
  );
}
