import type { ReactNode } from "react";
import type { TrackOutline } from "../contract/replay";

/** Map units: OpenF1 location is about 0.1 m, so a circuit spans some 10 000 units. */
const PAD = 0.06;

/** The circuit outline with y pointing up; children draw in the same units (y negated). */
export function TrackMap({
  track,
  label,
  children,
  outline = true,
}: {
  track: TrackOutline;
  label: string;
  children?: ReactNode;
  outline?: boolean;
}) {
  const xs = track.x;
  const ys = track.y.map((y) => -y);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = PAD * Math.max(maxX - minX, maxY - minY);
  const box = [minX - pad, minY - pad, maxX - minX + 2 * pad, maxY - minY + 2 * pad];
  const points = xs.map((x, k) => `${x},${ys[k]}`).join(" ");
  return (
    <svg className="map" viewBox={box.join(" ")} role="img" aria-label={label}>
      {outline && <polygon className="map-track" points={points} />}
      {children}
    </svg>
  );
}

/** Marker size in map units: the same share of the circuit at any zoom. */
export const markerSize = (track: TrackOutline) =>
  0.012 * Math.max(Math.max(...track.x) - Math.min(...track.x), Math.max(...track.y) - Math.min(...track.y));
