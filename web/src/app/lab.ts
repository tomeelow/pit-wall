import type { SimRace } from "../contract/sim";
import type { Evaluate, UndercutQuery, UndercutResult } from "../sim/index.ts";
import { SimPool } from "../worker/pool.ts";

/** Every question uses this seed: the same plan asked twice gives the same answer. */
export const SEED = 1;

let pool: SimPool | undefined;
let queue: Promise<unknown> = Promise.resolve();

/** The pool answers one request at a time; requests from different screens wait their turn. */
function serial<T>(task: () => Promise<T>): Promise<T> {
  const next = queue.then(task, task);
  queue = next.catch(() => undefined);
  return next;
}

const workers = () => (pool ??= new SimPool());

export class Cancelled extends Error {}

/** Held by one run of a tool; set when the inputs change or the screen goes, to stop it early. */
export interface Ticket {
  cancelled: boolean;
}

/** An Evaluate on the worker pool that stops at the next request once its ticket is cancelled. */
export function evaluator(race: SimRace, ticket: Ticket, onRaces: (n: number) => void): Evaluate {
  return (query, first) =>
    serial(async () => {
      if (ticket.cancelled) throw new Cancelled();
      const outcome = await workers().run(race, query, first);
      onRaces(query.runs * query.sets.length);
      return outcome;
    });
}

export const askUndercut = (race: SimRace, query: UndercutQuery): Promise<UndercutResult> =>
  serial(() => workers().undercut(race, query));
