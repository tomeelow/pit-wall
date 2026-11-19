import type { Race, Stint } from "../contract/race";

const LABEL_WIDTH = 44;
const PLOT_WIDTH = 900;
const ROW_HEIGHT = 20;
const BAR_HEIGHT = 14;
const AXIS_HEIGHT = 24;
const TICK_EVERY = 10;

function describe(driver: string, stint: Stint): string {
  const age = stint.tyre_age_at_start ? `, ${stint.tyre_age_at_start} laps old at start` : ", new";
  return `${driver} · ${stint.compound} · laps ${stint.start_lap}–${stint.end_lap}${age}`;
}

export function StintChart({ race }: { race: Race }) {
  const lapWidth = PLOT_WIDTH / race.total_laps;
  const height = race.drivers.length * ROW_HEIGHT + AXIS_HEIGHT;
  const ticks = Array.from(
    { length: Math.floor(race.total_laps / TICK_EVERY) + 1 },
    (_, i) => i * TICK_EVERY,
  );

  return (
    <svg
      className="stint-chart"
      viewBox={`0 0 ${LABEL_WIDTH + PLOT_WIDTH} ${height}`}
      role="img"
      aria-label={`Tyre strategies, ${race.name} ${race.season}`}
    >
      {race.drivers.map((driver, row) => {
        const y = row * ROW_HEIGHT;
        return (
          <g key={driver.driver} transform={`translate(0 ${y})`}>
            <text className="driver" x={LABEL_WIDTH - 8} y={ROW_HEIGHT / 2} dy="0.35em">
              {driver.driver}
            </text>
            {driver.stints.map((stint) => (
              <rect
                key={stint.stint}
                className={`stint compound-${stint.compound.toLowerCase()}`}
                x={LABEL_WIDTH + (stint.start_lap - 1) * lapWidth}
                y={(ROW_HEIGHT - BAR_HEIGHT) / 2}
                width={(stint.end_lap - stint.start_lap + 1) * lapWidth - 1}
                height={BAR_HEIGHT}
                rx={3}
              >
                <title>{describe(driver.driver, stint)}</title>
              </rect>
            ))}
          </g>
        );
      })}
      <g transform={`translate(${LABEL_WIDTH} ${race.drivers.length * ROW_HEIGHT})`}>
        {ticks.map((lap) => (
          <text key={lap} className="tick" x={lap * lapWidth} y={AXIS_HEIGHT / 2} dy="0.35em">
            {lap}
          </text>
        ))}
      </g>
    </svg>
  );
}
