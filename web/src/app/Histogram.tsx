import type { Distribution } from "../sim/index.ts";

interface Series {
  name: string;
  tone: "a" | "b";
  value: Distribution;
}

const WIDTH = 640;
const HEIGHT = 200;
const AXIS = 22;
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

/** Where the car finished across the runs, one bar per place, actual and alternative side by side. */
export function Histogram({ series }: { series: Series[] }) {
  const first = series[0]!.value;
  const showDsq = series.some((s) => s.value.disqualified > 0);
  const labels = [...first.places.map((_, k) => `P${k + 1}`), "Ret", ...(showDsq ? ["DSQ"] : [])];
  const shares = series.map(({ value }) =>
    [...value.places, value.notClassified, ...(showDsq ? [value.disqualified] : [])].map(
      (n) => n / value.runs,
    ),
  );
  const top = Math.max(...shares.flat(), 0.01);
  const slot = WIDTH / labels.length;
  const bar = (slot * 0.8) / series.length;
  const plot = HEIGHT - AXIS;
  const summary = series
    .map((s, j) => {
      const row = shares[j]!;
      return `${s.name}: most often ${labels[row.indexOf(Math.max(...row))]}`;
    })
    .join("; ");

  return (
    <svg className="histogram" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={summary}>
      <line className="baseline" x1={0} x2={WIDTH} y1={plot} y2={plot} />
      {labels.map((label, k) => (
        <g key={label}>
          {series.map((s, j) => {
            const share = shares[j]![k]!;
            const h = (share / top) * (plot - 8);
            return (
              <rect
                key={s.name}
                className={`bar-${s.tone}`}
                x={k * slot + slot * 0.1 + j * bar}
                y={plot - h}
                width={bar - 1}
                height={h}
              >
                <title>{`${label}, ${s.name.toLowerCase()}: ${pct(share)}`}</title>
              </rect>
            );
          })}
          <text className="tick" x={k * slot + slot / 2} y={HEIGHT - 6}>
            {label}
          </text>
        </g>
      ))}
    </svg>
  );
}

/** Places 1 to 5 and the rest, for a row of a table. */
export function Spark({ value, tone }: { value: Distribution; tone: "a" | "b" }) {
  const top5 = value.places.slice(0, 5);
  const rest = value.runs - top5.reduce((a, b) => a + b, 0);
  const shares = [...top5, rest].map((n) => n / value.runs);
  return (
    <svg className="spark" viewBox="0 0 60 20" role="img" aria-label={`P1 ${pct(shares[0]!)}`}>
      {shares.map((share, k) => (
        <rect key={k} className={`bar-${tone}`} x={k * 10} y={20 - share * 20} width={8} height={share * 20} />
      ))}
    </svg>
  );
}
