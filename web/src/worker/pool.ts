import type { SimRace } from "../contract/sim";
import { mergeOutcomes, type Outcome, type Query } from "../sim/index.ts";
import { split, type Job } from "./protocol.ts";

/** The part of a Worker the pool uses. */
export interface WorkerLike {
  onmessage: ((event: MessageEvent<Outcome | { error: string }>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
  postMessage(job: Job): void;
  terminate(): void;
}

const spawnWorker = (): WorkerLike =>
  new Worker(new URL("./sim.worker.ts", import.meta.url), { type: "module" });

/**
 * Monte Carlo off the main thread: a query's runs are split across workers and merged back in
 * run order. Runs are seeded by index, so the result does not depend on the number of workers.
 */
export class SimPool {
  private readonly workers: WorkerLike[];

  constructor(
    size = Math.max(1, (globalThis.navigator?.hardwareConcurrency ?? 2) - 1),
    spawn: () => WorkerLike = spawnWorker,
  ) {
    this.workers = Array.from({ length: size }, spawn);
  }

  /** Simulations first .. first + query.runs - 1 of the query. */
  run(race: SimRace, query: Query, first = 0): Promise<Outcome> {
    const chunks = split(query.runs, this.workers.length).map((c) => ({
      ...c,
      first: c.first + first,
    }));
    return Promise.all(
      chunks.map(
        (chunk, k) =>
          new Promise<Outcome>((resolve, reject) => {
            const worker = this.workers[k]!;
            worker.onmessage = ({ data }) =>
              "error" in data ? reject(new Error(data.error)) : resolve(data);
            worker.onerror = (event) => reject(new Error(event.message));
            worker.postMessage({ race, query, ...chunk });
          }),
      ),
    ).then(mergeOutcomes);
  }

  dispose(): void {
    for (const worker of this.workers) worker.terminate();
  }
}
