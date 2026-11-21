import type { Calibration } from "../contract/calibration";
import type { Manifest, RaceEntry } from "../contract/manifest";
import type { SimRace } from "../contract/sim";
import { percent } from "./Controls";
import type { Loaded } from "./hooks";
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
  const fieldPace = sim?.cars.filter((c) => c.pace_from === "field").map((c) => c.driver) ?? [];
  return (
    <div className="split">
      <section className="panel">
        <header>
          <h2>Model card</h2>
          <span className="sub">
            {entry.name} {entry.season}
          </span>
        </header>
        <dl className="facts">
          <dt>Bundle built</dt>
          <dd className="num">{manifest.generated_at.replace("T", " ").slice(0, 16)} UTC</dd>
          <dt>Code version</dt>
          <dd className="num">{manifest.git_sha}</dd>
          <dt>Race dataset</dt>
          <dd className="num">{entry.dataset_version}</dd>
          <dt>Schema</dt>
          <dd className="num">{manifest.schema_version}</dd>
          {sim ? (
            <>
              <dt>Era</dt>
              <dd>{sim.era}</dd>
              <dt>Posterior draws</dt>
              <dd className="num">{sim.draws}, one per simulated race</dd>
              <dt>Pace</dt>
              <dd>
                Fitted on the whole race.
                {fieldPace.length > 0 && ` Too few clean laps for ${fieldPace.join(", ")}: field pace instead.`}
              </dd>
              <dt>Rules</dt>
              <dd>
                {sim.rules.min_dry_compounds} dry compounds at least
                {sim.rules.min_stops > 0 && `, ${sim.rules.min_stops} stops at least`}
                {sim.rules.max_stint_laps !== null && `, stints of ${sim.rules.max_stint_laps} laps at most`}
              </dd>
            </>
          ) : (
            <>
              <dt>Simulation</dt>
              <dd>No simulation bundle for this race.</dd>
            </>
          )}
        </dl>
      </section>

      <section className="panel">
        <header>
          <h2>Calibration on held-out races</h2>
        </header>
        {calibration.status === "loading" && <Skeleton rows={8} label="Loading calibration" />}
        {calibration.status === "error" && <Failure message={calibration.message} />}
        {calibration.status === "none" && <Empty title="No calibration published">This bundle has none.</Empty>}
        {calibration.status === "ready" && <Scores calibration={calibration.value} era={sim?.era ?? null} />}
      </section>
    </div>
  );
}

function Scores({ calibration, era }: { calibration: Calibration; era: string | null }) {
  const { gate, segments, pit_histogram } = calibration;
  const top = Math.max(...pit_histogram);
  return (
    <div className="body">
      <p className={gate.passed ? "rules rules-ok" : "rules rules-break"}>
        {gate.passed ? "The publish gate passed." : `The publish gate failed: ${gate.reasons.join("; ")}.`}{" "}
        {calibration.runs.toLocaleString("en")} races per car-start, dataset {calibration.dataset_version}.
      </p>
      <div className="scroll">
        <table className="grid scores">
          <thead>
            <tr>
              <th>Segment</th>
              <th className="r">Races</th>
              <th className="r">Car-starts</th>
              <th className="r">Inside 50% band</th>
              <th className="r">Inside 80% band</th>
              <th className="r">Log score</th>
              <th className="r">Finish as started</th>
            </tr>
          </thead>
          <tbody>
            {segments.map((s) => (
              <tr key={s.segment} aria-selected={s.segment === "all" || s.segment === `era: ${era}`}>
                <td>{s.segment}</td>
                <td className="r num">{s.races}</td>
                <td className="r num">{s.entries.toLocaleString("en")}</td>
                <td className="r num">{percent(s.coverage_50)}</td>
                <td className="r num">{percent(s.coverage_80)}</td>
                <td className="r num">{s.log_score.toFixed(2)}</td>
                <td className="r num">{s.log_score_start_order.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="sub">
        Calibrated means 50% and 80% of real finishes fall inside the 50% and 80% bands. A higher log score
        is better; the last column is the baseline that every car finishes where it started. Per-track
        scores are not exported yet: the era and passing rows are the nearest.
      </p>
      <h3>Where real finishes fell in the simulated spread</h3>
      <svg className="pit" viewBox={`0 0 ${pit_histogram.length * 20} 60`} role="img" aria-label="PIT histogram: flat when calibrated">
        {pit_histogram.map((share, k) => (
          <rect key={k} className="bar-b" x={k * 20 + 1} y={60 - (share / top) * 56} width={18} height={(share / top) * 56} />
        ))}
      </svg>
      <p className="sub">
        Flat is calibrated; a U shape is overconfident. <a href={README}>Where the simulator fails</a>.
      </p>
    </div>
  );
}
