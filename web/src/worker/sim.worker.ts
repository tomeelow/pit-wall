import type { Outcome } from "../sim/index.ts";
import { handle, type Job } from "./protocol.ts";

// The DOM lib types `self` as a Window; inside a dedicated worker it is this.
interface WorkerScope {
  onmessage: ((event: MessageEvent<Job>) => void) | null;
  postMessage(message: Outcome | { error: string }, transfer?: Transferable[]): void;
}

const scope = self as unknown as WorkerScope;

scope.onmessage = (event) => {
  try {
    const outcome = handle(event.data);
    scope.postMessage(outcome, [outcome.position.buffer, outcome.status.buffer]);
  } catch (error) {
    scope.postMessage({ error: error instanceof Error ? error.message : String(error) });
  }
};
