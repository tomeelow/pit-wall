// The little of Node the scripts use. @types/node is not a dependency (yet): add it, and delete
// this file, when a script needs more.
declare const process: {
  argv: string[];
  exitCode: number | undefined;
  cwd(): string;
};
