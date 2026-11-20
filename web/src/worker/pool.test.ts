import { describe, expect, it } from "vitest";
import { actualStrategies, runSimulations, type Outcome, type Query } from "../sim/index.ts";
import { syntheticRace } from "../sim/synthetic.ts";
import { SimPool, type WorkerLike } from "./pool.ts";
import { handle, split, type Job } from "./protocol.ts";

/** A worker that runs the real job handler in-process, asynchronously like the real one. */
function inProcessWorker(): WorkerLike {
  const worker: WorkerLike = {
    onmessage: null,
    onerror: null,
    postMessage(job: Job) {
      queueMicrotask(() => {
        let data: Outcome | { error: string };
        try {
          data = handle(structuredClone(job));
        } catch (error) {
          data = { error: (error as Error).message };
        }
        worker.onmessage?.({ data } as MessageEvent<Outcome | { error: string }>);
      });
    },
    terminate() {},
  };
  return worker;
}

describe("split", () => {
  it("covers every run once, in contiguous chunks", () => {
    expect(split(10, 3)).toEqual([
      { first: 0, runs: 4 },
      { first: 4, runs: 3 },
      { first: 7, runs: 3 },
    ]);
    expect(split(2, 8)).toEqual([
      { first: 0, runs: 1 },
      { first: 1, runs: 1 },
    ]);
  });
});

describe("SimPool", () => {
  const race = syntheticRace({ cars: 8, laps: 25 });
  const query: Query = {
    fromLap: 3,
    sets: [actualStrategies(race, 3)],
    runs: 101,
    seed: 9,
    mode: { events: "sampled", noise: true },
  };

  it("gives the single-thread result whatever the number of workers", async () => {
    const single = runSimulations(race, query);
    for (const size of [1, 3, 7]) {
      const pool = new SimPool(size, inProcessWorker);
      const pooled = await pool.run(race, query);
      pool.dispose();
      expect(pooled.position).toEqual(single.position);
      expect(pooled.status).toEqual(single.status);
    }
  });

  it("rejects with the worker's error", async () => {
    const pool = new SimPool(2, inProcessWorker);
    await expect(pool.run(race, { ...query, fromLap: 999 })).rejects.toThrow(/after lap 999/);
  });
});
