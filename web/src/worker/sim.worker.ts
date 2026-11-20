import { handle, type Job, type Reply } from "./protocol.ts";

// The DOM lib types `self` as a Window; inside a dedicated worker it is this.
interface WorkerScope {
  onmessage: ((event: MessageEvent<Job>) => void) | null;
  postMessage(message: Reply, transfer?: Transferable[]): void;
}

const scope = self as unknown as WorkerScope;

scope.onmessage = (event) => {
  try {
    const result = handle(event.data);
    const transfer = "position" in result ? [result.position.buffer, result.status.buffer] : [];
    scope.postMessage(result, transfer);
  } catch (error) {
    scope.postMessage({ error: error instanceof Error ? error.message : String(error) });
  }
};
