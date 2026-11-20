.PHONY: setup verify verify-pipeline verify-web bench replay validate-sim undercut-check debrief contract contract-check ingest ingest-traces fit backtest fit-events validate-events fit-traffic validate-traffic fit-warmup export weekend data-pull data-push build dev

PY := cd pipeline && uv run --frozen
WEB := cd web && npm run -s

setup:
	cd pipeline && uv sync --frozen
	cd web && npm ci

# The one command CI runs. Green here means green in CI.
verify: verify-pipeline verify-web bench contract-check

verify-pipeline:
	$(PY) ruff check .
	$(PY) ruff format --check .
	$(PY) pyright
	$(PY) pytest

verify-web:
	$(WEB) typecheck
	$(WEB) lint
	$(WEB) test

NODE := node --disable-warning=ExperimentalWarning

# Engine speed against config/budgets.yaml. The engine runs unbundled under Node, as CI validation will.
bench:
	@args=$$($(PY) python -c "import yaml; b = yaml.safe_load(open('../config/budgets.yaml'))['sim_benchmark']; print(b['races'], b['laps'], b['cars'], b['max_seconds'])") && \
	cd web && $(NODE) scripts/bench.ts $$args

# Zero-noise replay of every simulable race in the exported bundle (needs `make export`).
replay:
	cd web && $(NODE) scripts/replay.ts

# Simulator calibration on the exported bundle, with the publish gate (config/thresholds.yaml).
# Run `make export` before (sim inputs) and after (to publish the accepted calibration).
validate-sim:
	$(PY) pitwall validate-sim

# The undercut module against every green pair of adjacent cars that stopped on consecutive laps
# (needs `make export`). Settings from config/pipeline.yaml (sim_validation).
undercut-check:
	@args=$$($(PY) python -c "import yaml; v = yaml.safe_load(open('../config/pipeline.yaml'))['sim_validation']; print(v['undercut_runs'], v['seed'], ','.join(map(str, v['undercut_bins'])))") && \
	cd web && $(NODE) scripts/undercut.ts public/data $$args

# Strategy debrief of the first DRIVERS finishers of RACES, e.g. RACES=2025-16,2026-09 DRIVERS=5
# (needs `make export`).
debrief:
	@seed=$$($(PY) python -c "import yaml; print(yaml.safe_load(open('../config/pipeline.yaml'))['sim_validation']['seed'])") && \
	cd web && $(NODE) scripts/debrief.ts public/data $$seed $(RACES) $(or $(DRIVERS),3)

# Regenerate JSON Schema and TypeScript types after editing pipeline/src/pitwall/export/contract.py.
contract:
	$(PY) pitwall contract --out ../contract
	$(WEB) contract

# Fails if the committed schemas or generated types differ from what the contract produces.
contract-check:
	@tmp=$$(mktemp -d) && \
	(cd pipeline && uv run --frozen pitwall contract --out $$tmp/schema 2>/dev/null) && \
	(cd web && node scripts/gen-contract.mjs $$tmp/schema $$tmp/ts) && \
	diff -r contract $$tmp/schema && diff -r web/src/contract $$tmp/ts; \
	status=$$?; rm -rf $$tmp; \
	if [ $$status -ne 0 ]; then echo "contract is stale: run 'make contract'"; exit 1; fi; \
	echo "contract up to date"

# One race with ROUND, otherwise every finished race of SEASON.
ingest:
	@test -n "$(SEASON)" || { echo "usage: make ingest SEASON=2024 [ROUND=1]"; exit 2; }
	$(PY) pitwall ingest --season $(SEASON) $(if $(ROUND),--round $(ROUND))

# Fastest-lap car data and track location for stored races that have none (SEASON=2024 for one).
ingest-traces:
	$(PY) pitwall ingest-traces $(if $(SEASON),--season $(SEASON))

# Fit the degradation model per era (ERA=2026 for one) and export draws if the gate passes.
fit:
	$(PY) pitwall fit-degradation $(if $(ERA),--era $(ERA))

# Leave-one-race-out over config/pipeline.yaml → degradation.backtest.races. Slow: one refit each.
backtest:
	$(PY) pitwall backtest-degradation

# Pit loss and SC/VSC/red-flag/DNF rates; every race gets a refit with itself masked out.
fit-events:
	$(PY) pitwall fit-events

# Leave-one-season-out validation of the neutralisation rates.
validate-events:
	$(PY) pitwall validate-events

# Dirty air and the pass model. Needs `make fit` first: pace comes from the degradation draws.
fit-traffic:
	$(PY) pitwall fit-traffic

# Tyre warm-up per C-number and stint lap, from the degradation fit's residuals.
fit-warmup:
	$(PY) pitwall fit-warmup

# Leave-one-season-out validation of the pass model, with a reliability table.
validate-traffic:
	$(PY) pitwall validate-traffic

export:
	$(PY) pitwall export

# The post-weekend run (ADR-008): new races of SEASON (default this year) and the last one again,
# refit, gates, export. ROUND= pulls one round; PUBLISH=1 uploads what changed to GitHub Releases.
weekend:
	$(PY) pitwall weekend $(if $(SEASON),--season $(SEASON)) $(if $(ROUND),--round $(ROUND)) $(if $(PUBLISH),--publish)

# The published races and models from GitHub Releases into .data (replaces local copies).
data-pull:
	$(PY) pitwall data-pull

# Upload every stored race and the models to GitHub Releases: seeding the store only.
data-push:
	$(PY) pitwall data-push

build:
	$(WEB) build

dev:
	$(WEB) dev
