import type { SimRace } from "../contract/sim";
import type { Outcome, Query, UndercutQuery, UndercutResult } from "../sim/index.ts";
import { runSimulations, undercut } from "../sim/index.ts";

export type Job =
  | { kind: "runs"; race: SimRace; query: Query; first: number; runs: number }
  | { kind: "undercut"; race: SimRace; query: UndercutQuery };

export type Reply = Outcome | UndercutResult | { error: string };

/** What a worker does with a job; kept apart from the worker globals so tests can call it. */
export function handle(job: Job): Outcome | UndercutResult {
  return job.kind === "runs"
    ? runSimulations(job.race, job.query, job.first, job.runs)
    : undercut(job.race, job.query);
}

/** Contiguous run ranges, one per worker, as even as possible. */
export function split(runs: number, workers: number): { first: number; runs: number }[] {
  const parts = Math.max(1, Math.min(workers, runs));
  const base = Math.floor(runs / parts);
  const extra = runs % parts;
  const chunks = [];
  let first = 0;
  for (let k = 0; k < parts; k++) {
    const size = base + (k < extra ? 1 : 0);
    chunks.push({ first, runs: size });
    first += size;
  }
  return chunks;
}
