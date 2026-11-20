import type { SimRace } from "../contract/sim";
import {
  mergeOutcomes,
  type Outcome,
  type Query,
  type UndercutQuery,
  type UndercutResult,
} from "../sim/index.ts";
import { split, type Job, type Reply } from "./protocol.ts";

/** The part of a Worker the pool uses. */
export interface WorkerLike {
  onmessage: ((event: MessageEvent<Reply>) => void) | null;
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
    const chunks = split(query.runs, this.workers.length);
    return Promise.all(
      chunks.map((chunk, k) =>
        post<Outcome>(this.workers[k]!, {
          kind: "runs",
          race,
          query,
          first: chunk.first + first,
          runs: chunk.runs,
        }),
      ),
    ).then(mergeOutcomes);
  }

  /** One undercut question, on one worker: it is a few hundred races. */
  undercut(race: SimRace, query: UndercutQuery): Promise<UndercutResult> {
    return post<UndercutResult>(this.workers[0]!, { kind: "undercut", race, query });
  }

  dispose(): void {
    for (const worker of this.workers) worker.terminate();
  }
}

function post<T extends Reply>(worker: WorkerLike, job: Job): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    worker.onmessage = ({ data }) =>
      "error" in data ? reject(new Error(data.error)) : resolve(data as T);
    worker.onerror = (event) => reject(new Error(event.message));
    worker.postMessage(job);
  });
}
