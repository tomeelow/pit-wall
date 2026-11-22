import type { Calibration } from "../contract/calibration";
import type { Manifest } from "../contract/manifest";
import type { Race } from "../contract/race";
import type { Replay } from "../contract/replay";
import type { SimRace } from "../contract/sim";
import type { TelemetryLap } from "../contract/telemetry";

// Typed as the generated literal: when the pipeline bumps SCHEMA_VERSION, tsc fails here until
// the app has been checked against the new contract.
export const SUPPORTED_SCHEMA: Manifest["schema_version"] = "0.7.0";

const major = (version: string) => version.split(".")[0];

export function isCompatible(version: string, supported: string = SUPPORTED_SCHEMA): boolean {
  return major(version) === major(supported);
}

async function fetchBundleFile<T extends { schema_version: string }>(path: string): Promise<T> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/${path}`);
  if (!response.ok) throw new Error(`Could not load ${path} (HTTP ${response.status})`);
  const body = (await response.json()) as T;
  if (!isCompatible(body.schema_version)) {
    throw new Error(
      `${path} uses schema ${body.schema_version}; this app reads ${SUPPORTED_SCHEMA}`,
    );
  }
  return body;
}

export const loadManifest = () => fetchBundleFile<Manifest>("manifest.json");
export const loadRace = (path: string) => fetchBundleFile<Race>(path);
export const loadSim = (path: string) => fetchBundleFile<SimRace>(path);
export const loadCalibration = (path: string) => fetchBundleFile<Calibration>(path);
export const loadReplay = (path: string) => fetchBundleFile<Replay>(path);
export const loadTelemetry = (path: string) => fetchBundleFile<TelemetryLap>(path);
