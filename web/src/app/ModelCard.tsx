import type { Calibration } from "../contract/calibration";
import type { Manifest, RaceEntry } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import { percent } from "./Controls";
import type { Loaded } from "./hooks";
import { useT } from "./i18n";
import { Empty, Failure, Skeleton } from "./States";

const README = "https://github.com/tomeelow/pit-wall#how-much-to-trust-it";

/** What produced the numbers on the other screens, and how well they have held up. */
export function ModelCard({
  manifest,
  entry,
  sim,
  calibration,
}: {
  manifest: Manifest;
  entry: RaceEntry;
  sim: SimRace | null;
  calibration: Loaded<Calibration>;
}) {
  const { model: tx } = useT();
  const fieldPace = sim?.cars.filter((c) => c.pace_from === "field").map((c) => c.driver) ?? [];
  return (
    <div className="split">
      <section className="panel">
        <header>
          <h2>{tx.title}</h2>
          <span className="sub">
            {entry.name} {entry.season}
          </span>
        </header>
        <dl className="facts">
          <dt>{tx.built}</dt>
          <dd className="num">{manifest.generated_at.replace("T", " ").slice(0, 16)} UTC</dd>
          <dt>{tx.code}</dt>
          <dd className="num">{manifest.git_sha}</dd>
          <dt>{tx.dataset}</dt>
          <dd className="num">{entry.dataset_version}</dd>
          <dt>{tx.schema}</dt>
          <dd className="num">{manifest.schema_version}</dd>
          {sim ? (
            <>
              <dt>{tx.era}</dt>
              <dd>{sim.era}</dd>
              <dt>{tx.draws}</dt>
              <dd className="num">{tx.drawsValue(sim.draws)}</dd>
              <dt>{tx.pace}</dt>
              <dd>
                {tx.paceWhole}
                {fieldPace.length > 0 && tx.fieldPace(fieldPace.join(", "))}
              </dd>
              <dt>{tx.rules}</dt>
              <dd>
                {tx.minCompounds(sim.rules.min_dry_compounds)}
                {sim.rules.min_stops > 0 && tx.minStops(sim.rules.min_stops)}
                {sim.rules.max_stint_laps !== null && tx.maxStint(sim.rules.max_stint_laps)}
              </dd>
            </>
          ) : (
            <>
              <dt>{tx.simulation}</dt>
              <dd>{tx.noSim}</dd>
            </>
          )}
        </dl>
      </section>

      <section className="panel">
        <header>
          <h2>{tx.calibration}</h2>
        </header>
        {calibration.status === "loading" && <Skeleton rows={8} label={tx.loadingCalibration} />}
        {calibration.status === "error" && <Failure message={calibration.message} />}
        {calibration.status === "none" && <Empty title={tx.noCalibration}>{tx.noCalibrationBody}</Empty>}
        {calibration.status === "ready" && <Scores calibration={calibration.value} era={sim?.era ?? null} />}
      </section>
    </div>
  );
}

function Scores({ calibration, era }: { calibration: Calibration; era: string | null }) {
  const t = useT();
  const { model: tx } = t;
  const { gate, segments, pit_histogram } = calibration;
  const top = Math.max(...pit_histogram);
  return (
    <div className="body">
      <p className={gate.passed ? "rules rules-ok" : "rules rules-break"}>
        {gate.passed ? tx.gatePassed : tx.gateFailed(gate.reasons.join("; "))}{" "}
        {tx.runs(calibration.runs, calibration.dataset_version)}
      </p>
      <div className="scroll">
        <table className="grid scores">
          <thead>
            <tr>
              <th>{tx.segment}</th>
              <th className="r">{tx.races}</th>
              <th className="r">{tx.carStarts}</th>
              <th className="r">{tx.inside50}</th>
              <th className="r">{tx.inside80}</th>
              <th className="r">{tx.logScore}</th>
              <th className="r">{tx.asStarted}</th>
            </tr>
          </thead>
          <tbody>
            {segments.map((s) => (
              <tr key={s.segment} aria-selected={s.segment === "all" || s.segment === `era: ${era}`}>
                <td>{tx.segmentName(s.segment)}</td>
                <td className="r num">{s.races}</td>
                <td className="r num">{t.n(s.entries)}</td>
                <td className="r num">{percent(s.coverage_50)}</td>
                <td className="r num">{percent(s.coverage_80)}</td>
                <td className="r num">{s.log_score.toFixed(2)}</td>
                <td className="r num">{s.log_score_start_order.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="sub">{tx.note}</p>
      <h3>{tx.pit}</h3>
      <svg className="pit" viewBox={`0 0 ${pit_histogram.length * 20} 60`} role="img" aria-label={tx.pitLabel}>
        {pit_histogram.map((share, k) => (
          <rect key={k} className="bar-b" x={k * 20 + 1} y={60 - (share / top) * 56} width={18} height={(share / top) * 56} />
        ))}
      </svg>
      <p className="sub">
        {tx.flat}
        <a href={README}>{tx.fails}</a>.
      </p>
    </div>
  );
}
