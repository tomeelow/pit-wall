export {
  createDraw,
  createRandoms,
  fillDraw,
  fillRandoms,
  type Draw,
  type Randoms,
} from "./draw.ts";
export {
  createTrace,
  createWorkspace,
  DNF,
  DSQ,
  FINISHED,
  isClassified,
  simulateRace,
  type Mode,
  type Trace,
  type Workspace,
} from "./engine.ts";
export { mergeOutcomes, runSimulations, type Outcome, type Query } from "./montecarlo.ts";
export { actualStrategies, compilePlan, prepare, type Prepared, type Strategy } from "./prepare.ts";
export { Rng } from "./rng.ts";
export { finishCounts, startLaps } from "./backtest.ts";
export { candidates } from "./candidates.ts";
export { debrief, EX_ANTE, EX_POST, type Decision, type Verdict } from "./debrief.ts";
export { optimise, type Ranked, type Search, type SearchResult } from "./optimise.ts";
export { checkRules, type BrokenRule, type InvalidPlan, type RuleCheck, type RuleIssue } from "./rules.ts";
export {
  compare,
  counterfactual,
  distribution,
  inProcess,
  paired,
  score,
  withStrategy,
  type Comparison,
  type CounterfactualQuery,
  type Distribution,
  type Evaluate,
  type Objective,
  type Paired,
} from "./strategy.ts";
export {
  undercut,
  type UndercutComponents,
  type UndercutQuery,
  type UndercutResult,
} from "./undercut.ts";
