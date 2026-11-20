import type { RaceEntry } from "../contract/manifest";

export const TABS = [
  "race",
  "replay",
  "telemetry",
  "whatif",
  "optimise",
  "undercut",
  "debrief",
  "model",
] as const;
export type Tab = (typeof TABS)[number];

/** What the screen shows: kept in the query string, so a view can be shared and reloaded. */
export interface View {
  race: string | null; // raceKey of a manifest entry
  driver: string | null; // three-letter code
  tab: Tab;
  lap: number | null; // decision lap for the strategy tools
  vs: string | null; // the driver compared against in telemetry
}

export const raceKey = (entry: RaceEntry) => `${entry.season}-${entry.round}`;

export function readView(search: string): View {
  const params = new URLSearchParams(search);
  const tab = params.get("tab");
  const lap = Number(params.get("lap"));
  return {
    race: params.get("race"),
    driver: params.get("driver"),
    tab: TABS.find((t) => t === tab) ?? "race",
    lap: Number.isInteger(lap) && lap > 0 ? lap : null,
    vs: params.get("vs"),
  };
}

export function writeView(view: View): string {
  const params = new URLSearchParams();
  if (view.race) params.set("race", view.race);
  if (view.driver) params.set("driver", view.driver);
  params.set("tab", view.tab);
  if (view.lap !== null) params.set("lap", String(view.lap));
  if (view.vs) params.set("vs", view.vs);
  return `?${params}`;
}
